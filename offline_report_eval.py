"""Offline historical evaluation for locally stored A-share CSV data.

The script replays a point-in-time technical report for every ``data/*.csv`` file,
then compares the report's short-/medium-term view with the subsequent realized
5-, 20- and 60-trading-day returns and maximum drawdowns.

It intentionally uses only the Python standard library so it can run in a clean
offline environment. Generated reports are rule-based technical summaries, not
investment advice.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import math
import os
import re
import statistics
import sys
from dataclasses import asdict, dataclass
from typing import Iterable, Sequence

DISCLAIMER = "仅供参考，不构成投资建议。市场有风险，投资需谨慎。"
DEFAULT_HORIZONS = (5, 20, 60)
QUALITY_ITEMS = (
    "是否引用了具体数据",
    "是否给出触发条件",
    "是否给出失效条件",
    "是否区分短中长期",
    "是否说明反方观点",
)


class OfflineEvalError(Exception):
    """Raised for user-facing evaluation errors."""


@dataclass(frozen=True)
class Bar:
    date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float | None
    pct_chg: float | None


@dataclass(frozen=True)
class TechnicalSnapshot:
    symbol: str
    analysis_date: dt.date
    close: float
    ma5: float | None
    ma20: float | None
    ma60: float | None
    rsi14: float | None
    macd_dif: float | None
    macd_dea: float | None
    macd: float | None
    return_20d_pct: float | None
    volume_change_pct: float | None
    history_bars: int


@dataclass(frozen=True)
class ReportView:
    short_term: str
    medium_term: str
    long_term: str
    score: int
    trigger: str
    invalidation: str
    counter_view: str
    text: str


@dataclass(frozen=True)
class RealizedOutcome:
    horizon: int
    end_date: str | None
    return_pct: float | None
    max_drawdown_pct: float | None
    hit: bool | None
    risk_exposure: str


@dataclass(frozen=True)
class EvaluationRow:
    symbol: str
    analysis_date: str
    close: float
    short_view: str
    medium_view: str
    long_view: str
    score: int
    quality_score: int
    quality_checks: dict[str, bool]
    outcomes: list[RealizedOutcome]
    report: str


def parse_trade_date(raw: str) -> dt.date:
    value = raw.strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise OfflineEvalError(f"无法识别日期 {raw!r}，请使用 YYYYMMDD 或 YYYY-MM-DD。")


def parse_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def load_bars(path: str) -> list[Bar]:
    bars: list[Bar] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"date", "open", "high", "low", "close", "volume"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise OfflineEvalError(f"{path} 缺少必要列：{', '.join(sorted(missing))}")
        for row in reader:
            parsed = {
                "open": parse_float(row.get("open")),
                "high": parse_float(row.get("high")),
                "low": parse_float(row.get("low")),
                "close": parse_float(row.get("close")),
                "volume": parse_float(row.get("volume")),
            }
            if any(value is None for value in parsed.values()):
                continue
            bars.append(
                Bar(
                    date=parse_trade_date(row["date"]),
                    open=parsed["open"] or 0.0,
                    high=parsed["high"] or 0.0,
                    low=parsed["low"] or 0.0,
                    close=parsed["close"] or 0.0,
                    volume=parsed["volume"] or 0.0,
                    amount=parse_float(row.get("amount")),
                    pct_chg=parse_float(row.get("pct_chg")),
                )
            )
    return sorted(bars, key=lambda item: item.date)


def average(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def moving_average(values: Sequence[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return average(values[-window:])


def pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (current / previous - 1) * 100


def calculate_rsi(closes: Sequence[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(len(closes) - period, len(closes))]
    gains = [max(delta, 0.0) for delta in deltas]
    losses = [max(-delta, 0.0) for delta in deltas]
    avg_gain = average(gains) or 0.0
    avg_loss = average(losses) or 0.0
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def ema_series(values: Sequence[float], span: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (span + 1)
    ema = [values[0]]
    for value in values[1:]:
        ema.append(alpha * value + (1 - alpha) * ema[-1])
    return ema


def calculate_macd(closes: Sequence[float]) -> tuple[float | None, float | None, float | None]:
    if len(closes) < 26:
        return None, None, None
    ema12 = ema_series(closes, 12)
    ema26 = ema_series(closes, 26)
    dif_values = [fast - slow for fast, slow in zip(ema12, ema26)]
    dea_values = ema_series(dif_values, 9)
    dif = dif_values[-1]
    dea = dea_values[-1]
    return dif, dea, 2 * (dif - dea)


def build_snapshot(symbol: str, bars: Sequence[Bar], analysis_date: dt.date) -> tuple[TechnicalSnapshot, int]:
    asof_index = -1
    for index, bar in enumerate(bars):
        if bar.date <= analysis_date:
            asof_index = index
        else:
            break
    if asof_index < 0:
        raise OfflineEvalError(f"{symbol} 在 {analysis_date.isoformat()} 前没有历史行情。")

    history = list(bars[: asof_index + 1])
    closes = [bar.close for bar in history]
    volumes = [bar.volume for bar in history]
    dif, dea, macd = calculate_macd(closes)
    snapshot = TechnicalSnapshot(
        symbol=symbol,
        analysis_date=history[-1].date,
        close=history[-1].close,
        ma5=moving_average(closes, 5),
        ma20=moving_average(closes, 20),
        ma60=moving_average(closes, 60),
        rsi14=calculate_rsi(closes),
        macd_dif=dif,
        macd_dea=dea,
        macd=macd,
        return_20d_pct=pct_change(closes[-1], closes[-21] if len(closes) > 20 else None),
        volume_change_pct=pct_change(volumes[-1], volumes[-2] if len(volumes) > 1 else None),
        history_bars=len(history),
    )
    return snapshot, asof_index


def format_pct(value: float | None) -> str:
    return "暂无数据" if value is None else f"{value:.2f}%"


def format_num(value: float | None) -> str:
    return "暂无数据" if value is None else f"{value:.2f}"


def classify_snapshot(snapshot: TechnicalSnapshot) -> ReportView:
    bullish = 0
    bearish = 0
    if snapshot.ma5 is not None and snapshot.ma20 is not None:
        bullish += snapshot.close > snapshot.ma5 > snapshot.ma20
        bearish += snapshot.close < snapshot.ma5 < snapshot.ma20
    if snapshot.ma20 is not None and snapshot.ma60 is not None:
        bullish += snapshot.ma20 > snapshot.ma60
        bearish += snapshot.ma20 < snapshot.ma60
    if snapshot.macd is not None:
        bullish += snapshot.macd > 0
        bearish += snapshot.macd < 0
    if snapshot.rsi14 is not None:
        bullish += 45 <= snapshot.rsi14 <= 70
        bearish += snapshot.rsi14 < 35 or snapshot.rsi14 > 80
    if snapshot.return_20d_pct is not None:
        bullish += snapshot.return_20d_pct > 3
        bearish += snapshot.return_20d_pct < -3

    if bullish >= bearish + 2:
        short_term = "偏多"
        medium_term = "偏多" if snapshot.ma20 and snapshot.ma60 and snapshot.ma20 >= snapshot.ma60 else "中性"
        score = min(85, 55 + bullish * 6)
    elif bearish >= bullish + 2:
        short_term = "偏空"
        medium_term = "偏空" if snapshot.ma20 and snapshot.ma60 and snapshot.ma20 <= snapshot.ma60 else "中性"
        score = max(20, 50 - bearish * 6)
    else:
        short_term = "中性"
        medium_term = "中性"
        score = 50 + (bullish - bearish) * 3

    long_term = "待基本面验证"
    trigger = (
        f"若收盘价有效站上 MA20（{format_num(snapshot.ma20)}）且 MACD 柱继续为正，"
        "短期偏多判断触发；若跌破 MA20 则不追高。"
    )
    invalidation = (
        f"若收盘价连续跌破 MA60（{format_num(snapshot.ma60)}）或 RSI14 跌至 35 以下，"
        "原偏多/中性判断失效并转入风险控制。"
    )
    counter_view = "反方观点：技术指标只反映量价，若行业景气、财务质量或宏观流动性恶化，历史形态可能失效。"
    text = f"""
    {snapshot.symbol} 离线回放报告（分析时点：{snapshot.analysis_date.isoformat()}）
    - 具体数据：收盘价 {snapshot.close:.2f}，MA5 {format_num(snapshot.ma5)}，MA20 {format_num(snapshot.ma20)}，MA60 {format_num(snapshot.ma60)}，RSI14 {format_num(snapshot.rsi14)}，MACD 柱 {format_num(snapshot.macd)}，近20日涨跌幅 {format_pct(snapshot.return_20d_pct)}。
    - 短期判断（未来约 5 个交易日）：{short_term}。
    - 中期判断（未来约 20-60 个交易日）：{medium_term}。
    - 长期判断（约 1 年）：{long_term}，本脚本不离线编造基本面结论。
    - 触发条件：{trigger}
    - 失效条件：{invalidation}
    - {counter_view}
    - 综合评分：{score}/100。
    {DISCLAIMER}
    """
    return ReportView(
        short_term=short_term,
        medium_term=medium_term,
        long_term=long_term,
        score=score,
        trigger=trigger,
        invalidation=invalidation,
        counter_view=counter_view,
        text=re.sub(r"\n[ \t]+", "\n", text.strip()),
    )


def max_drawdown_pct(start_close: float, future_bars: Sequence[Bar]) -> float | None:
    if not future_bars:
        return None
    peak = start_close
    max_drawdown = 0.0
    for bar in future_bars:
        peak = max(peak, bar.close)
        drawdown = (bar.close / peak - 1) * 100
        max_drawdown = min(max_drawdown, drawdown)
    return max_drawdown


def is_hit(view: str, realized_return: float | None) -> bool | None:
    if realized_return is None:
        return None
    if view == "偏多":
        return realized_return > 0
    if view == "偏空":
        return realized_return < 0
    return abs(realized_return) <= 3


def risk_bucket(drawdown_pct: float | None) -> str:
    if drawdown_pct is None:
        return "数据不足"
    if drawdown_pct <= -15:
        return "高风险暴露"
    if drawdown_pct <= -8:
        return "中等风险暴露"
    return "低风险暴露"


def evaluate_outcomes(
    bars: Sequence[Bar], asof_index: int, snapshot: TechnicalSnapshot, report: ReportView, horizons: Iterable[int]
) -> list[RealizedOutcome]:
    rows: list[RealizedOutcome] = []
    for horizon in horizons:
        future = list(bars[asof_index + 1 : asof_index + 1 + horizon])
        if len(future) < horizon:
            rows.append(RealizedOutcome(horizon, None, None, None, None, "数据不足"))
            continue
        realized_return = (future[-1].close / snapshot.close - 1) * 100
        drawdown = max_drawdown_pct(snapshot.close, future)
        view = report.short_term if horizon <= 5 else report.medium_term
        rows.append(
            RealizedOutcome(
                horizon=horizon,
                end_date=future[-1].date.isoformat(),
                return_pct=realized_return,
                max_drawdown_pct=drawdown,
                hit=is_hit(view, realized_return),
                risk_exposure=risk_bucket(drawdown),
            )
        )
    return rows


def quality_checks(report_text: str) -> dict[str, bool]:
    return {
        "是否引用了具体数据": bool(re.search(r"\d+(\.\d+)?%?|MA\d+|RSI|MACD", report_text)),
        "是否给出触发条件": "触发条件" in report_text,
        "是否给出失效条件": "失效条件" in report_text,
        "是否区分短中长期": all(term in report_text for term in ("短期", "中期", "长期")),
        "是否说明反方观点": "反方观点" in report_text,
    }


def evaluate_file(path: str, analysis_date: dt.date, horizons: Iterable[int]) -> EvaluationRow:
    symbol = os.path.splitext(os.path.basename(path))[0]
    bars = load_bars(path)
    if not bars:
        raise OfflineEvalError(f"{path} 没有可用行情。")
    snapshot, asof_index = build_snapshot(symbol, bars, analysis_date)
    report = classify_snapshot(snapshot)
    checks = quality_checks(report.text)
    outcomes = evaluate_outcomes(bars, asof_index, snapshot, report, horizons)
    return EvaluationRow(
        symbol=symbol,
        analysis_date=snapshot.analysis_date.isoformat(),
        close=snapshot.close,
        short_view=report.short_term,
        medium_view=report.medium_term,
        long_view=report.long_term,
        score=report.score,
        quality_score=sum(checks.values()),
        quality_checks=checks,
        outcomes=outcomes,
        report=report.text,
    )


def print_console(rows: Sequence[EvaluationRow]) -> None:
    print("离线报告评估结果")
    print("=" * 88)
    for row in rows:
        print(
            f"{row.symbol} | 分析日 {row.analysis_date} | 收盘 {row.close:.2f} | "
            f"短期 {row.short_view} | 中期 {row.medium_view} | 质量 {row.quality_score}/{len(QUALITY_ITEMS)}"
        )
        for outcome in row.outcomes:
            hit = "NA" if outcome.hit is None else ("命中" if outcome.hit else "未命中")
            print(
                f"  - {outcome.horizon:>2}日：收益 {format_pct(outcome.return_pct)}，"
                f"最大回撤 {format_pct(outcome.max_drawdown_pct)}，{hit}，{outcome.risk_exposure}"
            )
        failed = [name for name, ok in row.quality_checks.items() if not ok]
        print(f"  - 质量检查：{'全部通过' if not failed else '未通过：' + '、'.join(failed)}")
    print("=" * 88)
    total = sum(len(row.outcomes) for row in rows)
    usable = [outcome for row in rows for outcome in row.outcomes if outcome.hit is not None]
    hits = sum(1 for outcome in usable if outcome.hit)
    hit_rate = hits / len(usable) * 100 if usable else 0.0
    print(f"覆盖报告 {len(rows)} 份；可评估周期 {len(usable)}/{total}；命中率 {hit_rate:.2f}%")


def write_json(rows: Sequence[EvaluationRow], output_path: str) -> None:
    payload = []
    for row in rows:
        item = asdict(row)
        item["outcomes"] = [asdict(outcome) for outcome in row.outcomes]
        payload.append(item)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def parse_horizons(raw: str) -> tuple[int, ...]:
    horizons = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        value = int(item)
        if value <= 0:
            raise OfflineEvalError("评估周期必须为正整数。")
        horizons.append(value)
    if not horizons:
        raise OfflineEvalError("至少需要一个评估周期。")
    return tuple(horizons)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="离线回放评估 data/*.csv 历史行情上的技术分析报告质量和命中情况")
    parser.add_argument("--data-dir", default="data", help="CSV 行情目录，默认 data")
    parser.add_argument("--as-of-date", required=True, help="分析时点，格式 YYYYMMDD 或 YYYY-MM-DD")
    parser.add_argument("--horizons", default=",".join(map(str, DEFAULT_HORIZONS)), help="逗号分隔的评估周期，默认 5,20,60")
    parser.add_argument("--output", help="可选：将完整报告与评估明细输出为 JSON 文件")
    parser.add_argument("--limit", type=int, help="可选：只评估前 N 个 CSV，便于快速抽样")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        analysis_date = parse_trade_date(args.as_of_date)
        horizons = parse_horizons(args.horizons)
        paths = sorted(glob.glob(os.path.join(args.data_dir, "*.csv")))
        if args.limit is not None:
            paths = paths[: args.limit]
        if not paths:
            raise OfflineEvalError(f"{args.data_dir} 下未找到 CSV 文件。")

        rows: list[EvaluationRow] = []
        errors: list[str] = []
        for path in paths:
            try:
                rows.append(evaluate_file(path, analysis_date, horizons))
            except OfflineEvalError as exc:
                errors.append(str(exc))

        if not rows:
            raise OfflineEvalError("没有任何 CSV 可完成评估：" + "；".join(errors[:5]))
        print_console(rows)
        if errors:
            print("\n跳过的文件：")
            for error in errors[:20]:
                print(f"- {error}")
            if len(errors) > 20:
                print(f"- 其余 {len(errors) - 20} 个错误已省略")
        if args.output:
            write_json(rows, args.output)
            print(f"\nJSON 明细已写入：{args.output}")
    except OfflineEvalError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"[错误] 参数格式不正确：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
