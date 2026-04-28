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


def load_universe(cache_dir: Path, size: int = 50) -> List[str]:
    """优先沪深300成分；失败则回退到全市场按成交额排序。"""
    ak = _import_akshare()
    cache_file = cache_dir / f"universe_{size}.csv"
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
        codes = [str(r.get("代码", "")).strip() for r in rows[:size] if str(r.get("代码", "")).strip()]

    if size > 0:
        codes = codes[:size]

    with cache_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for c in codes:
            writer.writerow([c])
    return codes


def load_symbol_history(symbol: str, start: str, end: str, cache_dir: Path) -> List[Dict[str, Any]]:
    def _normalize_history_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        norm_rows: List[Dict[str, Any]] = []
        for r in rows:
            date_raw = r.get("date", r.get("日期", ""))
            d = str(date_raw).replace("-", "").strip()
            if not d:
                continue
            norm_rows.append(
                {
                    "date": d,
                    "open": _to_float(r.get("open", r.get("开盘", 0))),
                    "high": _to_float(r.get("high", r.get("最高", 0))),
                    "low": _to_float(r.get("low", r.get("最低", 0))),
                    "close": _to_float(r.get("close", r.get("收盘", 0))),
                    "volume": _to_float(r.get("volume", r.get("成交量", 0))),
                    "amount": _to_float(r.get("amount", r.get("成交额", 0))),
                    "pct_chg": _to_float(r.get("pct_chg", r.get("涨跌幅", 0))),
                }
            )
        return norm_rows

    cache_file = _cache_path(cache_dir, symbol)
    if cache_file.exists():
        with cache_file.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
            print(f"[history] {symbol} 原始df.shape=({len(rows)}, {len(rows[0]) if rows else 0}) 原始columns={list(rows[0].keys()) if rows else []}")
            norm_rows = _normalize_history_rows(rows)
            return [r for r in norm_rows if start <= r["date"] <= end]

    ak = _import_akshare()
    try:
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start, end_date=end, adjust="qfq")
        rows = _df_to_rows(df)
        print(f"[history] {symbol} 原始df.shape={getattr(df, 'shape', ('?', '?'))} 原始columns={list(getattr(df, 'columns', []))}")
    except Exception:
        print(f"[history] {symbol} 原始df.shape=(0, 0) 原始columns=[]")
        return []

    norm_rows = _normalize_history_rows(rows)

    with cache_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"])
        writer.writeheader()
        writer.writerows(norm_rows)

    return [r for r in norm_rows if start <= r["date"] <= end]


def load_hs300_history(start: str, end: str, cache_dir: Path) -> List[Dict[str, Any]]:
    """加载沪深300指数历史，用于大盘环境过滤。"""
    cache_file = cache_dir / "hs300_index.csv"
    if cache_file.exists():
        with cache_file.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
            out: List[Dict[str, Any]] = []
            for r in rows:
                d = str(r.get("date", "")).replace("-", "")
                if not d or not (start <= d <= end):
                    continue
                out.append({"date": d, "close": _to_float(r.get("close", 0))})
            return out

    ak = _import_akshare()
    try:
        idx_df = ak.stock_zh_index_daily_em(symbol="sh000300")
        idx_rows = _df_to_rows(idx_df)
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for r in idx_rows:
        d = str(r.get("date", "")).replace("-", "")
        close = _to_float(r.get("close", 0))
        if d and close > 0:
            out.append({"date": d, "close": close})

    with cache_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "close"])
        writer.writeheader()
        writer.writerows(out)

    return [r for r in out if start <= r["date"] <= end]


