#!/usr/bin/env python3
from __future__ import annotations

import time
import importlib
from pathlib import Path
from typing import Any

STD_COLS = ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]


def _normalize(df: Any) -> Any:
    pd = importlib.import_module("pandas")
    col_map = {
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
        "涨跌幅": "pct_chg",
    }
    out = df.rename(columns=col_map).copy()
    for c in STD_COLS:
        if c not in out.columns:
            out[c] = 0
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date"])
    for c in ["open", "high", "low", "close", "volume", "amount", "pct_chg"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)
    out = out[STD_COLS].sort_values("date").reset_index(drop=True)
    return out


def load_history(symbol: str, start_date: str, end_date: str, data_dir: Path = Path("data")) -> Any:
    pd = importlib.import_module("pandas")
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / f"{symbol}.csv"

    if csv_path.exists():
        try:
            cached = pd.read_csv(csv_path)
            cached = _normalize(cached)
            return cached
        except Exception:
            pass

    df = pd.DataFrame()
    ak = importlib.import_module("akshare")
    for _ in range(3):
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
            if df is not None and not df.empty:
                break
        except Exception:
            time.sleep(1)
            continue
        time.sleep(1)

    if df is None or df.empty:
        print(f"[WARN] {symbol} 无历史数据，跳过")
        return pd.DataFrame(columns=STD_COLS)

    out = _normalize(df)
    out.to_csv(csv_path, index=False)
    time.sleep(0.5)
    return out
