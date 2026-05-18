"""Distress and market-coldness scoring."""
from __future__ import annotations

import numpy as np
import pandas as pd


def percentile_of_current(series: pd.Series, current: float) -> float:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    values = values[values > 0]
    if values.empty or pd.isna(current) or current <= 0:
        return 0.5
    return float((values <= current).mean())


def calculate_distress(daily: pd.DataFrame, valuation: pd.DataFrame, hs300: pd.DataFrame) -> dict[str, float | bool]:
    daily = daily.sort_values("trade_date") if not daily.empty else daily
    valuation = valuation.sort_values("trade_date") if not valuation.empty else valuation
    latest_close = pd.to_numeric(daily.get("close", pd.Series(dtype=float)), errors="coerce").dropna()
    current_price = float(latest_close.iloc[-1]) if not latest_close.empty else 0.0
    high_3y = float(latest_close.max()) if not latest_close.empty else 0.0
    drawdown = (current_price / high_3y - 1) if high_3y > 0 else 0.0

    pe_col = "pe_ttm" if "pe_ttm" in valuation.columns else "pe"
    pe_series = pd.to_numeric(valuation.get(pe_col, pd.Series(dtype=float)), errors="coerce")
    pb_series = pd.to_numeric(valuation.get("pb", pd.Series(dtype=float)), errors="coerce")
    pe = float(pe_series.dropna().iloc[-1]) if not pe_series.dropna().empty else 0.0
    pb = float(pb_series.dropna().iloc[-1]) if not pb_series.dropna().empty else 0.0
    pe_pct = percentile_of_current(pe_series, pe)
    pb_pct = percentile_of_current(pb_series, pb)

    stock_return = _period_return(daily)
    hs300_return = _period_return(hs300)
    underperform = stock_return < hs300_return

    drawdown_score = min(abs(drawdown) / 0.7 * 100, 100)
    valuation_low_score = 100 - pe_pct * 100
    underperform_score = max(0, min((hs300_return - stock_return) * 100, 100))
    distress_score = drawdown_score * 0.5 + valuation_low_score * 0.3 + underperform_score * 0.2

    return {
        "current_price": current_price,
        "drawdown_from_3y_high": drawdown,
        "pe": pe,
        "pb": pb,
        "pe_percentile_3y": pe_pct,
        "pb_percentile_3y": pb_pct,
        "stock_return_1y": stock_return,
        "hs300_return_1y": hs300_return,
        "underperform_hs300": underperform,
        "distress_score": float(distress_score),
    }


def _period_return(df: pd.DataFrame) -> float:
    if df.empty or "close" not in df:
        return 0.0
    closes = pd.to_numeric(df.sort_values("trade_date")["close"], errors="coerce").dropna()
    if len(closes) < 2:
        return 0.0
    start_idx = max(0, len(closes) - 250)
    start = closes.iloc[start_idx]
    end = closes.iloc[-1]
    return float(end / start - 1) if start else 0.0
