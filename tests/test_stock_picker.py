from stock_picker import (
    FactorWeights,
    _fetch_akshare_flow,
    _fetch_akshare_market,
    _fetch_akshare_theme,
    _fetch_eastmoney_flow,
    _fetch_eastmoney_market,
    _normalize_ts_code,
    score_stocks,
)


class FakeDF:
    def __init__(self, rows):
        self._rows = rows

    def to_dict(self, orient="records"):
        assert orient == "records"
        return self._rows


class FakeAk:
    def stock_zh_a_spot_em(self):
        return FakeDF([
            {"代码": "600000", "名称": "浦发银行", "最新价": 10.2, "涨跌幅": 1.2, "换手率": 2.3, "量比": 1.4}
        ])

    def stock_individual_fund_flow_rank(self, indicator="今日"):
        assert indicator == "今日"
        return FakeDF([
            {"代码": "600000", "今日主力净流入-净额": 1200, "今日超大单净流入-净额": 300, "今日主力净流入-净占比": 9.1}
        ])

    def stock_board_hot_rank_em(self):
        return FakeDF([
            {"板块名称": "人工智能"},
            {"板块名称": "机器人"},
        ])

    def stock_board_industry_cons_em(self, symbol):
        if symbol == "人工智能":
            return FakeDF([{"代码": "600000"}, {"代码": "000001"}])
        return FakeDF([{"代码": "000001"}])


def test_score_contains_expected_columns_and_order():
    market = [
        {"ts_code": "000001.SZ", "name": "A", "close": "10", "pct_chg": "3.2", "vol_ratio": "1.6", "turnover_rate": "5.1"},
        {"ts_code": "000002.SZ", "name": "B", "close": "20", "pct_chg": "1.1", "vol_ratio": "0.9", "turnover_rate": "3.0"},
        {"ts_code": "000003.SZ", "name": "C", "close": "30", "pct_chg": "5.8", "vol_ratio": "2.1", "turnover_rate": "8.0"},
    ]
    flow = [
        {"ts_code": "000001.SZ", "main_net_inflow": "2000", "super_net_inflow": "700", "main_inflow_ratio": "12"},
        {"ts_code": "000002.SZ", "main_net_inflow": "500", "super_net_inflow": "100", "main_inflow_ratio": "4"},
        {"ts_code": "000003.SZ", "main_net_inflow": "3500", "super_net_inflow": "1000", "main_inflow_ratio": "19"},
    ]
    theme = [{"theme": "AI", "heat_score": "95"}, {"theme": "机器人", "heat_score": "90"}, {"theme": "光伏", "heat_score": "60"}]
    theme_map = [
        {"ts_code": "000001.SZ", "theme": "AI"},
        {"ts_code": "000001.SZ", "theme": "机器人"},
        {"ts_code": "000002.SZ", "theme": "光伏"},
        {"ts_code": "000003.SZ", "theme": "AI"},
    ]

    result = score_stocks(market, flow, theme, theme_map, FactorWeights())
    assert len(result) == 3
    assert result[0]["ts_code"] in {"000003.SZ", "000001.SZ"}
    for col in ["money_flow_z", "momentum_z", "liquidity_z", "hot_theme_score", "total_score", "risk_flag"]:
        assert col in result[0]


def test_normalize_ts_code():
    assert _normalize_ts_code("600000") == "600000.SH"
    assert _normalize_ts_code("000001") == "000001.SZ"
    assert _normalize_ts_code("000001.SZ") == "000001.SZ"


def test_eastmoney_parsers(monkeypatch):
    payload = {
        "data": {
            "diff": [
                {"f12": "600000", "f14": "浦发银行", "f2": 10.2, "f3": 1.3, "f8": 2.1, "f10": 1.5, "f62": 1000, "f66": 300, "f184": 8.5}
            ]
        }
    }

    def fake_get_json(url: str, timeout: int = 12):
        return payload

    monkeypatch.setattr("stock_picker._http_get_json", fake_get_json)

    market = _fetch_eastmoney_market(page_size=1)
    flow = _fetch_eastmoney_flow(page_size=1)

    assert market[0]["ts_code"] == "600000.SH"
    assert flow[0]["main_net_inflow"] == "1000"


def test_akshare_parsers(monkeypatch):
    monkeypatch.setattr("stock_picker._import_akshare", lambda: FakeAk())

    market = _fetch_akshare_market(limit=1)
    flow = _fetch_akshare_flow(limit=1)
    theme, theme_map = _fetch_akshare_theme(board_top=2, board_cons_limit=2)

    assert market[0]["ts_code"] == "600000.SH"
    assert flow[0]["main_net_inflow"] == "1200"
    assert any(t["theme"] == "人工智能" for t in theme)
    assert any(tm["ts_code"] == "600000.SH" for tm in theme_map)
