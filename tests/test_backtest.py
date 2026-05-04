from backtest import TradeRecord, calc_metrics, max_drawdown, parse_args, run_trade


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


def test_run_trade_accepts_string_numeric_fields():
    rows = [
        {"date": "20240101", "open": "10", "high": "10.2", "low": "9.8", "close": "10", "amount": "100000000", "pct_chg": "1.0"},
        {"date": "20240102", "open": "10.1", "high": "10.3", "low": "9.9", "close": "10.2", "amount": "120000000", "pct_chg": "1.2"},
        {"date": "20240103", "open": "10.2", "high": "10.6", "low": "10.0", "close": "10.5", "amount": "130000000", "pct_chg": "2.0"},
        {"date": "20240104", "open": "10.5", "high": "10.8", "low": "10.4", "close": "10.7", "amount": "150000000", "pct_chg": "1.9"},
    ]
    tr = run_trade("000001", 0, rows, "hold_3", 0.003, 0.001)
    assert tr is not None
    assert tr.sell_price > 0


def test_run_trade_gap_filter():
    rows_gap_up = [
        {"date": "20240101", "open": "10", "high": "10.2", "low": "9.8", "close": "10"},
        {"date": "20240102", "open": "10.3", "high": "10.5", "low": "10.1", "close": "10.4"},
        {"date": "20240103", "open": "10.2", "high": "10.4", "low": "10.0", "close": "10.3"},
        {"date": "20240104", "open": "10.2", "high": "10.4", "low": "10.0", "close": "10.3"},
    ]
    assert run_trade("000001", 0, rows_gap_up, "hold_3", 0.003, 0.001) is None


def test_parse_args_defaults(monkeypatch):
    monkeypatch.setattr("sys.argv", ["backtest.py"])
    args = parse_args()
    assert args.months == 12
    assert args.universe_size == 30
    assert args.max_days == 0
    assert args.modes == ["momentum_hold3_v1", "momentum_hold3_v5", "multi_strategy_v1"]
    assert args.fee_rate == 0.003
    assert args.slippage == 0.001
