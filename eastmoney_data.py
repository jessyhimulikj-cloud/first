#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from eastmoney_client import request_eastmoney_skill

STD_COLS = ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
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
    return out[STD_COLS].sort_values("date").reset_index(drop=True)


def load_history(symbol: str, months: int = 12, data_dir: Path = Path("data")) -> pd.DataFrame:
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / f"{symbol}.csv"
    if csv_path.exists():
        try:
            return _normalize_df(pd.read_csv(csv_path))
        except Exception:
            pass

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=31 * months)
    start = start_dt.strftime("%Y%m%d")
    end = end_dt.strftime("%Y%m%d")

    query = (
        f"A股{symbol}最近{months}个月历史日线，开始{start}，结束{end}，"
        "字段:日期 开盘价 最高价 最低价 收盘价 成交量 成交额 涨跌幅"
    )
    payload = request_eastmoney_skill(query)
    if not payload:
        return pd.DataFrame(columns=STD_COLS)

    rows = ((payload.get("data") or {}).get("rows")) or []
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame(columns=STD_COLS)

    out = _normalize_df(pd.DataFrame(rows))
    if not out.empty:
        out.to_csv(csv_path, index=False)
    return out
