#!/usr/bin/env python3
"""短线策略回测脚本。

回测流程：
1) 每个交易日收盘后用 stock_picker 同款逻辑打分
2) 取 Top3 中分数最高的 1 只
3) 次日开盘买入
4) 三种卖出策略：持有3天 / 持有5天 / 止盈+6%止损-3%

输出：backtest_result.csv
"""

from __future__ import annotations

import argparse
import importlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import csv

from stock_picker import _is_excluded_stock, _normalize_ts_code, robust_zscores


@dataclass
class TradeRecord:
    symbol: str
    buy_date: str
    sell_date: str
    buy_price: float
    sell_price: float
    ret: float
    mode: str


def _import_akshare() -> Any:
    try:
        return importlib.import_module("akshare")
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("未安装 akshare。请执行: pip install akshare pandas") from exc


def _df_to_rows(df: Any) -> List[Dict[str, Any]]:
    if not hasattr(df, "to_dict"):
        raise TypeError("返回数据不是 DataFrame")
    return df.to_dict(orient="records")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _cache_path(cache_dir: Path, symbol: str) -> Path:
    return cache_dir / f"{symbol}.csv"


def load_universe_300(cache_dir: Path) -> List[str]:
    """优先沪深300成分；失败则回退到全市场前300（按成交额）。"""
    ak = _import_akshare()
    cache_file = cache_dir / "universe_300.csv"
    if cache_file.exists():
        with cache_file.open("r", encoding="utf-8", newline="") as f:
            return [row[0] for row in csv.reader(f) if row]

    codes: List[str] = []
    try:
        cons_df = ak.index_stock_cons(symbol="000300")
        cons_rows = _df_to_rows(cons_df)
        for r in cons_rows:
            code = str(r.get("品种代码") or r.get("成分券代码") or r.get("代码") or "").strip()
            if code:
                codes.append(code)
    except Exception:
        spot_df = ak.stock_zh_a_spot_em()
        rows = _df_to_rows(spot_df)
        rows.sort(key=lambda x: _to_float(x.get("成交额", 0)), reverse=True)
        codes = [str(r.get("代码", "")).strip() for r in rows[:300] if str(r.get("代码", "")).strip()]

    with cache_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for c in codes:
            writer.writerow([c])
    return codes


def load_symbol_history(symbol: str, start: str, end: str, cache_dir: Path) -> List[Dict[str, Any]]:
    cache_file = _cache_path(cache_dir, symbol)
    if cache_file.exists():
        with cache_file.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
            return [r for r in rows if start <= str(r["date"]).replace("-", "") <= end]

    ak = _import_akshare()
    try:
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start, end_date=end, adjust="qfq")
        rows = _df_to_rows(df)
    except Exception:
        return []

    norm_rows: List[Dict[str, Any]] = []
    for r in rows:
        d = str(r.get("日期", "")).replace("-", "")
        if not d:
            continue
        norm_rows.append(
            {
                "date": d,
                "open": _to_float(r.get("开盘", 0)),
                "high": _to_float(r.get("最高", 0)),
                "low": _to_float(r.get("最低", 0)),
                "close": _to_float(r.get("收盘", 0)),
                "pct_chg": _to_float(r.get("涨跌幅", 0)),
                "amount": _to_float(r.get("成交额", 0)),
            }
        )

    with cache_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "pct_chg", "amount"])
        writer.writeheader()
        writer.writerows(norm_rows)

    return norm_rows


def momentum(closes: List[float], days: int) -> float:
    if len(closes) < days + 1:
        raise ValueError("历史不足")
    return (closes[-1] / closes[-(days + 1)] - 1.0) * 100.0


