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
import math
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


FINANCIAL_LOOKBACK_YEARS = 5
MIN_FINANCIAL_PERIODS = 8


def get_financial_start_date() -> str:
    """Return the earliest report date used for the rolling financial window."""
    today = dt.datetime.now()
    try:
        start = today.replace(year=today.year - FINANCIAL_LOOKBACK_YEARS)
    except ValueError:  # Handles leap day.
        start = today.replace(year=today.year - FINANCIAL_LOOKBACK_YEARS, day=28)
    return start.strftime("%Y%m%d")


def normalize_financial_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    """Keep the latest disclosed row for each report period and sort newest first."""
    if df is None or df.empty:
        return pd.DataFrame()

    normalized = df.copy()
    if "end_date" not in normalized.columns:
        return normalized.reset_index(drop=True)

    normalized["end_date"] = normalized["end_date"].astype(str)
    sort_columns = ["end_date"]
    ascending = [False]
    if "ann_date" in normalized.columns:
        normalized["ann_date"] = normalized["ann_date"].astype(str)
        sort_columns.append("ann_date")
        ascending.append(False)

    normalized = normalized.sort_values(sort_columns, ascending=ascending)
    normalized = normalized.drop_duplicates(subset=["end_date"], keep="first")
    recent_periods = normalized["end_date"].head(MIN_FINANCIAL_PERIODS)
    start_date = get_financial_start_date()
    keep_mask = (normalized["end_date"] >= start_date) | normalized["end_date"].isin(recent_periods)
    return normalized.loc[keep_mask].reset_index(drop=True)


def fetch_financial_frame(func: Any, ts_code: str, fields: str, start_date: str) -> pd.DataFrame:
    """Fetch a rolling financial frame and retry without date filter if fewer than 8 periods return."""
    df = normalize_financial_frame(func(ts_code=ts_code, start_date=start_date, fields=fields))
    if len(df) >= MIN_FINANCIAL_PERIODS:
        return df

    try:
        expanded = normalize_financial_frame(func(ts_code=ts_code, fields=fields))
    except Exception:
        return df
    if len(expanded) > len(df):
        return expanded
    return df


def get_financial_data(pro: ts.pro_api, ts_code: str) -> dict[str, pd.DataFrame]:
    financials: dict[str, pd.DataFrame] = {
        "income": pd.DataFrame(),
        "indicator": pd.DataFrame(),
        "balancesheet": pd.DataFrame(),
        "cashflow": pd.DataFrame(),
    }
    start_date = get_financial_start_date()
    window_note = f"最近 {FINANCIAL_LOOKBACK_YEARS} 年，且至少保留最近 {MIN_FINANCIAL_PERIODS} 个报告期"

    print_step(f"获取财务数据：利润表（{window_note}）")
    try:
        income = fetch_financial_frame(
            pro.income,
            ts_code,
            "ts_code,end_date,ann_date,report_type,total_revenue,n_income_attr_p",
            start_date,
        )
        if not income.empty:
            financials["income"] = income
            print_success(f"利润表获取成功，保留 {len(income)} 个报告期")
        else:
            print_warning("利润表数据为空")
    except Exception as exc:
        print_warning(f"利润表获取失败：{exc}")

    print_step(f"获取财务数据：财务指标（{window_note}）")
    try:
        indicator = fetch_financial_frame(
            pro.fina_indicator,
            ts_code,
            "ts_code,end_date,ann_date,roe,grossprofit_margin,netprofit_margin,profit_dedt",
            start_date,
        )
        if not indicator.empty:
            financials["indicator"] = indicator
            print_success(f"财务指标获取成功，保留 {len(indicator)} 个报告期")
        else:
            print_warning("财务指标数据为空")
    except Exception as exc:
        print_warning(f"财务指标获取失败：{exc}")

    print_step(f"获取财务数据：资产负债表（{window_note}）")
    try:
        balance = fetch_financial_frame(
            pro.balancesheet,
            ts_code,
            "ts_code,end_date,ann_date,total_assets,total_liab",
            start_date,
        )
        if not balance.empty:
            financials["balancesheet"] = balance
            print_success(f"资产负债表获取成功，保留 {len(balance)} 个报告期")
        else:
            print_warning("资产负债表数据为空")
    except Exception as exc:
        print_warning(f"资产负债表获取失败：{exc}")

    print_step(f"获取财务数据：现金流量表（{window_note}）")
    try:
        cashflow = fetch_financial_frame(
            pro.cashflow,
            ts_code,
            "ts_code,end_date,ann_date,n_cashflow_act",
            start_date,
        )
        if not cashflow.empty:
            financials["cashflow"] = cashflow
            print_success(f"现金流量表获取成功，保留 {len(cashflow)} 个报告期")
        else:
            print_warning("现金流量表数据为空")
    except Exception as exc:
        print_warning(f"现金流量表获取失败：{exc}")

    return financials


