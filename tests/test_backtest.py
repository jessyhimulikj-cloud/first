from backtest import TradeRecord, calc_metrics, max_drawdown


def test_max_drawdown():
    mdd = max_drawdown([0.1, -0.2, 0.05, -0.1])
    assert mdd < 0


def test_calc_metrics_basic():
    trades = [
        TradeRecord("000001", "20240102", "20240103", 10, 10.5, 0.05, "hold_3"),
        TradeRecord("000002", "20240104", "20240105", 10, 9.7, -0.03, "hold_3"),
    ]
    m = calc_metrics(trades)
    assert m["total_trades"] == 2
    assert 0 <= m["win_rate"] <= 1
    assert "2024" in m["annual_returns"]
