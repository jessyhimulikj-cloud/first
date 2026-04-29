#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from eastmoney_client import request_eastmoney_skill


STD_COLS = ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]


def normalize_history_df(df: pd.DataFrame) -> pd.DataFrame:
    col_map = {
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
        "涨跌幅": "pct_chg",
    }
    out = df.rename(columns=col_map).copy()
    for c in STD_COLS:
        if c not in out.columns:
            out[c] = 0
    out["date"] = out["date"].astype(str).str.replace("-", "", regex=False)
    for c in ["open", "high", "low", "close", "volume", "amount", "pct_chg"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)
    out = out[STD_COLS]
    out = out[out["date"].str.len() == 8]
    out = out.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return out


def update_symbol(symbol: str, start: str, end: str, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / f"{symbol}.csv"

    local_df = pd.DataFrame(columns=STD_COLS)
    if csv_path.exists():
        try:
            local_df = pd.read_csv(csv_path)
            local_df = normalize_history_df(local_df)
        except Exception as exc:
            print(f"[update_data] 读取本地CSV失败 {symbol}: {exc}")

    query_start = start
    if not local_df.empty:
        max_date = str(local_df["date"].max())
        if max_date >= end:
            print(f"[update_data] {symbol} 已是最新，无需更新。")
            return
        query_start = max_date

    query = f"A股{symbol}历史日线，开始{query_start}，结束{end}，字段:日期 开盘 最高 最低 收盘 成交量 成交额 涨跌幅"
    remote_df = request_eastmoney_skill(query)
    if remote_df.empty:
        print(f"[update_data] {symbol} 无法获取远端数据。")
        return

    remote_df = normalize_history_df(remote_df)
    merged = pd.concat([local_df, remote_df], ignore_index=True)
    merged = merged.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    merged = merged[STD_COLS]
    merged.to_csv(csv_path, index=False)
    print(f"[update_data] {symbol} 已更新: {csv_path}, 共{len(merged)}行")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", nargs="+", required=True)
    p.add_argument("--start", required=True, help="YYYYMMDD")
    p.add_argument("--end", required=True, help="YYYYMMDD")
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    for s in args.symbols:
        update_symbol(s, args.start, args.end, args.data_dir)