def to_numeric(value: Any) -> float | None:
    """Convert scalar financial values to float, returning None for missing values."""
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pct_change_text(current: Any, previous: Any) -> str:
    current_value = to_numeric(current)
    previous_value = to_numeric(previous)
    if current_value is None or previous_value in (None, 0):
        return "暂无可比数据"
    return f"{(current_value / previous_value - 1) * 100:.2f}%"


def trend_direction(values: list[float]) -> str:
    if len(values) < 2:
        return "数据不足"
    first = values[-1]
    last = values[0]
    if pd.isna(first) or pd.isna(last):
        return "数据不足"
    if last > first:
        return "上升"
    if last < first:
        return "下降"
    return "基本持平"


def get_period_row(df: pd.DataFrame, end_date: str) -> pd.Series | None:
    if df.empty or "end_date" not in df.columns:
        return None
    matched = df[df["end_date"].astype(str) == str(end_date)]
    if matched.empty:
        return None
    return matched.iloc[0]


def safe_ratio(numerator: Any, denominator: Any) -> float | None:
    numerator_value = to_numeric(numerator)
    denominator_value = to_numeric(denominator)
    if numerator_value is None or denominator_value in (None, 0):
        return None
    return numerator_value / denominator_value


def calculate_financial_trends(financials: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Calculate multi-period financial trends and recent anomaly combinations."""
    print_step("计算财务趋势：同比、利润率、现金流、资产负债率与异常组合")
    income = financials.get("income", pd.DataFrame())
    indicator = financials.get("indicator", pd.DataFrame())
    balance = financials.get("balancesheet", pd.DataFrame())
    cashflow = financials.get("cashflow", pd.DataFrame())

    periods = sorted(
        {str(value) for df in (income, indicator, balance, cashflow) if not df.empty for value in df.get("end_date", [])},
        reverse=True,
    )
    trend_rows: list[dict[str, Any]] = []
    for end_date in periods:
        income_row = get_period_row(income, end_date)
        indicator_row = get_period_row(indicator, end_date)
        balance_row = get_period_row(balance, end_date)
        cashflow_row = get_period_row(cashflow, end_date)
        previous_year = f"{int(end_date[:4]) - 1}{end_date[4:]}" if len(end_date) == 8 and end_date[:4].isdigit() else ""
        previous_income = get_period_row(income, previous_year) if previous_year else None
        previous_indicator = get_period_row(indicator, previous_year) if previous_year else None
        previous_cashflow = get_period_row(cashflow, previous_year) if previous_year else None

        operating_cashflow = cashflow_row.get("n_cashflow_act") if cashflow_row is not None else None
        net_profit = income_row.get("n_income_attr_p") if income_row is not None else None
        total_assets = balance_row.get("total_assets") if balance_row is not None else None
        total_liab = balance_row.get("total_liab") if balance_row is not None else None
        trend_rows.append(
            {
                "end_date": end_date,
                "revenue": income_row.get("total_revenue") if income_row is not None else None,
                "revenue_yoy": pct_change_text(
                    income_row.get("total_revenue") if income_row is not None else None,
                    previous_income.get("total_revenue") if previous_income is not None else None,
                ),
                "net_profit": net_profit,
                "net_profit_yoy": pct_change_text(
                    net_profit,
                    previous_income.get("n_income_attr_p") if previous_income is not None else None,
                ),
                "deducted_net_profit": indicator_row.get("profit_dedt") if indicator_row is not None else None,
                "deducted_net_profit_yoy": pct_change_text(
                    indicator_row.get("profit_dedt") if indicator_row is not None else None,
                    previous_indicator.get("profit_dedt") if previous_indicator is not None else None,
                ),
                "roe": indicator_row.get("roe") if indicator_row is not None else None,
                "gross_margin": indicator_row.get("grossprofit_margin") if indicator_row is not None else None,
                "net_margin": indicator_row.get("netprofit_margin") if indicator_row is not None else None,
                "operating_cashflow": operating_cashflow,
                "operating_cashflow_to_net_profit": safe_ratio(operating_cashflow, net_profit),
                "operating_cashflow_yoy": pct_change_text(
                    operating_cashflow,
                    previous_cashflow.get("n_cashflow_act") if previous_cashflow is not None else None,
                ),
                "debt_ratio": safe_ratio(total_liab, total_assets) * 100 if safe_ratio(total_liab, total_assets) is not None else None,
            }
        )

    latest = trend_rows[0] if trend_rows else {}
    anomalies: list[str] = []
    latest_revenue_yoy = latest.get("revenue_yoy")
    latest_profit_yoy = latest.get("net_profit_yoy")
    latest_cashflow_yoy = latest.get("operating_cashflow_yoy")
    revenue_yoy_value = to_numeric(str(latest_revenue_yoy).replace("%", "")) if latest_revenue_yoy != "暂无可比数据" else None
    profit_yoy_value = to_numeric(str(latest_profit_yoy).replace("%", "")) if latest_profit_yoy != "暂无可比数据" else None
    cashflow_yoy_value = to_numeric(str(latest_cashflow_yoy).replace("%", "")) if latest_cashflow_yoy != "暂无可比数据" else None
    cashflow_profit_ratio = latest.get("operating_cashflow_to_net_profit")

    if revenue_yoy_value is not None and profit_yoy_value is not None and revenue_yoy_value > 0 and profit_yoy_value < 0:
        anomalies.append("最近一期收入同比增长但归母净利润同比下滑，需关注增收不增利风险。")
    if profit_yoy_value is not None and cashflow_yoy_value is not None and profit_yoy_value > 0 and cashflow_yoy_value < 0:
        anomalies.append("最近一期归母净利润同比增长但经营现金流同比恶化，需关注利润质量。")
    if profit_yoy_value is not None and profit_yoy_value > 0 and cashflow_profit_ratio is not None and cashflow_profit_ratio < 0.8:
        anomalies.append("最近一期经营现金流/净利润低于 0.8，利润现金含量偏弱。")
    if not anomalies:
        anomalies.append("最近一期未发现收入、利润与现金流之间的典型背离组合，仍需结合行业周期和会计政策复核。")

    roe_values = [value for value in (to_numeric(row.get("roe")) for row in trend_rows) if value is not None]
    gross_margin_values = [value for value in (to_numeric(row.get("gross_margin")) for row in trend_rows) if value is not None]
    net_margin_values = [value for value in (to_numeric(row.get("net_margin")) for row in trend_rows) if value is not None]
    debt_ratio_values = [value for value in (to_numeric(row.get("debt_ratio")) for row in trend_rows) if value is not None]
    conclusions = [
        f"ROE 多期趋势：{trend_direction(roe_values)}。",
        f"毛利率多期趋势：{trend_direction(gross_margin_values)}。",
        f"净利率多期趋势：{trend_direction(net_margin_values)}。",
        f"资产负债率趋势：{trend_direction(debt_ratio_values)}。",
        *anomalies,
    ]
    print_success("财务趋势计算完成")
    return {"rows": trend_rows, "conclusions": conclusions}

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
        numeric_value = float(value)
        if math.isnan(numeric_value) or math.isinf(numeric_value):
            return "暂无数据"
        return f"{numeric_value:.{digits}f}{suffix}"
    return str(value)



def format_financial_trend_rows(rows: list[dict[str, Any]], limit: int = 20) -> str:
    if not rows:
        return "暂无多期财务数据"

    headers = [
        "报告期",
        "营收",
        "营收同比",
        "归母净利润",
        "归母净利润同比",
        "扣非净利润",
        "扣非净利润同比",
        "ROE",
        "毛利率",
        "净利率",
        "经营现金流",
        "经营现金流/净利润",
        "经营现金流同比",
        "资产负债率",
    ]
    lines = [" | ".join(headers), " | ".join(["---"] * len(headers))]
    for row in rows[:limit]:
        lines.append(
            " | ".join(
                [
                    str(row.get("end_date", "暂无数据")),
                    safe_fmt(row.get("revenue"), " 元"),
                    str(row.get("revenue_yoy", "暂无可比数据")),
                    safe_fmt(row.get("net_profit"), " 元"),
                    str(row.get("net_profit_yoy", "暂无可比数据")),
                    safe_fmt(row.get("deducted_net_profit"), " 元"),
                    str(row.get("deducted_net_profit_yoy", "暂无可比数据")),
                    safe_fmt(row.get("roe"), "%"),
                    safe_fmt(row.get("gross_margin"), "%"),
                    safe_fmt(row.get("net_margin"), "%"),
                    safe_fmt(row.get("operating_cashflow"), " 元"),
                    safe_fmt(row.get("operating_cashflow_to_net_profit"), " 倍"),
                    str(row.get("operating_cashflow_yoy", "暂无可比数据")),
                    safe_fmt(row.get("debt_ratio"), "%"),
                ]
            )
        )
    return "\n".join(lines)


def format_raw_financial_tables(financials: dict[str, pd.DataFrame], limit: int = 20) -> str:
    table_config = [
        ("利润表原始数据", "income", ["end_date", "ann_date", "report_type", "total_revenue", "n_income_attr_p"]),
        ("财务指标原始数据", "indicator", ["end_date", "ann_date", "roe", "grossprofit_margin", "netprofit_margin", "profit_dedt"]),
        ("资产负债表原始数据", "balancesheet", ["end_date", "ann_date", "total_assets", "total_liab"]),
        ("现金流量表原始数据", "cashflow", ["end_date", "ann_date", "n_cashflow_act"]),
    ]
    sections: list[str] = []
    for title, key, columns in table_config:
        df = financials.get(key, pd.DataFrame())
        if df.empty:
            sections.append(f"{title}：暂无数据")
            continue
        available_columns = [column for column in columns if column in df.columns]
        raw_lines = [" | ".join(available_columns), " | ".join(["---"] * len(available_columns))]
        for _, raw_row in df[available_columns].head(limit).iterrows():
            raw_lines.append(" | ".join(str(raw_row.get(column, "暂无数据")) for column in available_columns))
        sections.append(f"{title}：\n" + "\n".join(raw_lines))
    return "\n\n".join(sections)

def build_structured_text(
    stock_basic: pd.Series,
    tech: pd.DataFrame,
    financials: dict[str, pd.DataFrame],
    valuation: pd.DataFrame,
) -> str:
    print_step("整理结构化分析文本")
    latest = tech.iloc[-1]
    previous = tech.iloc[-2] if len(tech) >= 2 else latest
    latest_val = valuation.iloc[-1]
    financial_trends = calculate_financial_trends(financials)
    trend_rows = financial_trends.get("rows", [])
    trend_conclusions = financial_trends.get("conclusions", [])
    latest_financial = trend_rows[0] if trend_rows else {}
    financial_table = format_financial_trend_rows(trend_rows)
    raw_financial_tables = format_raw_financial_tables(financials)

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

    财务趋势结论（基于最近 {FINANCIAL_LOOKBACK_YEARS} 年，且至少最近 {MIN_FINANCIAL_PERIODS} 个报告期）：
    {chr(10).join(f'- {item}' for item in trend_conclusions)}

    财务数据（最新可得报告摘要）：
    - 报告期：{latest_financial.get('end_date', '暂无数据')}
    - 营收：{safe_fmt(latest_financial.get('revenue'), ' 元')}
    - 营收同比：{latest_financial.get('revenue_yoy', '暂无可比数据')}
    - 归母净利润：{safe_fmt(latest_financial.get('net_profit'), ' 元')}
    - 归母净利润同比：{latest_financial.get('net_profit_yoy', '暂无可比数据')}
    - 扣非净利润：{safe_fmt(latest_financial.get('deducted_net_profit'), ' 元')}
    - 扣非净利润同比：{latest_financial.get('deducted_net_profit_yoy', '暂无可比数据')}
    - ROE：{safe_fmt(latest_financial.get('roe'), '%')}
    - 毛利率：{safe_fmt(latest_financial.get('gross_margin'), '%')}
    - 净利率：{safe_fmt(latest_financial.get('net_margin'), '%')}
    - 经营现金流：{safe_fmt(latest_financial.get('operating_cashflow'), ' 元')}
    - 经营现金流/净利润：{safe_fmt(latest_financial.get('operating_cashflow_to_net_profit'), ' 倍')}
    - 资产负债率：{safe_fmt(latest_financial.get('debt_ratio'), '%')}

    财务趋势原始计算表：
    {financial_table}

    财务报表原始数据：
    {raw_financial_tables}

    估值数据：
    - PE：{safe_fmt(latest_val.get('pe'))}
    - PB：{safe_fmt(latest_val.get('pb'))}
    - 总市值：{safe_fmt(latest_val.get('total_mv'), ' 万元')}
    - 流通市值：{safe_fmt(latest_val.get('circ_mv'), ' 万元')}
    - 换手率：{safe_fmt(latest_val.get('turnover_rate'), '%')}
    - 量比：{safe_fmt(latest_val.get('volume_ratio'))}

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