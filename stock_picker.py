#!/usr/bin/env python3
"""Tushare + DeepSeek 短线 AI 选股系统。"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from deepseek_client import analyze_candidate_pool
from leader_analyzer import score_leaders
from sentiment_analyzer import analyze_market_sentiment
from strategy_config import ShortTermStrategyConfig
from theme_analyzer import analyze_hot_themes, attach_theme_scores
from trend_analyzer import add_trend_features
from tushare_data_loader import load_daily_tushare, load_hs300_tushare, load_stock_basic_tushare, normalize_daily_df

DISCLAIMER = "免责声明：以上内容仅用于量化研究和交易辅助，不构成投资建议。"


def _median(values: List[float]) -> float:
    arr = sorted(values)
    n = len(arr)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 0:
        return (arr[mid - 1] + arr[mid]) / 2
    return arr[mid]


def robust_zscores(values: List[float]) -> List[float]:
    if not values:
        return []
    med = _median(values)
    abs_dev = [abs(v - med) for v in values]
    mad = _median(abs_dev)
    if mad == 0:
        mean = sum(values) / len(values)
        var = sum((v - mean) ** 2 for v in values) / len(values)
        std = var ** 0.5
        if std == 0:
            return [0.0 for _ in values]
        return [(v - mean) / std for v in values]
    return [0.6745 * (v - med) / mad for v in values]


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_ts_code(code: str) -> str:
    code = str(code).strip()
    if code.endswith((".SH", ".SZ", ".BJ")):
        return code
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def _is_excluded_stock(code: str, name: str, close: float, amount: float, pct_chg: float, config: ShortTermStrategyConfig | None = None) -> tuple[bool, str]:
    config = config or ShortTermStrategyConfig()
    name_u = str(name).upper()
    code_s = str(code)
    if "ST" in name_u or "退" in str(name):
        return True, "st_or_delist"
    if code_s.startswith(("8", "4")) or code_s.endswith(".BJ"):
        return True, "beijing_exchange"
    if close < config.min_price:
        return True, "low_price"
    if amount < config.min_amount:
        return True, "low_amount"
    if pct_chg <= -9.5:
        return True, "limit_down"
    if pct_chg >= 9.5:
        return True, "limit_up"
    return False, "normal"


def _calc_momentum(close_list: List[float], days: int) -> float:
    if len(close_list) < days + 1:
        raise ValueError("历史数据不足")
    latest = close_list[-1]
    base = close_list[-(days + 1)]
    if base == 0:
        raise ValueError("历史价格为0")
    return (latest / base - 1.0) * 100.0


def _latest_per_symbol(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("ts_code") or row.get("symbol") or "")
        if not code:
            continue
        date = str(row.get("trade_date") or row.get("date") or "")
        if code not in latest or date >= str(latest[code].get("trade_date") or latest[code].get("date") or ""):
            latest[code] = row
    return list(latest.values())


def _load_tushare_market_history(args: argparse.Namespace, config: ShortTermStrategyConfig) -> List[Dict[str, Any]]:
    """加载用于选股的多日行情；优先 data/*.csv 缓存，必要时请求 Tushare。"""
    data_dir = Path(args.data_dir)
    all_rows: List[Dict[str, Any]] = []
    csv_files = sorted(p for p in data_dir.glob("*.csv") if len(p.stem) == 6 and p.stem.isdigit()) if data_dir.exists() else []
    if csv_files:
        for p in csv_files[: args.universe_size if args.universe_size > 0 else None]:
            try:
                with p.open("r", encoding="utf-8", newline="") as f:
                    file_rows = list(csv.DictReader(f))
            except Exception:
                continue
            for row in file_rows:
                r = dict(row)
                r["ts_code"] = _normalize_ts_code(p.stem)
                r["symbol"] = p.stem
                r.setdefault("name", p.stem)
                r.setdefault("industry", "缓存股票")
                if "trade_date" not in r or not r.get("trade_date"):
                    r["trade_date"] = str(r.get("date", "")).replace("-", "")
                all_rows.append(r)
        return all_rows

    if not os.getenv("TUSHARE_TOKEN", "").strip():
        print("[WARN] 未配置 TUSHARE_TOKEN 且 data 目录无可用CSV，输出空结果。")
        return []

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=max(80, int(args.months * 31)))
    start_date = start_dt.strftime("%Y%m%d")
    end_date = end_dt.strftime("%Y%m%d")
    basic = load_stock_basic_tushare(args.cache_dir)
    basic_rows = basic.to_dict(orient="records") if hasattr(basic, "to_dict") else []
    if args.universe_size > 0:
        basic_rows = basic_rows[: args.universe_size]
    for idx, info in enumerate(basic_rows, start=1):
        ts_code = str(info.get("ts_code", ""))
        if not ts_code:
            continue
        try:
            daily = load_daily_tushare(ts_code, start_date, end_date, args.cache_dir)
            norm = normalize_daily_df(daily, basic)
            all_rows.extend(norm.to_dict(orient="records"))
        except Exception as exc:
            print(f"[WARN] {ts_code} Tushare加载失败: {exc}")
        if idx % 20 == 0:
            print(f"  已加载历史数据 {idx}/{len(basic_rows)}")
    return all_rows


def _build_hs300_rows(args: argparse.Namespace) -> List[Dict[str, Any]]:
    if not os.getenv("TUSHARE_TOKEN", "").strip():
        return []
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=90)
    try:
        df = load_hs300_tushare(start_dt.strftime("%Y%m%d"), end_dt.strftime("%Y%m%d"), args.cache_dir)
        if hasattr(df, "rename"):
            df = df.rename(columns={"trade_date": "date"})
            return df.to_dict(orient="records")
    except Exception:
        return []
    return []


def _score_liquidity(rows: List[Dict[str, Any]]) -> None:
    amount_z = robust_zscores([_to_float(r.get("amount")) for r in rows])
    turnover_z = robust_zscores([_to_float(r.get("turnover_rate")) for r in rows])
    volume_z = robust_zscores([_to_float(r.get("volume_ratio")) for r in rows])
    for i, r in enumerate(rows):
        val = 0.5 + 0.2 * amount_z[i] + 0.15 * turnover_z[i] + 0.15 * volume_z[i]
        r["liquidity_score"] = round(max(0.0, min(1.0, val)), 4)


def _filter_candidates(rows: List[Dict[str, Any]], hot_names: set[str], config: ShortTermStrategyConfig) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        code = str(r.get("ts_code") or r.get("symbol") or "")
        name = str(r.get("name") or code)
        close = _to_float(r.get("close"))
        amount = _to_float(r.get("amount"))
        pct_chg = _to_float(r.get("pct_chg"))
        excluded, reason = _is_excluded_stock(code, name, close, amount, pct_chg, config)
        r["risk_flag"] = reason
        if excluded:
            continue
        if str(r.get("main_theme")) not in hot_names:
            continue
        if not (_to_float(r.get("close")) > _to_float(r.get("ma5")) > _to_float(r.get("ma10")) > 0):
            continue
        if not (config.momentum_5_min <= _to_float(r.get("momentum_5")) <= config.momentum_5_max):
            continue
        if _to_float(r.get("volume_ratio")) < config.volume_ratio_min:
            continue
        if _to_float(r.get("close_position"), 0.0) < config.close_position_min:
            continue
        out.append(r)
    return out


def _fetch_tushare_short_term(args: argparse.Namespace) -> tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    config = build_config(args)
    rows = _load_tushare_market_history(args, config)
    rows = add_trend_features(rows, config)
    latest = _latest_per_symbol(rows)
    hs300_rows = _build_hs300_rows(args) if config.use_market_filter else []
    sentiment = analyze_market_sentiment(latest, hs300_rows)
    themes, hot_names = analyze_hot_themes(latest, config.hot_theme_top_pct)
    latest = attach_theme_scores(latest, themes)
    candidates = _filter_candidates(latest, hot_names, config)
    candidates = score_leaders(candidates)
    _score_liquidity(candidates)
    for r in candidates:
        r["market_sentiment"] = sentiment["market_sentiment"]
        r["risk_level"] = sentiment["risk_level"]
        r["sentiment_cycle_score"] = sentiment["sentiment_cycle_score"]
        r["total_score"] = round(
            _to_float(r.get("hot_theme_score")) * 0.30
            + _to_float(r.get("sentiment_cycle_score")) * 0.15
            + _to_float(r.get("leader_score")) * 0.25
            + _to_float(r.get("trend_strength_score")) * 0.20
            + _to_float(r.get("liquidity_score")) * 0.10,
            6,
        )
    candidates.sort(key=lambda x: _to_float(x.get("total_score")), reverse=True)
    return candidates, sentiment, themes


def _write_csv(rows: List[Dict[str, Any]], path: Path, columns: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True) if path.parent != Path("") else None
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for idx, row in enumerate(rows, start=1):
            r = dict(row)
            r.setdefault("rank", idx)
            for k, v in list(r.items()):
                if isinstance(v, (list, dict)):
                    r[k] = json.dumps(v, ensure_ascii=False)
            writer.writerow({k: r.get(k, "") for k in columns})


def save_json(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True) if path.parent != Path("") else None
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _flatten_ai_pick(pick: Dict[str, Any]) -> Dict[str, Any]:
    plan = pick.get("operation_plan") or {}
    return {
        "ai_rating": pick.get("ai_rating", ""),
        "ai_confidence": pick.get("confidence", ""),
        "why_selected": pick.get("why_selected", ""),
        "leader_judgement": pick.get("leader_judgement", ""),
        "trend_judgement": pick.get("trend_judgement", ""),
        "buy_condition": plan.get("buy_condition", ""),
        "position_advice": plan.get("position", ""),
        "stop_loss": plan.get("stop_loss", ""),
        "take_profit": plan.get("take_profit", ""),
        "max_holding_days": plan.get("max_holding_days", ""),
        "risk_points": "；".join(str(x) for x in (pick.get("risk_points") or [])),
    }


def build_final_picks(candidates: List[Dict[str, Any]], sentiment: Dict[str, Any], themes: List[Dict[str, Any]], args: argparse.Namespace) -> List[Dict[str, Any]]:
    config = build_config(args)
    pool = candidates[: args.ai_candidate_size]
    if args.enable_ai_analysis:
        analysis = analyze_candidate_pool(pool, sentiment, themes, final_top_n=args.ai_top_n, model=args.deepseek_model)
    else:
        from deepseek_client import build_fallback_analysis

        analysis = build_fallback_analysis(pool, sentiment, args.top, "未启用 DeepSeek 分析，当前结果为量化模型Top3。")
    by_code = {str(r.get("ts_code")): r for r in pool}
    final: List[Dict[str, Any]] = []
    for idx, pick in enumerate((analysis.get("picks") or [])[: config.final_top_n], start=1):
        base = dict(by_code.get(str(pick.get("ts_code")), {}))
        if not base and idx <= len(pool):
            base = dict(pool[idx - 1])
        base.update({"rank": idx})
        base.update(_flatten_ai_pick(pick))
        final.append(base)
    while len(final) < config.final_top_n and len(final) < len(pool):
        base = dict(pool[len(final)])
        base.update({"rank": len(final) + 1})
        final.append(base)
    return final[: config.final_top_n]


CANDIDATE_COLUMNS = [
    "rank", "ts_code", "name", "industry", "main_theme", "theme_rank", "theme_strength", "market_sentiment", "risk_level",
    "close", "pct_chg", "amount", "turnover_rate", "momentum_3", "momentum_5", "volume_ratio", "close_position", "ma5", "ma10", "ma20",
    "hot_theme_score", "sentiment_cycle_score", "leader_score", "trend_strength_score", "liquidity_score", "total_score", "is_leader", "leader_rank", "leader_reason", "trend_reason", "risk_flag",
]

PICK_COLUMNS = [
    "rank", "ts_code", "name", "main_theme", "market_sentiment", "risk_level", "close", "pct_chg", "amount", "momentum_3", "momentum_5", "volume_ratio", "ma5", "ma10", "ma20",
    "hot_theme_score", "sentiment_cycle_score", "leader_score", "trend_strength_score", "liquidity_score", "total_score", "ai_rating", "ai_confidence", "why_selected", "leader_judgement", "trend_judgement", "buy_condition", "position_advice", "stop_loss", "take_profit", "max_holding_days", "risk_points",
]

HOT_THEME_COLUMNS = ["rank", "theme_name", "theme_strength", "hot_theme_score", "pct_chg_1d", "pct_chg_3d", "pct_chg_5d", "amount_ratio", "strong_stock_count", "limit_up_count"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tushare + DeepSeek 短线 AI 选股系统")
    parser.add_argument("--source", choices=["tushare"], default="tushare")
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--candidate-size", type=int, default=20)
    parser.add_argument("--universe-size", type=int, default=80)
    parser.add_argument("--months", type=int, default=3)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache_tushare"))
    parser.add_argument("--output", type=Path, default=Path("picked_stocks.csv"))
    parser.add_argument("--candidate-output", type=Path, default=Path("candidate_pool.csv"))
    parser.add_argument("--market-sentiment-output", type=Path, default=Path("market_sentiment.json"))
    parser.add_argument("--hot-themes-output", type=Path, default=Path("hot_themes.csv"))
    parser.add_argument("--enable-ai-analysis", action="store_true")
    parser.add_argument("--ai-top-n", type=int, default=3)
    parser.add_argument("--ai-candidate-size", type=int, default=20)
    parser.add_argument("--deepseek-model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
    parser.add_argument("--min-price", type=float, default=3.0)
    parser.add_argument("--min-amount", type=float, default=100_000_000.0)
    parser.add_argument("--momentum-5-min", type=float, default=3.0)
    parser.add_argument("--momentum-5-max", type=float, default=18.0)
    parser.add_argument("--volume-ratio-min", type=float, default=1.2)
    parser.add_argument("--volume-ratio-max", type=float, default=2.5)
    parser.add_argument("--close-position-min", type=float, default=0.6)
    parser.add_argument("--no-market-filter", action="store_true")
    parser.add_argument("--auto-daily", action="store_true")
    parser.add_argument("--daily-time", default="15:10")
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> ShortTermStrategyConfig:
    return ShortTermStrategyConfig(
        min_price=args.min_price,
        min_amount=args.min_amount,
        momentum_5_min=args.momentum_5_min,
        momentum_5_max=args.momentum_5_max,
        volume_ratio_min=args.volume_ratio_min,
        volume_ratio_max=args.volume_ratio_max,
        close_position_min=args.close_position_min,
        candidate_size=args.candidate_size,
        final_top_n=args.top,
        use_market_filter=not args.no_market_filter,
    )


def print_report(final: List[Dict[str, Any]], sentiment: Dict[str, Any], themes: List[Dict[str, Any]], ai_enabled: bool) -> None:
    print("=== 市场情绪 ===")
    print(f"周期: {sentiment.get('market_sentiment', '')}")
    print(f"风险等级: {sentiment.get('risk_level', '')}")
    print(f"说明: {sentiment.get('sentiment_reason', '')}\n")
    print("=== 今日主线热点 ===")
    for t in themes[:3]:
        print(f"{t.get('rank')}. {t.get('theme_name')} score={float(t.get('hot_theme_score', 0)):.4f}")
    print("\n=== DeepSeek 精选三只短线标的 ===" if ai_enabled else "\n=== 量化模型Top3短线观察标的 ===")
    for row in final:
        print(f"\n#{row.get('rank')} {row.get('ts_code')} {row.get('name')}")
        print(f"主线: {row.get('main_theme', '')}")
        print(f"AI评级: {row.get('ai_rating', '')}")
        print(f"入选原因: {row.get('why_selected', '')}")
        print(f"龙头判断: {row.get('leader_judgement', '')}")
        print(f"趋势判断: {row.get('trend_judgement', '')}")
        print("操作建议:")
        print(f"- 买入条件: {row.get('buy_condition', '')}")
        print(f"- 仓位: {row.get('position_advice', '')}")
        print(f"- 止损: {row.get('stop_loss', '')}")
        print(f"- 止盈: {row.get('take_profit', '')}")
        print(f"- 最长持有: {row.get('max_holding_days', '')}天")
        print(f"风险: {row.get('risk_points', '')}")
    if not ai_enabled:
        print("\n未启用 DeepSeek 分析，当前结果为量化模型 Top3。")
    print(f"\n{DISCLAIMER}")


def run_once(args: argparse.Namespace) -> None:
    candidates, sentiment, themes = _fetch_tushare_short_term(args)
    candidate_pool = candidates[: args.candidate_size]
    final = build_final_picks(candidates, sentiment, themes, args)
    _write_csv(candidate_pool, args.candidate_output, CANDIDATE_COLUMNS)
    _write_csv(final, args.output, PICK_COLUMNS)
    save_json({"trade_date": datetime.now().strftime("%Y%m%d"), **sentiment}, args.market_sentiment_output)
    _write_csv(themes, args.hot_themes_output, HOT_THEME_COLUMNS)
    print_report(final, sentiment, themes, args.enable_ai_analysis)
    print(f"\n已输出: {args.output}")
    print(f"候选池: {args.candidate_output}")
    print(f"市场情绪: {args.market_sentiment_output}")
    print(f"热点主线: {args.hot_themes_output}")


def _next_run_time(daily_time: str) -> datetime:
    hh, mm = daily_time.split(":")
    target = datetime.now().replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if target <= datetime.now():
        target += timedelta(days=1)
    return target


def run_daily(args: argparse.Namespace) -> None:
    print(f"已开启每日自动选股：{args.daily_time}，Top={args.top}")
    while True:
        nxt = _next_run_time(args.daily_time)
        wait_seconds = max(1, int((nxt - datetime.now()).total_seconds()))
        print(f"下一次运行时间：{nxt.strftime('%Y-%m-%d %H:%M:%S')}，等待 {wait_seconds} 秒")
        time.sleep(wait_seconds)
        run_once(args)


def main() -> None:
    args = parse_args()
    if args.auto_daily:
        run_daily(args)
    else:
        run_once(args)


if __name__ == "__main__":
    main()
