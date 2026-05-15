#!/usr/bin/env python3
"""市场情绪周期分析。"""
from __future__ import annotations

from typing import Any, Dict, List


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def analyze_market_sentiment(rows: List[Dict[str, Any]], hs300_rows: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    total = len(rows)
    if total == 0:
        return {
            "market_sentiment": "ice_point",
            "sentiment_cycle_score": 0.0,
            "sentiment_reason": "无可用市场数据",
            "risk_level": "high",
            "up_count": 0,
            "down_count": 0,
            "limit_up_count": 0,
            "limit_down_count": 0,
            "total_amount": 0.0,
        }

    pct = [_to_float(r.get("pct_chg")) for r in rows]
    up_count = sum(1 for x in pct if x > 0)
    down_count = sum(1 for x in pct if x < 0)
    limit_up_count = sum(1 for x in pct if x >= 9.5)
    limit_down_count = sum(1 for x in pct if x <= -9.5)
    strong_count = sum(1 for x in pct if x >= 5)
    total_amount = sum(_to_float(r.get("amount")) for r in rows)
    up_ratio = up_count / total if total else 0.0
    limit_up_ratio = limit_up_count / total if total else 0.0
    limit_down_ratio = limit_down_count / total if total else 0.0

    index_trend_ok = True
    if hs300_rows and len(hs300_rows) >= 20:
        closes = [_to_float(r.get("close")) for r in hs300_rows[-20:]]
        ma20 = sum(closes) / len(closes) if closes else 0.0
        index_trend_ok = closes[-1] >= ma20 if ma20 else True

    raw_score = up_ratio * 0.45 + min(limit_up_ratio * 10, 0.25) + min(strong_count / max(total, 1) * 5, 0.20)
    raw_score += 0.10 if index_trend_ok else -0.10
    raw_score -= min(limit_down_ratio * 10, 0.30)
    score = max(0.0, min(1.0, raw_score))

    if limit_down_ratio > 0.03 or (up_ratio < 0.30 and not index_trend_ok):
        cycle, risk = "decline", "high"
    elif up_ratio < 0.35 and limit_up_count < max(3, total * 0.005):
        cycle, risk = "ice_point", "high"
    elif up_ratio < 0.50:
        cycle, risk = "recovery", "medium"
    elif up_ratio > 0.75 and limit_up_ratio > 0.02:
        cycle, risk = "climax", "medium_high"
    else:
        cycle, risk = "main_rise", "medium"

    reason = f"上涨{up_count}家、下跌{down_count}家、涨停/接近涨停{limit_up_count}家、跌停/接近跌停{limit_down_count}家，沪深300趋势{'偏强' if index_trend_ok else '偏弱'}。"
    return {
        "market_sentiment": cycle,
        "sentiment_cycle_score": round(score, 4),
        "sentiment_reason": reason,
        "risk_level": risk,
        "up_count": up_count,
        "down_count": down_count,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "total_amount": round(total_amount, 4),
    }
