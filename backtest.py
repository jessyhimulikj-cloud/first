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
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import csv

from stock_picker import _is_excluded_stock, _normalize_ts_code, robust_zscores
from update_data import fallback_symbols


@dataclass
class TradeRecord:
    symbol: str
    buy_date: str
    sell_date: str
    buy_price: float
    sell_price: float
    ret: float
    mode: str
    exit_reason: str = "other"


# 所有策略参数统一放在 STRATEGY_CONFIG，后续自动调参只需要改这里或通过命令行覆盖。
STRATEGY_CONFIG = {
    "default": {"take_profit": 0.04, "stop_loss": 0.025, "hold_days": 3},
    "momentum_hold3_v9": {"take_profit": 0.04, "stop_loss": 0.025, "hold_days": 3},
    "param_mode_v1": {"take_profit": 0.04, "stop_loss": 0.025, "hold_days": 3},
}


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


def _normalize_yyyymmdd(value: Any) -> str:
    """统一日期为 YYYYMMDD 字符串。"""
    s = str(value).strip()
    if not s:
        return ""
    s = s.replace("-", "").replace("/", "")
    if len(s) == 8 and s.isdigit():
        return s
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.strftime("%Y%m%d")
    except Exception:
        return s


def _cache_path(cache_dir: Path, symbol: str) -> Path:
    return cache_dir / f"{symbol}.csv"


def _em_symbol(symbol: str) -> str:
    symbol6 = re.sub(r"\D", "", str(symbol))[:6]
    if len(symbol6) != 6:
        return ""
    if symbol6.startswith("6"):
        return f"1.{symbol6}"
    return f"0.{symbol6}"


def _em_session() -> Any:
    requests = importlib.import_module("requests")
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    return session


def load_universe(cache_dir: Path, size: int = 50, data_dir: Path = Path("data")) -> List[str]:
    """使用与 update_data.py 一致的股票池，并优先使用 data 目录已有 CSV。"""
    cache_file = cache_dir / f"universe_{size}.csv"
    csv_symbols = set()
    if data_dir.exists():
        for p in data_dir.glob("*.csv"):
            code = p.stem.strip()
            if len(code) == 6 and code.isdigit():
                csv_symbols.add(code)

    ordered_from_csv = [s for s in fallback_symbols if s in csv_symbols]
    ordered_from_fallback = [s for s in fallback_symbols if s not in csv_symbols]
    all_candidates = ordered_from_csv + ordered_from_fallback
    symbols = all_candidates[:size] if size > 0 else all_candidates
    code_name_pairs = [(s, s) for s in symbols]
    codes = list(symbols)

    with cache_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for code, name in code_name_pairs:
            writer.writerow([code, name])

    preview = code_name_pairs[:10]
    print("[universe] 前10个股票代码和名称:")
    for code, name in preview:
        print(f"  {code} {name}")
    return codes


def load_symbol_history(symbol: str, start: str, end: str, cache_dir: Path) -> List[Dict[str, Any]]:
    csv_path = Path("data") / f"{symbol}.csv"
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return []
    full_rows: List[Dict[str, Any]] = []
    for row in rows:
        d = str(row.get("date", "")).replace("-", "").strip()
        if len(d) != 8:
            continue
        full_rows.append(
            {
                "date": d,
                "open": _to_float(row.get("open", 0)),
                "high": _to_float(row.get("high", 0)),
                "low": _to_float(row.get("low", 0)),
                "close": _to_float(row.get("close", 0)),
                "volume": _to_float(row.get("volume", 0)),
                "amount": _to_float(row.get("amount", 0)),
                "amount_yuan": _to_float(row.get("amount", 0)) * 1000.0,
                "pct_chg": _to_float(row.get("pct_chg", 0)),
            }
        )
    full_rows.sort(key=lambda x: x["date"])

    closes = [r["close"] for r in full_rows]
    volumes = [r["volume"] for r in full_rows]
    for i, r in enumerate(full_rows):
        r["ma5"] = (sum(closes[i - 4 : i + 1]) / 5.0) if i >= 4 else None
        r["ma20"] = (sum(closes[i - 19 : i + 1]) / 20.0) if i >= 19 else None
        r["ma60"] = (sum(closes[i - 59 : i + 1]) / 60.0) if i >= 59 else None
        r["vol_ma5"] = (sum(volumes[i - 4 : i + 1]) / 5.0) if i >= 4 else None

    out = [r for r in full_rows if start <= r["date"] <= end]
    return out


