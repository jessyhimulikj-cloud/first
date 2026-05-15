import json

from deepseek_client import analyze_candidate_pool, build_fallback_analysis


def test_fallback_without_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    out = analyze_candidate_pool([{"ts_code": "000001.SZ", "name": "A"}], {"market_sentiment": "main_rise"}, [], 1)
    assert len(out["picks"]) == 1
    assert "未配置" in out["picks"][0]["why_selected"]


def test_deepseek_valid_json(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "market_view": {"sentiment_cycle": "main_rise", "risk_level": "medium", "summary": "ok"},
                                    "picks": [
                                        {
                                            "rank": 1,
                                            "ts_code": "000001.SZ",
                                            "name": "A",
                                            "main_theme": "AI",
                                            "ai_rating": "A",
                                            "confidence": 0.8,
                                            "why_selected": "强",
                                            "leader_judgement": "前排",
                                            "trend_judgement": "强化",
                                            "operation_plan": {"buy_condition": "观察", "position": "20%", "stop_loss": "MA10", "take_profit": "分批", "max_holding_days": 5},
                                            "risk_points": ["风险"],
                                        }
                                    ],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

    monkeypatch.setattr("deepseek_client.requests.post", lambda *a, **k: Resp())
    out = analyze_candidate_pool([{"ts_code": "000001.SZ", "name": "A"}], {"market_sentiment": "main_rise"}, [], 1)
    assert out["picks"][0]["ai_rating"] == "A"


def test_deepseek_invalid_json_fallback(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "not json"}}]}

    monkeypatch.setattr("deepseek_client.requests.post", lambda *a, **k: Resp())
    out = analyze_candidate_pool([{"ts_code": "000001.SZ", "name": "A"}], {"market_sentiment": "main_rise"}, [], 1)
    assert "DeepSeek分析失败" in out["picks"][0]["why_selected"]
