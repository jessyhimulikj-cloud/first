#!/usr/bin/env python3
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _import_pandas() -> Any:
    try:
        import pandas as pd

        return pd
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("未安装 pandas，请执行: pip install pandas") from exc


def _import_tushare(token: str) -> Any:
    try:
        import tushare as ts
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("未安装 tushare，请执行: pip install tushare") from exc
    ts.set_token(token)
    return ts


def _to_ts_code(symbol: str) -> str:
    s = str(symbol).strip()
    if len(s) != 6 or (not s.isdigit()):
        raise ValueError(f"symbol 格式错误: {symbol}")
    if s.startswith(("000", "001", "002", "300", "301")):
        return f"{s}.SZ"
    if s.startswith(("600", "601", "603", "605", "688")):
        return f"{s}.SH"
    raise ValueError(f"不支持的 symbol 前缀: {symbol}")


def load_history_tushare(symbol: str, months: int = 12, data_dir: Path | str = "data") -> Any:
    pd = _import_pandas()
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)
    csv_path = data_path / f"{symbol}.csv"

    if csv_path.exists():
        df_cached = pd.read_csv(csv_path)
        if not df_cached.empty:
            return df_cached

    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("缺少环境变量 TUSHARE_TOKEN")

    ts = _import_tushare(token)
    pro = ts.pro_api()

    ts_code = _to_ts_code(symbol)
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=31 * months)
    end_date = end_dt.strftime("%Y%m%d")
    start_date = start_dt.strftime("%Y%m%d")

    df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"])

    rename_map = {
        "trade_date": "date",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "vol": "volume",
        "amount": "amount",
        "pct_chg": "pct_chg",
    }
    df = df.rename(columns=rename_map)
    for c in ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]:
        if c not in df.columns:
            df[c] = 0
    df = df[["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y%m%d")
    for c in ["open", "high", "low", "close", "volume", "amount", "pct_chg"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    df.to_csv(csv_path, index=False, encoding="utf-8")
    return df

