#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

from data_loader import load_history


fallback_symbols = [
    "000001", "000002", "000063", "000333", "000651",
    "000725", "002129", "002230", "002241", "002475",
    "002594", "002714", "300014", "300015", "300059",
    "300122", "300274", "300750", "300760", "300782",
    "600000", "600009", "600030", "600036", "600050",
    "600276", "600309", "600519", "600887", "601012",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--months", type=int, default=12)
    p.add_argument("--universe-size", type=int, default=30)
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=31 * args.months)
    start = start_dt.strftime("%Y%m%d")
    end = end_dt.strftime("%Y%m%d")

    symbols = fallback_symbols[: args.universe_size] if args.universe_size > 0 else fallback_symbols

    ok = 0
    fail = 0
    for symbol in symbols:
        csv_path = args.data_dir / f"{symbol}.csv"
        if csv_path.exists():
            continue
        df = load_history(symbol, start, end, data_dir=args.data_dir)
        if df.empty:
            fail += 1
        else:
            ok += 1

    print(f"成功数量: {ok}")
    print(f"失败数量: {fail}")
    print(f"CSV保存路径: {args.data_dir.resolve()}")
