#!/usr/bin/env python3
"""主线热点分析。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm_map(values: Dict[str, float]) -> Dict[str, float]:
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: 0.5 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def analyze_hot_themes(rows: List[Dict[str, Any]], top_pct: float = 0.2) -> Tuple[List[Dict[str, Any]], set[str]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        theme = str(r.get("main_theme") or r.get("industry") or "未分类").strip() or "未分类"
        grouped[theme].append(r)

    pct1: Dict[str, float] = {}
    pct3: Dict[str, float] = {}
    pct5: Dict[str, float] = {}
    amount: Dict[str, float] = {}
    strong: Dict[str, float] = {}
    limit_up: Dict[str, float] = {}
    for theme, items in grouped.items():
        n = max(len(items), 1)
        pct1[theme] = sum(_to_float(x.get("pct_chg")) for x in items) / n
        pct3[theme] = sum(_to_float(x.get("momentum_3")) for x in items) / n
        pct5[theme] = sum(_to_float(x.get("momentum_5")) for x in items) / n
        amount[theme] = sum(_to_float(x.get("amount")) for x in items)
        strong[theme] = sum(1 for x in items if _to_float(x.get("pct_chg")) >= 5 or _to_float(x.get("momentum_3")) >= 8)
        limit_up[theme] = sum(1 for x in items if _to_float(x.get("pct_chg")) >= 9.5)

    norms = [_norm_map(m) for m in (pct1, pct3, pct5, amount, strong)]
    themes: List[Dict[str, Any]] = []
    for theme in grouped:
        score = sum(n.get(theme, 0.0) * 0.20 for n in norms)
        themes.append(
            {
                "theme_name": theme,
                "theme_strength": round(score, 4),
                "hot_theme_score": round(score, 4),
                "pct_chg_1d": round(pct1[theme], 4),
                "pct_chg_3d": round(pct3[theme], 4),
                "pct_chg_5d": round(pct5[theme], 4),
                "amount_ratio": round(amount[theme] / max(sum(amount.values()), 1.0), 4),
                "strong_stock_count": int(strong[theme]),
                "limit_up_count": int(limit_up[theme]),
            }
        )
    themes.sort(key=lambda x: float(x["hot_theme_score"]), reverse=True)
    for idx, t in enumerate(themes, start=1):
        t["rank"] = idx
        t["theme_rank"] = idx

    keep_n = max(1, int(len(themes) * top_pct + 0.999)) if themes else 0
    hot_names = {str(t["theme_name"]) for t in themes[:keep_n]}
    return themes, hot_names


def attach_theme_scores(rows: List[Dict[str, Any]], themes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_name = {str(t["theme_name"]): t for t in themes}
    out: List[Dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        theme = str(r.get("main_theme") or r.get("industry") or "未分类").strip() or "未分类"
        info = by_name.get(theme, {})
        r["main_theme"] = theme
        r["theme_rank"] = info.get("theme_rank", 9999)
        r["theme_strength"] = info.get("theme_strength", 0.0)
        r["hot_theme_score"] = info.get("hot_theme_score", 0.0)
        out.append(r)
    return out
