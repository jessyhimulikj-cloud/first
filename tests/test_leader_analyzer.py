from leader_analyzer import score_leaders


def test_score_leaders_marks_front_rank():
    rows = [
        {"main_theme": "AI", "momentum_5": 10, "amount": 100, "volume_ratio": 1.5, "trend_strength_score": 0.9, "hot_theme_score": 1, "momentum_3": 5},
        {"main_theme": "AI", "momentum_5": 5, "amount": 80, "volume_ratio": 1.2, "trend_strength_score": 0.6, "hot_theme_score": 1, "momentum_3": 2},
    ]
    out = score_leaders(rows)
    assert out[0]["leader_score"] >= out[1]["leader_score"]
    assert out[0]["is_leader"] is True
