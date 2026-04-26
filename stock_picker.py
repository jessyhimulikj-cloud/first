#!/usr/bin/env python3
"""自动选股系统（资金流 + 热点）

支持两种数据源：
1) csv：从本地 CSV 读取
2) eastmoney：从东方财富接口拉取行情和资金流，题材数据可选 CSV
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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


def _http_get_json(url: str, timeout: int = 12) -> dict:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _normalize_ts_code(code: str) -> str:
    return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"


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
    # 资金流榜字段：f62 主力净流入，f66 超大单净流入，f184 主力净占比
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
        mean = sum(vals) / len(vals) if vals else 0.0
        out[ts_code] = {"hot_theme_score": mean, "theme_count": float(len(set(tlist)))}
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
            }
        )

    flow_z = robust_zscores([r["money_flow_raw"] for r in records])
    momentum_z = robust_zscores([r["momentum_raw"] for r in records])
    liq_z = robust_zscores([r["liquidity_raw"] for r in records])

    for idx, r in enumerate(records):
        r["money_flow_z"] = flow_z[idx]
        r["momentum_z"] = momentum_z[idx]
        r["liquidity_z"] = liq_z[idx]
        r["total_score"] = (
            weights.money_flow * r["money_flow_z"]
            + weights.momentum * r["momentum_z"]
            + weights.liquidity * r["liquidity_z"]
            + weights.hot_theme * r["hot_theme_score"]
        )
        risk_flag = "normal"
        if float(r["turnover_rate"]) > 25:
            risk_flag = "high_turnover"
        if float(r["pct_chg"]) > 9:
            risk_flag = "limit_up_nearby"
        r["risk_flag"] = risk_flag

    records.sort(key=lambda x: float(x["total_score"]), reverse=True)
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="资金流+热点自动选股")
    parser.add_argument("--source", choices=["csv", "eastmoney"], default="csv", help="数据源：csv/eastmoney")
    parser.add_argument("--market", type=Path, help="行情 CSV（source=csv 时必填）")
    parser.add_argument("--flow", type=Path, help="资金流 CSV（source=csv 时必填）")
    parser.add_argument("--theme", type=Path, help="题材热度 CSV（可选）")
    parser.add_argument("--theme-map", type=Path, help="个股题材映射 CSV（可选）")
    parser.add_argument("--em-page-size", type=int, default=200, help="东方财富拉取股票数")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path("picked_stocks.csv"))
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


def _load_theme_optional(args: argparse.Namespace) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    if args.theme and args.theme_map:
        return (
            read_csv(args.theme, REQUIRED_THEME_COLUMNS, "theme"),
            read_csv(args.theme_map, REQUIRED_THEME_MAP_COLUMNS, "theme_map"),
        )
    return [], []


def load_data(args: argparse.Namespace) -> tuple[List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]]]:
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


def write_output(rows: List[Dict[str, float | str]], path: Path, topn: int) -> None:
    selected = rows[:topn]
    columns = [
        "ts_code",
        "name",
        "close",
        "pct_chg",
        "main_net_inflow",
        "main_inflow_ratio",
        "theme_count",
        "money_flow_z",
        "momentum_z",
        "liquidity_z",
        "hot_theme_score",
        "total_score",
        "risk_flag",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for r in selected:
            writer.writerow({k: r[k] for k in columns})

    print("=== Top Picks ===")
    for r in selected:
        print(f"{r['ts_code']:>10} {r['name']:<8} score={float(r['total_score']):.4f} risk={r['risk_flag']}")
    print(f"\n已输出到: {path}")


def main() -> None:
    args = parse_args()
    weights = build_weights(args)

    market, flow, theme, theme_map = load_data(args)
    rows = score_stocks(market, flow, theme, theme_map, weights)
    write_output(rows, args.output, args.top)


if __name__ == "__main__":
    main()
