"""A-share universe construction and risk-name filtering."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from . import config
from .data_loader import DataLoader


def build_universe(loader: DataLoader) -> pd.DataFrame:
    """Fetch listed A shares and remove ST, delisting, very new, and invalid names."""
    stocks = loader.stock_basic()
    if stocks.empty:
        return stocks

    df = stocks.copy()
    df["name"] = df["name"].fillna("")
    risk_name = df["name"].str.contains("ST|退", case=False, regex=True, na=False)
    cutoff = (datetime.now() - timedelta(days=365 * config.MIN_LISTING_YEARS)).strftime("%Y%m%d")
    df = df.loc[~risk_name & (df["list_date"].astype(str) <= cutoff)]
    df = df[["ts_code", "name", "industry", "list_date", "market"]].copy()
    df.to_csv(config.CACHE_DIR / "universe.csv", index=False)
    return df.reset_index(drop=True)
