#!/usr/bin/env python3
from __future__ import annotations

import os
from typing import Any

import requests


SKILL_API_URL = os.getenv("MX_API_URL", "https://openai.maoxiang.ai/skills/query")


def request_eastmoney_skill(query: str) -> dict[str, Any] | None:
    api_key = os.getenv("MX_APIKEY", "").strip()
    if not api_key:
        print("[eastmoney_client] 缺少 MX_APIKEY，请先配置环境变量。")
        return None

    session = requests.Session()
    session.trust_env = False
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }

    print(f"[eastmoney_client] API URL: {SKILL_API_URL}")
    print(f"[eastmoney_client] headers include apikey: {'apikey' in headers}")
    print(f"[eastmoney_client] headers include Authorization: {'Authorization' in headers}")

    payload: dict[str, Any] = {"query": query}
    resp = session.post(SKILL_API_URL, headers=headers, json=payload, timeout=20)

    text = resp.text or ""
    if text.lstrip().startswith("<!DOCTYPE html>"):
        raise RuntimeError("请求到了网页，不是API接口，请检查endpoint")

    if resp.status_code >= 400:
        body = text[:300]
        print(f"[eastmoney_client] 请求失败 status={resp.status_code}, body={body}")
        return None

    try:
        return resp.json()
    except Exception:
        print(f"[eastmoney_client] 响应解析失败 status={resp.status_code}, body={text[:300]}")
        return None
