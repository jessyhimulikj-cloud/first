from stock_picker import (
    _calc_momentum,
    _fetch_akshare_short_term,
    _is_excluded_stock,
    _normalize_ts_code,
    parse_args,
    robust_zscores,
)


class FakeDF:
    def __init__(self, rows):
        self._rows = rows

    def to_dict(self, orient="records"):
        assert orient == "records"
        return self._rows


class FakeAk:
    def stock_zh_a_spot_em(self):
        return FakeDF(
            [
                {"代码": "600000", "名称": "浦发银行", "最新价": 10.0, "涨跌幅": 2.0, "成交额": 2e8},
                {"代码": "000001", "名称": "平安银行", "最新价": 11.0, "涨跌幅": 1.5, "成交额": 3e8},
                {"代码": "000002", "名称": "*ST测试", "最新价": 4.0, "涨跌幅": 1.0, "成交额": 2e8},
            ]
        )

    def stock_zh_a_hist(self, symbol, period="daily", adjust="qfq"):
        assert period == "daily"
        assert adjust == "qfq"
        if symbol == "600000":
            closes = [12.0, 11.5, 11.0, 10.8, 10.6, 10.4, 10.2, 10.1, 10.0, 10.0, 10.1, 10.2, 10.25, 10.3, 10.35, 10.4, 10.45, 10.5, 10.55, 10.6]
            vols = [200, 210, 220, 180, 170, 160, 150, 145, 140, 138, 136, 135, 140, 145, 150, 160, 170, 180, 190, 260]
            pcts = [-1.5, -1.2, -1.0, -0.8, -0.5, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.2, 0.3, 0.4, 0.4, 0.5, 0.5, 0.5, 0.4, 0.5]
        else:
            closes = [11.8, 11.3, 10.9, 10.7, 10.5, 10.3, 10.1, 10.0, 9.95, 9.9, 9.95, 10.0, 10.05, 10.1, 10.15, 10.2, 10.25, 10.3, 10.35, 10.4]
            vols = [190, 195, 200, 170, 160, 155, 150, 145, 140, 138, 136, 134, 138, 142, 146, 150, 158, 166, 174, 250]
            pcts = [-1.2, -1.0, -0.8, -0.6, -0.4, -0.3, -0.2, -0.1, -0.1, -0.1, 0.1, 0.2, 0.2, 0.3, 0.3, 0.4, 0.4, 0.4, 0.4, 0.4]
        return FakeDF([{"收盘": c, "成交量": v, "涨跌幅": p} for c, v, p in zip(closes, vols, pcts)])

    def stock_board_hot_rank_em(self):
        return FakeDF(
            [
                {"板块名称": "人工智能", "涨跌幅": 3.5},
                {"板块名称": "机器人", "涨跌幅": 2.0},
                {"板块名称": "冷门板块", "涨跌幅": -1.0},
                {"板块名称": "次热板块", "涨跌幅": 1.0},
                {"板块名称": "普通板块", "涨跌幅": 0.5},
            ]
        )

    def stock_board_industry_cons_em(self, symbol):
        if symbol == "人工智能":
            return FakeDF([{"代码": "600000"}, {"代码": "000001"}])
        return FakeDF([])


def test_normalize_ts_code():
    assert _normalize_ts_code("600000") == "600000.SH"
    assert _normalize_ts_code("000001") == "000001.SZ"


def test_is_excluded_stock():
    assert _is_excluded_stock("000001", "*ST测试", 10, 2e8, 1)[0] is True
    assert _is_excluded_stock("800001", "某股票", 10, 2e8, 1)[0] is True
    assert _is_excluded_stock("000001", "正常", 2.8, 2e8, 1)[0] is True
    assert _is_excluded_stock("000001", "正常", 10, 9e7, 1)[0] is True
    assert _is_excluded_stock("000001", "正常", 10, 2e8, -6)[0] is True
    assert _is_excluded_stock("000001", "正常", 10, 2e8, 8)[0] is True


def test_calc_momentum():
    closes = [10, 10.5, 11, 11.2, 11.5, 12]
    m3 = _calc_momentum(closes, 3)
    m5 = _calc_momentum(closes, 5)
    assert m3 > 0
    assert m5 > 0


def test_fetch_akshare_short_term(monkeypatch):
    monkeypatch.setattr("stock_picker._import_akshare", lambda: FakeAk())
    args = type("Args", (), {"ak_hist_limit": 20})()
    rows = _fetch_akshare_short_term(args)
    assert len(rows) == 2
    assert rows[0]["ts_code"].endswith((".SH", ".SZ"))
    assert "total_score" in rows[0]
    assert "momentum_3" in rows[0]
    assert "momentum_5" in rows[0]
    assert "ret_5" in rows[0]
    assert "ret_10" in rows[0]
    assert "ma5" in rows[0]
    assert "ma10" in rows[0]
    assert "volume_ratio" in rows[0]
    assert rows[0]["trend_flag"] == "uptrend_confirmed"


def test_robust_zscores_non_empty():
    z = robust_zscores([1, 2, 3])
    assert len(z) == 3
