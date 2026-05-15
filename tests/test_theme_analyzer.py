from theme_analyzer import analyze_hot_themes, attach_theme_scores


def test_hot_theme_ranking_and_attach():
    rows = [
        {"industry": "AI", "pct_chg": 5, "momentum_3": 8, "momentum_5": 12, "amount": 100},
        {"industry": "AI", "pct_chg": 4, "momentum_3": 6, "momentum_5": 10, "amount": 90},
        {"industry": "Bank", "pct_chg": 1, "momentum_3": 1, "momentum_5": 2, "amount": 50},
    ]
    themes, hot = analyze_hot_themes(rows, top_pct=0.5)
    assert themes[0]["theme_name"] == "AI"
    assert "AI" in hot
    attached = attach_theme_scores(rows, themes)
    assert attached[0]["main_theme"] == "AI"
    assert attached[0]["hot_theme_score"] > attached[-1]["hot_theme_score"]
