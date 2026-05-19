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


def get_financial_data(pro: ts.pro_api, ts_code: str) -> dict[str, pd.Series | None]:
    financials: dict[str, pd.Series | None] = {"income": None, "indicator": None, "balancesheet": None}

    print_step("获取财务数据：营收、净利润")
    try:
        income = pro.income(
            ts_code=ts_code,
            fields="ts_code,end_date,ann_date,report_type,total_revenue,n_income_attr_p",
        )
        if income is not None and not income.empty:
            financials["income"] = income.sort_values("end_date", ascending=False).iloc[0]
            print_success("营收、净利润获取成功")
        else:
            print_warning("营收、净利润数据为空")
    except Exception as exc:
        print_warning(f"营收、净利润获取失败：{exc}")

    print_step("获取财务数据：ROE、毛利率")
    try:
        indicator = pro.fina_indicator(
            ts_code=ts_code,
            fields="ts_code,end_date,ann_date,roe,grossprofit_margin",
        )
        if indicator is not None and not indicator.empty:
            financials["indicator"] = indicator.sort_values("end_date", ascending=False).iloc[0]
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
            financials["balancesheet"] = balance.sort_values("end_date", ascending=False).iloc[0]
            print_success("资产负债率获取成功")
        else:
            print_warning("资产负债率数据为空")
    except Exception as exc:
        print_warning(f"资产负债率获取失败：{exc}")

    return financials




def format_tushare_date(value: Any) -> str:
    """Return a compact Tushare date value as YYYYMMDD text when possible."""
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (dt.datetime, dt.date)):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    if not text:
        return ""
    return text.replace("-", "")[:8]


def normalize_event_frame(df: pd.DataFrame, event_type: str, date_columns: tuple[str, ...]) -> pd.DataFrame:
    """Normalize one optional Tushare event frame into a shared event schema."""
    if df is None or df.empty:
        return pd.DataFrame()

    normalized = df.copy()
    normalized["event_type"] = event_type
    normalized["event_date"] = ""
    for column in date_columns:
        if column in normalized.columns:
            normalized["event_date"] = normalized[column].apply(format_tushare_date)
            break

    return normalized


def call_optional_tushare(func: Any, friendly_name: str, **kwargs: Any) -> pd.DataFrame:
    """Call a best-effort Tushare endpoint without aborting the whole analysis."""
    print_step(f"尝试获取{friendly_name}")
    try:
        df = func(**kwargs)
    except Exception as exc:  # Tushare permissions and endpoint availability vary by account.
        print_warning(f"{friendly_name}获取失败，已跳过：{exc}")
        return pd.DataFrame()

    if df is None or df.empty:
        print_warning(f"{friendly_name}为空，已跳过")
        return pd.DataFrame()

    print_success(f"{friendly_name}获取成功，共 {len(df)} 条记录")
    return df


