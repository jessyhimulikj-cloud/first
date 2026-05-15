import csv
from pathlib import Path

from stock_picker import (
    _calc_momentum,
    _fetch_tushare_short_term,
    _is_excluded_stock,
    _normalize_ts_code,
    parse_args,
    robust_zscores,
    run_once,
)


def _sample_history():
    rows = []
    specs = [
        ("000001.SZ", "龙一", "人工智能", 10.0),
        ("000002.SZ", "龙二", "人工智能", 11.0),
        ("000063.SZ", "龙三", "人工智能", 12.0),
        ("000333.SZ", "普通", "家电", 8.0),
    ]
    for code, name, industry, base in specs:
        for i in range(25):
            close = base + i * 0.08
            if i == 24:
                close += 0.45
            rows.append(
                {
                    "trade_date": f"202605{i+1:02d}",
                    "date": f"202605{i+1:02d}",
                    "ts_code": code,
                    "symbol": code[:6],
                    "name": name,
                    "industry": industry,
                    "open": close - 0.1,
                    "high": close + 0.1,
                    "low": close - 0.3,
                    "close": close,
                    "pct_chg": 4.0 if industry == "人工智能" else 0.5,
                    "volume": 1000 + i * 20 + (1200 if i == 24 else 0),
                    "amount": 200_000_000 + i * 1_000_000,
                    "turnover_rate": 5.0,
                }
            )
    return rows


def test_normalize_ts_code():
    assert _normalize_ts_code("600000") == "600000.SH"
    assert _normalize_ts_code("000001") == "000001.SZ"


def test_is_excluded_stock():
    assert _is_excluded_stock("000001", "*ST测试", 10, 2e8, 1)[0] is True
    assert _is_excluded_stock("800001", "某股票", 10, 2e8, 1)[0] is True
    assert _is_excluded_stock("000001", "正常", 2.8, 2e8, 1)[0] is True
    assert _is_excluded_stock("000001", "正常", 10, 9e7, 1)[0] is True
    assert _is_excluded_stock("000001", "正常", 10, 2e8, -6)[0] is False
    assert _is_excluded_stock("000001", "正常", 10, 2e8, 8)[0] is False


def test_calc_momentum():
    closes = [10, 10.5, 11, 11.2, 11.5, 12]
    assert _calc_momentum(closes, 3) > 0
    assert _calc_momentum(closes, 5) > 0


def test_fetch_tushare_short_term(monkeypatch):
    args = type(
        "Args",
        (),
        {
            "min_price": 3.0,
            "min_amount": 100_000_000,
            "momentum_5_min": 3.0,
            "momentum_5_max": 18.0,
            "volume_ratio_min": 1.2,
            "volume_ratio_max": 2.5,
            "close_position_min": 0.6,
            "candidate_size": 20,
            "top": 3,
            "no_market_filter": True,
            "data_dir": Path("data"),
            "universe_size": 10,
            "months": 3,
            "cache_dir": Path(".cache_tushare"),
        },
    )()
    monkeypatch.setattr("stock_picker._load_tushare_market_history", lambda args, config: _sample_history())
    rows, sentiment, themes = _fetch_tushare_short_term(args)
    assert len(rows) >= 3
    assert sentiment["market_sentiment"] in {"ice_point", "recovery", "main_rise", "climax", "decline"}
    assert themes[0]["theme_name"] == "人工智能"
    assert "leader_score" in rows[0]
    assert "trend_strength_score" in rows[0]
    assert "hot_theme_score" in rows[0]


def test_run_once_outputs_three_without_ai(monkeypatch, tmp_path):
    monkeypatch.setattr("stock_picker._load_tushare_market_history", lambda args, config: _sample_history())
    monkeypatch.setattr(
        "sys.argv",
        [
            "stock_picker.py",
            "--output",
            str(tmp_path / "picked.csv"),
            "--candidate-output",
            str(tmp_path / "candidate.csv"),
            "--market-sentiment-output",
            str(tmp_path / "sentiment.json"),
            "--hot-themes-output",
            str(tmp_path / "themes.csv"),
            "--no-market-filter",
        ],
    )
    args = parse_args()
    run_once(args)
    with (tmp_path / "picked.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    assert "why_selected" in rows[0]
    assert (tmp_path / "candidate.csv").exists()
    assert (tmp_path / "sentiment.json").exists()
    assert (tmp_path / "themes.csv").exists()


def test_robust_zscores_non_empty():
    z = robust_zscores([1, 2, 3])
    assert len(z) == 3
