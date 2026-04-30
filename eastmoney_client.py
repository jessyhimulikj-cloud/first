#!/usr/bin/env python3
from __future__ import annotations

import os
from typing import Any

import requests


SKILL_API_URL = "https://api.eastmoney.com/skills/v1/query"


def request_eastmoney_skill(query: str) -> dict[str, Any] | None:
    api_key = os.getenv("EASTMONEY_APIKEY", "").strip()
    if not api_key:
        print("[eastmoney_client] 缺少 EASTMONEY_APIKEY，请先配置环境变量。")
        return None

    session = requests.Session()
    session.trust_env = False
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    payload: dict[str, Any] = {"query": query}

    resp = session.post(SKILL_API_URL, headers=headers, json=payload, timeout=20)
    if resp.status_code >= 400:
        body = resp.text[:300]
        print(f"[eastmoney_client] 请求失败 status={resp.status_code}, body={body}")
        return None

    try:
        return resp.json()
    except Exception:
        print(f"[eastmoney_client] 响应解析失败 status={resp.status_code}, body={resp.text[:300]}")
        return None