def load_hs300_history(start: str, end: str, cache_dir: Path) -> List[Dict[str, Any]]:
    """使用 Tushare index_daily 加载沪深300指数历史，用于大盘环境过滤。"""
    cache_file = cache_dir / "hs300_index.csv"
    if cache_file.exists():
        with cache_file.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
            out: List[Dict[str, Any]] = []
            for r in rows:
                d = str(r.get("date", "")).replace("-", "")
                if not d or not (start <= d <= end):
                    continue
                out.append(
                    {
                        "date": d,
                        "open": _to_float(r.get("open", 0)),
                        "high": _to_float(r.get("high", 0)),
                        "low": _to_float(r.get("low", 0)),
                        "close": _to_float(r.get("close", 0)),
                        "volume": _to_float(r.get("volume", 0)),
                    }
                )
            return out

    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("缺少环境变量 TUSHARE_TOKEN，无法获取沪深300指数数据")
    try:
        import tushare as ts
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("未安装 tushare/pandas，请执行: pip install tushare pandas") from exc
    ts.set_token(token)
    pro = ts.pro_api()

    try:
        idx_df = pro.index_daily(ts_code="000300.SH", start_date=start, end_date=end)
    except Exception:
        return []
    if idx_df is None or idx_df.empty:
        return []

    keep = ["trade_date", "open", "high", "low", "close", "vol"]
    for c in keep:
        if c not in idx_df.columns:
            idx_df[c] = 0
    idx_df = idx_df[keep].copy()
    idx_df = idx_df.rename(columns={"trade_date": "date", "vol": "volume"})
    idx_df["date"] = pd.to_datetime(idx_df["date"], errors="coerce").dt.strftime("%Y%m%d")
    idx_df = idx_df.dropna(subset=["date"]).sort_values("date")

    out: List[Dict[str, Any]] = []
    for _, r in idx_df.iterrows():
        d = str(r.get("date", "")).replace("-", "")
        if d and start <= d <= end:
            out.append(
                {
                    "date": d,
                    "open": _to_float(r.get("open", 0)),
                    "high": _to_float(r.get("high", 0)),
                    "low": _to_float(r.get("low", 0)),
                    "close": _to_float(r.get("close", 0)),
                    "volume": _to_float(r.get("volume", 0)),
                }
            )

    with cache_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(out)
    return out


def build_hs300_filter(index_rows: List[Dict[str, Any]]) -> Dict[str, bool]:
    """返回 date -> allow（True可交易），弱势条件：close<MA10 or MA5<MA10 or MA10<MA20。"""
    if not index_rows:
        return {}
    rows = sorted(index_rows, key=lambda x: x["date"])
    allow: Dict[str, bool] = {}
    closes: List[float] = []
    for r in rows:
        closes.append(float(r["close"]))
        if len(closes) < 20:
            allow[r["date"]] = True
            continue
        ma5 = sum(closes[-5:]) / 5.0
        ma10 = sum(closes[-10:]) / 10.0
        ma20 = sum(closes[-20:]) / 20.0
        close = float(r["close"])
        weak_today = (close < ma10) or (ma5 < ma10) or (ma10 < ma20)
        allow[r["date"]] = not weak_today
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


