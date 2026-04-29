#!/usr/bin/env python3
"""每日自动选股运行器。

功能：
1. 每天 15:10 自动运行
2. 调用 stock_picker.py（eastmoney 模式）
3. 输出 picked_stocks_YYYYMMDD.csv
4. 累计写入 history.csv
5. 当天已运行过则跳过
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="每日自动选股运行器")
    parser.add_argument("--time", default="15:10", help="每日运行时间，格式 HH:MM")
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    parser.add_argument("--history", type=Path, default=Path("history.csv"))
    parser.add_argument("--once", action="store_true", help="立即执行一次并退出（调试用）")
    return parser.parse_args()


def today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def build_output_file(output_dir: Path, date_str: str) -> Path:
    return output_dir / f"picked_stocks_{date_str}.csv"


def already_ran_today(history_file: Path, date_str: str, output_file: Path) -> bool:
    if output_file.exists():
        return True

    if not history_file.exists():
        return False

    try:
        with history_file.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("run_date") == date_str:
                    return True
    except Exception:
        return False

    return False


def run_picker(output_file: Path, top: int) -> None:
    cmd = [
        sys.executable,
        "stock_picker.py",
        "--source",
        "eastmoney",
        "--top",
        str(top),
        "--output",
        str(output_file),
    ]
    print("执行命令:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def read_picks(output_file: Path) -> List[Dict[str, str]]:
    if not output_file.exists():
        return []
    with output_file.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def append_history(history_file: Path, run_date: str, picks: List[Dict[str, str]]) -> None:
    history_file.parent.mkdir(parents=True, exist_ok=True)
    file_exists = history_file.exists()

    fields = [
        "run_date",
        "rank",
        "ts_code",
        "name",
        "close",
        "pct_chg",
        "total_score",
        "buy_suggestion",
    ]
    with history_file.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not file_exists:
            writer.writeheader()

        for idx, row in enumerate(picks, start=1):
            writer.writerow(
                {
                    "run_date": run_date,
                    "rank": idx,
                    "ts_code": row.get("ts_code", ""),
                    "name": row.get("name", ""),
                    "close": row.get("close", ""),
                    "pct_chg": row.get("pct_chg", ""),
                    "total_score": row.get("total_score", ""),
                    "buy_suggestion": "建议次日开盘价附近分批买入",
                }
            )


def print_recommendation(picks: List[Dict[str, str]]) -> None:
    if not picks:
        print("今日无推荐股票。")
        return

    print("\n=== 今日推荐股票 ===")
    for i, row in enumerate(picks, start=1):
        code = row.get("ts_code", "")
        name = row.get("name", "")
        score = row.get("total_score", "")
        close = row.get("close", "")
        print(f"#{i} {code} {name} | 分数={score} | 收盘价={close}")
        print("   买入建议：次日开盘价附近，分批买入，控制仓位。")


def next_run_time(hhmm: str) -> datetime:
    hh, mm = hhmm.split(":")
    target = datetime.now().replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if target <= datetime.now():
        target += timedelta(days=1)
    return target


def execute_once(args: argparse.Namespace) -> None:
    run_date = today_str()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_file = build_output_file(args.output_dir, run_date)

    if already_ran_today(args.history, run_date, output_file):
        print(f"[{run_date}] 今日已运行过，跳过。")
        return

    try:
        run_picker(output_file, args.top)
    except Exception as exc:
        print(f"选股执行失败: {exc}")
        return

    picks = read_picks(output_file)
    append_history(args.history, run_date, picks)
    print_recommendation(picks)
    print(f"\n结果文件: {output_file}")
    print(f"历史文件: {args.history}")


def main() -> None:
    args = parse_args()

    if args.once:
        execute_once(args)
        return

    print(f"已启动每日任务，执行时间: {args.time}")
    while True:
        try:
            nxt = next_run_time(args.time)
        except Exception:
            print("--time 格式错误，应为 HH:MM，例如 15:10")
            return

        wait_sec = max(1, int((nxt - datetime.now()).total_seconds()))
        print(f"下一次执行: {nxt.strftime('%Y-%m-%d %H:%M:%S')}，等待 {wait_sec} 秒")
        time.sleep(wait_sec)
        execute_once(args)


if __name__ == "__main__":
    main()