def fetch_top_list_events(pro: ts.pro_api, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch top list events with per-trade-date queries (top_list requires trade_date)."""
    print_step("尝试获取龙虎榜（按交易日逐日检索）")
    try:
        daily_dates = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date, fields="trade_date")
    except Exception as exc:
        print_warning(f"龙虎榜交易日获取失败，已跳过：{exc}")
        return pd.DataFrame()

    if daily_dates is None or daily_dates.empty or "trade_date" not in daily_dates.columns:
        print_warning("龙虎榜交易日为空，已跳过")
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    trade_dates = (
        daily_dates["trade_date"].dropna().astype(str).sort_values(ascending=False).head(30).tolist()
    )
    for trade_date in trade_dates:
        day_df = call_optional_tushare(
            pro.top_list,
            "龙虎榜",
            trade_date=trade_date,
            ts_code=ts_code,
            fields="trade_date,ts_code,name,close,pct_change,turnover_rate,amount,l_sell,l_buy,l_amount,net_amount,net_rate,amount_rate,float_values,reason",
        )
        if not day_df.empty:
            frames.append(day_df)

    if not frames:
        print_warning("龙虎榜在最近交易日未命中该股票记录或权限不可用")
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True, sort=False).drop_duplicates()
    print_success(f"龙虎榜整理完成，共 {len(merged)} 条记录")
    return merged


def get_recent_events(pro: ts.pro_api, ts_code: str) -> pd.DataFrame:
    """Fetch recent stock events from available Tushare Pro endpoints.

    The Tushare permission matrix differs by account, so this function treats
    every event endpoint as optional and returns whatever can be fetched. It
    prioritizes confirmed company events and then market/news catalysts for
    the last 90 calendar days.
    """
    end_date = dt.datetime.now().strftime("%Y%m%d")
    start_date = (dt.datetime.now() - dt.timedelta(days=90)).strftime("%Y%m%d")
    symbol = ts_code.split(".")[0]
    stock_name = ""
    industry = ""
    basic_func = getattr(pro, "stock_basic", None)
    if basic_func is not None:
        basic_df = call_optional_tushare(
            basic_func,
            "事件检索辅助基础信息",
            exchange="",
            list_status="L",
            fields="ts_code,name,industry",
        )
        if not basic_df.empty and "ts_code" in basic_df.columns:
            matched = basic_df[basic_df["ts_code"] == ts_code]
            if not matched.empty:
                stock_name = str(matched.iloc[0].get("name", "") or "").strip()
                industry = str(matched.iloc[0].get("industry", "") or "").strip()
    frames: list[pd.DataFrame] = []

    event_requests = [
        {
            "func_name": "forecast",
            "friendly_name": "业绩预告",
            "event_type": "业绩预告",
            "date_columns": ("ann_date", "end_date"),
            "kwargs": {
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date,
                "fields": "ts_code,ann_date,end_date,type,p_change_min,p_change_max,net_profit_min,net_profit_max,last_parent_net,first_ann_date,summary,change_reason",
            },
        },
        {
            "func_name": "express",
            "friendly_name": "业绩快报",
            "event_type": "业绩快报",
            "date_columns": ("ann_date", "end_date"),
            "kwargs": {
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date,
                "fields": "ts_code,ann_date,end_date,revenue,operate_profit,total_profit,n_income,total_assets,diluted_eps,diluted_roe,yoy_net_profit,bps,perf_summary,is_audit,remark",
            },
        },
        {
            "func_name_candidates": ("anns_d", "anns"),
            "friendly_name": "重大公告",
            "event_type": "重大公告",
            "date_columns": ("ann_date",),
            "kwargs": {
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date,
                "fields": "ts_code,ann_date,title,url,rec_time",
            },
        },
        {
            "func_name": "dividend",
            "friendly_name": "分红送转",
            "event_type": "分红送转",
            "date_columns": ("ann_date", "record_date", "ex_date", "imp_ann_date"),
            "kwargs": {
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date,
                "fields": "ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,cash_div,cash_div_tax,record_date,ex_date,pay_date,div_listdate,imp_ann_date,base_date,base_share",
            },
        },
        {
            "func_name": "share_float",
            "friendly_name": "限售股解禁",
            "event_type": "限售股解禁",
            "date_columns": ("float_date", "ann_date"),
            "kwargs": {
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date,
                "fields": "ts_code,ann_date,float_date,float_share,float_ratio,holder_name,share_type",
            },
        },
        {
            "func_name": "stk_holdertrade",
            "friendly_name": "股东增减持",
            "event_type": "股东增减持",
            "date_columns": ("ann_date", "begin_date", "close_date"),
            "kwargs": {
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date,
                "fields": "ts_code,ann_date,holder_name,holder_type,in_de,change_vol,change_ratio,after_share,after_ratio,avg_price,total_share,begin_date,close_date",
            },
        },
        {
            "func_name": "news",
            "friendly_name": "新闻摘要",
            "event_type": "新闻摘要",
            "date_columns": ("datetime",),
            "kwargs": {
                "start_date": start_date,
                "end_date": end_date,
                "src": "sina",
                "fields": "datetime,content,title,channels",
            },
            "post_filter": "news",
        },
    ]

    for request in event_requests:
        func = None
        if "func_name_candidates" in request:
            for candidate in request["func_name_candidates"]:
                func = getattr(pro, candidate, None)
                if func is not None:
                    break
        else:
            func = getattr(pro, request["func_name"], None)
        if func is None:
            print_warning(f"Tushare 当前客户端不支持{request['friendly_name']}接口，已跳过")
            continue

        df = call_optional_tushare(func, request["friendly_name"], **request["kwargs"])
        if df.empty:
            continue

        if request.get("post_filter") == "news":
            text_columns = [column for column in ("title", "content") if column in df.columns]
            if text_columns:
                mask = pd.Series(False, index=df.index)
                stock_name_markers = [marker for marker in (symbol, ts_code, stock_name, industry) if marker]
                for column in text_columns:
                    column_text = df[column].fillna("").astype(str)
                    for marker in stock_name_markers:
                        mask = mask | column_text.str.contains(marker, case=False, regex=False)
                df = df[mask]
            if df.empty:
                print_warning("新闻摘要未匹配到股票代码相关内容，已跳过")
                continue

        normalized = normalize_event_frame(df, request["event_type"], request["date_columns"])
        if not normalized.empty:
            frames.append(normalized)

    top_list_df = fetch_top_list_events(pro, ts_code, start_date, end_date)
    if not top_list_df.empty:
        normalized_top = normalize_event_frame(top_list_df, "龙虎榜", ("trade_date",))
        if not normalized_top.empty:
            frames.append(normalized_top)

    if not frames:
        print_warning("最近 90 天事件数据为空或当前 Tushare 权限不可用")
        return pd.DataFrame()

    events = pd.concat(frames, ignore_index=True, sort=False)
    events = events[events["event_date"].astype(str) >= start_date]
    events = events.sort_values("event_date", ascending=False, na_position="last").reset_index(drop=True)
    print_success(f"事件数据整理完成，共 {len(events)} 条可用记录")
    return events


def summarize_events(events_df: pd.DataFrame) -> str:
    """Summarize normalized recent events for the model prompt."""
    if events_df is None or events_df.empty:
        return (
            "最近 90 天未获取到可用事件数据；可能是无相关事件、接口权限不足或数据源暂不可用。"
            "请在最终报告中单独输出“待验证资讯线索”小节：基于公司与行业背景给出 3-5 条需要人工核验的新闻关键词/方向，"
            "并明确标注为“非事实数据、仅用于信息检索”。"
        )

    def pick(row: pd.Series, columns: tuple[str, ...]) -> str:
        parts = []
        for column in columns:
            if column in row.index and not pd.isna(row.get(column)):
                value = str(row.get(column)).strip()
                if value and value.lower() != "nan":
                    parts.append(f"{column}={value}")
        return "；".join(parts)

    summary_fields = {
        "业绩预告": ("type", "p_change_min", "p_change_max", "net_profit_min", "net_profit_max", "summary", "change_reason"),
        "业绩快报": ("revenue", "n_income", "yoy_net_profit", "diluted_eps", "diluted_roe", "perf_summary", "remark"),
        "重大公告": ("title", "url"),
        "分红送转": ("div_proc", "stk_div", "stk_bo_rate", "stk_co_rate", "cash_div", "cash_div_tax", "record_date", "ex_date", "pay_date"),
        "限售股解禁": ("float_date", "float_share", "float_ratio", "holder_name", "share_type"),
        "龙虎榜": ("close", "pct_change", "turnover_rate", "amount", "net_amount", "reason"),
        "股东增减持": ("holder_name", "holder_type", "in_de", "change_vol", "change_ratio", "avg_price", "begin_date", "close_date"),
        "新闻摘要": ("datetime", "title", "content", "channels"),
    }

    lines = ["最近 90 天事件数据（来自当前 Tushare 权限可获取接口；新闻为未验证线索，需交叉验证）："]
    preferred_order = ["业绩预告", "业绩快报", "重大公告", "分红送转", "限售股解禁", "龙虎榜", "股东增减持", "新闻摘要"]
    for event_type in preferred_order:
        group = events_df[events_df["event_type"] == event_type]
        if group.empty:
            lines.append(f"- {event_type}：暂无可用数据。")
            continue

        lines.append(f"- {event_type}：共 {len(group)} 条，最近记录如下：")
        for _, row in group.head(5).iterrows():
            detail = pick(row, summary_fields.get(event_type, tuple(row.index)))
            if len(detail) > 500:
                detail = detail[:500] + "..."
            lines.append(f"  * 日期 {row.get('event_date') or '未知'}：{detail or '暂无详情字段'}")

    return "\n".join(lines)


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


def _safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number) or number in (float("inf"), float("-inf")):
        return None
    return number


def _valuation_label(percentile: float | None, current: float | None, note: str = "") -> str:
    if current is None or note:
        return "极端"
    if percentile is None:
        return "合理"
    if percentile <= 20:
        return "估值偏低"
    if percentile <= 70:
        return "合理"
    if percentile <= 90:
        return "偏高"
    return "极端"


def _format_metric_summary(metric: dict[str, Any]) -> str:
    percentile = metric.get("percentile")
    percentile_text = "暂无数据" if percentile is None else f"{percentile:.1f}%"
    note = metric.get("note") or "无"
    return (
        f"当前值 {safe_fmt(metric.get('current'))}；"
        f"近1年最小值 {safe_fmt(metric.get('min'))}；"
        f"最大值 {safe_fmt(metric.get('max'))}；"
        f"中位数 {safe_fmt(metric.get('median'))}；"
        f"历史分位 {percentile_text}；"
        f"标签 {metric.get('label')}；"
        f"说明 {note}"
    )


def calculate_valuation_metrics(valuation: pd.DataFrame) -> dict[str, Any]:
    """Calculate one-year PE/PB ranges, percentiles, and valuation labels.

    PE uses only positive, finite observations in a practical range because
    negative PE usually means losses and extremely large PE values often distort
    historical comparisons. PB uses positive, finite observations in a practical
    range.
    """
    print_step("计算估值指标：PE/PB近1年区间、分位与标签")
    metric_rules = {
        "pe": {"upper": 1000.0, "name": "PE"},
        "pb": {"upper": 100.0, "name": "PB"},
    }
    result: dict[str, Any] = {}

    for metric, rule in metric_rules.items():
        if metric not in valuation.columns or valuation.empty:
            result[metric] = {
                "current": None,
                "min": None,
                "max": None,
                "median": None,
                "percentile": None,
                "label": "极端",
                "note": f"{rule['name']}数据缺失，无法判断估值分位。",
            }
            continue

        series = pd.to_numeric(valuation[metric], errors="coerce")
        current = _safe_number(series.iloc[-1]) if not series.empty else None
        upper = rule["upper"]
        valid = series[(series > 0) & (series <= upper)].dropna()

        note = ""
        if current is None:
            note = f"当前{rule['name']}为空，无法计算当前估值分位。"
        elif current <= 0:
            note = f"当前{rule['name']}为负或零，通常代表盈利为负/指标不可比。"
        elif current > upper:
            note = f"当前{rule['name']}超过{upper:g}，属于极端值，分位参考意义有限。"
        elif valid.empty:
            note = f"近1年缺少有效{rule['name']}样本，无法计算历史分位。"

        if valid.empty:
            percentile = None
            metric_min = metric_max = metric_median = None
        else:
            metric_min = float(valid.min())
            metric_max = float(valid.max())
            metric_median = float(valid.median())
            if note:
                percentile = None
            else:
                percentile = float((valid <= current).mean() * 100)

        label = _valuation_label(percentile, current, note)
        result[metric] = {
            "current": current,
            "min": metric_min,
            "max": metric_max,
            "median": metric_median,
            "percentile": percentile,
            "label": label,
            "note": note,
        }

    label_rank = {"估值偏低": 0, "合理": 1, "偏高": 2, "极端": 3}
    overall_label = max(
        (result["pe"]["label"], result["pb"]["label"]),
        key=lambda label: label_rank.get(label, 3),
    )
    result["overall_label"] = overall_label
    result["interpretation"] = (
        "分位越低代表当前估值越接近近1年低位；需结合盈利质量判断是否具备吸引力，"
        "避免仅因PE/PB低就判断便宜。"
    )
    print_success("估值指标计算完成")
    return result


def calculate_factor_scores(
    tech: pd.DataFrame,
    valuation_metrics: dict[str, Any],
    financials: dict[str, pd.Series | None],
) -> dict[str, Any]:
    """Build a simple, explainable factor scorecard for LLM grounding."""
    print_step("计算多因子评分：趋势、估值、质量、风险")
    latest = tech.iloc[-1]
    score_details: dict[str, dict[str, Any]] = {}

    # Trend (0-100)
    trend_score = 50.0
    if _safe_number(latest.get("ma5")) and _safe_number(latest.get("ma20")):
        trend_score += 15 if latest.get("ma5") > latest.get("ma20") else -15
    if _safe_number(latest.get("close")) and _safe_number(latest.get("ma20")):
        trend_score += 10 if latest.get("close") > latest.get("ma20") else -10
    rsi = _safe_number(latest.get("rsi14"))
    if rsi is not None:
        if 40 <= rsi <= 65:
            trend_score += 10
        elif rsi > 80 or rsi < 20:
            trend_score -= 10
    trend_score = float(max(0, min(100, trend_score)))
    score_details["trend"] = {"score": trend_score, "reason": "MA相对位置 + RSI区间"}

    # Valuation (0-100)
    label_to_score = {"估值偏低": 80.0, "合理": 60.0, "偏高": 35.0, "极端": 20.0}
    pe_label = valuation_metrics.get("pe", {}).get("label", "极端")
    pb_label = valuation_metrics.get("pb", {}).get("label", "极端")
    valuation_score = (label_to_score.get(pe_label, 20.0) + label_to_score.get(pb_label, 20.0)) / 2
    score_details["valuation"] = {"score": valuation_score, "reason": f"PE标签={pe_label}, PB标签={pb_label}"}

    # Quality (0-100)
    indicator = financials.get("indicator")
    balance = financials.get("balancesheet")
    quality_score = 50.0
    roe = _safe_number(indicator.get("roe")) if indicator is not None else None
    gpm = _safe_number(indicator.get("grossprofit_margin")) if indicator is not None else None
    debt_ratio = None
    if balance is not None and _safe_number(balance.get("total_assets")) and _safe_number(balance.get("total_liab")):
        debt_ratio = float(balance.get("total_liab") / balance.get("total_assets") * 100)
    if roe is not None:
        quality_score += 20 if roe >= 12 else (8 if roe >= 8 else -10)
    if gpm is not None:
        quality_score += 10 if gpm >= 20 else (-8 if gpm < 10 else 0)
    if debt_ratio is not None:
        quality_score += 8 if debt_ratio <= 50 else (-10 if debt_ratio >= 70 else 0)
    quality_score = float(max(0, min(100, quality_score)))
    score_details["quality"] = {"score": quality_score, "reason": "ROE + 毛利率 + 资产负债率"}

    # Risk (higher means safer)
    risk_score = 50.0
    ret20 = _safe_number(latest.get("return_20d_pct"))
    vol_chg = _safe_number(latest.get("volume_change_pct"))
    if ret20 is not None and abs(ret20) >= 20:
        risk_score -= 10
    if vol_chg is not None and abs(vol_chg) >= 80:
        risk_score -= 10
    if debt_ratio is not None and debt_ratio >= 70:
        risk_score -= 10
    risk_score = float(max(0, min(100, risk_score)))
    score_details["risk"] = {"score": risk_score, "reason": "波动 + 成交量异动 + 杠杆水平"}

    composite = round(
        score_details["trend"]["score"] * 0.30
        + score_details["valuation"]["score"] * 0.25
        + score_details["quality"]["score"] * 0.25
        + score_details["risk"]["score"] * 0.20,
        1,
    )
    print_success(f"多因子评分计算完成，综合分 {composite}")
    return {"details": score_details, "composite": composite}


def build_structured_text(
    stock_basic: pd.Series,
    tech: pd.DataFrame,
    financials: dict[str, pd.Series | None],
    valuation: pd.DataFrame,
    events_summary: str,
    external_news_analysis: str = "",
) -> str:
    print_step("整理结构化分析文本")
    latest = tech.iloc[-1]
    previous = tech.iloc[-2] if len(tech) >= 2 else latest
    latest_val = valuation.iloc[-1]
    valuation_metrics = calculate_valuation_metrics(valuation)
    factor_scores = calculate_factor_scores(tech, valuation_metrics, financials)
    income = financials.get("income")
    indicator = financials.get("indicator")
    balance = financials.get("balancesheet")

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
    - 报告期（财务指标）：{indicator.get('end_date') if indicator is not None else '暂无数据'}
    - ROE：{safe_fmt(indicator.get('roe') if indicator is not None else None, '%')}
    - 毛利率：{safe_fmt(indicator.get('grossprofit_margin') if indicator is not None else None, '%')}
    - 报告期（资产负债表）：{balance.get('end_date') if balance is not None else '暂无数据'}
    - 资产负债率：{safe_fmt(debt_ratio, '%')}

    估值数据：
    - PE近1年统计：{_format_metric_summary(valuation_metrics['pe'])}
    - PB近1年统计：{_format_metric_summary(valuation_metrics['pb'])}
    - 综合估值标签：{valuation_metrics['overall_label']}
    - 估值解读要求：{valuation_metrics['interpretation']}
    - 总市值：{safe_fmt(latest_val.get('total_mv'), ' 万元')}
    - 流通市值：{safe_fmt(latest_val.get('circ_mv'), ' 万元')}
    - 换手率：{safe_fmt(latest_val.get('turnover_rate'), '%')}
    - 量比：{safe_fmt(latest_val.get('volume_ratio'))}

    多因子打分（用于约束AI输出，不可忽略反证）：
    - 趋势因子得分：{safe_fmt(factor_scores['details']['trend']['score'])}；依据：{factor_scores['details']['trend']['reason']}
    - 估值因子得分：{safe_fmt(factor_scores['details']['valuation']['score'])}；依据：{factor_scores['details']['valuation']['reason']}
    - 质量因子得分：{safe_fmt(factor_scores['details']['quality']['score'])}；依据：{factor_scores['details']['quality']['reason']}
    - 风险因子得分：{safe_fmt(factor_scores['details']['risk']['score'])}；依据：{factor_scores['details']['risk']['reason']}
    - 综合因子评分（0-100）：{safe_fmt(factor_scores['composite'])}

    近期事件与潜在催化剂：
    {events_summary}

    DeepSeek资讯检索与分析（外部补充）：
    {external_news_analysis or "未触发外部资讯检索补充。"}

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
        "涉及事件数据时，必须区分数据已确认的事实、可能影响股价的催化剂、尚未验证的市场预期。"
    )
    user_prompt = f"""
    请基于以下结构化数据，生成 A 股股票 AI 投资分析报告。
    你必须严格执行“先证据、后结论”，并采用多角色审议格式：
    - 角色A（基本面研究员）
    - 角色B（技术面研究员）
    - 角色C（风控官）
    - 角色D（投委会秘书，汇总）

    必须包含以下内容：
    1. 三个角色各自的“核心观点+证据+反证”
    2. 短期/中期/长期建议（3-5日、2-3月、1年）
    3. 可执行计划：建议仓位（轻仓/标准仓/重仓）、入场区间、止损、止盈、失效条件
    4. 风险提示（至少3条）
    5. 综合评分（0-100，并解释依据；要引用输入中的多因子分项得分）
    6. 是否适合当前买入（只能使用审慎、观望、分批关注等非绝对表述）
    7. 事件驱动分析：请明确分成“已确认事实”“可能影响股价的催化剂”“尚未验证的市场预期”三类
    8. 若输入中明确提示事件/新闻缺失，请新增“待验证资讯线索”小节，给出3-5条检索关键词（公司层面+行业层面），并注明这些线索不是事实陈述。

    请使用中文，结构清晰，避免夸大收益。评价估值吸引力时，必须结合盈利质量
    （如净利润、ROE、毛利率、资产负债率）与估值分位，不要孤立评价 PE/PB。
    若证据不足，请明确写“证据不足，建议观望或仅跟踪”。
    最后再次注明“{DISCLAIMER}”。

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


def call_deepseek_news_research(config: Config, ts_code: str, stock_name: str, industry: str) -> str:
    """Use DeepSeek to perform focused news clue retrieval + analysis when Tushare news is unavailable."""
    print_step("调用 DeepSeek 进行资讯检索与事件分析补充")
    today = dt.datetime.now().strftime("%Y-%m-%d")
    system_prompt = (
        "你是A股资讯研究员。请围绕目标公司做资讯检索型总结与事件分析。"
        "若无法确认具体事实，请明确标注“待核验”。禁止编造确定性事实。"
    )
    user_prompt = f"""
    请针对以下标的输出“资讯检索与分析补充”：
    - 股票代码：{ts_code}
    - 公司名称：{stock_name or '未知'}
    - 行业：{industry or '未知'}
    - 当前日期：{today}

    输出要求（必须按此结构）：
    1) 近30天可能相关的重要资讯（3-6条）：每条包含【主题】【潜在影响】【核验状态(已核验/待核验)】。
    2) 行业层面催化与风险（2-4条）：每条包含【逻辑】【对该股可能影响】。
    3) 资金与情绪线索（2-3条）：如风格切换、题材热度、成交行为变化等。
    4) 综合结论：给出短期/中期的“资讯面倾向”（偏多/中性/偏空）并说明依据。

    注意：
    - 优先给出可执行的检索结论，而不是泛泛建议。
    - 凡是不确定的信息必须标注“待核验”。
    - 使用中文，简洁清晰。
    """
    payload = {
        "model": config.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": textwrap.dedent(user_prompt).strip()},
        ],
        "temperature": 0.2,
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
    except Exception as exc:
        print_warning(f"DeepSeek资讯检索补充失败，已跳过：{exc}")
        return "DeepSeek资讯检索补充失败，本次仅使用Tushare可得结构化数据。"
    print_success("DeepSeek资讯检索补充完成")
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
    events = get_recent_events(pro, ts_code)
    events_summary = summarize_events(events)
    external_news_analysis = ""
    if events is None or events.empty or "新闻摘要" not in events.get("event_type", pd.Series(dtype=str)).values:
        external_news_analysis = call_deepseek_news_research(
            config=config,
            ts_code=ts_code,
            stock_name=str(stock_basic.get("name") or "").strip(),
            industry=str(stock_basic.get("industry") or "").strip(),
        )
    structured_text = build_structured_text(
        stock_basic,
        tech,
        financials,
        valuation,
        events_summary,
        external_news_analysis=external_news_analysis,
    )

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
