"""Historical low-valuation scoring."""
from __future__ import annotations

import pandas as pd


def add_valuation_score(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    pe_low = 100 - result["pe_percentile_3y"].fillna(0.5) * 100
    pb_low = 100 - result["pb_percentile_3y"].fillna(0.5) * 100
    result["valuation_score"] = pe_low * 0.6 + pb_low * 0.4
    return result