def build_hs300_filter(index_rows: List[Dict[str, Any]], confirm_days: int = 3) -> Dict[str, bool]:
    """
    返回 date -> 是否允许交易。
    规则：
    - 弱势定义：close < ma20
    - 若连续 confirm_days 天弱势，则判定为空仓（当天不交易）
    """
    if not index_rows:
        return {}
    rows = sorted(index_rows, key=lambda x: x["date"])
    allow: Dict[str, bool] = {}
    closes: List[float] = []
    weak_flags: List[bool] = []
    for r in rows:
        closes.append(float(r["close"]))
        if len(closes) < 20:
            allow[r["date"]] = True
        else:
            ma20 = sum(closes[-20:]) / 20.0
            weak_today = float(r["close"]) < ma20
            weak_flags.append(weak_today)
            if confirm_days <= 1:
                allow[r["date"]] = not weak_today
            else:
                recent = weak_flags[-confirm_days:]
                allow[r["date"]] = not (len(recent) == confirm_days and all(recent))
    return allow


def align_regime_filter_to_trade_days(trade_days: List[str], index_allow: Dict[str, bool]) -> Dict[str, bool]:
    """
    将指数过滤结果对齐到个股交易日。
    返回 date -> allow（True 可交易 / False 不可交易）。
    规则：若当天指数无数据，沿用最近一个已知交易日的状态。
    """
    if not trade_days:
        return {}
    if not index_allow:
        return {d: True for d in trade_days}

    aligned: Dict[str, bool] = {}
    known_days = sorted(index_allow.keys())
    j = 0
    last_allow = True
    for day in sorted(trade_days):
        while j < len(known_days) and known_days[j] <= day:
            last_allow = index_allow[known_days[j]]
            j += 1
        aligned[day] = last_allow
    return aligned


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
        close = _to_float(row.get("close", 0))
        amount = _to_float(row.get("amount", 0))
        pct_chg = _to_float(row.get("pct_chg", 0))
        if close <= 0 or amount <= 0:
            continue

        closes = [_to_float(r.get("close", 0)) for r in rows[: idx + 1]]
        closes = [c for c in closes if c > 0]
        vols = [_to_float(r.get("amount", 0)) for r in rows[: idx + 1]]
        pcts = [_to_float(r.get("pct_chg", 0)) for r in rows[: idx + 1]]
        if len(closes) < 20 or len(vols) < 6 or len(pcts) < 3:
            continue

        name = name_map.get(symbol, symbol)
        # 关键修复：过滤前先转为 float，避免 str/int 比较异常
        excluded, _ = _is_excluded_stock(symbol, name, close, amount, pct_chg)
        if excluded:
            continue

        try:
            m3 = momentum(closes, 3)
            m5 = momentum(closes, 5)
            m10 = momentum(closes, 10)
        except Exception:
            continue

        ma5 = sum(closes[-5:]) / 5.0
        ma10 = sum(closes[-10:]) / 10.0
        ma10_prev = sum(closes[-11:-1]) / 10.0
        if not (close > ma5 > ma10):
            continue
        if not (ma10 > ma10_prev):
            continue
        if not (3 <= m5 <= 15):
            continue

        avg_vol5 = sum(vols[-5:]) / 5.0
        if avg_vol5 <= 0:
            continue
        volume_ratio = amount / avg_vol5
        if volume_ratio <= 1.3:
            continue

        candidates.append(
            {
            "symbol": symbol,
            "close": close,
            "pct_chg": pct_chg,
            "amount": amount,
            "momentum_3": m3,
            "momentum_5": m5,
            "ret_5": m5,
            "ret_10": m10,
            "ma5": ma5,
            "ma10": ma10,
            "volume_ratio": volume_ratio,
            }
        )

    if not candidates:
        return None

    liq_z = robust_zscores([c["amount"] for c in candidates])
    for i, c in enumerate(candidates):
        c["liquidity_z"] = liq_z[i]
        c["total_score"] = 0.30 * c["momentum_5"] + 0.20 * c["momentum_3"] + 0.30 * c["liquidity_z"] + 0.20 * c["pct_chg"]

    candidates.sort(key=lambda x: x["total_score"], reverse=True)
    top3 = candidates[:3]
    return top3[0]["symbol"] if top3 else None


def _apply_cost(raw_ret: float, fee_rate: float, slippage: float) -> float:
    """交易成本：手续费(总) + 双边滑点。"""
    return raw_ret - (fee_rate + 2 * slippage)


