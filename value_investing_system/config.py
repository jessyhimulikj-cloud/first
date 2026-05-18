"""Central configuration for the value investing system.

Secrets are loaded from .env and are never hard-coded. All scoring constants live
here so future iterations can tune the model without editing scoring modules.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # Allows --help and static checks before dependencies are installed.
    def load_dotenv() -> None:
        return None

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
DAILY_DIR = DATA_DIR / "daily"
FINANCIAL_DIR = DATA_DIR / "financial"
VALUATION_DIR = DATA_DIR / "valuation"
OUTPUT_DIR = BASE_DIR / "output"

for directory in [DATA_DIR, CACHE_DIR, DAILY_DIR, FINANCIAL_DIR, VALUATION_DIR, OUTPUT_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

load_dotenv()

TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

INDUSTRY_SCORE = {
    "半导体": 90,
    "芯片": 90,
    "人工智能": 90,
    "算力": 88,
    "机器人": 88,
    "创新药": 85,
    "高端制造": 82,
    "新能源": 75,
    "消费电子": 72,
    "军工": 70,
    "白酒": 60,
    "地产": 20,
    "房地产": 20,
    "传统煤炭": 35,
    "煤炭": 35,
}

SCORE_WEIGHTS = {
    "industry_score": 0.25,
    "position_score": 0.20,
    "distress_score": 0.20,
    "survival_score": 0.15,
    "reversal_score": 0.15,
    "valuation_score": 0.05,
}

AI_WEIGHT = 0.30
QUANT_WEIGHT = 0.70

DEFAULT_TOP_N = 30
DEFAULT_MIN_SCORE = 65.0
DEFAULT_CACHE_DAYS = 7
MIN_LISTING_YEARS = 2
TRADING_DAYS_3Y = 750
TRADING_DAYS_1Y = 250
SURVIVAL_MIN_SCORE = 50.0
DISTRESS_PRIORITY_SCORE = 60.0
