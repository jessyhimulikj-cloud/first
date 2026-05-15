#!/usr/bin/env python3
"""龙头股识别。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _rank_score(rank: int, total: int) -> float:
    if total <= 1:
        return 1.0
    return max(0.0, 1.0 - (rank - 1) / (total - 1))


def score_leaders(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        grouped[str(r.get("main_theme") or r.get("industry") or "未分类")].append(r)

    out: List[Dict[str, Any]] = []
    for _, items in grouped.items():
        by_mom = sorted(items, key=lambda r: _to_float(r.get("momentum_5")), reverse=True)
        by_amount = sorted(items, key=lambda r: _to_float(r.get("amount")), reverse=True)
        mom_rank = {id(r): i for i, r in enumerate(by_mom, start=1)}
        amount_rank = {id(r): i for i, r in enumerate(by_amount, start=1)}
        total = len(items)
        avg_mom3 = sum(_to_float(r.get("momentum_3")) for r in items) / max(total, 1)
        for row in items:
            mr = mom_rank[id(row)]
            ar = amount_rank[id(row)]
            theme_strength = _to_float(row.get("hot_theme_score"))
            rel3 = 1.0 if _to_float(row.get("momentum_3")) >= avg_mom3 else 0.4
            score = (
                theme_strength * 0.25
                + _rank_score(mr, total) * 0.20
                + _rank_score(ar, total) * 0.15
                + min(_to_float(row.get("volume_ratio")) / 2.0, 1.0) * 0.15
                + _to_float(row.get("trend_strength_score")) * 0.15
                + rel3 * 0.10
            )
            r = dict(row)
            r["leader_rank"] = mr
            r["leader_score"] = round(min(score, 1.0), 4)
            r["is_leader"] = mr <= max(1, int(total * 0.2 + 0.999))
            r["leader_reason"] = f"主线内5日涨幅排名第{mr}，成交额排名第{ar}，相对强度{'较强' if rel3 >= 1 else '一般'}。"
            out.append(r)
    return out
