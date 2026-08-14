"""
wiki_universe.py — 위키피디아에서 S&P 500/400/600 구성종목 명단을 가져온다
================================================================
Finnhub는 S&P 500 지수 구성종목만 지원하고(그마저도 유료로 옮겨간 정황), S&P 400/600은
아예 지원하지 않는다. 대신 위키피디아의 공개 문서 표를 파싱해 무료로 유니버스 명단을 만든다.
API 키 불필요. 지수 구성종목은 자주 안 바뀌므로 주 1회(max_age_days=7)만 갱신한다 —
개별 종목의 시세·재무데이터(data_pipeline.py가 담당)는 이와 별개로 매일 갱신된다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

CACHE_DIR = Path(".cache")
CACHE_DIR.mkdir(exist_ok=True)
UNIVERSE_CACHE = CACHE_DIR / "universe.parquet"

INDEX_URLS = [
    "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
]

_HEADERS = {"User-Agent": "Mozilla/5.0 (screening-bot; contact: repo-owner)"}


def fetch_index_table(url: str, symbol_col_candidates: list[str] | None = None) -> pd.DataFrame:
    """위키피디아 구성종목 표를 파싱해 [ticker, name, sector] DataFrame으로 반환한다.
    표 헤더 열 이름은 문서마다 조금씩 다를 수 있어 후보 목록 중 첫 매치를 사용한다."""
    from bs4 import BeautifulSoup

    if symbol_col_candidates is None:
        symbol_col_candidates = ["Symbol", "Ticker symbol", "Ticker"]
    name_col_candidates = ["Security", "Company", "Name"]
    sector_col_candidates = ["GICS Sector", "GICSSector", "GICS Sub-Industry", "Sector"]

    r = requests.get(url, timeout=30, headers=_HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table", {"class": "wikitable"})
    if table is None:
        raise RuntimeError(f"위키피디아 페이지에서 constituents 표를 찾지 못했습니다: {url}")

    # Try to get headers from <thead>, but fall back to first row of <tbody> if no <thead>
    thead = table.find("thead")
    if thead is not None:
        headers = [th.get_text(strip=True) for th in thead.find_all("th")]
    else:
        tbody = table.find("tbody")
        if tbody is None:
            raise RuntimeError(f"위키피디아 페이지에서 <tbody>를 찾지 못했습니다: {url}")
        first_row = tbody.find("tr")
        if first_row is None:
            raise RuntimeError(f"위키피디아 테이블의 첫 번째 행을 찾지 못했습니다: {url}")
        headers = [th.get_text(strip=True) for th in first_row.find_all("th")]
        if not headers:
            # If first row doesn't have th, it might have td (data row, not header)
            raise RuntimeError(f"위키피디아 테이블의 헤더 행을 찾지 못했습니다: {url}")

    def pick(candidates: list[str]) -> int | None:
        for c in candidates:
            if c in headers:
                return headers.index(c)
        return None

    sym_idx = pick(symbol_col_candidates)
    name_idx = pick(name_col_candidates)
    sector_idx = pick(sector_col_candidates)
    if sym_idx is None:
        raise RuntimeError(f"티커 컬럼을 찾지 못했습니다 (헤더: {headers})")

    rows = []
    tbody = table.find("tbody")
    for tr in tbody.find_all("tr"):
        # Skip header rows (those with th cells)
        if tr.find("th"):
            continue
        cells = tr.find_all("td")
        if not cells or len(cells) <= sym_idx:
            continue
        ticker = cells[sym_idx].get_text(strip=True)
        name = cells[name_idx].get_text(strip=True) if name_idx is not None and len(cells) > name_idx else ""
        sector = cells[sector_idx].get_text(strip=True) if sector_idx is not None and len(cells) > sector_idx else ""
        if ticker:
            rows.append({"ticker": ticker, "name": name, "sector": sector})

    return pd.DataFrame(rows)


def get_universe(force: bool = False, max_age_days: int = 7) -> pd.DataFrame:
    """S&P 500+400+600 합산 유니버스를 반환한다. index=ticker, columns=[name, sector].
    캐시가 max_age_days 이내로 신선하면 재사용, 아니면(또는 force=True) 3개 위키피디아
    문서를 다시 파싱해 캐시를 갱신한다."""
    if not force and UNIVERSE_CACHE.exists():
        age_days = (datetime.now(timezone.utc).timestamp() - UNIVERSE_CACHE.stat().st_mtime) / 86400
        if age_days <= max_age_days:
            return pd.read_parquet(UNIVERSE_CACHE).set_index("ticker")

    frames = [fetch_index_table(url) for url in INDEX_URLS]
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset="ticker", keep="first")

    UNIVERSE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(UNIVERSE_CACHE, index=False)

    return combined.set_index("ticker")
