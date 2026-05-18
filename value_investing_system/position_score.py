"""Company competitive-position scoring inside each industry."""
from __future__ import annotations

import numpy as np
import pandas as pd


def add_position_score(df: pd.DataFrame) -> pd.DataFrame:
    """Score market-cap rank, revenue rank, R&D intensity, and gross margin.

    Deep qualitative leader checks are intentionally left to the AI layer; the
    first quantitative version awards up to 80 points from available data.
    """
    result = df.copy()
    result["position_score"] = 0.0
    if result.empty:
        return result

    for industry, idx in result.groupby("industry", dropna=False).groups.items():
        group = result.loc[idx]
        n = max(len(group), 1)
        top_cut = max(int(np.ceil(n * 0.30)), 1)

        market_leaders = group["market_cap"].rank(method="min", ascending=False) <= top_cut
        revenue_leaders = group["revenue"].rank(method="min", ascending=False) <= top_cut
        rd_median = group["rd_expense_rate"].median(skipna=True)
        gm_median = group["gross_margin"].median(skipna=True)

        result.loc[group.index[market_leaders.fillna(False)], "position_score"] += 25
        result.loc[group.index[revenue_leaders.fillna(False)], "position_score"] += 20
        if pd.notna(rd_median):
            result.loc[group.index[group["rd_expense_rate"] > rd_median], "position_score"] += 20
        if pd.notna(gm_median):
            result.loc[group.index[group["gross_margin"] > gm_median], "position_score"] += 15

    return result
