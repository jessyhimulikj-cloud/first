"""CLI entry point for the A-share distressed-turnaround value screener."""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path

from . import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger(__name__)
OUTPUT_COLUMNS = [
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
    "rating",
    "reason",
]


def main() -> None:
    args = parse_args()
    from .data_loader import DataLoader
    from .deepseek_analyzer import analyze_candidates
    from .report_generator import generate_report

    loader = DataLoader(refresh=args.refresh_data)
    output_path = _resolve_output(args.output)

    quant = run_quant_screen(loader, top_n=args.top, min_score=args.min_score)
    quant_path = output_path if not args.use_deepseek else config.OUTPUT_DIR / "value_candidates.csv"
    quant_path.parent.mkdir(parents=True, exist_ok=True)
    quant.to_csv(quant_path, index=False)
    LOGGER.info("Wrote quantitative candidates to %s", quant_path)

    if args.use_deepseek:
        ai_path = output_path
        ai_result = analyze_candidates(quant_path, ai_path, args.top)
        generate_report(ai_result, config.OUTPUT_DIR / "value_report.md", used_ai=True)
        LOGGER.info("Wrote AI candidates to %s", ai_path)
    else:
        generate_report(quant, config.OUTPUT_DIR / "value_report.md", used_ai=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A股困境反转 + 长期成长价值选股系统")
    parser.add_argument("--top", type=int, default=config.DEFAULT_TOP_N, help="输出前 N 只股票")
    parser.add_argument("--min-score", type=float, default=config.DEFAULT_MIN_SCORE, help="最低量化分数")
    parser.add_argument("--use-deepseek", action="store_true", help="是否启用 DeepSeek 分析")
    parser.add_argument("--output", default=str(config.OUTPUT_DIR / "value_candidates.csv"), help="输出文件路径")
    parser.add_argument("--refresh-data", action="store_true", help="强制刷新 Tushare 数据")
    return parser.parse_args()


def run_quant_screen(loader, top_n: int, min_score: float):
    import pandas as pd

    from .data_loader import as_float
    from .distress_score import calculate_distress
    from .industry_score import add_industry_score
    from .position_score import add_position_score
    from .reversal_score import calculate_reversal
    from .survival_score import add_survival_score
    from .universe import build_universe
    from .valuation_score import add_valuation_score

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=365 * 3 + 30)).strftime("%Y%m%d")
    financial_start = (datetime.now() - timedelta(days=365 * 4)).strftime("%Y%m%d")

    universe = add_industry_score(build_universe(loader))
    if universe.empty:
        LOGGER.warning("Universe is empty. Check Tushare token/permissions or cached data.")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    hs300 = loader.hs300_daily(start, end)
    rows = []
    for _, stock in universe.iterrows():
        ts_code = stock["ts_code"]
        try:
            daily = loader.daily(ts_code, start, end)
            valuation = loader.daily_basic(ts_code, start, end)
            fina = loader.fina_indicator(ts_code, financial_start, end)
            income = loader.income(ts_code, financial_start, end)
            balance = loader.balancesheet(ts_code, financial_start, end)
            cashflow = loader.cashflow(ts_code, financial_start, end)
            rows.append(_build_stock_row(stock, daily, valuation, fina, income, balance, cashflow, hs300))
        except Exception as exc:  # noqa: BLE001 - skip bad names but continue screening
            LOGGER.warning("Skip %s because data processing failed: %s", ts_code, exc)

    if not rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = pd.DataFrame(rows)
    df = add_position_score(df)
    df = add_survival_score(df)
    df = add_valuation_score(df)
    df = _add_total_score(df)
    df["rating"] = df["total_score"].apply(quant_rating)
    df["reason"] = df.apply(_reason, axis=1)
    df = df[df["survival_pass"] & (df["total_score"] >= min_score)].copy()
    df = df.sort_values("total_score", ascending=False).head(top_n)
    return df[[col for col in OUTPUT_COLUMNS if col in df.columns]]


