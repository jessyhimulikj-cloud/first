#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import itertools
import subprocess
from pathlib import Path
from typing import Any, Dict, List


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--max-runs", type=int, default=300)
    p.add_argument("--python", type=str, default="python")
    return p.parse_args()


def build_param_grid() -> List[Dict[str, Any]]:
    grid = itertools.product(
        [2, 3, 4, 5],  # hold_days
        [0.03, 0.04, 0.05, 0.06, 0.08],  # take_profit
        [0.02, 0.025, 0.03, 0.035, 0.04],  # stop_loss
        [1.2, 1.3, 1.5, 1.8, 2.0],  # volume_ratio
        [1.5, 2.0, 2.5],  # pct_min
        [5.0, 6.0, 7.0],  # pct_max
        [200000000, 300000000, 500000000],  # amount_min
        [0.65, 0.70, 0.75],  # close_pos_min
        [5.0, 7.0, 9.0],  # ret3_max
    )
    out: List[Dict[str, Any]] = []
    for x in grid:
        out.append(
            {
                "hold_days": x[0],
                "take_profit": x[1],
                "stop_loss": x[2],
                "volume_ratio": x[3],
                "pct_min": x[4],
                "pct_max": x[5],
                "amount_min": x[6],
                "close_pos_min": x[7],
                "ret3_max": x[8],
            }
        )
    return out


def parse_temp_result(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    metrics: Dict[str, Any] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("mode") != "param_mode_v1":
                continue
            k = row.get("metric", "")
            v = row.get("value", "")
            metrics[k] = v
    if not metrics:
        raise RuntimeError("temp_result.csv 中没有 param_mode_v1 指标")
    out: Dict[str, Any] = {}
    for k in [
        "total_trades",
        "win_rate",
        "avg_return",
        "max_drawdown",
        "profit_loss_ratio",
        "avg_win",
        "avg_loss",
        "stop_profit_count",
        "stop_loss_count",
        "timeout_exit_count",
    ]:
        raw = metrics.get(k, "0")
        out[k] = float(raw) if k != "total_trades" and not k.endswith("_count") else int(float(raw))
    out["score"] = out["win_rate"] * 100 + out["profit_loss_ratio"] * 20 + out["avg_return"] * 1000 + out["max_drawdown"] * 50
    return out


def run_one(py: str, params: Dict[str, Any], temp_path: Path) -> subprocess.CompletedProcess[str]:
    cmd = [
        py, "backtest.py",
        "--modes", "param_mode_v1",
        "--hold-days", str(params["hold_days"]),
        "--take-profit", str(params["take_profit"]),
        "--stop-loss", str(params["stop_loss"]),
        "--volume-ratio", str(params["volume_ratio"]),
        "--pct-min", str(params["pct_min"]),
        "--pct-max", str(params["pct_max"]),
        "--amount-min", str(params["amount_min"]),
        "--close-pos-min", str(params["close_pos_min"]),
        "--ret3-max", str(params["ret3_max"]),
        "--months", "12",
        "--universe-size", "100",
        "--no-market-filter",
        "--output", str(temp_path),
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> None:
    args = parse_args()
    grid = build_param_grid()
    total = min(args.max_runs, len(grid))
    temp_path = Path("temp_result.csv")
    results: List[Dict[str, Any]] = []

    for i, p in enumerate(grid[:total], start=1):
        row = dict(p)
        row["error"] = ""
        try:
            cp = run_one(args.python, p, temp_path)
            if cp.returncode != 0:
                row["error"] = (cp.stderr or cp.stdout or "backtest failed").strip()[:500]
            else:
                row.update(parse_temp_result(temp_path))
        except Exception as exc:
            row["error"] = str(exc)[:500]

        for k in ["total_trades", "win_rate", "avg_return", "max_drawdown", "profit_loss_ratio", "avg_win", "avg_loss", "stop_profit_count", "stop_loss_count", "timeout_exit_count", "score"]:
            row.setdefault(k, 0)
        results.append(row)
        print(f"[{i}/{total}] win_rate={row.get('win_rate',0):.2f} pl={row.get('profit_loss_ratio',0):.2f} dd={row.get('max_drawdown',0):.2f} trades={row.get('total_trades',0)}")

    results.sort(key=lambda x: float(x.get("score", 0)), reverse=True)
    headers = [
        "hold_days", "take_profit", "stop_loss", "volume_ratio", "pct_min", "pct_max",
        "amount_min", "close_pos_min", "ret3_max",
        "total_trades", "win_rate", "avg_return", "max_drawdown", "profit_loss_ratio",
        "avg_win", "avg_loss", "stop_profit_count", "stop_loss_count", "timeout_exit_count",
        "score", "error",
    ]
    with Path("optimize_results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(results)

    best = [
        r for r in results
        if float(r.get("win_rate", 0)) >= 0.60
        and float(r.get("profit_loss_ratio", 0)) >= 1.50
        and float(r.get("max_drawdown", 0)) >= -0.20
        and int(r.get("total_trades", 0)) >= 30
    ]
    if not best:
        best = results[:20]
    with Path("best_models.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(best)

    print(f"done: optimize_results.csv={len(results)} rows, best_models.csv={len(best)} rows")


if __name__ == "__main__":
    main()