def pick_stock_for_day(day: str, universe_data: Dict[str, List[Dict[str, Any]]], name_map: Dict[str, str]) -> str | None:
    candidates: List[Dict[str, Any]] = []

    for symbol, rows in universe_data.items():
        idx = next((i for i, r in enumerate(rows) if r["date"] == day), -1)
        if idx < 5:
            continue

        row = rows[idx]
        closes = [r["close"] for r in rows[: idx + 1]]

        name = name_map.get(symbol, symbol)
        excluded, _ = _is_excluded_stock(symbol, name, row["close"], row["amount"], row["pct_chg"])
        if excluded:
            continue

        try:
            m3 = momentum(closes, 3)
            m5 = momentum(closes, 5)
        except Exception:
            continue

        candidates.append(
            {
                "symbol": symbol,
                "close": row["close"],
                "pct_chg": row["pct_chg"],
                "amount": row["amount"],
                "momentum_3": m3,
                "momentum_5": m5,
            }
        )

    if not candidates:
        return None

    liq_z = robust_zscores([c["amount"] for c in candidates])
    for i, c in enumerate(candidates):
        c["liquidity_z"] = liq_z[i]
        c["total_score"] = 0.35 * c["momentum_5"] + 0.25 * c["momentum_3"] + 0.25 * c["liquidity_z"] + 0.15 * c["pct_chg"]

    candidates.sort(key=lambda x: x["total_score"], reverse=True)
    top3 = candidates[:3]
    return top3[0]["symbol"] if top3 else None


def run_trade(symbol: str, day_idx: int, rows: List[Dict[str, Any]], mode: str) -> TradeRecord | None:
    buy_idx = day_idx + 1
    if buy_idx >= len(rows):
        return None

    buy_price = rows[buy_idx]["open"]
    if buy_price <= 0:
        return None

    if mode == "hold_3":
        sell_idx = buy_idx + 2
        if sell_idx >= len(rows):
            return None
        sell_price = rows[sell_idx]["close"]
        return TradeRecord(symbol, rows[buy_idx]["date"], rows[sell_idx]["date"], buy_price, sell_price, sell_price / buy_price - 1, mode)

    if mode == "hold_5":
        sell_idx = buy_idx + 4
        if sell_idx >= len(rows):
            return None
        sell_price = rows[sell_idx]["close"]
        return TradeRecord(symbol, rows[buy_idx]["date"], rows[sell_idx]["date"], buy_price, sell_price, sell_price / buy_price - 1, mode)

    # take_profit_stop_loss
    tp = buy_price * 1.06
    sl = buy_price * 0.97
    last_idx = min(len(rows) - 1, buy_idx + 4)

    for i in range(buy_idx, last_idx + 1):
        day = rows[i]
        if day["low"] <= sl:
            return TradeRecord(symbol, rows[buy_idx]["date"], day["date"], buy_price, sl, sl / buy_price - 1, mode)
        if day["high"] >= tp:
            return TradeRecord(symbol, rows[buy_idx]["date"], day["date"], buy_price, tp, tp / buy_price - 1, mode)

    sell_price = rows[last_idx]["close"]
    return TradeRecord(symbol, rows[buy_idx]["date"], rows[last_idx]["date"], buy_price, sell_price, sell_price / buy_price - 1, mode)


def max_drawdown(returns: List[float]) -> float:
    equity = 1.0
    peak = 1.0
    mdd = 0.0
    for r in returns:
        equity *= 1 + r
        if equity > peak:
            peak = equity
        dd = (equity - peak) / peak
        if dd < mdd:
            mdd = dd
    return mdd


def calc_metrics(trades: List[TradeRecord]) -> Dict[str, Any]:
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "avg_return": 0.0,
            "max_drawdown": 0.0,
            "profit_loss_ratio": 0.0,
            "annual_returns": {},
        }

    rets = [t.ret for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]

    annual: Dict[str, float] = {}
    for t in trades:
        y = t.sell_date[:4]
        annual[y] = annual.get(y, 1.0) * (1 + t.ret)
    annual = {k: v - 1 for k, v in annual.items()}

    avg_gain = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    pl_ratio = (avg_gain / abs(avg_loss)) if avg_loss != 0 else 0.0

    return {
        "total_trades": len(trades),
        "win_rate": len(wins) / len(rets),
        "avg_return": sum(rets) / len(rets),
        "max_drawdown": max_drawdown(rets),
        "profit_loss_ratio": pl_ratio,
        "annual_returns": annual,
    }


