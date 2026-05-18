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


@dataclass(frozen=True)
class MarketValuationSnapshot:
    latest: pd.Series
    previous: pd.Series
    latest_val: pd.Series
    aligned_trade_date: Any
    latest_market_trade_date: Any
    latest_valuation_trade_date: Any

    @property
    def has_date_gap(self) -> bool:
        return self.latest_market_trade_date != self.latest_valuation_trade_date


def align_market_and_valuation(tech: pd.DataFrame, valuation: pd.DataFrame) -> MarketValuationSnapshot:
    """Align technical indicators and valuation data on their latest common trade date."""
    print_step("按交易日对齐行情技术指标与估值数据")
    if tech.empty:
        raise AnalyzerError("技术指标数据为空，无法进行数据对齐。")
    if valuation.empty:
        raise AnalyzerError("估值数据为空，无法进行数据对齐。")
    if "trade_date" not in tech.columns or "trade_date" not in valuation.columns:
        raise AnalyzerError("技术指标和估值数据都必须包含 trade_date 字段才能对齐。")

    tech_sorted = tech.sort_values("trade_date").reset_index(drop=True)
    valuation_sorted = valuation.sort_values("trade_date").reset_index(drop=True)
    latest_market_trade_date = tech_sorted["trade_date"].iloc[-1]
    latest_valuation_trade_date = valuation_sorted["trade_date"].iloc[-1]

    aligned = tech_sorted.merge(
        valuation_sorted,
        on="trade_date",
        how="inner",
        suffixes=("", "_valuation"),
    ).sort_values("trade_date")
    if aligned.empty:
        raise AnalyzerError("技术指标和估值数据没有重叠交易日，无法生成一致的结构化分析文本。")

    aligned_trade_date = aligned["trade_date"].iloc[-1]
    latest = tech_sorted[tech_sorted["trade_date"] == aligned_trade_date].iloc[-1]
    latest_val = valuation_sorted[valuation_sorted["trade_date"] == aligned_trade_date].iloc[-1]
    previous_candidates = tech_sorted[tech_sorted["trade_date"] < aligned_trade_date]
    previous = previous_candidates.iloc[-1] if not previous_candidates.empty else latest

    if latest_market_trade_date != latest_valuation_trade_date:
        print_warning(
            "最新行情日与最新估值日不一致："
            f"行情 {latest_market_trade_date}，估值 {latest_valuation_trade_date}；"
            f"将使用共同最新交易日 {aligned_trade_date}。"
        )
    print_success(f"行情与估值数据已对齐到交易日 {aligned_trade_date}")
    return MarketValuationSnapshot(
        latest=latest,
        previous=previous,
        latest_val=latest_val,
        aligned_trade_date=aligned_trade_date,
        latest_market_trade_date=latest_market_trade_date,
        latest_valuation_trade_date=latest_valuation_trade_date,
    )


def build_structured_text(
    stock_basic: pd.Series,
    market_snapshot: MarketValuationSnapshot,
    financials: dict[str, pd.Series | None],
) -> str:
    print_step("整理结构化分析文本")
    latest = market_snapshot.latest
    previous = market_snapshot.previous
    latest_val = market_snapshot.latest_val
    if market_snapshot.has_date_gap:
        alignment_note = (
            "最新行情日与最新估值日不一致："
            f"最新行情日为 {market_snapshot.latest_market_trade_date}，"
            f"最新估值日为 {market_snapshot.latest_valuation_trade_date}；"
            f"为避免错配，以下行情与估值均使用二者都有数据的最新交易日 "
            f"{market_snapshot.aligned_trade_date}。"
        )
    else:
        alignment_note = f"行情与估值数据已按交易日 {market_snapshot.aligned_trade_date} 对齐。"
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

    数据对齐说明：
    - {alignment_note}

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
    market_snapshot = align_market_and_valuation(tech, valuation)
    structured_text = build_structured_text(stock_basic, market_snapshot, financials)

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