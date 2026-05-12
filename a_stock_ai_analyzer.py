"""A股股票 AI 投资分析主程序。

运行方式：
    python a_stock_ai_analyzer.py

流程：
1. 输入股票代码
2. 获取 Tushare 股票数据
3. 计算技术/估值/财务指标
4. 生成走势图
5. 调用 DeepSeek AI 分析
6. 自动生成 PDF 投资报告

免责声明：本程序输出内容仅供参考，不构成投资建议。市场有风险，投资需谨慎。
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import tushare as ts

from charts import draw_price_chart
from deepseek_client import analyze_with_ai
from pdf_report import generate_pdf

DISCLAIMER = "仅供参考，不构成投资建议。市场有风险，投资需谨慎。"
CHARTS_DIR = Path("charts")
REPORTS_DIR = Path("reports")


class AnalyzerError(Exception):
    """可展示给用户的业务异常。"""


def print_step(message: str) -> None:
    """打印清晰的步骤日志。"""
    print(f"\n[步骤] {message}")


def print_success(message: str) -> None:
    print(f"[完成] {message}")


def print_warning(message: str) -> None:
    print(f"[提示] {message}")


def print_error(message: str) -> None:
    print(f"[错误] {message}")


def ensure_output_dirs() -> None:
    """自动创建走势图和报告目录。"""
    print_step("检查输出目录")
    try:
        CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AnalyzerError(f"创建 charts/ 或 reports/ 目录失败：{exc}") from exc
    print_success("输出目录已就绪：charts/、reports/")


def setup_matplotlib_chinese_font() -> None:
    """尽量自动配置 matplotlib 中文字体，避免走势图中文乱码。"""
    print_step("配置 matplotlib 中文字体")
    try:
        import matplotlib.pyplot as plt

        plt.rcParams["font.sans-serif"] = [
            "Microsoft YaHei",
            "SimHei",
            "Noto Sans CJK SC",
            "Arial Unicode MS",
            "DejaVu Sans",
        ]
        plt.rcParams["axes.unicode_minus"] = False
        print_success("matplotlib 中文字体配置完成")
    except Exception as exc:
        print_warning(f"matplotlib 中文字体自动配置失败，将继续运行：{exc}")


def get_tushare_token() -> str:
    """从环境变量读取 Tushare Token。"""
    print_step("读取 Tushare Token")
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        raise AnalyzerError(
            "未检测到环境变量 TUSHARE_TOKEN。请在 Windows PowerShell 中执行：\n"
            '  setx TUSHARE_TOKEN "你的TushareToken"\n'
            "设置后重新打开 VS Code 终端再运行。"
        )
    print_success("Tushare Token 已读取（不会打印或保存 Token）")
    return token


def normalize_stock_code(raw_code: str) -> str:
    """把 002594 转换为 Tushare 需要的 002594.SZ 格式。"""
    code = raw_code.strip().upper()
    if code.endswith((".SZ", ".SH", ".BJ")):
        return code
    if not (code.isdigit() and len(code) == 6):
        raise AnalyzerError("股票代码格式不正确，请输入 6 位 A 股代码，例如 002594。")
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    raise AnalyzerError("暂不支持该股票代码前缀，请输入常见 A 股代码，例如 002594、600519。")


def init_tushare(token: str) -> Any:
    """初始化 Tushare Pro 客户端。"""
    print_step("初始化 Tushare Pro")
    try:
        ts.set_token(token)
        pro = ts.pro_api()
    except Exception as exc:
        raise AnalyzerError(f"Tushare Pro 初始化失败：{exc}") from exc
    print_success("Tushare Pro 初始化完成")
    return pro


def fetch_stock_basic(pro: Any, ts_code: str) -> pd.Series:
    """获取股票基础信息。"""
    print_step("获取股票基础信息")
    try:
        stock_basic = pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date",
        )
    except Exception as exc:
        raise AnalyzerError(f"股票基础信息获取失败：{exc}") from exc

    if stock_basic is None or stock_basic.empty:
        raise AnalyzerError("股票基础信息为空，请检查 Tushare 权限或网络连接。")

    matched = stock_basic[stock_basic["ts_code"] == ts_code]
    if matched.empty:
        raise AnalyzerError(f"未找到 {ts_code} 的上市股票信息，请确认股票代码是否正确。")

    print_success("股票基础信息获取成功")
    return matched.iloc[0]


def fetch_daily_data(pro: Any, ts_code: str) -> pd.DataFrame:
    """获取最近一年日 K 线数据。"""
    print_step("获取最近一年日 K 线数据")
    end_date = dt.datetime.now().strftime("%Y%m%d")
    start_date = (dt.datetime.now() - dt.timedelta(days=420)).strftime("%Y%m%d")

    try:
        df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    except Exception as exc:
        raise AnalyzerError(f"日 K 线数据获取失败：{exc}") from exc

    if df is None or df.empty:
        raise AnalyzerError("日 K 线数据为空，请检查股票代码、Tushare 权限或接口积分。")

    df = df.sort_values("trade_date").reset_index(drop=True)
    print_success(f"日 K 线数据获取成功，共 {len(df)} 条记录")
    return df


def fetch_valuation_data(pro: Any, ts_code: str) -> pd.DataFrame:
    """获取 PE、PB 等估值数据。"""
    print_step("获取估值数据 PE、PB")
    end_date = dt.datetime.now().strftime("%Y%m%d")
    start_date = (dt.datetime.now() - dt.timedelta(days=420)).strftime("%Y%m%d")

    try:
        valuation = pro.daily_basic(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,trade_date,pe,pb,total_mv,circ_mv,turnover_rate,volume_ratio",
        )
    except Exception as exc:
        print_warning(f"估值数据获取失败，将使用空值继续：{exc}")
        return pd.DataFrame()

    if valuation is None or valuation.empty:
        print_warning("估值数据为空，将使用空值继续")
        return pd.DataFrame()

    valuation = valuation.sort_values("trade_date").reset_index(drop=True)
    print_success("估值数据获取成功")
    return valuation


def fetch_financial_indicator(pro: Any, ts_code: str) -> pd.Series | None:
    """获取 ROE 等财务指标。"""
    print_step("获取财务指标 ROE")
    try:
        indicator = pro.fina_indicator(
            ts_code=ts_code,
            fields="ts_code,end_date,ann_date,roe,grossprofit_margin",
        )
    except Exception as exc:
        print_warning(f"财务指标获取失败，将使用空值继续：{exc}")
        return None

    if indicator is None or indicator.empty:
        print_warning("财务指标为空，将使用空值继续")
        return None

    print_success("财务指标获取成功")
    return indicator.sort_values("end_date", ascending=False).iloc[0]


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """计算 RSI 指标。"""
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def calculate_indicators(df: pd.DataFrame, valuation: pd.DataFrame, indicator: pd.Series | None) -> pd.DataFrame:
    """计算并合并主流程需要的指标。"""
    print_step("计算技术指标：MA5、MA10、MA20、RSI、MACD、最近20日涨跌幅")
    try:
        result = df.copy()
        result["ma5"] = result["close"].rolling(window=5).mean()
        result["ma10"] = result["close"].rolling(window=10).mean()
        result["ma20"] = result["close"].rolling(window=20).mean()
        result["rsi"] = calculate_rsi(result["close"])

        ema12 = result["close"].ewm(span=12, adjust=False).mean()
        ema26 = result["close"].ewm(span=26, adjust=False).mean()
        macd_dif = ema12 - ema26
        macd_dea = macd_dif.ewm(span=9, adjust=False).mean()
        result["macd"] = 2 * (macd_dif - macd_dea)
        result["return_20d_pct"] = (result["close"] / result["close"].shift(20) - 1) * 100

        result["pe"] = pd.NA
        result["pb"] = pd.NA
        if valuation is not None and not valuation.empty:
            valuation_cols = valuation[["trade_date", "pe", "pb"]].copy()
            result = result.merge(valuation_cols, on="trade_date", how="left", suffixes=("", "_valuation"))
            result["pe"] = result["pe_valuation"].combine_first(result["pe"])
            result["pb"] = result["pb_valuation"].combine_first(result["pb"])
            result = result.drop(columns=["pe_valuation", "pb_valuation"])

        result["roe"] = indicator.get("roe") if indicator is not None else pd.NA
    except Exception as exc:
        raise AnalyzerError(f"指标计算失败：{exc}") from exc

    print_success("指标计算完成")
    return result


def latest_valid_value(df: pd.DataFrame, column: str) -> Any:
    """获取某列最新的非空值。"""
    if column not in df.columns:
        return pd.NA
    values = df[column].dropna()
    if values.empty:
        return pd.NA
    return values.iloc[-1]


def format_value(value: Any, suffix: str = "", digits: int = 2) -> str:
    """格式化提示词中的数值。"""
    if value is None or pd.isna(value):
        return "暂无数据"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}{suffix}"
    return str(value)


def build_ai_prompt(stock_name: str, df: pd.DataFrame) -> str:
    """整理 DeepSeek AI 分析需要的 prompt 字符串。"""
    print_step("整理 DeepSeek AI 分析 Prompt")
    latest = df.iloc[-1]
    prompt = f"""
