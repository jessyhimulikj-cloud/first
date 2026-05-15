import csv
from pathlib import Path

from daily_runner import already_ran_today, append_history, build_output_file


def test_build_output_file(tmp_path: Path):
    p = build_output_file(tmp_path, "20260427")
    assert p.name == "picked_stocks_20260427.csv"


def test_already_ran_today_by_output(tmp_path: Path):
    output = tmp_path / "picked_stocks_20260427.csv"
    output.write_text("x")
    assert already_ran_today(tmp_path / "history.csv", "20260427", output) is True


def test_append_history_and_detect(tmp_path: Path):
    history = tmp_path / "history.csv"
    picks = [
        {"ts_code": "000001.SZ", "name": "平安银行", "close": "10", "pct_chg": "1.2", "total_score": "2.3"}
    ]
    append_history(history, "20260427", picks)

    with history.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["run_date"] == "20260427"

    output = tmp_path / "picked_stocks_20260427.csv"
    assert already_ran_today(history, "20260427", output) is True


def test_run_picker_uses_tushare_and_ai(monkeypatch, tmp_path: Path):
    from daily_runner import run_picker

    captured = {}

    def fake_run(cmd, check):
        captured["cmd"] = cmd
        captured["check"] = check

    monkeypatch.setattr("daily_runner.subprocess.run", fake_run)
    run_picker(tmp_path / "picked.csv", 3, enable_ai_analysis=True, ai_candidate_size=12)
    assert "tushare" in captured["cmd"]
    assert "--enable-ai-analysis" in captured["cmd"]
    assert "--ai-candidate-size" in captured["cmd"]
