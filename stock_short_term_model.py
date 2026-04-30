#!/usr/bin/env python3
"""A股短线选股与回测脚本（3-5天）。

升级点：
1. 更贴近A股交易规则：涨跌停过滤、停牌/一字板过滤。
2. 新增换手率因子。
3. 分层仓位管理（按分数分层）。
4. 止损止盈与最大持有期联合退出。

说明：
- 默认从 Eastmoney 的沪深A股列表中截取前 N 只股票。
- 默认优先读取本地 data_a_share/*.csv（可复现、便于离线）。
- 如启用 --download，会尝试通过 akshare 下载近1年日线。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

DATA_DIR = Path("data_a_share")
OUTPUT_DIR = Path("output")


@dataclass
class StrategyConfig:
    top_n_stocks: int = 200
    daily_pick_count: int = 6
    hold_days_min: int = 3
    hold_days_max: int = 5
    stop_loss: float = -0.05
    take_profit: float = 0.08


def get_a_share_universe(top_n: int = 200) -> List[str]:
    """获取A股股票池（前 top_n 只，格式类似 000001.SZ / 600000.SH）。"""
    try:
        import akshare as ak

        spot = ak.stock_zh_a_spot_em()
        # Eastmoney 的代码字段通常为“代码”
        codes = spot["代码"].astype(str).tolist()
        mapped = [f"{c}.SH" if c.startswith("6") else f"{c}.SZ" for c in codes]
        return mapped[:top_n]
    except Exception:
        # 下载接口不可用时，回退示例股票池
        fallback = [
            "600000.SH", "600036.SH", "601318.SH", "600519.SH", "601688.SH",
            "000001.SZ", "000333.SZ", "000651.SZ", "300750.SZ", "002415.SZ",
        ]
        return fallback[:top_n]


def normalize_akshare_daily(df: pd.DataFrame) -> pd.DataFrame:
    """统一列名到 Date/Open/High/Low/Close/Volume/TurnoverRate。"""
    rename_map = {
        "日期": "Date",
        "开盘": "Open",
        "收盘": "Close",
        "最高": "High",
        "最低": "Low",
        "成交量": "Volume",
        "换手率": "TurnoverRate",
    }
    data = df.rename(columns=rename_map).copy()
    cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
    for col in cols:
        if col not in data.columns:
            raise ValueError(f"缺少必要列: {col}")
    if "TurnoverRate" not in data.columns:
        data["TurnoverRate"] = np.nan
    data["Date"] = pd.to_datetime(data["Date"])
    data = data.sort_values("Date").set_index("Date")
    return data[["Open", "High", "Low", "Close", "Volume", "TurnoverRate"]].dropna(subset=["Open", "High", "Low", "Close", "Volume"])


def download_a_share_data(tickers: List[str], period_years: int = 1) -> Dict[str, pd.DataFrame]:
    """下载A股日线并保存本地。"""
    import akshare as ak

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    result: Dict[str, pd.DataFrame] = {}
    start = (pd.Timestamp.today() - pd.Timedelta(days=365 * period_years)).strftime("%Y%m%d")
    end = pd.Timestamp.today().strftime("%Y%m%d")

    for ticker in tickers:
        code = ticker.split(".")[0]
        try:
            raw = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")
            if raw.empty:
                continue
            df = normalize_akshare_daily(raw)
            df.to_csv(DATA_DIR / f"{ticker}.csv")
            result[ticker] = df
        except Exception:
            continue
    return result


def load_local_data(tickers: List[str]) -> Dict[str, pd.DataFrame]:
    """优先读取本地CSV数据。"""
    data_map: Dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        p = DATA_DIR / f"{ticker}.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p)
        if "Date" not in df.columns:
            continue
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(set(df.columns)):
            continue
        if "TurnoverRate" not in df.columns:
            df["TurnoverRate"] = np.nan
        data_map[ticker] = df[["Open", "High", "Low", "Close", "Volume", "TurnoverRate"]]
    return data_map


def add_a_share_filters_and_features(df: pd.DataFrame) -> pd.DataFrame:
    feat = df.copy()
    prev_close = feat["Close"].shift(1)

    # 近似涨跌停（主板10%）：实际可根据 ST/创业板科创板差异再细化
    feat["limit_up"] = feat["Close"] >= prev_close * 1.098
    feat["limit_down"] = feat["Close"] <= prev_close * 0.902

    # 停牌近似：成交量为0或价格缺失
    feat["suspended"] = (feat["Volume"] <= 0) | feat[["Open", "High", "Low", "Close"]].isna().any(axis=1)

    # 一字板：高低开收几乎一致，且通常封板
    feat["one_word_board"] = (
        (feat["High"] - feat["Low"]).abs() <= (feat["Close"] * 0.001)
    )

    # 因子
    feat["ret_3"] = feat["Close"].pct_change(3)
    feat["ret_5"] = feat["Close"].pct_change(5)
    feat["volatility_10"] = feat["Close"].pct_change().rolling(10).std()
    feat["volume_ratio"] = feat["Volume"] / feat["Volume"].rolling(20).mean()
    feat["turnover_5"] = feat["TurnoverRate"].rolling(5).mean()

    # 评分：动量+量能+换手，惩罚过高波动
    feat["score"] = (
        0.35 * feat["ret_3"]
        + 0.25 * feat["ret_5"]
        + 0.20 * (feat["volume_ratio"] - 1.0)
        + 0.20 * feat["turnover_5"].fillna(feat["turnover_5"].median()) / 10.0
        - 0.20 * feat["volatility_10"]
    )

    # 可交易过滤：剔除停牌、一字板、涨跌停
    feat["tradable"] = (~feat["suspended"]) & (~feat["one_word_board"]) & (~feat["limit_up"]) & (~feat["limit_down"])
    return feat


def allocate_weights(n: int) -> np.ndarray:
    """分层仓位：前2只高配，中间次之，尾部低配。"""
    if n <= 0:
        return np.array([])
    if n == 1:
        return np.array([1.0])
    weights = []
    for i in range(n):
        if i < 2:
            weights.append(1.5)
        elif i < 4:
            weights.append(1.0)
        else:
            weights.append(0.7)
    w = np.array(weights, dtype=float)
    return w / w.sum()


def simulate_trade_path(df: pd.DataFrame, start_idx: int, cfg: StrategyConfig) -> Tuple[float, int, str]:
    """按止损/止盈/最大持有期模拟单笔交易。"""
    entry = float(df.iloc[start_idx]["Close"])
    exit_ret = 0.0
    hold = cfg.hold_days_max
    reason = "max_hold"

    for d in range(1, cfg.hold_days_max + 1):
        px = float(df.iloc[start_idx + d]["Close"])
        ret = (px - entry) / entry
        if d >= cfg.hold_days_min and ret >= cfg.take_profit:
            exit_ret, hold, reason = ret, d, "take_profit"
            break
        if d >= 1 and ret <= cfg.stop_loss:
            exit_ret, hold, reason = ret, d, "stop_loss"
            break
        exit_ret = ret
        hold = d
    return exit_ret, hold, reason


def backtest(data_map: Dict[str, pd.DataFrame], cfg: StrategyConfig) -> Tuple[pd.DataFrame, pd.DataFrame]:
    feature_map = {t: add_a_share_filters_and_features(df) for t, df in data_map.items()}
    if not feature_map:
        return pd.DataFrame(), pd.DataFrame()

    common_dates = sorted(set.intersection(*[set(df.index) for df in feature_map.values()]))
    common_dates = common_dates[25:-cfg.hold_days_max]

    trades, daily = [], []
    for dt in common_dates:
        cands = []
        for ticker, df in feature_map.items():
            row = df.loc[dt]
            if (not bool(row.get("tradable", False))) or pd.isna(row.get("score", np.nan)):
                continue
            cands.append((ticker, float(row["score"])))

        if len(cands) < cfg.daily_pick_count:
            continue

        picks = sorted(cands, key=lambda x: x[1], reverse=True)[: cfg.daily_pick_count]
        weights = allocate_weights(len(picks))

        rets = []
        for i, (ticker, score) in enumerate(picks):
            df = feature_map[ticker]
            idx = df.index.get_loc(dt)
            ret, hold, reason = simulate_trade_path(df, idx, cfg)
            rets.append(ret * weights[i])
            trades.append(
                {
                    "date": dt,
                    "ticker": ticker,
                    "score": score,
                    "weight": weights[i],
                    "holding_days": hold,
                    "exit_reason": reason,
                    "return": ret,
                    "weighted_return": ret * weights[i],
                }
            )

        daily.append(
            {
                "date": dt,
                "picked": ",".join([p[0] for p in picks]),
                "daily_return": float(np.sum(rets)),
            }
        )

    trades_df = pd.DataFrame(trades)
    daily_df = pd.DataFrame(daily)
    if not daily_df.empty:
        daily_df["equity_curve"] = (1 + daily_df["daily_return"]).cumprod()
    return trades_df, daily_df


def summarize(daily_df: pd.DataFrame, trades_df: pd.DataFrame) -> str:
    if daily_df.empty:
        return "无回测结果，请检查数据。"
    total = daily_df["equity_curve"].iloc[-1] - 1
    ann = (1 + daily_df["daily_return"].mean()) ** 252 - 1
    sharpe = daily_df["daily_return"].mean() / (daily_df["daily_return"].std() + 1e-12) * np.sqrt(252)
    mdd = ((daily_df["equity_curve"].cummax() - daily_df["equity_curve"]) / daily_df["equity_curve"].cummax()).max()
    tp = (trades_df["exit_reason"] == "take_profit").mean() if not trades_df.empty else 0.0
    sl = (trades_df["exit_reason"] == "stop_loss").mean() if not trades_df.empty else 0.0
    return (
        f"总收益: {total:.2%}\n年化(估算): {ann:.2%}\n夏普(估算): {sharpe:.2f}\n最大回撤: {mdd:.2%}\n"
        f"止盈退出占比: {tp:.2%}\n止损退出占比: {sl:.2%}\n回测交易日: {len(daily_df)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="A股短线3-5天模型")
    parser.add_argument("--top-n", type=int, default=200)
    parser.add_argument("--pick-count", type=int, default=6)
    parser.add_argument("--hold-min", type=int, default=3)
    parser.add_argument("--hold-max", type=int, default=5)
    parser.add_argument("--stop-loss", type=float, default=-0.05)
    parser.add_argument("--take-profit", type=float, default=0.08)
    parser.add_argument("--download", action="store_true", help="是否在线下载数据")
    args = parser.parse_args()

    cfg = StrategyConfig(
        top_n_stocks=args.top_n,
        daily_pick_count=args.pick_count,
        hold_days_min=args.hold_min,
        hold_days_max=args.hold_max,
        stop_loss=args.stop_loss,
        take_profit=args.take_profit,
    )

    tickers = get_a_share_universe(cfg.top_n_stocks)
    print(f"股票池数量: {len(tickers)}")

    data_map = load_local_data(tickers)
    if args.download or len(data_map) < min(20, cfg.top_n_stocks):
        print("本地数据不足，尝试在线下载A股数据...")
        downloaded = download_a_share_data(tickers, period_years=1)
        data_map.update(downloaded)

    print(f"可用股票数量: {len(data_map)}")

    trades_df, daily_df = backtest(data_map, cfg)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trades_df.to_csv(OUTPUT_DIR / "daily_picks.csv", index=False)
    daily_df.to_csv(OUTPUT_DIR / "backtest_pnl.csv", index=False)

    print("输出文件：")
    print(f"- {OUTPUT_DIR / 'daily_picks.csv'}")
    print(f"- {OUTPUT_DIR / 'backtest_pnl.csv'}")
    print("\n绩效摘要：")
    print(summarize(daily_df, trades_df))


if __name__ == "__main__":
    main()