请基于以下 A 股股票数据生成投资分析报告。请不要给出绝对买卖指令，必须使用审慎表述，并注明“{DISCLAIMER}”。

股票名称：{stock_name}
最新价格：{format_value(latest.get('close'))}
MA5：{format_value(latest_valid_value(df, 'ma5'))}
MA10：{format_value(latest_valid_value(df, 'ma10'))}
MA20：{format_value(latest_valid_value(df, 'ma20'))}
RSI：{format_value(latest_valid_value(df, 'rsi'))}
MACD：{format_value(latest_valid_value(df, 'macd'))}
PE：{format_value(latest_valid_value(df, 'pe'))}
PB：{format_value(latest_valid_value(df, 'pb'))}
ROE：{format_value(latest_valid_value(df, 'roe'), '%')}
最近20日涨跌幅：{format_value(latest_valid_value(df, 'return_20d_pct'), '%')}

请输出以下内容：
1. 短期分析（3-5个交易日）
2. 中期分析（2-3个月）
3. 长期分析（1年左右）
4. 主要风险提示
5. 综合评分（0-100）
6. 是否适合当前买入（仅可使用“观望”“谨慎关注”“分批关注”等非绝对表达）
""".strip()
    print_success("Prompt 整理完成")
    return prompt


def generate_chart(df: pd.DataFrame, stock_name: str) -> str:
    """调用 charts.py 生成走势图。"""
    print_step("生成股票走势图")
    try:
        chart_path = draw_price_chart(df, stock_name)
    except Exception as exc:
        raise AnalyzerError(f"走势图生成失败：{exc}") from exc
    print_success(f"走势图生成成功：{chart_path}")
    return chart_path


def analyze_by_ai(prompt: str) -> str:
    """调用 deepseek_client.py 生成 AI 分析。"""
    print_step("调用 DeepSeek AI 生成投资分析")
    try:
        analysis = analyze_with_ai(prompt)
    except Exception as exc:
        raise AnalyzerError(f"DeepSeek AI 分析失败：{exc}") from exc

    if not analysis:
        raise AnalyzerError("DeepSeek AI 返回内容为空，请稍后重试。")
    if DISCLAIMER not in analysis:
        analysis = f"{analysis}\n\n{DISCLAIMER}"

    print_success("DeepSeek AI 分析完成")
    return analysis


def generate_report(stock_name: str, analysis: str, chart_path: str) -> str:
    """调用 pdf_report.py 自动生成 PDF 报告。"""
    print_step("生成 PDF 投资报告")
    try:
        pdf_path = generate_pdf(stock_name, analysis, chart_path)
    except Exception as exc:
        raise AnalyzerError(f"PDF 报告生成失败：{exc}") from exc
    print_success("PDF 投资报告生成完成")
    return pdf_path


def run_analysis(raw_code: str) -> str:
    """完整运行股票分析、AI 分析和 PDF 报告生成流程。"""
    print("=" * 72)
    print("A股股票 AI 投资分析系统")
    print(DISCLAIMER)
    print("=" * 72)

    ensure_output_dirs()
    setup_matplotlib_chinese_font()

    token = get_tushare_token()
    ts_code = normalize_stock_code(raw_code)
    print_success(f"股票代码已识别为：{ts_code}")

    pro = init_tushare(token)
    stock_basic = fetch_stock_basic(pro, ts_code)
    stock_name = str(stock_basic.get("name", ts_code))
    print_success(f"股票名称：{stock_name}")

    df = fetch_daily_data(pro, ts_code)
    valuation = fetch_valuation_data(pro, ts_code)
    financial_indicator = fetch_financial_indicator(pro, ts_code)
    df = calculate_indicators(df, valuation, financial_indicator)

    chart_path = generate_chart(df, stock_name)
    prompt = build_ai_prompt(stock_name, df)
    analysis = analyze_by_ai(prompt)
    pdf_path = generate_report(stock_name, analysis, chart_path)

    return pdf_path


def main() -> int:
    """程序入口。"""
    try:
        print_step("启动程序")
        stock_code = input("请输入股票代码（例如 002594）：").strip()
        if not stock_code:
            raise AnalyzerError("股票代码不能为空。")

        pdf_path = run_analysis(stock_code)
        print("\n" + "=" * 72)
        print("PDF报告生成成功：", pdf_path)
        print("=" * 72)
        return 0
    except KeyboardInterrupt:
        print_error("用户已取消操作。")
        return 130
    except AnalyzerError as exc:
        print_error(str(exc))
        print(f"[免责声明] {DISCLAIMER}")
        return 1
    except Exception as exc:
        print_error(f"程序发生未知错误：{exc}")
        print(f"[免责声明] {DISCLAIMER}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
