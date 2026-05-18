"""Industry prospect scoring based on configurable long-term themes."""
from __future__ import annotations

import pandas as pd

from .config import INDUSTRY_SCORE


def score_industry_name(industry: str | float | None) -> float:
    """Return configured score, using substring matching and a neutral default."""
    text = "" if pd.isna(industry) else str(industry)
    for keyword, score in INDUSTRY_SCORE.items():
        if keyword in text:
            return float(score)
    return 50.0


def add_industry_score(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["industry_score"] = result["industry"].apply(score_industry_name)
    return result
