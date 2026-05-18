"""A-share AI investment analysis CLI powered by Tushare Pro and DeepSeek.

This tool is designed for Windows 11 + VS Code terminals, but also runs on
Linux/macOS. API keys are loaded from environment variables only:

- TUSHARE_TOKEN: Tushare Pro token
- DEEPSEEK_API_KEY: DeepSeek API key

Disclaimer: generated content is for reference only and does not constitute
investment advice.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import textwrap
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests
import tushare as ts

DISCLAIMER = "仅供参考，不构成投资建议。市场有风险，投资需谨慎。"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"


class AnalyzerError(Exception):
    """User-friendly error for expected failures."""


@dataclass(frozen=True)
class Config:
    tushare_token: str
    deepseek_api_key: str
    deepseek_model: str = DEFAULT_DEEPSEEK_MODEL


def print_step(message: str) -> None:
    """Print a clear step message for terminal users."""
    print(f"\n[步骤] {message}")


def print_success(message: str) -> None:
    print(f"[完成] {message}")


def print_warning(message: str) -> None:
    print(f"[提示] {message}")


def load_config() -> Config:
    """Load API credentials from environment variables."""
    print_step("读取环境变量中的 API Key")
    tushare_token = os.getenv("TUSHARE_TOKEN", "").strip()
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    deepseek_model = os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL).strip() or DEFAULT_DEEPSEEK_MODEL

    missing = []
    if not tushare_token:
        missing.append("TUSHARE_TOKEN")
    if not deepseek_api_key:
        missing.append("DEEPSEEK_API_KEY")
    if missing:
        raise AnalyzerError(
            "缺少环境变量："
            + ", ".join(missing)
            + "。请先在 Windows PowerShell 中设置，例如：\n"
            + '  setx TUSHARE_TOKEN "你的TushareToken"\n'
            + '  setx DEEPSEEK_API_KEY "你的DeepSeekKey"\n'
            + "设置后请重新打开 VS Code 终端。"
        )

    print_success("API Key 已读取（不会在程序中打印或保存）")
    return Config(tushare_token=tushare_token, deepseek_api_key=deepseek_api_key, deepseek_model=deepseek_model)


def normalize_stock_code(raw_code: str) -> str:
    """Convert a user input such as 002594 to a Tushare ts_code."""
    code = raw_code.strip().upper()
    if code.endswith((".SZ", ".SH", ".BJ")):
        return code
    if not (code.isdigit() and len(code) == 6):
        raise AnalyzerError("股票代码格式不正确。请输入 6 位股票代码，例如 002594。")
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    raise AnalyzerError("暂不支持该股票代码前缀，请输入常见 A 股代码，例如 002594、600519。")


def init_tushare(config: Config) -> ts.pro_api:
    print_step("初始化 Tushare Pro")
    ts.set_token(config.tushare_token)
    pro = ts.pro_api()
    print_success("Tushare Pro 初始化完成")
    return pro


def call_tushare(func: Any, friendly_name: str, **kwargs: Any) -> pd.DataFrame:
    """Call a Tushare endpoint with friendly error handling."""
    print_step(f"获取{friendly_name}")
    try:
        df = func(**kwargs)
    except Exception as exc:  # Tushare raises broad exceptions for API/network issues.
        raise AnalyzerError(f"{friendly_name}获取失败：{exc}") from exc
    if df is None or df.empty:
        raise AnalyzerError(f"{friendly_name}为空，请检查股票代码、Tushare 权限或接口积分。")
    print_success(f"{friendly_name}获取成功，共 {len(df)} 条记录")
    return df


def get_stock_basic(pro: ts.pro_api, ts_code: str) -> pd.Series:
    df = call_tushare(
        pro.stock_basic,
        "股票基础信息",
        exchange="",
        list_status="L",
        fields="ts_code,symbol,name,area,industry,market,list_date",
    )
    matched = df[df["ts_code"] == ts_code]
    if matched.empty:
        raise AnalyzerError(f"未找到股票 {ts_code} 的基础信息，请确认代码是否为已上市 A 股。")
    return matched.iloc[0]


def get_daily_data(pro: ts.pro_api, ts_code: str) -> pd.DataFrame:
    end_date = dt.datetime.now().strftime("%Y%m%d")
    start_date = (dt.datetime.now() - dt.timedelta(days=420)).strftime("%Y%m%d")
    df = call_tushare(
        pro.daily,
        "最近一年日K线数据",
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
    )
    df = df.sort_values("trade_date").reset_index(drop=True)
    return df


def get_daily_basic(pro: ts.pro_api, ts_code: str) -> pd.DataFrame:
    end_date = dt.datetime.now().strftime("%Y%m%d")
    start_date = (dt.datetime.now() - dt.timedelta(days=420)).strftime("%Y%m%d")
    df = call_tushare(
        pro.daily_basic,
        "估值数据",
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
        fields="ts_code,trade_date,pe,pb,total_mv,circ_mv,turnover_rate,volume_ratio",
    )
    return df.sort_values("trade_date").reset_index(drop=True)


def get_financial_data(pro: ts.pro_api, ts_code: str) -> dict[str, pd.Series | pd.DataFrame | None]:
    financials: dict[str, pd.Series | pd.DataFrame | None] = {
        "income": None,
        "income_history": None,
        "indicator": None,
        "indicator_history": None,
        "balancesheet": None,
        "balancesheet_history": None,
        "cashflow": None,
        "cashflow_history": None,
    }

    print_step("获取财务数据：营收、净利润")
    try:
        income = pro.income(
            ts_code=ts_code,
            fields="ts_code,end_date,ann_date,report_type,total_revenue,n_income_attr_p",
        )
        if income is not None and not income.empty:
            income = income.sort_values("end_date", ascending=False).drop_duplicates("end_date")
            financials["income"] = income.iloc[0]
            financials["income_history"] = income
            print_success("营收、净利润获取成功")
        else:
            print_warning("营收、净利润数据为空")
    except Exception as exc:
        print_warning(f"营收、净利润获取失败：{exc}")

    print_step("获取财务数据：ROE、毛利率")
    try:
        indicator_fields = "ts_code,end_date,ann_date,roe,grossprofit_margin,netprofit_margin,tr_yoy,netprofit_yoy"
        try:
            indicator = pro.fina_indicator(ts_code=ts_code, fields=indicator_fields)
        except Exception:
            indicator = pro.fina_indicator(ts_code=ts_code, fields="ts_code,end_date,ann_date,roe,grossprofit_margin")
        if indicator is not None and not indicator.empty:
            indicator = indicator.sort_values("end_date", ascending=False).drop_duplicates("end_date")
            financials["indicator"] = indicator.iloc[0]
            financials["indicator_history"] = indicator
            print_success("ROE、毛利率获取成功")
        else:
            print_warning("ROE、毛利率数据为空")
    except Exception as exc:
        print_warning(f"ROE、毛利率获取失败：{exc}")

    print_step("获取财务数据：资产负债率")
    try:
        balance = pro.balancesheet(
            ts_code=ts_code,
            fields="ts_code,end_date,ann_date,total_assets,total_liab",
        )
        if balance is not None and not balance.empty:
            balance = balance.sort_values("end_date", ascending=False).drop_duplicates("end_date")
            financials["balancesheet"] = balance.iloc[0]
            financials["balancesheet_history"] = balance
            print_success("资产负债率获取成功")
        else:
            print_warning("资产负债率数据为空")
    except Exception as exc:
        print_warning(f"资产负债率获取失败：{exc}")

    print_step("获取财务数据：经营现金流")
    try:
        cashflow = pro.cashflow(
            ts_code=ts_code,
            fields="ts_code,end_date,ann_date,n_cashflow_act",
        )
        if cashflow is not None and not cashflow.empty:
            cashflow = cashflow.sort_values("end_date", ascending=False).drop_duplicates("end_date")
            financials["cashflow"] = cashflow.iloc[0]
            financials["cashflow_history"] = cashflow
            print_success("经营现金流获取成功")
        else:
            print_warning("经营现金流数据为空")
    except Exception as exc:
        print_warning(f"经营现金流获取失败：{exc}")

    return financials


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def calculate_technical_indicators(daily: pd.DataFrame) -> pd.DataFrame:
    print_step("计算技术指标：MA、RSI、MACD、成交量变化、近20日涨跌幅")
    df = daily.copy()
    for window in (5, 10, 20, 60):
        df[f"ma{window}"] = df["close"].rolling(window=window).mean()

    df["rsi14"] = calculate_rsi(df["close"])
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd_dif"] = ema12 - ema26
    df["macd_dea"] = df["macd_dif"].ewm(span=9, adjust=False).mean()
    df["macd"] = 2 * (df["macd_dif"] - df["macd_dea"])
    df["volume_change_pct"] = df["vol"].pct_change() * 100
    df["return_20d_pct"] = (df["close"] / df["close"].shift(20) - 1) * 100
    print_success("技术指标计算完成")
    return df


def safe_fmt(value: Any, suffix: str = "", digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "暂无数据"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}{suffix}"
    return str(value)


def safe_float(value: Any) -> float | None:
    """Convert pandas/numpy scalar values to float while preserving missing data."""
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp_score(value: float, lower: float = 0, upper: float = 100) -> float:
    return max(lower, min(upper, value))


def score_by_range(value: float | None, ranges: list[tuple[float, float]]) -> float:
    """Return the score for the first threshold the value reaches."""
    if value is None:
        return 50
    for threshold, score in ranges:
        if value >= threshold:
            return score
    return 20


def percentile_rank(series: pd.Series, current: Any, lower_is_better: bool = False) -> float | None:
    """Calculate the historical percentile rank of current in a numeric series."""
    current_value = safe_float(current)
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if current_value is None or len(numeric) < 20:
        return None
    rank = (numeric <= current_value).mean() * 100
    if lower_is_better:
        rank = 100 - rank
    return float(rank)


def calculate_growth_rate(latest: float | None, previous: float | None) -> float | None:
    if latest is None or previous is None or previous == 0:
        return None
    return (latest / abs(previous) - 1) * 100


def calculate_cagr(latest: float | None, earliest: float | None, periods: float) -> float | None:
    if latest is None or earliest is None or earliest <= 0 or latest <= 0 or periods <= 0:
        return None
    return ((latest / earliest) ** (1 / periods) - 1) * 100


def latest_as_series(value: pd.Series | pd.DataFrame | None) -> pd.Series | None:
    if isinstance(value, pd.Series):
        return value
    if isinstance(value, pd.DataFrame) and not value.empty:
        return value.iloc[0]
    return None


def get_history(value: pd.Series | pd.DataFrame | None) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return pd.DataFrame()


def calculate_factor_score(
    tech: pd.DataFrame,
    financials: dict[str, pd.Series | pd.DataFrame | None],
    valuation: pd.DataFrame,
) -> dict[str, Any]:
    """Generate a deterministic factor score before the model explains/refines it."""
    latest = tech.iloc[-1]
    previous = tech.iloc[-2] if len(tech) >= 2 else latest
    latest_val = valuation.iloc[-1]
    income = latest_as_series(financials.get("income"))
    indicator = latest_as_series(financials.get("indicator"))
    balance = latest_as_series(financials.get("balancesheet"))
    cashflow = latest_as_series(financials.get("cashflow"))
    income_history = get_history(financials.get("income_history"))
    valuation_history = valuation.copy()

    roe = safe_float(indicator.get("roe") if indicator is not None else None)
    gross_margin = safe_float(indicator.get("grossprofit_margin") if indicator is not None else None)
    net_margin = safe_float(indicator.get("netprofit_margin") if indicator is not None else None)
    revenue_yoy = safe_float(indicator.get("tr_yoy") if indicator is not None else None)
    profit_yoy = safe_float(indicator.get("netprofit_yoy") if indicator is not None else None)
    net_profit = safe_float(income.get("n_income_attr_p") if income is not None else None)
    operating_cashflow = safe_float(cashflow.get("n_cashflow_act") if cashflow is not None else None)
    cashflow_quality = None
    if net_profit not in (None, 0) and operating_cashflow is not None:
        cashflow_quality = operating_cashflow / abs(net_profit)

    debt_ratio = None
    if balance is not None:
        total_assets = safe_float(balance.get("total_assets"))
        total_liab = safe_float(balance.get("total_liab"))
        if total_assets:
            debt_ratio = total_liab / total_assets * 100 if total_liab is not None else None

    if not income_history.empty and len(income_history) >= 2:
        latest_income = income_history.iloc[0]
        comparable_income = income_history.iloc[1]
        if revenue_yoy is None:
            revenue_yoy = calculate_growth_rate(
                safe_float(latest_income.get("total_revenue")), safe_float(comparable_income.get("total_revenue"))
            )
        if profit_yoy is None:
            profit_yoy = calculate_growth_rate(
                safe_float(latest_income.get("n_income_attr_p")), safe_float(comparable_income.get("n_income_attr_p"))
            )

    revenue_cagr = None
    profit_cagr = None
    if not income_history.empty and len(income_history) >= 4:
        recent = income_history.iloc[0]
        earlier = income_history.iloc[min(len(income_history) - 1, 3)]
        revenue_cagr = calculate_cagr(
            safe_float(recent.get("total_revenue")), safe_float(earlier.get("total_revenue")), periods=3
        )
        profit_cagr = calculate_cagr(
            safe_float(recent.get("n_income_attr_p")), safe_float(earlier.get("n_income_attr_p")), periods=3
        )

    pe = safe_float(latest_val.get("pe"))
    pb = safe_float(latest_val.get("pb"))
    pe_attractiveness = percentile_rank(valuation_history["pe"], pe, lower_is_better=True) if "pe" in valuation_history else None
    pb_attractiveness = percentile_rank(valuation_history["pb"], pb, lower_is_better=True) if "pb" in valuation_history else None
    pe_score = pe_attractiveness if pe_attractiveness is not None else (70 if pe is not None and 0 < pe <= 25 else 45)
    pb_score = pb_attractiveness if pb_attractiveness is not None else (70 if pb is not None and 0 < pb <= 3 else 45)

    close = safe_float(latest.get("close"))
    ma5 = safe_float(latest.get("ma5"))
    ma10 = safe_float(latest.get("ma10"))
    ma20 = safe_float(latest.get("ma20"))
    ma60 = safe_float(latest.get("ma60"))
    return_20d = safe_float(latest.get("return_20d_pct"))
    rsi = safe_float(latest.get("rsi14"))
    macd = safe_float(latest.get("macd"))
    macd_dif = safe_float(latest.get("macd_dif"))
    macd_dea = safe_float(latest.get("macd_dea"))
    volume_change_pct = safe_float(latest.get("volume_change_pct"))
    daily_return = None
    previous_close = safe_float(previous.get("close"))
    if close is not None and previous_close:
        daily_return = (close / previous_close - 1) * 100

    profitability_score = clamp_score(
        score_by_range(roe, [(20, 95), (15, 85), (10, 70), (5, 55), (0, 40)]) * 0.35
        + score_by_range(gross_margin, [(50, 90), (35, 78), (25, 65), (15, 50), (0, 35)]) * 0.25
        + score_by_range(net_margin, [(20, 90), (12, 75), (8, 65), (3, 50), (0, 35)]) * 0.2
        + score_by_range(cashflow_quality, [(1.2, 90), (1.0, 78), (0.7, 60), (0.3, 45), (0, 30)]) * 0.2
    )
    growth_score = clamp_score(
        score_by_range(revenue_yoy, [(30, 95), (15, 80), (5, 65), (0, 50), (-10, 35)]) * 0.35
        + score_by_range(profit_yoy, [(30, 95), (15, 80), (5, 65), (0, 50), (-10, 35)]) * 0.35
        + score_by_range(revenue_cagr, [(20, 90), (12, 78), (5, 65), (0, 50), (-5, 35)]) * 0.15
        + score_by_range(profit_cagr, [(20, 90), (12, 78), (5, 65), (0, 50), (-5, 35)]) * 0.15
    )
    valuation_score = clamp_score(pe_score * 0.55 + pb_score * 0.45)

    ma_bullish = all(value is not None for value in (close, ma5, ma10, ma20, ma60)) and close > ma5 > ma10 > ma20 > ma60
    ma_bearish = all(value is not None for value in (close, ma5, ma10, ma20, ma60)) and close < ma5 < ma10 < ma20 < ma60
    ma_score = 85 if ma_bullish else 25 if ma_bearish else 55
    return_score = score_by_range(return_20d, [(10, 80), (3, 65), (-3, 55), (-10, 40), (-20, 25)])
    rsi_score = 50 if rsi is None else 35 if rsi >= 80 else 50 if rsi >= 70 else 80 if 45 <= rsi <= 65 else 65 if 35 <= rsi < 45 else 35 if rsi < 25 else 55
    macd_score = 75 if macd is not None and macd > 0 and macd_dif is not None and macd_dea is not None and macd_dif > macd_dea else 35 if macd is not None and macd < 0 else 50
    technical_score = clamp_score(ma_score * 0.35 + return_score * 0.25 + rsi_score * 0.2 + macd_score * 0.2)

    risk_deductions: list[tuple[str, float]] = []
    if debt_ratio is not None and debt_ratio >= 70:
        risk_deductions.append((f"资产负债率偏高（{safe_fmt(debt_ratio, '%')}）", 18))
    if revenue_yoy is not None and revenue_yoy < 0:
        risk_deductions.append((f"营收同比下滑（{safe_fmt(revenue_yoy, '%')}）", 10))
    if profit_yoy is not None and profit_yoy < 0:
        risk_deductions.append((f"净利润同比下滑（{safe_fmt(profit_yoy, '%')}）", 15))
    if (pe_attractiveness is not None and pe_attractiveness < 15) or (pb_attractiveness is not None and pb_attractiveness < 15):
        risk_deductions.append(("PE/PB 处于历史偏贵区间", 10))
    if daily_return is not None and volume_change_pct is not None and daily_return <= -3 and volume_change_pct >= 50:
        risk_deductions.append(("出现放量下跌信号", 12))
    if cashflow_quality is not None and cashflow_quality < 0.5:
        risk_deductions.append((f"经营现金流质量偏弱（现金流/净利润 {safe_fmt(cashflow_quality)}）", 12))

    risk_penalty = min(35, sum(penalty for _, penalty in risk_deductions))
    risk_score = clamp_score(100 - risk_penalty)
    total_score = clamp_score(
        profitability_score * 0.25
        + growth_score * 0.2
        + valuation_score * 0.2
        + technical_score * 0.2
        + risk_score * 0.15
    )

    bonus_items: list[str] = []
    if roe is not None and roe >= 15:
        bonus_items.append(f"ROE 较高（{safe_fmt(roe, '%')}）")
    if cashflow_quality is not None and cashflow_quality >= 1:
        bonus_items.append("经营现金流覆盖净利润")
    if revenue_yoy is not None and revenue_yoy >= 15:
        bonus_items.append(f"营收同比增长较快（{safe_fmt(revenue_yoy, '%')}）")
    if profit_yoy is not None and profit_yoy >= 15:
        bonus_items.append(f"净利润同比增长较快（{safe_fmt(profit_yoy, '%')}）")
    if ma_bullish:
        bonus_items.append("均线呈多头排列")
    if pe_attractiveness is not None and pe_attractiveness >= 70:
        bonus_items.append("PE 处于历史相对便宜区间")

    if total_score >= 80:
        level = "优秀"
    elif total_score >= 65:
        level = "良好"
    elif total_score >= 50:
        level = "中性"
    elif total_score >= 35:
        level = "偏弱"
    else:
        level = "高风险"

    return {
        "total_score": round(total_score, 1),
        "dimension_scores": {
            "盈利质量": round(profitability_score, 1),
            "成长性": round(growth_score, 1),
            "估值吸引力": round(valuation_score, 1),
            "技术趋势": round(technical_score, 1),
            "风险控制": round(risk_score, 1),
        },
        "bonus_items": bonus_items or ["暂无显著加分项"],
        "deduction_items": [item for item, _ in risk_deductions] or ["暂无显著扣分项"],
        "level": level,
        "key_metrics": {
            "营收同比": revenue_yoy,
            "净利润同比": profit_yoy,
            "营收三期复合增长": revenue_cagr,
            "净利润三期复合增长": profit_cagr,
            "现金流/净利润": cashflow_quality,
            "PE历史吸引力分位": pe_attractiveness,
            "PB历史吸引力分位": pb_attractiveness,
            "PE行业分位": None,
            "PB行业分位": None,
        },
    }


def format_factor_score(factor_score: dict[str, Any]) -> str:
    dimension_lines = "\n".join(
        f"- {name}：{safe_fmt(score)} 分" for name, score in factor_score["dimension_scores"].items()
    )
    bonus_lines = "\n".join(f"- {item}" for item in factor_score["bonus_items"])
    deduction_lines = "\n".join(f"- {item}" for item in factor_score["deduction_items"])
    metrics = factor_score["key_metrics"]
    metric_lines = "\n".join(
        f"- {name}：{safe_fmt(value, '%' if '同比' in name or '复合增长' in name or '分位' in name else '')}"
        for name, value in metrics.items()
    )
    return f"""
    程序基础因子评分（模型应优先解释该评分，仅能在明确说明理由时小幅微调）：
    - 总分：{safe_fmt(factor_score['total_score'])} 分
    - 最终等级：{factor_score['level']}
    - 评分维度：
    {textwrap.indent(dimension_lines, '  ')}
    - 加分项：
    {textwrap.indent(bonus_lines, '  ')}
    - 扣分项：
    {textwrap.indent(deduction_lines, '  ')}
    - 关键评分指标：
    {textwrap.indent(metric_lines, '  ')}
    """


def build_structured_text(
    stock_basic: pd.Series,
    tech: pd.DataFrame,
    financials: dict[str, pd.Series | pd.DataFrame | None],
    valuation: pd.DataFrame,
) -> str:
    print_step("整理结构化分析文本")
    latest = tech.iloc[-1]
    previous = tech.iloc[-2] if len(tech) >= 2 else latest
    latest_val = valuation.iloc[-1]
    income = financials.get("income")
    indicator = financials.get("indicator")
    balance = financials.get("balancesheet")
    cashflow = financials.get("cashflow")
    factor_score = calculate_factor_score(tech, financials, valuation)
    factor_score_text = format_factor_score(factor_score)

    debt_ratio = None
    if balance is not None and not pd.isna(balance.get("total_assets")) and balance.get("total_assets"):
        debt_ratio = balance.get("total_liab") / balance.get("total_assets") * 100

    text = f"""
    股票基础信息：
    - 代码：{stock_basic.get('ts_code')}
    - 名称：{stock_basic.get('name')}
    - 地区：{stock_basic.get('area')}
    - 行业：{stock_basic.get('industry')}
    - 市场：{stock_basic.get('market')}
    - 上市日期：{stock_basic.get('list_date')}

    最新行情与技术指标：
    - 最新交易日：{latest.get('trade_date')}
    - 收盘价：{safe_fmt(latest.get('close'))}
    - 前收盘价：{safe_fmt(previous.get('close'))}
    - MA5：{safe_fmt(latest.get('ma5'))}
    - MA10：{safe_fmt(latest.get('ma10'))}
    - MA20：{safe_fmt(latest.get('ma20'))}
    - MA60：{safe_fmt(latest.get('ma60'))}
    - RSI14：{safe_fmt(latest.get('rsi14'))}
    - MACD DIF：{safe_fmt(latest.get('macd_dif'))}
    - MACD DEA：{safe_fmt(latest.get('macd_dea'))}
    - MACD 柱：{safe_fmt(latest.get('macd'))}
    - 最新成交量变化：{safe_fmt(latest.get('volume_change_pct'), '%')}
    - 近20个交易日涨跌幅：{safe_fmt(latest.get('return_20d_pct'), '%')}

    财务数据（最新可得报告）：
    - 报告期（利润表）：{income.get('end_date') if income is not None else '暂无数据'}
    - 营收：{safe_fmt(income.get('total_revenue') if income is not None else None, ' 元')}
    - 归母净利润：{safe_fmt(income.get('n_income_attr_p') if income is not None else None, ' 元')}
    - 经营活动现金流净额：{safe_fmt(cashflow.get('n_cashflow_act') if cashflow is not None else None, ' 元')}
    - 报告期（财务指标）：{indicator.get('end_date') if indicator is not None else '暂无数据'}
    - ROE：{safe_fmt(indicator.get('roe') if indicator is not None else None, '%')}
    - 毛利率：{safe_fmt(indicator.get('grossprofit_margin') if indicator is not None else None, '%')}
    - 净利率：{safe_fmt(indicator.get('netprofit_margin') if indicator is not None else None, '%')}
    - 营收同比：{safe_fmt(indicator.get('tr_yoy') if indicator is not None else None, '%')}
    - 净利润同比：{safe_fmt(indicator.get('netprofit_yoy') if indicator is not None else None, '%')}
    - 报告期（资产负债表）：{balance.get('end_date') if balance is not None else '暂无数据'}
    - 资产负债率：{safe_fmt(debt_ratio, '%')}

    估值数据：
    - PE：{safe_fmt(latest_val.get('pe'))}
    - PB：{safe_fmt(latest_val.get('pb'))}
    - 总市值：{safe_fmt(latest_val.get('total_mv'), ' 万元')}
    - 流通市值：{safe_fmt(latest_val.get('circ_mv'), ' 万元')}
    - 换手率：{safe_fmt(latest_val.get('turnover_rate'), '%')}
    - 量比：{safe_fmt(latest_val.get('volume_ratio'))}

    {factor_score_text}

    分析周期定义：
    - 短期：3-5个交易日
    - 中期：2-3个月
    - 长期：1年左右
    """
    structured = textwrap.dedent(text).strip()
    print_success("结构化文本整理完成")
    return structured


def call_deepseek(config: Config, structured_text: str) -> str:
    print_step("调用 DeepSeek API 生成深度分析报告")
    system_prompt = (
        "你是严谨的A股研究助理。请基于用户提供的数据生成分析报告，"
        "不得编造未提供的数据，不得给出绝对买卖指令，必须明确提示：仅供参考，不构成投资建议。"
    )
    user_prompt = f"""
    请基于以下结构化数据，生成 A 股股票 AI 投资分析报告，必须包含：
    1. 短期投资建议（3-5个交易日）
    2. 中期投资建议（2-3个月）
    3. 长期投资建议（1年左右）
    4. 风险提示
    5. 综合评分（0-100，并解释依据）
    6. 是否适合当前买入（只能使用审慎、观望、分批关注等非绝对表述）

    关于评分：结构化数据中已经包含“程序基础因子评分”。你不得随意改变程序评分；
    应优先解释程序评分的来源和含义。若确有必要微调总分或等级，只能在明确列出数据依据、
    微调幅度和原因后进行小幅修正，且不得凭空引入未提供的数据。

    请使用中文，结构清晰，避免夸大收益，最后再次注明“{DISCLAIMER}”。

    数据如下：
    {structured_text}
    """
    payload = {
        "model": config.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": textwrap.dedent(user_prompt).strip()},
        ],
        "temperature": 0.3,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {config.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
    except requests.Timeout as exc:
        raise AnalyzerError("DeepSeek API 请求超时，请稍后重试或检查网络。") from exc
    except requests.RequestException as exc:
        detail = exc.response.text if getattr(exc, "response", None) is not None else str(exc)
        raise AnalyzerError(f"DeepSeek API 调用失败：{detail}") from exc
    except (KeyError, IndexError, ValueError) as exc:
        raise AnalyzerError(f"DeepSeek API 返回格式异常：{exc}") from exc

    if DISCLAIMER not in content:
        content = f"{content}\n\n{DISCLAIMER}"
    print_success("DeepSeek 分析报告生成完成")
    return content


def analyze_stock(raw_code: str) -> str:
    print("=" * 72)
    print("A股股票 AI 投资分析系统 - 第一版")
    print(DISCLAIMER)
    print("=" * 72)

    config = load_config()
    ts_code = normalize_stock_code(raw_code)
    print_success(f"股票代码已识别为 Tushare 格式：{ts_code}")

    pro = init_tushare(config)
    stock_basic = get_stock_basic(pro, ts_code)
    daily = get_daily_data(pro, ts_code)
    tech = calculate_technical_indicators(daily)
    valuation = get_daily_basic(pro, ts_code)
    financials = get_financial_data(pro, ts_code)
    structured_text = build_structured_text(stock_basic, tech, financials, valuation)

    print("\n" + "-" * 72)
    print("已整理的数据摘要：")
    print(structured_text)
    print("-" * 72)

    report = call_deepseek(config, structured_text)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A股股票 AI 投资分析系统")
    parser.add_argument("stock_code", nargs="?", help="6 位 A 股股票代码，例如 002594；也支持 002594.SZ")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_code = args.stock_code or input("请输入股票代码（例如 002594）：").strip()
    try:
        report = analyze_stock(raw_code)
    except AnalyzerError as exc:
        print(f"\n[错误] {exc}")
        print(f"[免责声明] {DISCLAIMER}")
        return 1
    except KeyboardInterrupt:
        print("\n[错误] 用户已取消操作。")
        return 130

    print("\n" + "=" * 72)
    print("AI 深度分析报告")
    print("=" * 72)
    print(report)
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
