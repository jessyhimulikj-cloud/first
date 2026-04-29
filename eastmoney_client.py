#!/usr/bin/env python3
from __future__ import annotations

import os
from typing import Any

import pandas as pd
import requests


SKILL_API_URL = "https://api.eastmoney.com/skills/v1/query"


def request_eastmoney_skill(query: str) -> pd.DataFrame:
    api_key = os.getenv("EASTMONEY_APIKEY", "").strip()
    if not api_key:
        print("[eastmoney_client] 缺少 EASTMONEY_APIKEY，请先配置环境变量。")
        return pd.DataFrame()

    session = requests.Session()
    session.trust_env = False
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    payload: dict[str, Any] = {"query": query}

    try:
        resp = session.post(SKILL_API_URL, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
    except Exception as exc:
        print(f"[eastmoney_client] 请求失败: {exc}")
        return pd.DataFrame()

    try:
        data = resp.json()
    except Exception as exc:
        print(f"[eastmoney_client] 响应不是有效 JSON: {exc}")
        return pd.DataFrame()

    rows = ((data or {}).get("data") or {}).get("rows")
    if not isinstance(rows, list) or not rows:
        print(f"[eastmoney_client] 无数据返回，响应键: {list((data or {}).keys())}")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    if df.empty:
        print("[eastmoney_client] DataFrame 为空。")
        return df

    return df
