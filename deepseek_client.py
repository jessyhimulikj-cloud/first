"""Unified DeepSeek client and prompt templates for A-share analysis."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Literal

import requests

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_DISCLAIMER = "仅供参考，不构成投资建议。市场有风险，投资需谨慎。"

PromptTemplateName = Literal["basic_report", "deep_research_report", "risk_review", "trade_plan"]

SYSTEM_PROMPT = (
    "你是严谨的A股研究助理。请基于用户提供的数据生成分析报告，"
    "不得编造未提供的数据，不得给出绝对买卖指令，"
    "必须明确提示：仅供参考，不构成投资建议。"
)

PROMPT_TEMPLATES: dict[PromptTemplateName, str] = {
    "basic_report": """
        请基于以下结构化数据，生成 A 股股票 AI 投资分析报告，必须包含：
        1. 短期投资建议（3-5个交易日）
        2. 中期投资建议（2-3个月）
        3. 长期投资建议（1年左右）
        4. 风险提示
        5. 综合评分（0-100，并解释依据）
        6. 是否适合当前买入（只能使用审慎、观望、分批关注等非绝对表述）

        请使用中文，结构清晰，避免夸大收益，最后再次注明“{disclaimer}”。

        数据如下：
        {structured_text}
    """,
    "deep_research_report": """
        请基于以下结构化数据，生成更深入的 A 股研究报告，必须包含：
        1. 公司与行业定位概览
        2. 基本面质量分析（盈利能力、成长性、资产负债情况，仅限已提供数据）
        3. 技术面趋势分析（均线、RSI、MACD、成交量、近20日涨跌幅）
        4. 估值状态分析（PE、PB、市值、换手率、量比）
        5. 短期（3-5个交易日）、中期（2-3个月）、长期（1年左右）观察要点
        6. 核心风险与需要继续跟踪的数据
        7. 综合评分（0-100，并说明扣分项和加分项）

        请使用中文，结构清晰，明确区分事实、推断与不确定性，不得补充未提供的外部数据，
        最后再次注明“{disclaimer}”。

        数据如下：
        {structured_text}
    """,
    "risk_review": """
        请基于以下结构化数据，生成 A 股风险复核报告，必须包含：
        1. 数据完整性与可能缺口
        2. 技术面风险（趋势、超买超卖、量价、波动）
        3. 基本面风险（盈利、ROE、毛利率、负债率，仅限已提供数据）
        4. 估值与流动性风险（PE、PB、市值、换手率、量比）
        5. 短期、中期、长期分别需要警惕的情形
        6. 风险等级（低/中/高）与理由
        7. 风险控制建议（只能给出仓位、观察、止损纪律等非绝对表述）

        请使用中文，优先指出不确定性和下行风险，不得夸大确定性，最后再次注明“{disclaimer}”。

        数据如下：
        {structured_text}
    """,
    "trade_plan": """
        请基于以下结构化数据，生成审慎的 A 股交易计划草案，必须包含：
        1. 当前状态判断（趋势、估值、基本面数据质量）
        2. 观察触发条件（例如均线、量能、RSI、MACD 等，必须来自已提供数据）
        3. 分批关注思路（仅可使用假设性、条件式表述，不得给出绝对买卖指令）
        4. 风险控制框架（仓位上限、止损/止盈纪律、复盘频率，用原则性表述）
        5. 短期、中期、长期计划差异
        6. 不适合交易或需要等待的情形

        请使用中文，所有建议都要以“如果/当/需要观察到”等条件式表达，
        避免收益承诺，最后再次注明“{disclaimer}”。

        数据如下：
        {structured_text}
    """,
}


SUPPORTED_PROMPT_TEMPLATES: tuple[str, ...] = tuple(PROMPT_TEMPLATES)


class DeepSeekClientError(Exception):
    """Raised when the DeepSeek API call fails or returns invalid data."""


@dataclass(frozen=True)
class DeepSeekClient:
    """Single DeepSeek API client used by all report-generation paths."""

    api_key: str
    model: str = DEFAULT_DEEPSEEK_MODEL
    api_url: str = DEEPSEEK_API_URL
    timeout: int = 90
    temperature: float = 0.3
    disclaimer: str = DEFAULT_DISCLAIMER

    def render_prompt(self, template: PromptTemplateName, structured_text: str) -> str:
        """Render one of the supported prompt templates with structured stock data."""
        if template not in PROMPT_TEMPLATES:
            valid_templates = ", ".join(SUPPORTED_PROMPT_TEMPLATES)
            raise DeepSeekClientError(
                f"未知 DeepSeek Prompt 模板：{template}。可选：{valid_templates}"
            )

        return textwrap.dedent(PROMPT_TEMPLATES[template]).strip().format(
            disclaimer=self.disclaimer,
            structured_text=structured_text,
        )

    def analyze_structured_data(
        self, structured_text: str, template: PromptTemplateName = "basic_report"
    ) -> str:
        """Generate an AI report from structured stock data through the unified client."""
        user_prompt = self.render_prompt(template, structured_text)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                self.api_url, headers=headers, json=payload, timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
        except requests.Timeout as exc:
            raise DeepSeekClientError("DeepSeek API 请求超时，请稍后重试或检查网络。") from exc
        except requests.RequestException as exc:
            detail = (
                exc.response.text if getattr(exc, "response", None) is not None else str(exc)
            )
            raise DeepSeekClientError(f"DeepSeek API 调用失败：{detail}") from exc
        except (KeyError, IndexError, ValueError) as exc:
            raise DeepSeekClientError(f"DeepSeek API 返回格式异常：{exc}") from exc

        if self.disclaimer not in content:
            content = f"{content}\n\n{self.disclaimer}"
        return content


__all__ = [
    "DEFAULT_DEEPSEEK_MODEL",
    "DEEPSEEK_API_URL",
    "DeepSeekClient",
    "DeepSeekClientError",
    "PROMPT_TEMPLATES",
    "PromptTemplateName",
    "SUPPORTED_PROMPT_TEMPLATES",
]
