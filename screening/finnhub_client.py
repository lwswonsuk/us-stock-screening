"""
finnhub_client.py — Finnhub API 래퍼
================================================================
FMP를 대체하는 개별 종목 시세·재무데이터 소스. Finnhub 무료 티어는 하루 총량 상한이 아니라
분당 60건 속도 제한이므로, 호출 빈도만 조절하면 S&P 500+400+600 전체를 매일 무료로 처리할 수 있다.

이 모듈은 Finnhub 응답을 raw dict 그대로 반환한다 — FMP 때와 동일하게, 필드명 매핑은
data_pipeline.py에서 전담해 Finnhub가
필드명을 바꿔도 이 파일이 아니라 매핑 지점 하나만 고치면 되게 한다.

사전 준비: setx FINNHUB_API_KEY "..." (Windows) 또는 export FINNHUB_API_KEY=...

⚠️ 필드명 미검증: get_basic_financials()가 반환하는 'metric' 객체의 정확한 키 이름(ROE, 부채비율,
PER/PBR, 배당수익률/성향, 매출성장률에 해당하는 키)은 이 파일 작성 시점에 실시간 문서 접근이
막혀 있어 완전히 확정하지 못했다. data_pipeline.fetch_finance_one()을 구현하기 전에 실제
FINNHUB_API_KEY로 한 번 호출해 실제 필드명을 확인할 것.
"""

from __future__ import annotations

import os

import requests

BASE_URL = "https://finnhub.io/api/v1"
TIMEOUT = 30


def _api_key() -> str:
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        raise RuntimeError(
            "FINNHUB_API_KEY 환경변수가 없습니다. "
            "터미널에서 setx FINNHUB_API_KEY \"발급받은키\" 로 등록 후 새 터미널을 여세요."
        )
    return key


def get_quote(ticker: str) -> dict:
    """현재가/전일종가 등 raw dict. {c, h, l, o, pc, d, dp, t}."""
    key = _api_key()
    r = requests.get(f"{BASE_URL}/quote", params={"symbol": ticker, "token": key}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_basic_financials(ticker: str) -> dict:
    """재무비율 raw dict (metric 객체만 추출). 없으면 빈 dict."""
    key = _api_key()
    r = requests.get(
        f"{BASE_URL}/stock/metric",
        params={"symbol": ticker, "metric": "all", "token": key},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    payload = r.json()
    return payload.get("metric") or {}


def get_company_profile(ticker: str) -> dict:
    """회사 프로필 raw dict (섹터/업종/시총 등). {name, ticker, finnhubIndustry, marketCapitalization, ...}."""
    key = _api_key()
    r = requests.get(f"{BASE_URL}/stock/profile2", params={"symbol": ticker, "token": key}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()
