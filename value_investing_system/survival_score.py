"""Financial survival checks for excluding obvious blow-up risks."""
from __future__ import annotations

import pandas as pd


def score_survival(row: pd.Series) -> tuple[float, bool, str]:
    """Return (score, pass_hard_filters, reason)."""
    score = 100.0
    reasons: list[str] = []
    debt_to_assets = _num(row.get("debt_to_assets"), 0)
    net_assets = _num(row.get("net_assets"), 0)
    cash_to_short_debt = _num(row.get("cash_to_short_debt"), 0)
    ocf_positive_years = int(_num(row.get("ocf_positive_years_3y"), 0))

    hard_failures = []
    if net_assets <= 0:
        hard_failures.append("净资产为负或缺失")
    if debt_to_assets >= 75:
        hard_failures.append("资产负债率过高")
    if ocf_positive_years < 1:
        hard_failures.append("近三年经营现金流均未转正")
    if cash_to_short_debt <= 0.5:
        hard_failures.append("货币资金/短债不足")

    if 60 <= debt_to_assets < 75:
        score -= 15
        reasons.append("资产负债率处于60%-75%压力区间")
    if ocf_positive_years == 1:
        score -= 15
        reasons.append("近三年经营现金流仅一年为正")
    if 0.5 < cash_to_short_debt < 1:
        score -= 15
        reasons.append("货币资金/短债低于1")
    if bool(row.get("net_profit_declining", False)):
        score -= 10
        reasons.append("净利润连续下滑")
    if _num(row.get("goodwill_to_net_assets"), 0) > 0.3:
        score -= 10
        reasons.append("商誉占净资产比例较高")

    score = max(score, 0.0)
    pass_filter = not hard_failures and score >= 50
    reason = "; ".join(hard_failures + reasons) or "财务生存能力通过初筛"
    return score, pass_filter, reason


def add_survival_score(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    scored = result.apply(score_survival, axis=1)
    result["survival_score"] = [item[0] for item in scored]
    result["survival_pass"] = [item[1] for item in scored]
    result["survival_reason"] = [item[2] for item in scored]
    return result


def _num(value, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