def pick_stock_for_day(
    day: str,
    universe_data: Dict[str, List[Dict[str, Any]]],
    name_map: Dict[str, str],
    mode: str = "loose_hold3",
    param_cfg: Dict[str, float] | None = None,
) -> List[str]:
    """按日选股（row-by-date），支持 loose_hold3 / momentum_hold3_v1 / momentum_hold3_v2 / momentum_hold3_v3 / momentum_hold3_v4 / momentum_hold3_v5 / momentum_hold3_v7 / momentum_hold3_v8 / momentum_hold3_v9。"""
    current_date = _normalize_yyyymmdd(day)
    picked: List[str] = []
    if mode == "momentum_hold3_v2":
        max_picks = 1
    elif mode in ("momentum_hold3_v1", "momentum_hold3_v3", "momentum_hold3_v4", "momentum_hold3_v5", "momentum_hold3_v7", "momentum_hold3_v8", "momentum_hold3_v9"):
        max_picks = 2
    elif mode == "param_mode_v1":
        max_picks = 2
    else:
        max_picks = 3
    for symbol, rows in universe_data.items():
        day_rows = [r for r in rows if _normalize_yyyymmdd(r.get("date", "")) == current_date]
        if not day_rows:
            continue
        r = day_rows[0]
        idx = next((i for i, x in enumerate(rows) if _normalize_yyyymmdd(x.get("date", "")) == current_date), -1)
        if idx < 0:
            continue
        try:
            close = float(r["close"])
            ma20 = float(r["ma20"])
            ma60 = float(r["ma60"])
            pct_chg = float(r["pct_chg"])
            amount = float(r["amount"])
            amount_yuan = float(r.get("amount_yuan", amount * 1000.0))
            volume = float(r["volume"])
            vol_ma5 = float(r["vol_ma5"])
            high = float(r["high"])
            low = float(r["low"])
        except Exception:
            continue
        _ = ma60, name_map
        if math.isnan(close) or math.isnan(ma20):
            continue

        if mode in ("momentum_hold3_v1", "momentum_hold3_v2", "momentum_hold3_v3", "momentum_hold3_v4", "momentum_hold3_v5", "momentum_hold3_v7", "momentum_hold3_v8", "momentum_hold3_v9", "param_mode_v1"):
            if math.isnan(ma60) or math.isnan(vol_ma5):
                continue
            if idx < 3:
                continue
            if not (close > ma20 and close > ma60):
                continue
            if mode == "momentum_hold3_v2":
                if not (2.0 <= pct_chg <= 6.0):
                    continue
                if amount_yuan <= 500000000:
                    continue
                if vol_ma5 <= 0 or volume <= vol_ma5 * 1.3:
                    continue
            elif mode == "momentum_hold3_v3":
                if not (1.5 <= pct_chg <= 5.5):
                    continue
                if amount_yuan <= 300000000:
                    continue
                if vol_ma5 <= 0 or volume <= vol_ma5 * 1.2:
                    continue
            elif mode == "momentum_hold3_v9":
                if not (2.0 <= pct_chg <= 6.0):
                    continue
                if amount_yuan <= 300000000:
                    continue
                if vol_ma5 <= 0 or volume <= vol_ma5 * 1.3:
                    continue
            elif mode == "param_mode_v1":
                cfg = param_cfg or {}
                pct_min = float(cfg.get("pct_min", 2.0))
                pct_max = float(cfg.get("pct_max", 6.0))
                volume_ratio = float(cfg.get("volume_ratio", 1.5))
                amount_min = float(cfg.get("amount_min", 300000000))
                if not (pct_min <= pct_chg <= pct_max):
                    continue
                if amount_yuan <= amount_min:
                    continue
                if vol_ma5 <= 0 or volume <= vol_ma5 * volume_ratio:
                    continue
            elif mode in ("momentum_hold3_v4", "momentum_hold3_v5", "momentum_hold3_v7", "momentum_hold3_v8"):
                if not (1.5 <= pct_chg <= 5.5):
                    continue
                if amount_yuan <= 300000000:
                    continue
                if vol_ma5 <= 0 or volume <= vol_ma5 * 1.2:
                    continue
            else:
                if not (1.5 <= pct_chg <= 5.5):
                    continue
                if amount_yuan <= 300000000:
                    continue
                if vol_ma5 <= 0 or volume <= vol_ma5 * 1.2:
                    continue

            day_range = high - low
            if day_range <= 0:
                continue
            close_pos = (close - low) / day_range
            if mode in ("momentum_hold3_v2", "momentum_hold3_v9", "param_mode_v1"):
                close_pos_min = float((param_cfg or {}).get("close_pos_min", 0.7)) if mode == "param_mode_v1" else 0.7
                if close_pos <= close_pos_min:
                    continue
            elif close_pos <= 0.65:
                continue

            prev3_close = _to_float(rows[idx - 3].get("close", 0))
            if prev3_close <= 0:
                continue
            ret3 = (close / prev3_close - 1.0) * 100.0
            if mode in ("momentum_hold3_v9", "param_mode_v1"):
                ret3_max = float((param_cfg or {}).get("ret3_max", 7.0)) if mode == "param_mode_v1" else 7.0
                if ret3 >= ret3_max:
                    continue
            elif mode in ("momentum_hold3_v2", "momentum_hold3_v3"):
                if ret3 >= 8:
                    continue
            elif ret3 >= 9:
                continue
            if mode in ("momentum_hold3_v9", "param_mode_v1"):
                p1 = _to_float(rows[idx - 1].get("pct_chg", 0))
                p2 = _to_float(rows[idx - 2].get("pct_chg", 0))
                if p1 > 0 and p2 > 0:
                    continue
            if mode == "momentum_hold3_v3":
                p1 = _to_float(rows[idx - 1].get("pct_chg", 0))
                p2 = _to_float(rows[idx - 2].get("pct_chg", 0))
                p3 = _to_float(rows[idx - 3].get("pct_chg", 0))
                if p1 > 0 and p2 > 0 and p3 > 0:
                    continue
            picked.append(symbol)
        elif close > ma20 and pct_chg > 0 and amount_yuan > 100000000:
            picked.append(symbol)
        if len(picked) >= max_picks:
            break
    return picked


def _score_symbol_for_day(symbol: str, day: str, universe_data: Dict[str, List[Dict[str, Any]]]) -> float:
    rows = universe_data.get(symbol, [])
    idx = next((i for i, r in enumerate(rows) if _normalize_yyyymmdd(r.get("date", "")) == _normalize_yyyymmdd(day)), -1)
    if idx < 0:
        return -1e18
    row = rows[idx]
    pct_chg = _to_float(row.get("pct_chg", 0))
    volume = _to_float(row.get("volume", 0))
    return pct_chg + volume / 1e8