def save_result(path: Path, mode_to_metrics: Dict[str, Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["mode", "metric", "value"])
        for mode, m in mode_to_metrics.items():
            writer.writerow([mode, "total_trades", m["total_trades"]])
            writer.writerow([mode, "win_rate", f"{m['win_rate']:.4f}"])
            writer.writerow([mode, "avg_return", f"{m['avg_return']:.4f}"])
            writer.writerow([mode, "max_drawdown", f"{m['max_drawdown']:.4f}"])
            writer.writerow([mode, "profit_loss_ratio", f"{m['profit_loss_ratio']:.4f}"])
            for year, ret in sorted(m["annual_returns"].items()):
                writer.writerow([mode, f"year_{year}", f"{ret:.4f}"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="短线策略回测")
    parser.add_argument("--source", choices=["akshare", "eastmoney"], default="akshare", help="当前优先使用 akshare")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--limit-300", action="store_true", help="限制为沪深300成分股，提升速度")
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache_backtest"))
    parser.add_argument("--output", type=Path, default=Path("backtest_result.csv"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.source == "eastmoney":
        print("[提示] 回测历史日线当前统一使用 akshare，已自动切换。")

    args.cache_dir.mkdir(parents=True, exist_ok=True)

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=365 * args.years + 30)
    start = start_dt.strftime("%Y%m%d")
    end = end_dt.strftime("%Y%m%d")

    print(f"[1/5] 加载股票池（start={start}, end={end}）...")
    universe = load_universe_300(args.cache_dir) if args.limit_300 else load_universe_300(args.cache_dir)
    print(f"股票池数量: {len(universe)}")

    print("[2/5] 加载历史数据（带缓存）...")
    universe_data: Dict[str, List[Dict[str, Any]]] = {}
    for i, symbol in enumerate(universe, start=1):
        rows = load_symbol_history(symbol, start, end, args.cache_dir)
        if rows:
            universe_data[symbol] = rows
        if i % 30 == 0:
            print(f"  已加载 {i}/{len(universe)}")

    if not universe_data:
        raise RuntimeError("无可用历史数据，请检查网络或 akshare")

    print("[3/5] 构建交易日历...")
    trading_days = sorted({r["date"] for rows in universe_data.values() for r in rows})
    print(f"交易日数量: {len(trading_days)}")

    # 名称映射（用实时快照，失败则用代码）
    name_map: Dict[str, str] = {}
    try:
        ak = _import_akshare()
        spot_rows = _df_to_rows(ak.stock_zh_a_spot_em())
        name_map = {str(r.get("代码", "")).strip(): str(r.get("名称", "")).strip() for r in spot_rows}
    except Exception:
        pass

    print("[4/5] 执行回测...")
    modes = ["hold_3", "hold_5", "take_profit_stop_loss"]
    mode_trades: Dict[str, List[TradeRecord]] = {m: [] for m in modes}

    for idx, day in enumerate(trading_days[:-6]):
        symbol = pick_stock_for_day(day, universe_data, name_map)
        if not symbol:
            continue

        rows = universe_data.get(symbol, [])
        day_idx = next((i for i, r in enumerate(rows) if r["date"] == day), -1)
        if day_idx < 0:
            continue

        for mode in modes:
            try:
                tr = run_trade(symbol, day_idx, rows, mode)
                if tr:
                    mode_trades[mode].append(tr)
            except Exception:
                continue

        if idx % 50 == 0:
            print(f"  回测进度: {idx}/{len(trading_days)}")

    print("[5/5] 统计并输出...")
    mode_to_metrics = {m: calc_metrics(ts) for m, ts in mode_trades.items()}
    save_result(args.output, mode_to_metrics)

    print(f"回测完成，结果已输出: {args.output}")
    for mode, m in mode_to_metrics.items():
        print(
            f"{mode}: trades={m['total_trades']}, win_rate={m['win_rate']:.2%}, "
            f"avg_ret={m['avg_return']:.2%}, max_dd={m['max_drawdown']:.2%}, pl={m['profit_loss_ratio']:.2f}"
        )


if __name__ == "__main__":
    main()
