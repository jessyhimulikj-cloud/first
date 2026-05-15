#!/usr/bin/env python3
"""DeepSeek OpenAI-compatible Chat Completions 客户端。"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

try:
    import requests  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - 环境未安装 requests 时仍允许量化流程运行
    class _MissingRequests:
        def post(self, *args, **kwargs):
            raise ModuleNotFoundError("未安装 requests，请执行: pip install requests")

    requests = _MissingRequests()  # type: ignore

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


def _empty_ai_fields(reason: str = "") -> Dict[str, Any]:
    return {
        "ai_rating": "",
        "ai_confidence": "",
        "why_selected": reason,
        "leader_judgement": "",
        "trend_judgement": "",
        "buy_condition": "",
        "position_advice": "",
        "stop_loss": "",
        "take_profit": "",
        "max_holding_days": "",
        "risk_points": "",
    }


def build_fallback_analysis(candidates: List[Dict[str, Any]], market_context: Dict[str, Any], final_top_n: int = 3, reason: str = "未启用 DeepSeek，使用量化Top3。") -> Dict[str, Any]:
    picks = []
    for idx, row in enumerate(candidates[:final_top_n], start=1):
        picks.append(
            {
                "rank": idx,
                "ts_code": row.get("ts_code", ""),
                "name": row.get("name", ""),
                "main_theme": row.get("main_theme", ""),
                "ai_rating": "",
                "confidence": "",
                "why_selected": reason,
                "leader_judgement": row.get("leader_reason", ""),
                "trend_judgement": row.get("trend_reason", ""),
                "operation_plan": {
                    "buy_condition": "未启用AI分析，仅作为量化观察标的；等待分时企稳且不追高。",
                    "position": "单只仓位建议不超过总资金20%，并根据个人风险承受能力调整。",
                    "stop_loss": "跌破MA10或亏损3%-5%及时止损。",
                    "take_profit": "盈利6%-10%可分批止盈，放量滞涨优先减仓。",
                    "max_holding_days": 5,
                },
                "risk_points": ["量化模型可能失效。", "市场情绪退潮时短线波动会放大。"],
            }
        )
    return {
        "market_view": {
            "sentiment_cycle": market_context.get("market_sentiment", ""),
            "risk_level": market_context.get("risk_level", ""),
            "summary": market_context.get("sentiment_reason", ""),
        },
        "picks": picks,
    }


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        text = text[start : end + 1]
    return json.loads(text)


def analyze_candidate_pool(
    candidates: List[Dict[str, Any]],
    market_context: Dict[str, Any],
    hot_themes: List[Dict[str, Any]],
    final_top_n: int = 3,
    model: str | None = None,
    timeout: int = 45,
) -> Dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return build_fallback_analysis(candidates, market_context, final_top_n, "未配置 DEEPSEEK_API_KEY，使用量化Top3。")

    base_url = os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model_name = model or os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL)
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是A股短线量化研究助手。只能基于用户提供的候选池二次精选，输出严格JSON；"
                    "不得使用必涨、稳赚、确定性收益等表述；必须包含风险提示；内容不构成投资建议。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "从候选池精选恰好3只短线观察标的，并给出原因、龙头判断、趋势判断、条件式操作计划和风险点。",
                        "required_schema": {
                            "market_view": {"sentiment_cycle": "str", "risk_level": "str", "summary": "str"},
                            "picks": [
                                {
                                    "rank": "int",
                                    "ts_code": "str",
                                    "name": "str",
                                    "main_theme": "str",
                                    "ai_rating": "A/B/C/D",
                                    "confidence": "0-1",
                                    "why_selected": "str",
                                    "leader_judgement": "str",
                                    "trend_judgement": "str",
                                    "operation_plan": {
                                        "buy_condition": "str",
                                        "position": "str",
                                        "stop_loss": "str",
                                        "take_profit": "str",
                                        "max_holding_days": "int",
                                    },
                                    "risk_points": ["str"],
                                }
                            ],
                        },
                        "market_context": market_context,
                        "hot_themes": hot_themes[:10],
                        "candidates": candidates,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = _extract_json(content)
        picks = parsed.get("picks") or []
        if len(picks) != final_top_n:
            raise ValueError(f"DeepSeek 返回 picks 数量不是 {final_top_n}")
        return parsed
    except Exception as exc:
        return build_fallback_analysis(candidates, market_context, final_top_n, f"DeepSeek分析失败，使用量化Top3：{str(exc)[:120]}")
