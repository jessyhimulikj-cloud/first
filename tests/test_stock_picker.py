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
            closes = [7.8, 8.0, 8.1, 8.2, 8.35, 8.5, 8.7, 8.9, 9.2, 9.6, 10.0]
            vols = [100, 110, 120, 130, 140, 180, 190, 210, 230, 240, 420]
            pcts = [0.5, 0.8, 1.0, 0.4, 1.2, 1.1, 1.8, 2.0, 2.2, 2.6, 3.0]
        else:
            closes = [8.9, 9.0, 9.05, 9.2, 9.35, 9.5, 9.7, 9.9, 10.2, 10.6, 11.0]
            vols = [120, 125, 130, 140, 150, 170, 180, 190, 210, 220, 420]
            pcts = [0.3, 0.6, 0.7, 0.5, 1.0, 1.2, 1.4, 1.8, 2.0, 2.4, 2.8]
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
