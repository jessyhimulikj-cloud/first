#!/usr/bin/env python3
"""自动选股系统（CSV + AkShare）

- 保留 csv 模式
- 新增 akshare 模式（短线 3-5 天模型）
- 支持每天定时自动输出 TopN 到 picked_stocks.csv
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlencode

REQUIRED_MARKET_COLUMNS = ["ts_code", "name", "close", "pct_chg", "vol_ratio", "turnover_rate"]
REQUIRED_FLOW_COLUMNS = ["ts_code", "main_net_inflow", "super_net_inflow", "main_inflow_ratio"]
REQUIRED_THEME_COLUMNS = ["theme", "heat_score"]
REQUIRED_THEME_MAP_COLUMNS = ["ts_code", "theme"]

EASTMONEY_BASE = "https://push2.eastmoney.com/api/qt/clist/get"


@dataclass
class FactorWeights:
    money_flow: float = 0.45
    momentum: float = 0.25
    liquidity: float = 0.15
    hot_theme: float = 0.15


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


def read_csv(path: Path, required_cols: List[str], name: str) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"找不到 {name} 文件: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"{name} 为空")
        missing = [c for c in required_cols if c not in reader.fieldnames]
        if missing:
            raise ValueError(f"{name} 缺少字段: {missing}")
        return list(reader)


def _to_float(row: Dict[str, str], key: str) -> float:
    return float(row.get(key, "0") or 0)


def _normalize_ts_code(code: str) -> str:
    code = str(code).strip()
    if code.endswith(".SH") or code.endswith(".SZ"):
        return code
    return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"


def _import_akshare() -> Any:
    try:
        return importlib.import_module("akshare")
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("未安装 akshare。请执行: pip install akshare pandas") from exc


def _df_to_rows(df: Any) -> List[Dict[str, Any]]:
    if not hasattr(df, "to_dict"):
        raise TypeError("数据源返回不是 DataFrame")
    return df.to_dict(orient="records")


def _pick(row: Dict[str, Any], keys: List[str], default: Any = 0) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return default


def _is_excluded_stock(code: str, name: str, close: float, amount: float, pct_chg: float) -> Tuple[bool, str]:
    name_u = name.upper()
    if "ST" in name_u or "*ST" in name_u or "退" in name:
        return True, "st_or_delist"
    if str(code).startswith("8") or str(code).startswith("4"):
        return True, "beijing_exchange"
    if close < 3:
        return True, "low_price"
    if amount < 1e8:
        return True, "low_amount"
    if pct_chg < -5:
        return True, "drop_too_much"
    if pct_chg > 9.5:
        return True, "chase_limit_up"
    return False, "normal"


def _calc_momentum(close_list: List[float], days: int) -> float:
    if len(close_list) < days + 1:
        raise ValueError("历史数据不足")
    latest = close_list[-1]
    base = close_list[-(days + 1)]
    if base == 0:
        raise ValueError("历史价格为0")
    return (latest / base - 1.0) * 100.0


def _fetch_hot_board_symbols(ak: Any) -> set[str]:
    """仅保留当前涨幅排名前20%的板块成分股。"""
    hot_symbols: set[str] = set()
    try:
        board_rows = _df_to_rows(ak.stock_board_hot_rank_em())
        if not board_rows:
            return hot_symbols

        board_rows.sort(key=lambda x: float(_pick(x, ["涨跌幅", "今日涨跌幅", "change_percent"], 0) or 0), reverse=True)
        top_n = max(1, int(len(board_rows) * 0.2))

        for b in board_rows[:top_n]:
            board_name = str(_pick(b, ["板块名称", "名称", "name"], "")).strip()
            if not board_name:
                continue
            try:
                cons_rows = _df_to_rows(ak.stock_board_industry_cons_em(symbol=board_name))
                for c in cons_rows:
                    code = str(_pick(c, ["代码", "code"], "")).strip()
                    if code:
                        hot_symbols.add(code)
            except Exception:
                continue
    except Exception:
        return set()
    return hot_symbols


def _fetch_akshare_short_term(args: argparse.Namespace) -> List[Dict[str, float | str]]:
    ak = _import_akshare()
    spot_rows = _df_to_rows(ak.stock_zh_a_spot_em())
    hot_symbols = _fetch_hot_board_symbols(ak)

    candidates: List[Dict[str, Any]] = []
    for r in spot_rows:
        code = str(_pick(r, ["代码", "code"], "")).strip()
        name = str(_pick(r, ["名称", "name"], "")).strip()
        if not code or not name:
            continue

        close = float(_pick(r, ["最新价", "最新", "close"], 0) or 0)
        pct_chg = float(_pick(r, ["涨跌幅", "pct_chg"], 0) or 0)
        amount = float(_pick(r, ["成交额", "amount"], 0) or 0)

        excluded, reason = _is_excluded_stock(code, name, close, amount, pct_chg)
        if excluded:
            continue
        if hot_symbols and code not in hot_symbols:
            continue

        candidates.append(
            {
                "ts_code": _normalize_ts_code(code),
                "code": code,
                "name": name,
                "close": close,
                "pct_chg": pct_chg,
                "amount": amount,
                "risk_flag": reason,
            }
        )

    # 先按成交额排序，限制后续历史请求数量，避免接口太慢
    candidates.sort(key=lambda x: float(x["amount"]), reverse=True)
    candidates = candidates[: args.ak_hist_limit]

    picked: List[Dict[str, float | str]] = []
    for c in candidates:
        try:
            hist_df = ak.stock_zh_a_hist(symbol=str(c["code"]), period="daily", adjust="qfq")
            hist_rows = _df_to_rows(hist_df)
            closes = [float(_pick(h, ["收盘", "close"], 0) or 0) for h in hist_rows if float(_pick(h, ["收盘", "close"], 0) or 0) > 0]
            vols = [float(_pick(h, ["成交量", "volume"], 0) or 0) for h in hist_rows]
            pct_list = [float(_pick(h, ["涨跌幅", "pct_chg"], 0) or 0) for h in hist_rows]
            if len(closes) < 11 or len(vols) < 6 or len(pct_list) < 3:
                continue

            ma5 = sum(closes[-5:]) / 5.0
            ma10 = sum(closes[-10:]) / 10.0
            trend_ok = ma5 > ma10 and closes[-1] > ma5
            if not trend_ok:
                continue

            momentum_3 = _calc_momentum(closes, 3)
            momentum_5 = _calc_momentum(closes, 5)
            if momentum_5 < 0:
                continue
            if any(p <= -9.5 for p in pct_list[-3:]):
                continue

            avg_vol_5 = sum(vols[-5:]) / 5.0 if sum(vols[-5:]) > 0 else 0.0
            if avg_vol_5 <= 0:
                continue
            volume_ratio = vols[-1] / avg_vol_5
            if volume_ratio <= 1.5:
                continue

            picked.append(
                {
                    "ts_code": c["ts_code"],
                    "name": c["name"],
                    "close": c["close"],
                    "pct_chg": c["pct_chg"],
                    "amount": c["amount"],
                    "momentum_3": momentum_3,
                    "momentum_5": momentum_5,
                    "volume_ratio": volume_ratio,
                    "trend_flag": "uptrend_confirmed",
                    "risk_flag": "normal",
                }
            )
        except Exception:
            continue

    liquidity_z = robust_zscores([float(r["amount"]) for r in picked])
    for idx, r in enumerate(picked):
        r["liquidity_z"] = liquidity_z[idx]
        r["total_score"] = (
            0.30 * float(r["momentum_5"])
            + 0.20 * float(r["momentum_3"])
            + 0.30 * float(r["liquidity_z"])
            + 0.20 * float(r["pct_chg"])
        )

    picked.sort(key=lambda x: float(x["total_score"]), reverse=True)
    return picked


def _build_session() -> Any:
    """创建请求会话：禁用系统代理，统一浏览器头。"""
    requests = importlib.import_module("requests")
    session = requests.Session()
    session.trust_env = False  # 禁用系统代理，解决代理污染问题
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        }
    )
    return session


def _http_get_json(url: str, timeout: int = 12, max_retries: int = 3) -> dict:
    """
    使用 requests.Session 拉取 JSON。
    - 禁用系统代理
    - 最多重试 3 次
    - 返回 502 或请求失败自动重试
    """
    requests = importlib.import_module("requests")
    session = _build_session()
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, timeout=timeout)
            if response.status_code == 502:
                raise requests.HTTPError("502 Bad Gateway", response=response)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, json.JSONDecodeError) as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(0.8 * attempt)
                continue
            break

    raise RuntimeError(f"HTTP 请求失败，重试{max_retries}次仍失败: {url}") from last_exc


def _fetch_eastmoney_market(page_size: int = 200) -> List[Dict[str, str]]:
    params = {
        "pn": 1,
        "pz": page_size,
        "po": 1,
        "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:13,m:1+t:2,m:1+t:23",
        "fields": "f12,f14,f2,f3,f8,f10",
    }
    data = _http_get_json(f"{EASTMONEY_BASE}?{urlencode(params)}")
    diff = data.get("data", {}).get("diff", [])

    rows: List[Dict[str, str]] = []
    for item in diff:
        code = str(item.get("f12", "")).strip()
        if not code:
            continue
        rows.append(
            {
                "ts_code": _normalize_ts_code(code),
                "name": str(item.get("f14", "")),
                "close": str(item.get("f2", 0)),
                "pct_chg": str(item.get("f3", 0)),
                "turnover_rate": str(item.get("f8", 0)),
                "vol_ratio": str(item.get("f10", 0)),
            }
        )
    return rows


def _fetch_eastmoney_flow(page_size: int = 200) -> List[Dict[str, str]]:
    params = {
        "pn": 1,
        "pz": page_size,
        "po": 1,
        "np": 1,
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "fltt": 2,
        "invt": 2,
        "fid": "f62",
        "fs": "m:0+t:6,m:0+t:13,m:1+t:2,m:1+t:23",
        "fields": "f12,f62,f66,f184",
    }
    data = _http_get_json(f"{EASTMONEY_BASE}?{urlencode(params)}")
    diff = data.get("data", {}).get("diff", [])

    rows: List[Dict[str, str]] = []
    for item in diff:
        code = str(item.get("f12", "")).strip()
        if not code:
            continue
        rows.append(
            {
                "ts_code": _normalize_ts_code(code),
                "main_net_inflow": str(item.get("f62", 0)),
                "super_net_inflow": str(item.get("f66", 0)),
                "main_inflow_ratio": str(item.get("f184", 0)),
            }
        )
    return rows


def build_theme_score(theme_rows: List[Dict[str, str]], theme_map_rows: List[Dict[str, str]]) -> Dict[str, Dict[str, float]]:
    if not theme_rows or not theme_map_rows:
        return {}
    theme_heat = {r["theme"]: _to_float(r, "heat_score") for r in theme_rows}
    themes = list(theme_heat.keys())
    zvals = robust_zscores([theme_heat[t] for t in themes])
    theme_z = {t: z for t, z in zip(themes, zvals)}

    stock_themes: Dict[str, List[str]] = {}
    for row in theme_map_rows:
        stock_themes.setdefault(row["ts_code"], []).append(row["theme"])

    out: Dict[str, Dict[str, float]] = {}
    for ts_code, tlist in stock_themes.items():
        vals = [theme_z.get(t, 0.0) for t in tlist]
        out[ts_code] = {
            "hot_theme_score": sum(vals) / len(vals) if vals else 0.0,
            "theme_count": float(len(set(tlist))),
        }
    return out


def score_stocks(
    market_rows: List[Dict[str, str]],
    flow_rows: List[Dict[str, str]],
    theme_rows: List[Dict[str, str]],
    theme_map_rows: List[Dict[str, str]],
    weights: FactorWeights,
) -> List[Dict[str, float | str]]:
    market_by_code = {r["ts_code"]: r for r in market_rows}
    flow_by_code = {r["ts_code"]: r for r in flow_rows}
    theme_score = build_theme_score(theme_rows, theme_map_rows)

    records: List[Dict[str, float | str]] = []
    for ts_code in sorted(set(market_by_code).intersection(flow_by_code)):
        m = market_by_code[ts_code]
        f = flow_by_code[ts_code]

        pct_chg = _to_float(m, "pct_chg")
        vol_ratio = _to_float(m, "vol_ratio")
        turnover_rate = _to_float(m, "turnover_rate")
        main_net_inflow = _to_float(f, "main_net_inflow")
        super_net_inflow = _to_float(f, "super_net_inflow")
        main_inflow_ratio = _to_float(f, "main_inflow_ratio")

        money_flow_raw = 0.55 * main_net_inflow + 0.25 * super_net_inflow + 0.20 * main_inflow_ratio
        momentum_raw = 0.7 * pct_chg + 0.3 * vol_ratio
        liquidity_raw = 0.6 * turnover_rate + 0.4 * vol_ratio

        t = theme_score.get(ts_code, {"hot_theme_score": 0.0, "theme_count": 0.0})
        records.append(
            {
                "ts_code": ts_code,
                "name": m["name"],
                "close": _to_float(m, "close"),
                "pct_chg": pct_chg,
                "main_net_inflow": main_net_inflow,
                "main_inflow_ratio": main_inflow_ratio,
                "theme_count": t["theme_count"],
                "money_flow_raw": money_flow_raw,
                "momentum_raw": momentum_raw,
                "liquidity_raw": liquidity_raw,
                "hot_theme_score": t["hot_theme_score"],
                "turnover_rate": turnover_rate,
                "risk_flag": "normal",
            }
        )

    flow_z = robust_zscores([r["money_flow_raw"] for r in records])
    momentum_z = robust_zscores([r["momentum_raw"] for r in records])
    liq_z = robust_zscores([r["liquidity_raw"] for r in records])

    for idx, r in enumerate(records):
        r["total_score"] = (
            weights.money_flow * flow_z[idx]
            + weights.momentum * momentum_z[idx]
            + weights.liquidity * liq_z[idx]
            + weights.hot_theme * float(r["hot_theme_score"])
        )

    records.sort(key=lambda x: float(x["total_score"]), reverse=True)
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="资金流+热点自动选股")
    parser.add_argument("--source", choices=["csv", "eastmoney", "akshare"], default="csv")
    parser.add_argument("--market", type=Path, help="csv模式行情文件")
    parser.add_argument("--flow", type=Path, help="csv模式资金流文件")
    parser.add_argument("--theme", type=Path, help="csv模式题材文件")
    parser.add_argument("--theme-map", type=Path, help="csv模式题材映射")

    parser.add_argument("--em-page-size", type=int, default=200)

    parser.add_argument("--ak-hist-limit", type=int, default=150, help="akshare模式参与3/5日计算的股票上限")

    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("picked_stocks.csv"))

    parser.add_argument("--auto-daily", action="store_true")
    parser.add_argument("--daily-time", default="15:10")

    parser.add_argument("--w-money-flow", type=float, default=0.45)
    parser.add_argument("--w-momentum", type=float, default=0.25)
    parser.add_argument("--w-liquidity", type=float, default=0.15)
    parser.add_argument("--w-hot-theme", type=float, default=0.15)
    return parser.parse_args()


def build_weights(args: argparse.Namespace) -> FactorWeights:
    weights = FactorWeights(args.w_money_flow, args.w_momentum, args.w_liquidity, args.w_hot_theme)
    total = weights.money_flow + weights.momentum + weights.liquidity + weights.hot_theme
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"权重和必须为1，当前为 {total:.4f}")
    return weights


def _load_theme_optional(args: argparse.Namespace) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    if args.theme and args.theme_map:
        return read_csv(args.theme, REQUIRED_THEME_COLUMNS, "theme"), read_csv(args.theme_map, REQUIRED_THEME_MAP_COLUMNS, "theme_map")
    return [], []


def _load_legacy_data(args: argparse.Namespace) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]]]:
    if args.source == "csv":
        if not args.market or not args.flow:
            raise ValueError("source=csv 时必须提供 --market 和 --flow")
        market = read_csv(args.market, REQUIRED_MARKET_COLUMNS, "market")
        flow = read_csv(args.flow, REQUIRED_FLOW_COLUMNS, "flow")
        theme, theme_map = _load_theme_optional(args)
        return market, flow, theme, theme_map

    market = _fetch_eastmoney_market(args.em_page_size)
    flow = _fetch_eastmoney_flow(args.em_page_size)
    theme, theme_map = _load_theme_optional(args)
    return market, flow, theme, theme_map


def write_output(rows: List[Dict[str, float | str]], path: Path, topn: int, source: str) -> None:
    selected = rows[:topn]
    if source == "akshare":
        columns = [
            "ts_code",
            "name",
            "close",
            "pct_chg",
            "amount",
            "momentum_3",
            "momentum_5",
            "volume_ratio",
            "trend_flag",
            "total_score",
            "risk_flag",
        ]
    else:
        columns = ["ts_code", "name", "close", "pct_chg", "total_score", "risk_flag"]

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for r in selected:
            writer.writerow({k: r.get(k, "") for k in columns})

    print("=== Top Picks ===")
    for r in selected:
        print(f"{r.get('ts_code',''):>10} {str(r.get('name','')):<10} score={float(r.get('total_score',0)):.4f} risk={r.get('risk_flag','normal')}")
    print(f"\n已输出到: {path}")


def run_once(args: argparse.Namespace, weights: FactorWeights) -> None:
    if args.source == "akshare":
        rows = _fetch_akshare_short_term(args)
    else:
        market, flow, theme, theme_map = _load_legacy_data(args)
        rows = score_stocks(market, flow, theme, theme_map, weights)
    write_output(rows, args.output, args.top, args.source)


def _next_run_time(daily_time: str) -> datetime:
    try:
        hh, mm = daily_time.split(":")
        target = datetime.now().replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    except Exception as exc:
        raise ValueError("--daily-time 必须是 HH:MM，例如 15:10") from exc
    if target <= datetime.now():
        target = target + timedelta(days=1)
    return target


def run_daily(args: argparse.Namespace, weights: FactorWeights) -> None:
    print(f"已开启每日自动选股：{args.daily_time}，Top={args.top}")
    while True:
        nxt = _next_run_time(args.daily_time)
        wait_seconds = max(1, int((nxt - datetime.now()).total_seconds()))
        print(f"下一次运行: {nxt.strftime('%Y-%m-%d %H:%M:%S')}，等待 {wait_seconds} 秒")
        time.sleep(wait_seconds)
        try:
            run_once(args, weights)
        except Exception as exc:
            print(f"本次执行失败: {exc}")


def main() -> None:
    args = parse_args()
    weights = build_weights(args)
    if args.auto_daily:
        run_daily(args, weights)
    else:
        run_once(args, weights)


if __name__ == "__main__":
    main()
