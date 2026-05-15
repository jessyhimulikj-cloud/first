from sentiment_analyzer import analyze_market_sentiment


def _rows(up, down, limit_up=0, limit_down=0):
    rows = [{"pct_chg": 1, "amount": 1} for _ in range(up)] + [{"pct_chg": -1, "amount": 1} for _ in range(down)]
    rows += [{"pct_chg": 9.8, "amount": 1} for _ in range(limit_up)]
    rows += [{"pct_chg": -9.8, "amount": 1} for _ in range(limit_down)]
    return rows


def test_sentiment_cycles():
    assert analyze_market_sentiment(_rows(10, 90))["market_sentiment"] == "ice_point"
    assert analyze_market_sentiment(_rows(45, 55))["market_sentiment"] == "recovery"
    assert analyze_market_sentiment(_rows(60, 40))["market_sentiment"] == "main_rise"
    assert analyze_market_sentiment(_rows(90, 10, 5))["market_sentiment"] == "climax"
    assert analyze_market_sentiment(_rows(40, 60, 0, 8))["market_sentiment"] == "decline"
