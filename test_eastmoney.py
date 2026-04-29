#!/usr/bin/env python3
from eastmoney_client import request_eastmoney_skill


if __name__ == "__main__":
    symbol = "000001"
    query = f"A股{symbol}历史日线，开始20260101，结束20260429，字段:日期 开盘 最高 最低 收盘 成交量 成交额 涨跌幅"
    df = request_eastmoney_skill(query)
    if df.empty:
        symbol = "600519"
        query = f"A股{symbol}历史日线，开始20260101，结束20260429，字段:日期 开盘 最高 最低 收盘 成交量 成交额 涨跌幅"
        df = request_eastmoney_skill(query)
    print(df.head(5))
