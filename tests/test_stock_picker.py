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
            closes = [8, 8.2, 8.4, 8.6, 8.9, 9.2, 10]
        else:
            closes = [9, 9.1, 9.3, 9.6, 10.0, 10.5, 11]
        return FakeDF([{"收盘": c} for c in closes])


def test_normalize_ts_code():
    assert _normalize_ts_code("600000") == "600000.SH"
    assert _normalize_ts_code("000001") == "000001.SZ"


def test_is_excluded_stock():
    assert _is_excluded_stock("000001", "*ST测试", 10, 2e8, 1)[0] is True
    assert _is_excluded_stock("800001", "某股票", 10, 2e8, 1)[0] is True
    assert _is_excluded_stock("000001", "正常", 2.8, 2e8, 1)[0] is True
    assert _is_excluded_stock("000001", "正常", 10, 9e7, 1)[0] is True
    assert _is_excluded_stock("000001", "正常", 10, 2e8, -6)[0] is True
    assert _is_excluded_stock("000001", "正常", 10, 2e8, 10)[0] is True


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


def test_robust_zscores_non_empty():
    z = robust_zscores([1, 2, 3])
    assert len(z) == 3
