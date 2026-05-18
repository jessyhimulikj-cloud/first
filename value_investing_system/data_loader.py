"""Tushare data access with CSV caching and graceful degradation.

The loader prefers local CSV files, refreshes stale files, and logs warnings
instead of crashing when an optional dataset is unavailable. This keeps the first
screening pass usable even when a few stocks have incomplete disclosures.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from . import config

LOGGER = logging.getLogger(__name__)


class DataLoader:
    """Small wrapper around Tushare Pro APIs plus local CSV caches."""

    def __init__(self, refresh: bool = False, cache_days: int = config.DEFAULT_CACHE_DAYS) -> None:
        self.refresh = refresh
        self.cache_days = cache_days
        self._pro = None

    @property
    def pro(self):
        """Lazily initialize Tushare only when data is requested."""
        if self._pro is None:
            if not config.TUSHARE_TOKEN:
                raise RuntimeError("TUSHARE_TOKEN is missing. Please create .env from .env.example.")
            import tushare as ts

            ts.set_token(config.TUSHARE_TOKEN)
            self._pro = ts.pro_api(config.TUSHARE_TOKEN)
        return self._pro

    def cache_valid(self, path: Path) -> bool:
        if self.refresh or not path.exists():
            return False
        modified = datetime.fromtimestamp(path.stat().st_mtime)
        return datetime.now() - modified <= timedelta(days=self.cache_days)

    def read_or_fetch(self, path: Path, fetcher: Callable[[], pd.DataFrame], required: bool = False) -> pd.DataFrame:
        """Read a cache or call ``fetcher``; return an empty frame on recoverable failures."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.cache_valid(path):
            return pd.read_csv(path, dtype={"ts_code": str, "trade_date": str, "ann_date": str, "end_date": str})
        try:
            df = fetcher()
            if df is None:
                df = pd.DataFrame()
            df.to_csv(path, index=False)
            return df
        except Exception as exc:  # noqa: BLE001 - surface clear warnings without interrupting screening
            message = f"Failed to fetch {path.name}: {exc}"
            if required and not path.exists():
                raise RuntimeError(message) from exc
            LOGGER.warning(message)
            if path.exists():
                return pd.read_csv(path, dtype={"ts_code": str, "trade_date": str, "ann_date": str, "end_date": str})
            return pd.DataFrame()

    def stock_basic(self) -> pd.DataFrame:
        path = config.CACHE_DIR / "stock_basic.csv"
        return self.read_or_fetch(
            path,
            lambda: self.pro.stock_basic(
                exchange="",
                list_status="L",
                fields="ts_code,symbol,name,area,industry,market,list_date",
            ),
            required=True,
        )

    def daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        path = config.DAILY_DIR / f"{ts_code}_{start_date}_{end_date}.csv"
        return self.read_or_fetch(path, lambda: self.pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date))

    def daily_basic(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        path = config.VALUATION_DIR / f"daily_basic_{ts_code}_{start_date}_{end_date}.csv"
        fields = "ts_code,trade_date,close,turnover_rate,volume_ratio,pe,pe_ttm,pb,total_mv,circ_mv"
        return self.read_or_fetch(
            path,
            lambda: self.pro.daily_basic(ts_code=ts_code, start_date=start_date, end_date=end_date, fields=fields),
        )

    def fina_indicator(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        path = config.FINANCIAL_DIR / f"fina_indicator_{ts_code}_{start_date}_{end_date}.csv"
        return self.read_or_fetch(path, lambda: self.pro.fina_indicator(ts_code=ts_code, start_date=start_date, end_date=end_date))

    def income(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        path = config.FINANCIAL_DIR / f"income_{ts_code}_{start_date}_{end_date}.csv"
        return self.read_or_fetch(path, lambda: self.pro.income(ts_code=ts_code, start_date=start_date, end_date=end_date))

    def balancesheet(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        path = config.FINANCIAL_DIR / f"balancesheet_{ts_code}_{start_date}_{end_date}.csv"
        return self.read_or_fetch(path, lambda: self.pro.balancesheet(ts_code=ts_code, start_date=start_date, end_date=end_date))

    def cashflow(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        path = config.FINANCIAL_DIR / f"cashflow_{ts_code}_{start_date}_{end_date}.csv"
        return self.read_or_fetch(path, lambda: self.pro.cashflow(ts_code=ts_code, start_date=start_date, end_date=end_date))

    def hs300_daily(self, start_date: str, end_date: str) -> pd.DataFrame:
        path = config.CACHE_DIR / f"hs300_{start_date}_{end_date}.csv"
        return self.read_or_fetch(path, lambda: self.pro.index_daily(ts_code="399300.SZ", start_date=start_date, end_date=end_date))


def as_float(value: Any, default: float = 0.0) -> float:
    """Safely convert missing/nonnumeric values to a scoring default."""
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
