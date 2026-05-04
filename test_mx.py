#!/usr/bin/env python3
from eastmoney_client import request_eastmoney_skill


if __name__ == "__main__":
    query = "查询平安银行000001最近5个交易日的收盘价"
    payload = request_eastmoney_skill(query)
    if payload is None:
        print("请求失败或无返回")
    else:
        print(payload)
