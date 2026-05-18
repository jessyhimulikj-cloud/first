"""DeepSeek second-layer analysis for the quantitative shortlist."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pandas as pd
from openai import OpenAI

from . import config

LOGGER = logging.getLogger(__name__)
AI_FIELDS = [
    "ai_summary",
    "industry_logic",
    "company_position",
    "distress_reason",
    "reversal_potential",
    "main_risks",
    "final_judgement",
    "ai_score",
]
INPUT_FIELDS = [
    "ts_code",
    "name",
    "industry",
    "current_price",
    "market_cap",
    "drawdown_from_3y_high",
    "pe",
    "pb",
    "pe_percentile_3y",
    "pb_percentile_3y",
    "roe",
    "revenue_growth",
    "profit_growth",
    "debt_to_assets",
    "operating_cashflow",
    "industry_score",
    "position_score",
    "distress_score",
    "survival_score",
    "reversal_score",
    "valuation_score",
    "total_score",
]


def analyze_candidates(input_csv: Path, output_csv: Path, top_n: int) -> pd.DataFrame:
    """Analyze top quantitative candidates and merge AI JSON fields."""
    candidates = pd.read_csv(input_csv).sort_values("total_score", ascending=False).head(top_n)
    if not config.DEEPSEEK_API_KEY:
        LOGGER.warning("DEEPSEEK_API_KEY missing; writing AI output with empty analysis fields.")
        return _write_without_ai(candidates, output_csv)

    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    rows = []
    for _, row in candidates.iterrows():
        rows.append({**row.to_dict(), **_analyze_one(client, row)})
    result = pd.DataFrame(rows)
    result["ai_score"] = pd.to_numeric(result["ai_score"], errors="coerce").fillna(0)
    result["final_score"] = result["total_score"] * config.QUANT_WEIGHT + result["ai_score"] * config.AI_WEIGHT
    result["final_rating"] = result["final_score"].apply(final_rating)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_csv, index=False)
    return result


def _analyze_one(client: OpenAI, row: pd.Series) -> dict:
    payload = {field: _json_safe(row.get(field)) for field in INPUT_FIELDS}
    prompt = f"""
你是一名价值投资研究员，擅长分析 A 股“困境反转 + 长期成长”型公司。

请基于以下数据，判断该公司是否值得进入长期研究池。
重点不是看当前财务是否漂亮，而是判断行业空间、行业地位、当前低谷、财务生存能力、初步反转迹象和主要风险。
请严格基于给出的数据分析，不要编造不存在的信息。如果数据不足，请明确说明“数据不足，需人工进一步研究”。

公司数据：
{json.dumps(payload, ensure_ascii=False, indent=2)}

请只输出 JSON，格式如下：
{{
  "ai_summary": "一句话总结",
  "industry_logic": "行业前景分析",
  "company_position": "公司行业地位分析",
  "distress_reason": "当前低谷原因分析",
  "reversal_potential": "未来反转可能性分析",
  "main_risks": "主要风险",
  "final_judgement": "重点研究/观察/跟踪/暂不考虑",
  "ai_score": 0-100
}}
"""
    try:
        response = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = response.choices[0].message.content or ""
        parsed = parse_ai_json(content)
        return _normalize_ai_result(parsed, content)
    except Exception as exc:  # noqa: BLE001 - AI failure must not interrupt quant output
        LOGGER.warning("DeepSeek analysis failed for %s: %s", row.get("ts_code"), exc)
        return {**{field: "" for field in AI_FIELDS}, "ai_raw_text": str(exc), "ai_score": 0}


def parse_ai_json(text: str) -> dict:
    """Parse JSON even if the model wraps it in Markdown fences or commentary."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _normalize_ai_result(parsed: dict, raw: str) -> dict:
    result = {field: parsed.get(field, "") for field in AI_FIELDS}
    result["ai_score"] = max(0, min(float(result.get("ai_score") or 0), 100))
    result["ai_raw_text"] = raw
    return result


def _write_without_ai(candidates: pd.DataFrame, output_csv: Path) -> pd.DataFrame:
    result = candidates.copy()
    for field in AI_FIELDS:
        result[field] = 0 if field == "ai_score" else ""
    result["final_score"] = result["total_score"]
    result["final_rating"] = result["rating"]
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_csv, index=False)
    return result


def _json_safe(value):
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def final_rating(score: float) -> str:
    if score >= 85:
        return "重点研究"
    if score >= 75:
        return "观察"
    if score >= 65:
        return "跟踪"
    return "剔除"
