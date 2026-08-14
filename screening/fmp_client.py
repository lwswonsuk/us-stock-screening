"""
fmp_client.py — Financial Modeling Prep API 래퍼
================================================================
KOSPI판의 KRX(시세)+DART(재무) 조합을 FMP API 하나로 대체한다. 이 모듈은 원본 JSON
필드명을 최소한으로만 가공해 반환하고(quote/historical만 pandas화), 나머지 재무비율은
raw dict 그대로 반환한다 — 컬럼 매핑(FMP 필드명 → 내부 컬럼명)은 data_pipeline.py에서
담당해, FMP가 필드명을 바꿔도 이 파일이 아니라 매핑 지점 하나만 고치면 되게 한다.

사전 준비: setx FMP_API_KEY "..." (Windows) 또는 export FMP_API_KEY=... (macOS/Linux)
"""

from __future__ import annotations

import os

import pandas as pd
import requests

BASE_URL = "https://financialmodelingprep.com/api/v3"
TIMEOUT = 30


def _api_key() -> str:
    key = os.environ.get("FMP_API_KEY")
    if not key:
        raise RuntimeError(
            "FMP_API_KEY 환경변수가 없습니다. "
            "터미널에서 setx FMP_API_KEY \"발급받은키\" 로 등록 후 새 터미널을 여세요."
        )
    return key


def get_index_universe() -> pd.DataFrame:
    """S&P 500 + S&P 400 + S&P 600 구성종목을 합쳐 중복 제거한 유니버스를 반환한다.
    index=ticker, columns=[name, sector]."""
    key = _api_key()
    frames = []
    for endpoint in ("sp500_constituent", "sp400_constituent", "sp600_constituent"):
        r = requests.get(f"{BASE_URL}/{endpoint}", params={"apikey": key}, timeout=TIMEOUT)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            continue
        df = pd.DataFrame(rows)
        frames.append(df[["symbol", "name", "sector"]] if "sector" in df.columns else df[["symbol", "name"]])

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset="symbol", keep="first")
    combined = combined.rename(columns={"symbol": "ticker"})
    return combined.set_index("ticker")


def get_quotes(tickers: list[str]) -> pd.DataFrame:
    """티커 리스트의 현재가/시가총액/평균거래량을 한 번에 조회한다.
    index=ticker, columns=[price, market_cap, avg_volume]."""
    key = _api_key()
    batch = ",".join(tickers)
    r = requests.get(f"{BASE_URL}/quote/{batch}", params={"apikey": key}, timeout=TIMEOUT)
    r.raise_for_status()
    rows = r.json()
    df = pd.DataFrame(rows)
    df = df.rename(columns={"symbol": "ticker", "marketCap": "market_cap", "avgVolume": "avg_volume"})
    return df.set_index("ticker")[["price", "market_cap", "avg_volume"]]


def get_ratios_ttm(ticker: str) -> dict:
    """단일 종목의 TTM 재무비율 raw dict. 응답이 비어있으면 빈 dict."""
    key = _api_key()
    r = requests.get(f"{BASE_URL}/ratios-ttm/{ticker}", params={"apikey": key}, timeout=TIMEOUT)
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else {}


def get_key_metrics_ttm(ticker: str) -> dict:
    """단일 종목의 TTM 핵심 지표 raw dict."""
    key = _api_key()
    r = requests.get(f"{BASE_URL}/key-metrics-ttm/{ticker}", params={"apikey": key}, timeout=TIMEOUT)
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else {}


def get_income_statement_growth(ticker: str, period: str = "quarter", limit: int = 4) -> list[dict]:
    """최근 분기(또는 연간) 손익 성장률 raw 리스트 (최신순)."""
    key = _api_key()
    r = requests.get(
        f"{BASE_URL}/income-statement-growth/{ticker}",
        params={"period": period, "limit": limit, "apikey": key},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def get_historical_prices(ticker: str, days: int = 380) -> pd.DataFrame:
    """최근 daily OHLC 중 close만 오름차순(과거→최근)으로 정렬해 반환한다.
    columns=[date, close]."""
    key = _api_key()
    r = requests.get(
        f"{BASE_URL}/historical-price-full/{ticker}",
        params={"timeseries": days, "apikey": key},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    payload = r.json()
    rows = payload.get("historical", [])
    df = pd.DataFrame(rows)[["date", "close"]]
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def get_dividends(ticker: str) -> list[dict]:
    """배당 이력 raw 리스트."""
    key = _api_key()
    r = requests.get(
        f"{BASE_URL}/historical-price-full/stock_dividend/{ticker}",
        params={"apikey": key},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    payload = r.json()
    return payload.get("historical", [])
