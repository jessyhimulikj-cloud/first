#!/usr/bin/env python3
"""Tushare 数据获取与缓存。"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List

CACHE_DIR = Path(".cache_tushare")
STD_COLS = ["date", "trade_date", "ts_code", "symbol", "name", "industry", "open", "high", "low", "close", "pre_close", "volume", "amount", "pct_chg", "turnover_rate", "volume_ratio", "main_net_inflow"]


def _import_pandas() -> Any:
    try:
        import pandas as pd
        return pd
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("未安装 pandas，请执行: pip install pandas") from exc


def _import_tushare(token: str | None = None) -> Any:
    token = (token or os.getenv("TUSHARE_TOKEN", "")).strip()
    if not token:
        raise RuntimeError("缺少环境变量 TUSHARE_TOKEN")
    try:
        import tushare as ts
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("未安装 tushare，请执行: pip install tushare") from exc
    ts.set_token(token)
    return ts


def _pro_api() -> Any:
    return _import_tushare().pro_api()


def _to_ts_code(symbol: str) -> str | None:
    s = str(symbol).strip()
    if s.endswith((".SZ", ".SH", ".BJ")):
        return s
    if len(s) != 6 or (not s.isdigit()):
        print(f"[WARN] 无效股票代码格式，跳过: {symbol}")
        return None
    if s.startswith(("000", "001", "002", "003", "300", "301")):
        return f"{s}.SZ"
    if s.startswith(("600", "601", "603", "605", "688")):
        return f"{s}.SH"
    if s.startswith(("4", "8")):
        return f"{s}.BJ"
    print(f"[WARN] 未知股票代码前缀，跳过: {symbol}")
    return None


def _symbol_from_ts_code(ts_code: str) -> str:
    return str(ts_code).split(".")[0]


def _read_cache(path: Path) -> Any | None:
    pd = _import_pandas()
    if path.exists():
        try:
            df = pd.read_csv(path)
            if not df.empty:
                return df
        except Exception:
            return None
    return None


def _write_cache(df: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")


def _call_with_retry(func: Any, max_retries: int = 3, request_interval: float = 0.4, **kwargs: Any) -> Any:
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            out = func(**kwargs)
            time.sleep(request_interval)
            return out
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            time.sleep(10 if ("频率" in str(exc) or "rate" in msg or "too many" in msg) else request_interval)
            if attempt >= max_retries:
                raise
    if last_exc:
        raise last_exc


def load_stock_basic_tushare(cache_dir: Path | str = CACHE_DIR, force: bool = False) -> Any:
    pd = _import_pandas()
    path = Path(cache_dir) / "stock_basic.csv"
    if not force:
        cached = _read_cache(path)
        if cached is not None:
            return cached
    pro = _pro_api()
    df = _call_with_retry(
        pro.stock_basic,
        exchange="",
        list_status="L",
        fields="ts_code,symbol,name,area,industry,market,list_date",
    )
    if df is None:
        return pd.DataFrame(columns=["ts_code", "symbol", "name", "industry"])
    _write_cache(df, path)
    return df


def load_daily_tushare(ts_code: str, start_date: str, end_date: str, cache_dir: Path | str = CACHE_DIR, force: bool = False) -> Any:
    pd = _import_pandas()
    code = _to_ts_code(ts_code)
    if not code:
        return pd.DataFrame()
    path = Path(cache_dir) / "daily" / f"{code}_{start_date}_{end_date}.csv"
    if not force:
        cached = _read_cache(path)
        if cached is not None:
            return cached
    pro = _pro_api()
    df = _call_with_retry(pro.daily, ts_code=code, start_date=start_date, end_date=end_date)
    if df is None:
        df = pd.DataFrame()
    _write_cache(df, path)
    return df


def load_daily_basic_tushare(ts_code: str = "", start_date: str = "", end_date: str = "", trade_date: str = "", cache_dir: Path | str = CACHE_DIR, force: bool = False) -> Any:
    pd = _import_pandas()
    key = trade_date or f"{ts_code}_{start_date}_{end_date}"
    path = Path(cache_dir) / "daily_basic" / f"{key}.csv"
    if not force:
        cached = _read_cache(path)
        if cached is not None:
            return cached
    pro = _pro_api()
    kwargs = {"fields": "ts_code,trade_date,turnover_rate,volume_ratio,pe,pb,total_mv,circ_mv"}
    if trade_date:
        kwargs["trade_date"] = trade_date
    else:
        kwargs.update({"ts_code": _to_ts_code(ts_code) or ts_code, "start_date": start_date, "end_date": end_date})
    df = _call_with_retry(pro.daily_basic, **kwargs)
    if df is None:
        df = pd.DataFrame()
    _write_cache(df, path)
    return df


def load_moneyflow_tushare(ts_code: str = "", start_date: str = "", end_date: str = "", trade_date: str = "", cache_dir: Path | str = CACHE_DIR, force: bool = False) -> Any:
    pd = _import_pandas()
    key = trade_date or f"{ts_code}_{start_date}_{end_date}"
    path = Path(cache_dir) / "moneyflow" / f"{key}.csv"
    if not force:
        cached = _read_cache(path)
        if cached is not None:
            return cached
    pro = _pro_api()
    kwargs: dict[str, Any] = {}
    if trade_date:
        kwargs["trade_date"] = trade_date
    else:
        kwargs.update({"ts_code": _to_ts_code(ts_code) or ts_code, "start_date": start_date, "end_date": end_date})
    df = _call_with_retry(pro.moneyflow, **kwargs)
    if df is None:
        df = pd.DataFrame()
    _write_cache(df, path)
    return df


def load_hs300_tushare(start_date: str, end_date: str, cache_dir: Path | str = CACHE_DIR, force: bool = False) -> Any:
    pd = _import_pandas()
    path = Path(cache_dir) / "index" / f"000300.SH_{start_date}_{end_date}.csv"
    if not force:
        cached = _read_cache(path)
        if cached is not None:
            return cached
    pro = _pro_api()
    df = _call_with_retry(pro.index_daily, ts_code="000300.SH", start_date=start_date, end_date=end_date)
    if df is None:
        df = pd.DataFrame()
    _write_cache(df, path)
    return df


def load_trade_calendar_tushare(start_date: str, end_date: str, cache_dir: Path | str = CACHE_DIR, force: bool = False) -> Any:
    pd = _import_pandas()
    path = Path(cache_dir) / "trade_cal" / f"{start_date}_{end_date}.csv"
    if not force:
        cached = _read_cache(path)
        if cached is not None:
            return cached
    pro = _pro_api()
    df = _call_with_retry(pro.trade_cal, exchange="SSE", start_date=start_date, end_date=end_date)
    if df is None:
        df = pd.DataFrame()
    _write_cache(df, path)
    return df


def normalize_daily_df(df: Any, basic_df: Any | None = None, daily_basic_df: Any | None = None, moneyflow_df: Any | None = None) -> Any:
    pd = _import_pandas()
    if df is None or df.empty:
        return pd.DataFrame(columns=STD_COLS)
    out = df.copy()
    rename = {"vol": "volume"}
    out = out.rename(columns=rename)
    if "date" not in out.columns and "trade_date" in out.columns:
        out["date"] = out["trade_date"]
    if "symbol" not in out.columns and "ts_code" in out.columns:
        out["symbol"] = out["ts_code"].astype(str).str.split(".").str[0]
    if basic_df is not None and not basic_df.empty:
        keep = [c for c in ["ts_code", "name", "industry"] if c in basic_df.columns]
        out = out.merge(basic_df[keep].drop_duplicates("ts_code"), on="ts_code", how="left")
    for extra in (daily_basic_df, moneyflow_df):
        if extra is not None and not extra.empty and "ts_code" in extra.columns:
            join_cols = [c for c in ["ts_code", "trade_date"] if c in extra.columns and c in out.columns]
            if join_cols:
                out = out.merge(extra, on=join_cols, how="left", suffixes=("", "_extra"))
    if "main_net_inflow" not in out.columns:
        candidates = [c for c in ["net_mf_amount", "buy_lg_amount", "buy_elg_amount"] if c in out.columns]
        out["main_net_inflow"] = out[candidates].sum(axis=1) if candidates else 0
    for c in STD_COLS:
        if c not in out.columns:
            out[c] = "" if c in {"date", "trade_date", "ts_code", "symbol", "name", "industry"} else 0
    for c in ["open", "high", "low", "close", "pre_close", "volume", "amount", "pct_chg", "turnover_rate", "volume_ratio", "main_net_inflow"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)
    out["amount"] = out["amount"] * 1000.0  # Tushare amount 单位通常为千元，统一为元
    return out[STD_COLS].sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def load_history_tushare(
    symbol: str,
    months: int = 12,
    data_dir: Path | str = "data",
    max_retries: int = 3,
    request_interval: float = 0.4,
) -> Any:
    """向后兼容：下载单只股票历史日线到 data/{symbol}.csv。"""
    pd = _import_pandas()
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)
    symbol6 = _symbol_from_ts_code(symbol)
    csv_path = data_path / f"{symbol6}.csv"
    if csv_path.exists():
        df_cached = pd.read_csv(csv_path)
        if not df_cached.empty:
            return df_cached

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=31 * months)
    end_date = end_dt.strftime("%Y%m%d")
    start_date = start_dt.strftime("%Y%m%d")
    df = load_daily_tushare(symbol, start_date, end_date, cache_dir=CACHE_DIR, force=False)
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"])
    out = normalize_daily_df(df)
    out = out[["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]].copy()
    out.to_csv(csv_path, index=False, encoding="utf-8")
    time.sleep(request_interval)
    return out


def load_cached_market_rows(data_dir: Path | str = "data") -> List[dict[str, Any]]:
    """从 data/*.csv 读取每只股票最近一行，供无 token 时离线选股。"""
    pd = _import_pandas()
    rows: List[dict[str, Any]] = []
    for p in Path(data_dir).glob("*.csv"):
        if not (len(p.stem) == 6 and p.stem.isdigit()):
            continue
        try:
            df = pd.read_csv(p)
        except Exception:
            continue
        if df.empty:
            continue
        df = df.sort_values("date") if "date" in df.columns else df
        row = df.iloc[-1].to_dict()
        ts_code = _to_ts_code(p.stem) or p.stem
        row["ts_code"] = ts_code
        row["symbol"] = p.stem
        row.setdefault("name", p.stem)
        row.setdefault("industry", "缓存股票")
        row.setdefault("trade_date", str(row.get("date", "")).replace("-", ""))
        row.setdefault("amount", 0)
        rows.append(row)
    return rows
