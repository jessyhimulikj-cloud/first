"""Markdown report generation for candidate pools."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import config


def generate_report(candidates: pd.DataFrame, output_path: Path | None = None, used_ai: bool = False) -> Path:
    """Create a human-readable research report for the current screening run."""
    output_path = output_path or (config.OUTPUT_DIR / "value_report.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    score_col = "final_score" if used_ai and "final_score" in candidates else "total_score"
    rating_col = "final_rating" if used_ai and "final_rating" in candidates else "rating"
    lines = [
        "# A股困境反转 + 长期成长价值选股报告",
        "",
        "## 1. 系统说明",
        "本系统仅用于长期研究池筛选，不做自动买卖或短线荐股。核心目标是寻找行业没死、公司没死、价格处于低谷、未来有反转可能的 A 股公司。",
        "",
        "## 2. 筛选逻辑",
        "- 股票池：剔除 ST、退市特征名称和上市不足 2 年股票。",
        "- 量化评分：行业前景、行业地位、困境低谷、财务生存、反转信号、估值低位。",
        "- DeepSeek：仅对量化 Top N 做第二层研究摘要，不参与第一轮初筛。",
        "- 风险控制：净资产、资产负债率、经营现金流和短债压力不达标的公司会被剔除。",
        "",
        "## 3. Top 候选股列表",
    ]
    if candidates.empty:
        lines.append("本次没有满足条件的候选股。")
    else:
        cols = ["ts_code", "name", "industry", score_col, rating_col, "reason"]
        cols = [c for c in cols if c in candidates]
        lines.append(candidates[cols].to_markdown(index=False))

    lines += ["", "## 4. 每只股票的量化评分"]
    for _, row in candidates.iterrows():
        lines += [
            f"### {row.get('name', '')}（{row.get('ts_code', '')}）",
            f"- 行业：{row.get('industry', '')}",
            f"- 量化总分：{row.get('total_score', 0):.2f}，评级：{row.get('rating', '')}",
            f"- 分项：行业 {row.get('industry_score', 0):.1f} / 地位 {row.get('position_score', 0):.1f} / 困境 {row.get('distress_score', 0):.1f} / 生存 {row.get('survival_score', 0):.1f} / 反转 {row.get('reversal_score', 0):.1f} / 估值 {row.get('valuation_score', 0):.1f}",
            f"- 低谷：三年高点回撤 {row.get('drawdown_from_3y_high', 0):.2%}，PE分位 {row.get('pe_percentile_3y', 0):.2%}，PB分位 {row.get('pb_percentile_3y', 0):.2%}",
        ]
        if used_ai:
            lines += [
                "",
                "#### DeepSeek 分析摘要",
                f"- 摘要：{row.get('ai_summary', '')}",
                f"- 反转潜力：{row.get('reversal_potential', '')}",
                f"- 主要风险：{row.get('main_risks', '')}",
                f"- AI评分/最终评分：{row.get('ai_score', 0):.1f} / {row.get('final_score', 0):.1f}，最终评级：{row.get('final_rating', '')}",
            ]

    lines += [
        "",
        "## 5. 主要风险提示",
        "- Tushare 数据披露频率、字段权限和缓存时效会影响结果完整性。",
        "- 手工行业评分只代表初版偏好，需结合产业周期动态维护。",
        "- 困境反转公司本身不确定性较高，必须继续做财报、公告、竞争格局和管理层研究。",
        "",
        "## 6. 后续人工研究建议",
        "- 阅读最近三年年报、最新季报和重大公告，确认低谷原因是否可逆。",
        "- 对比行业龙头、订单、产能、价格周期、技术路线和监管政策。",
        "- 建立跟踪清单，持续观察现金流、毛利率、收入增速和估值分位变化。",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