def pick_multi_strategy_v1(day: str, universe_data: Dict[str, List[Dict[str, Any]]], name_map: Dict[str, str]) -> Dict[str, str]:
    """
    组合策略：
    - 优先 v5 信号，否则 v1
    - 若两者同时有信号，按 (pct_chg + volume) 评分排序
    - 每天最多 2 只
    返回: symbol -> strategy_mode(v1/v5)
    """
    v5 = pick_stock_for_day(day, universe_data, name_map, mode="momentum_hold3_v5")
    v1 = pick_stock_for_day(day, universe_data, name_map, mode="momentum_hold3_v1")
    if not v5 and not v1:
        return {}

    if v5 and not v1:
        return {s: "momentum_hold3_v5" for s in v5[:2]}
    if v1 and not v5:
        return {s: "momentum_hold3_v1" for s in v1[:2]}

    union = list(dict.fromkeys(v5 + v1))
    scored = []
    for s in union:
        scored.append(
            (
                s,
                _score_symbol_for_day(s, day, universe_data),
                1 if s in v5 else 0,
            )
        )
    scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
    out: Dict[str, str] = {}
    for s, _, _ in scored[:2]:
        out[s] = "momentum_hold3_v5" if s in v5 else "momentum_hold3_v1"
    return out


def _apply_cost(raw_ret: float, fee_rate: float, slippage: float) -> float:
    """交易成本：手续费(总) + 双边滑点。"""
    return raw_ret - (fee_rate + 2 * slippage)


