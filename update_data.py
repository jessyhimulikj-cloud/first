#!/usr/bin/env python3
from __future__ import annotations

import time

from eastmoney_data import load_history


fallback_symbols = [
    "000001", "000858", "002415", "300750", "300760", "600036", "600519", "601318", "603259", "688981",
    "000333", "002594", "300059", "600276", "601012", "601888", "603288", "605499", "688111", "000725",
]


if __name__ == "__main__":
    max_calls = 100
    ok = 0
    fail = 0
    calls = 0

    for symbol in fallback_symbols:
        if calls >= max_calls:
            break
        df = load_history(symbol, months=12)
        calls += 1
        if df.empty:
            fail += 1
        else:
            ok += 1
        time.sleep(1.5)

    print(f"成功数量: {ok}")
    print(f"失败数量: {fail}")
