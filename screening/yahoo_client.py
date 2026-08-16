"""
yahoo_client.py — Yahoo Finance 비공식 차트 API로 과거 일별 종가를 가져온다
================================================================
Finnhub 무료 티어가 미국 주식 캔들(과거시세) 조회를 유료 전용으로 옮겨서
(2026-08-15 라이브 확인: /stock/candle 전종목 403 Forbidden), 과거 12개월
시세만 이 API로 대체한다. API 키 불필요. 비공식 엔드포인트라 예고 없이
바뀔 수 있음 — 실패 시 개별 종목만 건너뛰고 파이프라인은 계속 진행한다
(us_alpha.get_historical_prices_batch가 이 패턴을 담당).
"""

from __future__ import annotations

import pandas as pd
import requests

BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
TIMEOUT = 30
_HEADERS = {"User-Agent": "Mozilla/5.0 (screening-bot)"}


def _normalize_ticker(ticker: str) -> str:
    """위키피디아 형식(BRK.B)을 야후 형식(BRK-B)으로 변환."""
    return ticker.replace(".", "-")


def get_daily_prices(ticker: str, days: int = 380) -> pd.DataFrame:
    """최근 daily close를 오름차순(과거→최근)으로 정렬해 반환한다. columns=[date, close].
    데이터가 없거나 형식이 예상과 다르면 빈 DataFrame(같은 컬럼 스키마)을 반환한다."""
    symbol = _normalize_ticker(ticker)
    range_param = "2y" if days > 380 else "1y"
    r = requests.get(
        f"{BASE_URL}/{symbol}",
        params={"range": range_param, "interval": "1d"},
        headers=_HEADERS,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    payload = r.json()

    results = payload.get("chart", {}).get("result")
    if not results:
        return pd.DataFrame(columns=["date", "close"])

    result = results[0]
    timestamps = result.get("timestamp")
    quotes = result.get("indicators", {}).get("quote") or [{}]
    closes = quotes[0].get("close")
    if not timestamps or not closes:
        return pd.DataFrame(columns=["date", "close"])

    df = pd.DataFrame({
        "date": pd.to_datetime(timestamps, unit="s"),
        "close": closes,
    }).dropna(subset=["close"])
    return df.sort_values("date").reset_index(drop=True)