def run_trade(
    symbol: str,
    day_idx: int,
    rows: List[Dict[str, Any]],
    mode: str,
    fee_rate: float,
    slippage: float,
    hold_days: int | None = None,
    take_profit: float | None = None,
    stop_loss: float | None = None,
) -> TradeRecord | None:
    cfg = STRATEGY_CONFIG.get(mode, STRATEGY_CONFIG["default"])
    take_profit = float(take_profit if take_profit is not None else cfg["take_profit"])
    stop_loss = float(stop_loss if stop_loss is not None else cfg["stop_loss"])
    hold_days = int(hold_days if hold_days is not None else cfg["hold_days"])
    hold_days = max(1, hold_days)

    buy_idx = day_idx + 1
    if buy_idx >= len(rows):
        return None

    signal_close = _to_float(rows[day_idx].get("close", 0))
    next_open = _to_float(rows[buy_idx].get("open", 0))
    if signal_close <= 0 or next_open <= 0:
        return None
    if mode != "loose_hold3":
        # 严格使用 T 日收盘选股、T+1 开盘买入
        open_gap_pct = (next_open / signal_close - 1.0) * 100
        # 次日开盘涨幅必须在 [-1%, +2%]
        if open_gap_pct > 2 or open_gap_pct < -1:
            return None

    # 买入价修正为 next_day_open，避免回测偏差
    buy_price = next_open
    if buy_price <= 0:
        return None

    if mode == "param_mode_v1":
        tp_price = buy_price * (1.0 + take_profit)
        sl_price = buy_price * (1.0 - stop_loss)
        last_idx = min(len(rows) - 1, buy_idx + hold_days - 1)
        sell_date = rows[last_idx]["date"]
        sell_price = _to_float(rows[last_idx].get("close", 0))
        exit_reason = "timeout_exit"
        for i in range(buy_idx, last_idx + 1):
            day = rows[i]
            high = _to_float(day.get("high", 0))
            low = _to_float(day.get("low", 0))
            close_i = _to_float(day.get("close", 0))
            if high > 0 and high >= tp_price:
                sell_date = day["date"]
                sell_price = tp_price
                exit_reason = "stop_profit"
                break
            if low > 0 and low <= sl_price:
                sell_date = day["date"]
                sell_price = sl_price
                exit_reason = "stop_loss"
                break
            if i == last_idx and close_i > 0:
                sell_date = day["date"]
                sell_price = close_i
                exit_reason = "timeout_exit"
        if sell_price <= 0:
            return None
        ret = _apply_cost((sell_price / buy_price - 1.0), fee_rate, slippage)
        return TradeRecord(symbol, rows[buy_idx]["date"], sell_date, buy_price, sell_price, ret, mode, exit_reason)

    if mode == "momentum_hold3_v4":
        sl_price = buy_price * (1.0 - stop_loss)
        last_idx = min(len(rows) - 1, buy_idx + hold_days - 1)
        sell_date = rows[last_idx]["date"]
        sell_price = _to_float(rows[last_idx].get("close", 0))
        exit_reason = "timeout_exit"
        trail_armed = False
        peak_price = buy_price

        for i in range(buy_idx, last_idx + 1):
            day = rows[i]
            high = _to_float(day.get("high", 0))
            low = _to_float(day.get("low", 0))
            close_i = _to_float(day.get("close", 0))

            if high > peak_price:
                peak_price = high

            # 提前止盈：买入后第2天涨幅 > 4% 直接卖出
            if i == buy_idx + 1 and close_i > 0 and (close_i / buy_price - 1.0) > 0.04:
                sell_date = day["date"]
                sell_price = close_i
                exit_reason = "stop_profit"
                break

            # 固定止损 -2.5%
            if low > 0 and low <= sl_price:
                sell_date = day["date"]
                sell_price = sl_price
                exit_reason = "stop_loss"
                break

            # 盈利达到 +3% 启动跟踪止盈
            if not trail_armed and high >= buy_price * 1.03:
                trail_armed = True
            if trail_armed and peak_price > 0 and close_i > 0:
                dd_from_peak = (peak_price - close_i) / peak_price
                if dd_from_peak > 0.015:
                    sell_date = day["date"]
                    sell_price = close_i
                    exit_reason = "stop_profit"
                    break

            # 时间止损：持有超过3天仍未盈利（此分支对应持有窗口末日）
            if i == last_idx and close_i > 0:
                sell_date = day["date"]
                sell_price = close_i
                exit_reason = "timeout_exit" if close_i <= buy_price else "stop_profit"

        if sell_price <= 0:
            return None
        ret = _apply_cost((sell_price / buy_price - 1.0), fee_rate, slippage)
        return TradeRecord(symbol, rows[buy_idx]["date"], sell_date, buy_price, sell_price, ret, mode, exit_reason)

    if mode in ("momentum_hold3_v5", "momentum_hold3_v9"):
        sl_price = buy_price * (1.0 - stop_loss)
        last_idx = min(len(rows) - 1, buy_idx + hold_days - 1)
        sell_date = rows[last_idx]["date"]
        sell_price = _to_float(rows[last_idx].get("close", 0))
        exit_reason = "timeout_exit"

        for i in range(buy_idx, last_idx + 1):
            day = rows[i]
            low = _to_float(day.get("low", 0))
            close_i = _to_float(day.get("close", 0))

            # 固定止损 -3%
            if low > 0 and low <= sl_price:
                sell_date = day["date"]
                sell_price = sl_price
                exit_reason = "stop_loss"
                break

            # 趋势保护：收盘价跌破 MA5 则卖出
            if i >= 4 and close_i > 0:
                window = rows[i - 4 : i + 1]
                ma5_now = sum(_to_float(x.get("close", 0)) for x in window) / 5.0
                if close_i < ma5_now:
                    sell_date = day["date"]
                    sell_price = close_i
                    exit_reason = "stop_profit"
                    break

            # 第5天仍持仓则强制卖出
            if i == last_idx and close_i > 0:
                sell_date = day["date"]
                sell_price = close_i
                exit_reason = "timeout_exit"

        if sell_price <= 0:
            return None
        ret = _apply_cost((sell_price / buy_price - 1.0), fee_rate, slippage)
        return TradeRecord(symbol, rows[buy_idx]["date"], sell_date, buy_price, sell_price, ret, mode, exit_reason)

    if mode == "momentum_hold3_v7":
        sl_price = buy_price * 0.97
        peak_price = buy_price
        protect_mode = False
        down_streak = 0
        prev_close = buy_price
        sell_date = rows[-1]["date"]
        sell_price = _to_float(rows[-1].get("close", 0))
        exit_reason = "timeout_exit"

        for i in range(buy_idx, len(rows)):
            day = rows[i]
            low = _to_float(day.get("low", 0))
            high = _to_float(day.get("high", 0))
            close_i = _to_float(day.get("close", 0))
            if close_i <= 0:
                continue

            if high > peak_price:
                peak_price = high

            # 固定止损 -3%
            if low > 0 and low <= sl_price:
                sell_date = day["date"]
                sell_price = sl_price
                exit_reason = "stop_loss"
                break

            # 趋势跟随：收盘价 < ma5 卖出
            if i >= 4:
                window = rows[i - 4 : i + 1]
                ma5_now = sum(_to_float(x.get("close", 0)) for x in window) / 5.0
                if close_i < ma5_now:
                    sell_date = day["date"]
                    sell_price = close_i
                    exit_reason = "stop_profit"
                    break

            # 浮盈 >4% 启动保护模式，回撤超2%卖出
            if (close_i / buy_price - 1.0) > 0.04:
                protect_mode = True
            if protect_mode and peak_price > 0:
                drawdown = (peak_price - close_i) / peak_price
                if drawdown > 0.02:
                    sell_date = day["date"]
                    sell_price = close_i
                    exit_reason = "stop_profit"
                    break

            # 弱势退出：连续2天下跌
            if close_i < prev_close:
                down_streak += 1
            else:
                down_streak = 0
            if down_streak >= 2:
                sell_date = day["date"]
                sell_price = close_i
                exit_reason = "stop_profit"
                break

            prev_close = close_i

        if sell_price <= 0:
            return None
        ret = _apply_cost((sell_price / buy_price - 1.0), fee_rate, slippage)
        return TradeRecord(symbol, rows[buy_idx]["date"], sell_date, buy_price, sell_price, ret, mode, exit_reason)

    if mode == "momentum_hold3_v8":
        sl_price = buy_price * (1.0 - stop_loss)
        peak_price = buy_price
        protect_mode = False
        down_streak = 0
        prev_close = buy_price
        last_idx = min(len(rows) - 1, buy_idx + hold_days - 1)
        sell_date = rows[last_idx]["date"]
        sell_price = _to_float(rows[last_idx].get("close", 0))
        exit_reason = "timeout_exit"

        for i in range(buy_idx, last_idx + 1):
            day = rows[i]
            low = _to_float(day.get("low", 0))
            high = _to_float(day.get("high", 0))
            close_i = _to_float(day.get("close", 0))
            if close_i <= 0:
                continue

            if high > peak_price:
                peak_price = high

            # 固定止损 -3%
            if low > 0 and low <= sl_price:
                sell_date = day["date"]
                sell_price = sl_price
                exit_reason = "stop_loss"
                break

            # 浮盈 >5% 启动保护，回撤 >2.5% 卖出
            if (close_i / buy_price - 1.0) > take_profit:
                protect_mode = True
            if protect_mode and peak_price > 0:
                drawdown = (peak_price - close_i) / peak_price
                if drawdown > 0.025:
                    sell_date = day["date"]
                    sell_price = close_i
                    exit_reason = "stop_profit"
                    break

            # 趋势退出放宽：收盘价 < ma10 才卖
            if i >= 9:
                window10 = rows[i - 9 : i + 1]
                ma10_now = sum(_to_float(x.get("close", 0)) for x in window10) / 10.0
                if close_i < ma10_now:
                    sell_date = day["date"]
                    sell_price = close_i
                    exit_reason = "stop_profit"
                    break

            # 弱势退出放宽：连续3天下跌
            if close_i < prev_close:
                down_streak += 1
            else:
                down_streak = 0
            if down_streak >= 3:
                sell_date = day["date"]
                sell_price = close_i
                exit_reason = "stop_profit"
                break

            prev_close = close_i

            # 第8天仍持仓则强制卖出
            if i == last_idx:
                sell_date = day["date"]
                sell_price = close_i
                exit_reason = "timeout_exit"

        if sell_price <= 0:
            return None
        ret = _apply_cost((sell_price / buy_price - 1.0), fee_rate, slippage)
        return TradeRecord(symbol, rows[buy_idx]["date"], sell_date, buy_price, sell_price, ret, mode, exit_reason)

    if mode in ("tp5_sl3_hold3", "strong_momentum_tp5_sl3_hold3", "momentum_hold3_v2", "momentum_hold3_v3"):
        tp_price = buy_price * (1.0 + take_profit)
        sl_price = buy_price * (1.0 - stop_loss)
        last_idx = min(len(rows) - 1, buy_idx + hold_days - 1)
        sell_date = rows[last_idx]["date"]
        sell_price = _to_float(rows[last_idx].get("close", 0))
        exit_reason = "timeout_exit"

        for i in range(buy_idx, last_idx + 1):
            day = rows[i]
            high = _to_float(day.get("high", 0))
            low = _to_float(day.get("low", 0))
            close_i = _to_float(day.get("close", 0))

            if high > 0 and high >= tp_price:
                sell_date = day["date"]
                sell_price = tp_price
                exit_reason = "stop_profit"
                break
            if low > 0 and low <= sl_price:
                sell_date = day["date"]
                sell_price = sl_price
                exit_reason = "stop_loss"
                break

            if i == last_idx and close_i > 0:
                sell_date = day["date"]
                sell_price = close_i
                exit_reason = "timeout_exit"

        if sell_price <= 0:
            return None
        ret = _apply_cost((sell_price / buy_price - 1.0), fee_rate, slippage)
        return TradeRecord(symbol, rows[buy_idx]["date"], sell_date, buy_price, sell_price, ret, mode, exit_reason)

    if mode in ("loose_hold3", "momentum_hold3_v1"):
        last_idx = min(len(rows) - 1, buy_idx + hold_days - 1)
        sell_price = _to_float(rows[last_idx].get("close", 0))
        if sell_price <= 0:
            return None
        ret = _apply_cost((sell_price / buy_price - 1.0), fee_rate, slippage)
        return TradeRecord(symbol, rows[buy_idx]["date"], rows[last_idx]["date"], buy_price, sell_price, ret, mode, "timeout_exit")

    # 新卖出策略：分段止盈 + 趋势持有 + 移动止盈，最多持有5天
    tp_partial = buy_price * (1.0 + take_profit)
    sl = buy_price * (1.0 - stop_loss)
    last_idx = min(len(rows) - 1, buy_idx + hold_days - 1)

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
    return TradeRecord(symbol, rows[buy_idx]["date"], sell_date, buy_price, final_sell_price, ret, mode, "other")


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
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "stop_profit_count": 0,
            "stop_loss_count": 0,
            "timeout_exit_count": 0,
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
    stop_profit_count = sum(1 for t in trades if t.exit_reason == "stop_profit")
    stop_loss_count = sum(1 for t in trades if t.exit_reason == "stop_loss")
    timeout_exit_count = sum(1 for t in trades if t.exit_reason == "timeout_exit")

    return {
        "total_trades": len(trades),
        "win_rate": len(wins) / len(rets),
        "avg_return": sum(rets) / len(rets),
        "max_drawdown": max_drawdown(rets),
        "profit_loss_ratio": pl_ratio,
        "avg_win": avg_gain,
        "avg_loss": avg_loss,
        "stop_profit_count": stop_profit_count,
        "stop_loss_count": stop_loss_count,
        "timeout_exit_count": timeout_exit_count,
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
            writer.writerow([mode, "avg_win", f"{m['avg_win']:.4f}"])
            writer.writerow([mode, "avg_loss", f"{m['avg_loss']:.4f}"])
            writer.writerow([mode, "stop_profit_count", m["stop_profit_count"]])
            writer.writerow([mode, "stop_loss_count", m["stop_loss_count"]])
            writer.writerow([mode, "timeout_exit_count", m["timeout_exit_count"]])
            for year, ret in sorted(m["annual_returns"].items()):
                writer.writerow([mode, f"year_{year}", f"{ret:.4f}"])


def parse_args() -> argparse.Namespace:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["akshare", "eastmoney"], default="akshare", help="data source")
    parser.add_argument("--months", type=int, default=12, help="backtest months")
    parser.add_argument("--universe-size", type=int, default=30, help="stock universe size")
    parser.add_argument("--max-days", type=int, default=0, help="max trading days")
    parser.add_argument("--fee-rate", type=float, default=0.003, help="transaction fee")
    parser.add_argument("--slippage", type=float, default=0.001, help="slippage")
    parser.add_argument("--regime-confirm-days", type=int, default=3, help="regime weak confirmation days")
    parser.add_argument("--hold-days", type=int, default=3, help="param mode hold days")
    parser.add_argument("--take-profit", type=float, default=0.06, help="param mode take profit ratio")
    parser.add_argument("--stop-loss", type=float, default=0.04, help="param mode stop loss ratio")
    parser.add_argument("--volume-ratio", type=float, default=1.5, help="param mode volume ratio")
    parser.add_argument("--pct-min", type=float, default=2.0, help="param mode pct min")
    parser.add_argument("--pct-max", type=float, default=6.0, help="param mode pct max")
    parser.add_argument("--amount-min", type=float, default=300000000, help="param mode min amount in yuan")
    parser.add_argument("--close-pos-min", type=float, default=0.7, help="param mode min close position")
    parser.add_argument("--ret3-max", type=float, default=7.0, help="param mode max 3-day return")
    parser.add_argument(
        "--modes",
        nargs="+",
        default=["momentum_hold3_v1", "momentum_hold3_v5", "multi_strategy_v1"],
        choices=["hold_3", "hold_5", "take_profit_stop_loss", "tp5_sl3_hold3", "strong_momentum_tp5_sl3_hold3", "loose_hold3", "momentum_hold3_v1", "momentum_hold3_v2", "momentum_hold3_v3", "momentum_hold3_v4", "momentum_hold3_v5", "momentum_hold3_v7", "momentum_hold3_v8", "momentum_hold3_v9", "multi_strategy_v1", "param_mode_v1"],
        help="sell mode",
    )
    parser.add_argument("--limit-300", action="store_true", help="use hs300 universe")
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache_backtest"), help="cache folder")
    parser.add_argument("--output", type=Path, default=Path("backtest_result.csv"), help="output csv path")
    parser.add_argument("--no-market-filter", action="store_true", help="disable market regime filter")
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
    print(f"backtest_start: {start}")
    print(f"backtest_end: {end}")

    print(f"[1/5] 加载股票池（start={start}, end={end}）...")
    data_dir = Path("data")
    universe = load_universe(args.cache_dir, size=args.universe_size, data_dir=data_dir)
    data_csv_count = len(list(data_dir.glob("*.csv"))) if data_dir.exists() else 0
    print(f"股票池数量: {len(universe)}")
    print(f"实际股票池数量: {len(universe)}")
    print(f"data目录CSV数量: {data_csv_count}")

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
    if success_symbols:
        sample_symbol = success_symbols[0]
        sample_row = universe_data[sample_symbol][-1]
        print(
            f"[diag-amount] symbol={sample_symbol} "
            f"amount={sample_row.get('amount', 0)} "
            f"amount_yuan={sample_row.get('amount_yuan', 0)}"
        )

    if not universe_data:
        print("[WARN] 无可用历史数据，输出空回测结果。")
        empty_metrics = {m: calc_metrics([]) for m in args.modes}
        save_result(args.output, empty_metrics)
        print(f"回测完成，结果已输出: {args.output}")
        for mode, m in empty_metrics.items():
            print(
                f"{mode}: trades={m['total_trades']}, win_rate={m['win_rate']:.2%}, "
                f"avg_ret={m['avg_return']:.2%}, max_dd={m['max_drawdown']:.2%}, pl={m['profit_loss_ratio']:.2f}"
            )
            print(f"win_rate,{m['win_rate']:.4f}")
            print(f"profit_loss_ratio,{m['profit_loss_ratio']:.4f}")
            print(f"max_drawdown,{m['max_drawdown']:.4f}")
            print(f"total_trades,{m['total_trades']}")
        return

    print("[3/5] 构建交易日历...")
    trading_days = sorted({r["date"] for rows in universe_data.values() for r in rows})
    print(f"交易日数量: {len(trading_days)}")

    if args.no_market_filter:
        aligned_hs300_allow = {d: True for d in trading_days}
    else:
        print("[3.5/5] 加载沪深300环境过滤...")
        hs300_rows = load_hs300_history(start, end, args.cache_dir)
        print(f"沪深300数据条数: {len(hs300_rows)}")
        if not hs300_rows:
            raise RuntimeError("沪深300指数数据为空，停止回测")
        hs300_allow = build_hs300_filter(hs300_rows)
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
        if idx < 5:
            hs_row = next((r for r in hs300_rows if r.get("date") == day), None) if not args.no_market_filter else None
            if hs_row:
                hs_closes = [float(x["close"]) for x in hs300_rows if x["date"] <= day]
                ma5 = sum(hs_closes[-5:]) / 5.0 if len(hs_closes) >= 5 else float("nan")
                ma10 = sum(hs_closes[-10:]) / 10.0 if len(hs_closes) >= 10 else float("nan")
                ma20 = sum(hs_closes[-20:]) / 20.0 if len(hs_closes) >= 20 else float("nan")
                weak_today = not aligned_hs300_allow.get(day, True)
                print(
                    f"[market-debug] date={day} close={hs_row.get('close')} "
                    f"MA5={ma5:.3f} MA10={ma10:.3f} MA20={ma20:.3f} weak={weak_today}"
                )
        if is_bear_market(day):
            print(f"{day} 跳过（弱势市场）")
            skipped_bear_days += 1
            continue
        for mode in modes:
            if mode == "multi_strategy_v1":
                picked_modes = pick_multi_strategy_v1(day, universe_data, name_map)
                for symbol, real_mode in picked_modes.items():
                    rows = universe_data.get(symbol, [])
                    day_idx = next((i for i, r in enumerate(rows) if r["date"] == day), -1)
                    if day_idx < 0:
                        continue
                    try:
                        tr = run_trade(symbol, day_idx, rows, real_mode, args.fee_rate, args.slippage, args.hold_days, args.take_profit, args.stop_loss)
                        if tr:
                            tr.mode = mode
                            mode_trades[mode].append(tr)
                    except Exception:
                        continue
                continue

            if mode not in ("loose_hold3", "momentum_hold3_v1", "momentum_hold3_v2", "momentum_hold3_v3", "momentum_hold3_v4", "momentum_hold3_v5", "momentum_hold3_v7", "momentum_hold3_v8", "momentum_hold3_v9", "param_mode_v1"):
                continue
            picks = pick_stock_for_day(
                day, universe_data, name_map, mode=mode,
                param_cfg={
                    "pct_min": args.pct_min,
                    "pct_max": args.pct_max,
                    "volume_ratio": args.volume_ratio,
                    "amount_min": args.amount_min,
                    "close_pos_min": args.close_pos_min,
                    "ret3_max": args.ret3_max,
                },
            )
            if not picks:
                continue
            for symbol in picks:
                rows = universe_data.get(symbol, [])
                day_idx = next((i for i, r in enumerate(rows) if r["date"] == day), -1)
                if day_idx < 0:
                    continue
                try:
                    tr = run_trade(symbol, day_idx, rows, mode, args.fee_rate, args.slippage, args.hold_days, args.take_profit, args.stop_loss)
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
        print(f"win_rate,{m['win_rate']:.4f}")
        print(f"profit_loss_ratio,{m['profit_loss_ratio']:.4f}")
        print(f"max_drawdown,{m['max_drawdown']:.4f}")
        print(f"total_trades,{m['total_trades']}")


if __name__ == "__main__":
    main()
