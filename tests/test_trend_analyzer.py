from trend_analyzer import score_trend_strength
from strategy_config import ShortTermStrategyConfig


def test_trend_strength_good_structure():
    row = {
        "close": 12,
        "ma5": 11.5,
        "ma10": 11,
        "ma20": 10,
        "ma5_prev": 11,
        "ma10_prev": 10.8,
        "momentum_3": 3,
        "momentum_5": 8,
        "volume_ratio": 1.5,
        "close_position": 0.8,
    }
    out = score_trend_strength(row, ShortTermStrategyConfig())
    assert out["trend_strength_score"] > 0.8


def test_trend_strength_weak_structure():
    row = {"close": 10, "ma5": 11, "ma10": 12, "ma20": 13, "momentum_3": -1, "momentum_5": -2, "volume_ratio": 0.8, "close_position": 0.2}
    out = score_trend_strength(row, ShortTermStrategyConfig())
    assert out["trend_strength_score"] < 0.3