def run_trade(symbol: str, day_idx: int, rows: List[Dict[str, Any]], mode: str, fee_rate: float, slippage: float) -> TradeRecord | None:
    buy_idx = day_idx + 1
    if buy_idx >= len(rows):
        return None

    signal_close = _to_float(rows[day_idx].get("close", 0))
    next_open = _to_float(rows[buy_idx].get("open", 0))
    if signal_close <= 0 or next_open <= 0:
        return None
    # 严格使用 T 日收盘选股、T+1 开盘买入
    open_gap_pct = (next_open / signal_close - 1.0) * 100
    # 次日开盘涨幅必须在 [-1%, +2%]
    if open_gap_pct > 2 or open_gap_pct < -1:
        return None

    # 买入价修正为 next_day_open，避免回测偏差
    buy_price = next_open
    if buy_price <= 0:
        return None

    # 新卖出策略：分段止盈 + 趋势持有 + 移动止盈，最多持有5天
    tp_partial = buy_price * 1.04
    sl = buy_price * 0.98
    last_idx = min(len(rows) - 1, buy_idx + 4)

    position = 1.0
    realized_gross = 0.0
    partial_done = False
    trail_armed = False
    peak_price = buy_price
    sell_date = rows[last_idx]["date"]
    final_sell_price = _to_float(rows[last_idx].get("close", 0))

    for i in range(buy_idx, last_idx + 1):
        day = rows[i]
        low = _to_float(day.get("low", 0))
        high = _to_float(day.get("high", 0))
        close_i = _to_float(day.get("close", 0))
        if high > peak_price:
            peak_price = high

        # 止损：-2%，优先级最高
        if position > 0 and low > 0 and low <= sl:
            realized_gross += position * (sl / buy_price - 1)
            position = 0.0
            sell_date = day["date"]
            final_sell_price = sl
            break

        # 分段止盈：+4% 先卖 50%
        if position > 0 and (not partial_done) and high > 0 and high >= tp_partial:
            realized_gross += 0.5 * (tp_partial / buy_price - 1)
            position -= 0.5
            partial_done = True
            sell_date = day["date"]

        # 盈利超过3%后，启用移动止盈（从高点回撤2%）
        if close_i >= buy_price * 1.03:
            trail_armed = True
        if position > 0 and trail_armed and peak_price > 0 and close_i > 0:
            drawdown_from_peak = (peak_price - close_i) / peak_price
            if drawdown_from_peak >= 0.02:
                realized_gross += position * (close_i / buy_price - 1)
                position = 0.0
                sell_date = day["date"]
                final_sell_price = close_i
                break

        # 趋势持有：趋势未破不提前卖；若跌破 MA5 则卖剩余仓位
        if position > 0:
            window = rows[max(0, i - 4) : i + 1]
            ma5_now = sum(_to_float(x.get("close", 0)) for x in window) / 5.0
            if close_i > 0 and close_i < ma5_now:
                realized_gross += position * (close_i / buy_price - 1)
                position = 0.0
                sell_date = day["date"]
                final_sell_price = close_i
                break

    if position > 0:
        if final_sell_price <= 0:
            final_sell_price = _to_float(rows[last_idx].get("close", 0))
        if final_sell_price <= 0:
            return None
        realized_gross += position * (final_sell_price / buy_price - 1)
        position = 0.0
        sell_date = rows[last_idx]["date"]

    ret = _apply_cost(realized_gross, fee_rate, slippage)
    if final_sell_price <= 0:
        return None
    return TradeRecord(symbol, rows[buy_idx]["date"], sell_date, buy_price, final_sell_price, ret, mode)


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
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["akshare", "eastmoney"], default="akshare", help="data source")
    parser.add_argument("--months", type=int, default=3, help="backtest months")
    parser.add_argument("--universe-size", type=int, default=50, help="stock universe size")
    parser.add_argument("--max-days", type=int, default=60, help="max trading days")
    parser.add_argument("--fee-rate", type=float, default=0.003, help="transaction fee")
    parser.add_argument("--slippage", type=float, default=0.001, help="slippage")
    parser.add_argument("--regime-confirm-days", type=int, default=3, help="regime weak confirmation days")
    parser.add_argument("--modes", nargs="+", default=["hold_3"], choices=["hold_3", "hold_5", "take_profit_stop_loss"], help="sell mode")
    parser.add_argument("--limit-300", action="store_true", help="use hs300 universe")
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache_backtest"), help="cache folder")
    parser.add_argument("--output", type=Path, default=Path("backtest_result.csv"), help="output csv path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.source == "eastmoney":
        print("[提示] 回测历史日线当前统一使用 akshare，已自动切换。")

    args.cache_dir.mkdir(parents=True, exist_ok=True)

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=31 * args.months + 10)
    start = start_dt.strftime("%Y%m%d")
    end = end_dt.strftime("%Y%m%d")

    print(f"[1/5] 加载股票池（start={start}, end={end}）...")
    universe = load_universe(args.cache_dir, size=args.universe_size)
    print(f"股票池数量: {len(universe)}")

    print("[2/5] 加载历史数据（带缓存）...")
    universe_data: Dict[str, List[Dict[str, Any]]] = {}
    success_symbols: List[str] = []
    failed_symbols: List[str] = []
    for i, symbol in enumerate(universe, start=1):
        rows = load_symbol_history(symbol, start, end, args.cache_dir)
        required_cols = {"date", "open", "high", "low", "close"}
        has_required = bool(rows) and required_cols.issubset(rows[0].keys())
        if has_required:
            universe_data[symbol] = rows
            success_symbols.append(symbol)
        else:
            failed_symbols.append(symbol)
        if i % 10 == 0:
            print(f"  已加载 {i}/{len(universe)}")

    print(f"成功加载股票数: {len(success_symbols)}")
    print(f"失败股票数: {len(failed_symbols)}")
    print(f"前3个成功股票代码: {success_symbols[:3]}")

    if not universe_data:
        raise RuntimeError("无可用历史数据，请检查网络或 akshare")

    print("[3/5] 构建交易日历...")
    trading_days = sorted({r["date"] for rows in universe_data.values() for r in rows})
    print(f"交易日数量: {len(trading_days)}")

    print("[3.5/5] 加载沪深300环境过滤...")
    hs300_rows = load_hs300_history(start, end, args.cache_dir)
    hs300_allow = build_hs300_filter(hs300_rows, confirm_days=args.regime_confirm_days)
    aligned_hs300_allow = align_regime_filter_to_trade_days(trading_days, hs300_allow)

    # 名称映射（用实时快照，失败则用代码）
    name_map: Dict[str, str] = {}
    try:
        ak = _import_akshare()
        spot_rows = _df_to_rows(ak.stock_zh_a_spot_em())
        name_map = {str(r.get("代码", "")).strip(): str(r.get("名称", "")).strip() for r in spot_rows}
    except Exception:
        pass

    print("[4/5] 执行回测...")
    modes = args.modes
    mode_trades: Dict[str, List[TradeRecord]] = {m: [] for m in modes}

    trade_days = trading_days[-args.max_days :] if args.max_days > 0 else trading_days
    skipped_bear_days = 0

    def is_bear_market(day: str) -> bool:
        return not aligned_hs300_allow.get(day, True)

    for idx, day in enumerate(trade_days[:-6]):
        if is_bear_market(day):
            print(f"{day} 跳过（弱势市场）")
            skipped_bear_days += 1
            continue
        symbol = pick_stock_for_day(day, universe_data, name_map)
        if not symbol:
            continue

        rows = universe_data.get(symbol, [])
        day_idx = next((i for i, r in enumerate(rows) if r["date"] == day), -1)
        if day_idx < 0:
            continue

        for mode in modes:
            try:
                tr = run_trade(symbol, day_idx, rows, mode, args.fee_rate, args.slippage)
                if tr:
                    mode_trades[mode].append(tr)
            except Exception:
                continue

        if idx % 20 == 0:
            print(f"  回测进度: {idx}/{len(trade_days)}")

    print("[5/5] 统计并输出...")
    print(f"弱势市场跳过交易日: {skipped_bear_days}")
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
