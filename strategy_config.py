#!/usr/bin/env python3
"""短线策略参数配置。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ShortTermStrategyConfig:
    """主线热点 + 情绪周期 + 龙头 + 趋势强化短线策略配置。"""

    min_price: float = 3.0
    min_amount: float = 100_000_000.0
    momentum_5_min: float = 3.0
    momentum_5_max: float = 18.0
    volume_ratio_min: float = 1.2
    volume_ratio_max: float = 2.5
    close_position_min: float = 0.6
    hot_theme_top_pct: float = 0.2
    candidate_size: int = 20
    final_top_n: int = 3
    use_market_filter: bool = True
    max_holding_days: int = 5
