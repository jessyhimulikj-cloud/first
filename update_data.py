#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

from backtest import load_universe
from data_loader import load_history


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--months", type=int, default=6)
    p.add_argument("--universe-size", type=int, default=50)
    p.add_argument("--cache-dir", type=Path, default=Path(".cache_backtest"))
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=31 * args.months + 10)
    start = start_dt.strftime("%Y%m%d")
    end = end_dt.strftime("%Y%m%d")

    symbols = load_universe(args.cache_dir, size=args.universe_size)
    ok = 0
    fail = 0
    for symbol in symbols:
        df = load_history(symbol, start, end, data_dir=args.data_dir)
        if df.empty:
            fail += 1
        else:
            ok += 1

    print(f"成功数量: {ok}")
    print(f"失败数量: {fail}")
    print(f"CSV保存路径: {args.data_dir.resolve()}")
