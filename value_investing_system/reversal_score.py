"""Early turnaround-signal scoring."""
from __future__ import annotations

import pandas as pd


def calculate_reversal(financial: pd.DataFrame, income: pd.DataFrame, cashflow: pd.DataFrame, daily: pd.DataFrame) -> float:
    """Score operational, cash-flow, R&D, and price-stabilization improvements."""
    score = 0.0
    fin = financial.sort_values("end_date") if not financial.empty else financial
    inc = income.sort_values("end_date") if not income.empty else income
    cf = cashflow.sort_values("end_date") if not cashflow.empty else cashflow

    if _latest_better(fin, "or_yoy"):
        score += 20
    if _latest_better(fin, "netprofit_yoy") or _loss_narrowing(inc):
        score += 20
    if _latest_better(cf, "n_cashflow_act"):
        score += 20
    if _latest_better(fin, "grossprofit_margin"):
        score += 15
    if _price_stabilized(daily):
        score += 15
    if _rd_continuing(fin):
        score += 10
    return float(min(score, 100))


def _latest_better(df: pd.DataFrame, column: str) -> bool:
    if df.empty or column not in df:
        return False
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    return len(values) >= 2 and values.iloc[-1] > values.iloc[-2]


def _loss_narrowing(income: pd.DataFrame) -> bool:
    if income.empty or "n_income_attr_p" not in income:
        return False
    values = pd.to_numeric(income["n_income_attr_p"], errors="coerce").dropna()
    return len(values) >= 2 and values.iloc[-2] < 0 and values.iloc[-1] > values.iloc[-2]


def _price_stabilized(daily: pd.DataFrame) -> bool:
    if daily.empty or "close" not in daily:
        return False
    closes = pd.to_numeric(daily.sort_values("trade_date")["close"], errors="coerce").dropna()
    if len(closes) < 120:
        return False
    latest = closes.iloc[-1]
    ma60 = closes.tail(60).mean()
    ma120 = closes.tail(120).mean()
    return latest > ma60 or latest > ma120


def _rd_continuing(financial: pd.DataFrame) -> bool:
    for col in ["rd_exp", "rd_expense", "rd_exp_ratio"]:
        if col in financial:
            values = pd.to_numeric(financial[col], errors="coerce").dropna()
            return len(values) >= 2 and values.tail(2).min() > 0
    return False
