import pandas as pd
from pathlib import Path

symbols = ["000001", "000002", "000063"]
current_date = "20260128"

for symbol in symbols:
    path = Path("data") / f"{symbol}.csv"
    print("\n====", symbol, "====")
    if not path.exists():
        print("csv missing:", path)
        continue

    df = pd.read_csv(path)
    if df.empty:
        print("csv empty")
        continue

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y%m%d")
    df = df.dropna(subset=["date"]).copy()
    df = df.sort_values("date")

    for c in ["close", "volume", "pct_chg"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["vol_ma5"] = df["volume"].rolling(5).mean()

    row = df[df["date"] == current_date]

    print("rows:", len(df))
    print("date range:", df["date"].iloc[0], "->", df["date"].iloc[-1])
    print("target row empty:", row.empty)

    if not row.empty:
        r = row.iloc[0]
        print("close:", r.get("close"))
        print("ma20:", r.get("ma20"))
        print("ma60:", r.get("ma60"))
        print("pct_chg:", r.get("pct_chg"))
        print("close > ma20:", r.get("close") > r.get("ma20"))