def _build_stock_row(
    stock: pd.Series,
    daily: pd.DataFrame,
    valuation: pd.DataFrame,
    fina: pd.DataFrame,
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cashflow: pd.DataFrame,
    hs300: pd.DataFrame,
) -> dict:
    from .data_loader import as_float
    from .distress_score import calculate_distress
    from .reversal_score import calculate_reversal
    import pandas as pd

    distress = calculate_distress(daily, valuation, hs300)
    latest_val = _latest(valuation)
    latest_fina = _latest(fina)
    latest_income = _latest(income)
    latest_balance = _latest(balance)
    latest_cashflow = _latest(cashflow)

    total_assets = as_float(latest_balance.get("total_assets"), 0)
    total_liab = as_float(latest_balance.get("total_liab"), 0)
    net_assets = total_assets - total_liab
    short_debt = as_float(latest_balance.get("st_borr"), 0) + as_float(latest_balance.get("non_cur_liab_due_1y"), 0)
    money_cap = as_float(latest_balance.get("money_cap"), 0)
    cash_to_short_debt = money_cap / short_debt if short_debt > 0 else 99.0
    goodwill = as_float(latest_balance.get("goodwill"), 0)

    net_profit_series = pd.to_numeric(income.sort_values("end_date").get("n_income_attr_p", pd.Series(dtype=float)), errors="coerce").dropna().tail(3)
    operating_cf = as_float(latest_cashflow.get("n_cashflow_act"), 0)
    ocf_years = int((pd.to_numeric(cashflow.get("n_cashflow_act", pd.Series(dtype=float)), errors="coerce").dropna().tail(3) > 0).sum())

    return {
        **stock.to_dict(),
        **distress,
        "market_cap": as_float(latest_val.get("total_mv"), 0),
        "roe": as_float(latest_fina.get("roe"), 0),
        "revenue_growth": as_float(latest_fina.get("or_yoy"), 0),
        "profit_growth": as_float(latest_fina.get("netprofit_yoy"), 0),
        "debt_to_assets": total_liab / total_assets * 100 if total_assets > 0 else 100.0,
        "operating_cashflow": operating_cf,
        "net_assets": net_assets,
        "cash_to_short_debt": cash_to_short_debt,
        "goodwill_to_net_assets": goodwill / net_assets if net_assets > 0 else 1.0,
        "ocf_positive_years_3y": ocf_years,
        "net_profit_declining": len(net_profit_series) >= 3 and net_profit_series.is_monotonic_decreasing,
        "revenue": as_float(latest_income.get("revenue"), 0),
        "rd_expense_rate": _rd_expense_rate(latest_fina, latest_income),
        "gross_margin": as_float(latest_fina.get("grossprofit_margin"), 0),
        "reversal_score": calculate_reversal(fina, income, cashflow, daily),
    }


def _latest(df):
    import pandas as pd
    if df.empty:
        return pd.Series(dtype=object)
    sort_col = "end_date" if "end_date" in df.columns else "trade_date"
    return df.sort_values(sort_col).iloc[-1]


def _rd_expense_rate(fina, income) -> float:
    from .data_loader import as_float
    ratio = as_float(fina.get("rd_exp_ratio"), 0)
    if ratio:
        return ratio
    revenue = as_float(income.get("revenue"), 0)
    rd = as_float(fina.get("rd_exp"), 0) or as_float(fina.get("rd_expense"), 0)
    return rd / revenue * 100 if revenue > 0 else 0.0


def _add_total_score(df):
    result = df.copy()
    result["total_score"] = 0.0
    for column, weight in config.SCORE_WEIGHTS.items():
        result["total_score"] += result[column].fillna(0) * weight
    return result


def quant_rating(score: float) -> str:
    if score >= 85:
        return "重点研究池"
    if score >= 75:
        return "观察池"
    if score >= 65:
        return "跟踪池"
    return "暂不考虑"


def _reason(row) -> str:
    positives = []
    if row.get("industry_score", 0) >= 70:
        positives.append("行业长期空间较好")
    if row.get("distress_score", 0) >= 60:
        positives.append("处于明显低谷/市场冷落阶段")
    if row.get("reversal_score", 0) >= 50:
        positives.append("出现初步反转信号")
    positives.append(str(row.get("survival_reason", "")))
    return "; ".join([p for p in positives if p])


def _resolve_output(path: str) -> Path:
    output = Path(path)
    if not output.is_absolute():
        output = Path.cwd() / output
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


if __name__ == "__main__":
    main()
