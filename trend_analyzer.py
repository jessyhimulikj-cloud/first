#!/usr/bin/env python3
"""趋势强化分析。"""
from __future__ import annotations

from typing import Any, Dict, List

from strategy_config import ShortTermStrategyConfig


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def add_trend_features(rows: List[Dict[str, Any]], config: ShortTermStrategyConfig | None = None) -> List[Dict[str, Any]]:
    """按股票分组补充 MA、动量、量比、收盘位置等趋势字段。"""
    config = config or ShortTermStrategyConfig()
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("ts_code") or row.get("symbol") or ""), []).append(row)

    out: List[Dict[str, Any]] = []
    for _, items in grouped.items():
        items = sorted(items, key=lambda r: str(r.get("trade_date") or r.get("date") or ""))
        closes = [_to_float(r.get("close")) for r in items]
        vols = [_to_float(r.get("volume") or r.get("vol")) for r in items]
        for i, row in enumerate(items):
            r = dict(row)
            close = closes[i]
            high = _to_float(r.get("high"), close)
            low = _to_float(r.get("low"), close)
            r["ma5"] = sum(closes[i - 4 : i + 1]) / 5.0 if i >= 4 else 0.0
            r["ma10"] = sum(closes[i - 9 : i + 1]) / 10.0 if i >= 9 else 0.0
            r["ma20"] = sum(closes[i - 19 : i + 1]) / 20.0 if i >= 19 else 0.0
            r["ma5_prev"] = sum(closes[i - 5 : i]) / 5.0 if i >= 5 else 0.0
            r["ma10_prev"] = sum(closes[i - 10 : i]) / 10.0 if i >= 10 else 0.0
            r["momentum_3"] = (close / closes[i - 3] - 1.0) * 100.0 if i >= 3 and closes[i - 3] else 0.0
            r["momentum_5"] = (close / closes[i - 5] - 1.0) * 100.0 if i >= 5 and closes[i - 5] else 0.0
            r["ret_10"] = (close / closes[i - 10] - 1.0) * 100.0 if i >= 10 and closes[i - 10] else 0.0
            vol_ma5 = sum(vols[i - 4 : i + 1]) / 5.0 if i >= 4 else 0.0
            r["volume_ratio"] = vols[i] / vol_ma5 if vol_ma5 > 0 else 0.0
            r["close_position"] = (close - low) / (high - low) if high > low else 0.5
            trend = score_trend_strength(r, config)
            r.update(trend)
            out.append(r)
    return out


def score_trend_strength(row: Dict[str, Any], config: ShortTermStrategyConfig | None = None) -> Dict[str, Any]:
    config = config or ShortTermStrategyConfig()
    close = _to_float(row.get("close"))
    ma5 = _to_float(row.get("ma5"))
    ma10 = _to_float(row.get("ma10"))
    ma20 = _to_float(row.get("ma20"))
    ma5_prev = _to_float(row.get("ma5_prev"))
    ma10_prev = _to_float(row.get("ma10_prev"))
    momentum_3 = _to_float(row.get("momentum_3"))
    momentum_5 = _to_float(row.get("momentum_5"))
    volume_ratio = _to_float(row.get("volume_ratio"))
    close_position = _to_float(row.get("close_position"), 0.5)

    score = 0.0
    reasons: List[str] = []
    if ma20 > 0 and close > ma5 > ma10 > ma20:
        score += 0.30
        reasons.append("close>ma5>ma10>ma20")
    elif ma10 > 0 and close > ma5 > ma10:
        score += 0.22
        reasons.append("close>ma5>ma10")
    if ma5 > ma5_prev > 0 and ma10 > ma10_prev > 0:
        score += 0.20
        reasons.append("ma5/ma10同步向上")
    if momentum_3 > 0:
        score += 0.12
        reasons.append("3日动量为正")
    if config.momentum_5_min <= momentum_5 <= config.momentum_5_max:
        score += 0.18
        reasons.append("5日涨幅处于短线强化区间")
    if config.volume_ratio_min <= volume_ratio <= config.volume_ratio_max:
        score += 0.12
        reasons.append("温和放量")
    elif volume_ratio > config.volume_ratio_max:
        score += 0.05
        reasons.append("量能偏高需防分歧")
    if close_position >= config.close_position_min:
        score += 0.08
        reasons.append("收盘位置较强")

    return {
        "trend_strength_score": round(min(score, 1.0), 4),
        "trend_reason": "；".join(reasons) if reasons else "趋势强化不足",
    }
