# Finnhub + Wikipedia Data Source Swap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the FMP-based data source (currently merged in `master`) with Finnhub (per-ticker quotes + fundamentals, free tier, no hard daily cap) + Wikipedia (index constituent lists, free, no API key), per the addendum in `docs/superpowers/specs/2026-08-14-us-stock-screening-design.md` §10. The algorithm (4-factor scoring, hard filters, weights) and the web UI/features do not change — this is a data-layer swap only.

**Architecture:** `screening/finnhub_client.py` replaces `screening/fmp_client.py` (thin REST wrapper, raw-dict passthrough for fundamentals). `screening/wiki_universe.py` is new — scrapes S&P 500/400/600 constituent tables from Wikipedia, cached weekly (separate cache file from the daily finance cache). `screening/data_pipeline.py` and `screening/us_alpha.py` are modified to consume the new client/universe source instead of FMP. `web/app/api/prices/route.ts` is rewritten to call Finnhub instead of FMP. The GitHub Actions workflow's secret changes from `FMP_API_KEY` to `FINNHUB_API_KEY`.

**Tech Stack:** Python 3.13 (`requests`, `pandas`, `beautifulsoup4` — new dependency for Wikipedia table parsing), Finnhub REST API (`https://finnhub.io/api/v1`), Next.js (unchanged elsewhere).

## Global Constraints

- Universe stays S&P 500 + S&P 400 + S&P 600 (~1,500 tickers) — only the *source* of the constituent list changes, not the scope.
- Individual-ticker data (quote, fundamentals, historical prices) refreshes **daily**, same as before.
- The constituent list (which tickers are in the index) refreshes **weekly** — a separate, less-frequent cache from the daily finance cache.
- Algorithm code (`screening/us_alpha.py`'s `Config`, `score_quality/value/gap/payout`, `apply_hard_filters`, `composite`) is UNCHANGED by this plan — only the data-assembly functions (`load_real`, `get_historical_prices_batch`) and `data_pipeline.py` change.
- Column names produced by `data_pipeline.fetch_finance_one()` and consumed by `us_alpha.py` stay the same as today (`roe_3y_avg`, `debt_ratio`, `op_margin`, `per`, `pbr`, `div_yield`, `payout_ratio`, `op_yoy`, `rev_yoy`, etc.) — only the FMP→internal mapping inside `fetch_finance_one` changes to Finnhub→internal.
- `FINANCE_CACHE = .cache/finance.parquet` (daily, per-ticker fundamentals) stays; add a new `UNIVERSE_CACHE = .cache/universe.parquet` (weekly, constituent list) with its own freshness check.
- ⚠️ Finnhub's exact `company_basic_financials` response field names are NOT fully verified against a live API call (network access to Finnhub's live docs was unavailable during planning). Endpoints and general field-name patterns below are best-effort from public documentation/training knowledge. Every task touching field-name mapping includes an explicit live-verification step the implementer must perform once a real `FINNHUB_API_KEY` is available — treat the field names in this plan as a starting hypothesis, not gospel, and adjust `finnhub_client.py`/`data_pipeline.py` to match what the live API actually returns.
- No changes to `screening/quotes.py`, `screening/profile_cache.py`, `screening/stock_profile.py`, `web/app/AdminGate.tsx`, `web/app/api/admin-login/route.ts`, `web/app/api/update-finance/route.ts`, `web/app/api/filtered/route.ts`, `web/app/FilteredDownloadButton.tsx`, `web/app/AlgorithmInfo.tsx`'s factor-model text, or any shadcn/ui component.

---

### Task 1: Finnhub API client

**Files:**
- Create: `screening/finnhub_client.py`
- Test: `screening/tests/test_finnhub_client.py`
- Modify: `screening/requirements.txt` (add `beautifulsoup4`, needed by Task 2, not this task — add it here since it's the natural place, one dependency-list edit)

**Interfaces:**
- Consumes: `FINNHUB_API_KEY` environment variable.
- Produces (consumed by Task 3's `data_pipeline.py`):
  - `get_quote(ticker: str) -> dict` — raw Finnhub `/quote` response (`{c, h, l, o, pc, d, dp, t}`).
  - `get_basic_financials(ticker: str) -> dict` — raw `metric` object from `/stock/metric?metric=all` (unparsed — column mapping happens in `data_pipeline.py`, matching the isolation pattern used for FMP).
  - `get_company_profile(ticker: str) -> dict` — raw `/stock/profile2` response (`{name, ticker, finnhubIndustry, marketCapitalization, ...}`).
  - `get_candles(ticker: str, days: int = 380) -> pandas.DataFrame` — daily close prices from `/stock/candle?resolution=D`, columns `[date, close]`, sorted oldest-to-newest (same shape as the old `fmp_client.get_historical_prices` it replaces).

- [ ] **Step 1: Write the failing tests**

```python
# screening/tests/test_finnhub_client.py
import pandas as pd
import pytest

import finnhub_client


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_get_quote_returns_raw_dict(monkeypatch):
    payload = {"c": 227.5, "h": 230.0, "l": 225.0, "o": 226.0, "pc": 225.8, "d": 1.7, "dp": 0.75, "t": 1755100800}

    def fake_get(url, params=None, timeout=None):
        assert url.endswith("/quote")
        assert params["symbol"] == "AAPL"
        assert params["token"] == "test-key"
        return _FakeResponse(payload)

    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    monkeypatch.setattr(finnhub_client.requests, "get", fake_get)

    result = finnhub_client.get_quote("AAPL")
    assert result["c"] == 227.5


def test_get_quote_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FINNHUB_API_KEY"):
        finnhub_client.get_quote("AAPL")


def test_get_basic_financials_returns_metric_object(monkeypatch):
    payload = {"metric": {"roeTTM": 1.5, "peTTM": 28.0}, "series": {}, "metricType": "all"}

    def fake_get(url, params=None, timeout=None):
        assert url.endswith("/stock/metric")
        assert params["symbol"] == "AAPL"
        assert params["metric"] == "all"
        return _FakeResponse(payload)

    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    monkeypatch.setattr(finnhub_client.requests, "get", fake_get)

    result = finnhub_client.get_basic_financials("AAPL")
    assert result == {"roeTTM": 1.5, "peTTM": 28.0}


def test_get_basic_financials_returns_empty_dict_when_metric_missing(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse({"metric": {}, "series": {}, "metricType": "all"})

    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    monkeypatch.setattr(finnhub_client.requests, "get", fake_get)

    assert finnhub_client.get_basic_financials("ZZZZ") == {}


def test_get_company_profile_returns_raw_dict(monkeypatch):
    payload = {"name": "Apple Inc", "ticker": "AAPL", "finnhubIndustry": "Technology", "marketCapitalization": 3500000.0}

    def fake_get(url, params=None, timeout=None):
        assert url.endswith("/stock/profile2")
        return _FakeResponse(payload)

    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    monkeypatch.setattr(finnhub_client.requests, "get", fake_get)

    result = finnhub_client.get_company_profile("AAPL")
    assert result["finnhubIndustry"] == "Technology"


def test_get_candles_returns_dataframe_sorted_ascending(monkeypatch):
    payload = {
        "s": "ok",
        "t": [1755000000, 1755086400],
        "c": [228.0, 230.0],
    }

    def fake_get(url, params=None, timeout=None):
        assert url.endswith("/stock/candle")
        assert params["resolution"] == "D"
        return _FakeResponse(payload)

    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    monkeypatch.setattr(finnhub_client.requests, "get", fake_get)

    df = finnhub_client.get_candles("AAPL", days=2)
    assert list(df["close"]) == [228.0, 230.0]
    assert list(df.columns) == ["date", "close"]


def test_get_candles_returns_empty_dataframe_when_no_data(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse({"s": "no_data"})

    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    monkeypatch.setattr(finnhub_client.requests, "get", fake_get)

    df = finnhub_client.get_candles("ZZZZ")
    assert df.empty
    assert list(df.columns) == ["date", "close"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `screening/`): `python -m pytest tests/test_finnhub_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'finnhub_client'`

- [ ] **Step 3: Implement `screening/finnhub_client.py`**

```python
"""
finnhub_client.py — Finnhub API 래퍼
================================================================
FMP를 대체하는 개별 종목 시세·재무데이터 소스. Finnhub 무료 티어는 하루 총량 상한이 아니라
분당 60건 속도 제한이므로, 호출 빈도만 조절하면 S&P 500+400+600 전체를 매일 무료로 처리할 수 있다.

이 모듈은 quote/candle만 최소 가공(pandas화)하고, 나머지 재무데이터(company_basic_financials)는
raw dict 그대로 반환한다 — FMP 때와 동일하게, 필드명 매핑은 data_pipeline.py에서 전담해 Finnhub가
필드명을 바꿔도 이 파일이 아니라 매핑 지점 하나만 고치면 되게 한다.

사전 준비: setx FINNHUB_API_KEY "..." (Windows) 또는 export FINNHUB_API_KEY=...

⚠️ 필드명 미검증: get_basic_financials()가 반환하는 'metric' 객체의 정확한 키 이름(ROE, 부채비율,
PER/PBR, 배당수익률/성향, 매출성장률에 해당하는 키)은 이 파일 작성 시점에 실시간 문서 접근이
막혀 있어 완전히 확정하지 못했다. data_pipeline.fetch_finance_one()을 구현하기 전에 실제
FINNHUB_API_KEY로 한 번 호출해 실제 필드명을 확인할 것.
"""

from __future__ import annotations

import os

import pandas as pd
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


def get_candles(ticker: str, days: int = 380) -> pd.DataFrame:
    """최근 daily close를 오름차순(과거→최근)으로 정렬해 반환한다. columns=[date, close].
    데이터가 없으면(s != "ok") 빈 DataFrame(같은 컬럼 스키마)을 반환한다."""
    import time as _time

    key = _api_key()
    now = int(_time.time())
    frm = now - days * 86400
    r = requests.get(
        f"{BASE_URL}/stock/candle",
        params={"symbol": ticker, "resolution": "D", "from": frm, "to": now, "token": key},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("s") != "ok" or not payload.get("t"):
        return pd.DataFrame(columns=["date", "close"])
    df = pd.DataFrame({
        "date": pd.to_datetime(payload["t"], unit="s"),
        "close": payload["c"],
    })
    return df.sort_values("date").reset_index(drop=True)
```

- [ ] **Step 4: Add `beautifulsoup4` to `screening/requirements.txt`**

```
pandas
numpy
requests
pyarrow
pytest
anthropic
beautifulsoup4
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_finnhub_client.py -v`
Expected: all pass

- [ ] **Step 6: Live smoke check (manual, not automated)**

With a real `FINNHUB_API_KEY` set:
```bash
python -c "import finnhub_client; print(finnhub_client.get_basic_financials('AAPL'))"
```
Read the printed dict's keys directly. Note down the actual field names for: ROE, debt-to-equity ratio,
operating margin, P/E, P/B, dividend yield, payout ratio, revenue growth (YoY), 52-week high/low or
52-week price return. **Task 3 depends on these exact names** — write them down now so Task 3's
implementer (a fresh subagent with no memory of this step) has them. If you cannot run this (no API key
yet), clearly say so in your report and note that Task 3 must perform this same live check before writing
the field-mapping code.

- [ ] **Step 7: Commit**

```bash
git add screening/finnhub_client.py screening/tests/test_finnhub_client.py screening/requirements.txt
git commit -m "feat: add Finnhub API client for per-ticker quotes and fundamentals"
```

---

### Task 2: Wikipedia index-constituent scraper

**Files:**
- Create: `screening/wiki_universe.py`
- Test: `screening/tests/test_wiki_universe.py`

**Interfaces:**
- Produces: `UNIVERSE_CACHE: Path` (`.cache/universe.parquet`), `fetch_index_table(url: str, symbol_col_candidates: list[str] = ["Symbol", "Ticker symbol"]) -> pandas.DataFrame` (parses one Wikipedia constituent table into a DataFrame with at least a `ticker` column), `get_universe(force: bool = False, max_age_days: int = 7) -> pandas.DataFrame` (returns the combined, deduplicated S&P 500+400+600 ticker list; reads from `UNIVERSE_CACHE` if fresh, otherwise re-scrapes all three Wikipedia pages and re-caches). Consumed by Task 3's `data_pipeline.py` in place of `fmp_client.get_index_universe`.
- Wikipedia URLs to scrape:
  - S&P 500: `https://en.wikipedia.org/wiki/List_of_S%26P_500_companies`
  - S&P 400 (MidCap): `https://en.wikipedia.org/wiki/List_of_S%26P_400_companies`
  - S&P 600 (SmallCap): `https://en.wikipedia.org/wiki/List_of_S%26P_600_companies`

- [ ] **Step 1: Write the failing tests**

```python
# screening/tests/test_wiki_universe.py
import pandas as pd

import wiki_universe


_FAKE_HTML = """
<html><body>
<table class="wikitable sortable" id="constituents">
<thead><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th></tr></thead>
<tbody>
<tr><td>AAPL</td><td>Apple Inc.</td><td>Information Technology</td></tr>
<tr><td>MSFT</td><td>Microsoft Corp.</td><td>Information Technology</td></tr>
<tr><td>BRK.B</td><td>Berkshire Hathaway</td><td>Financials</td></tr>
</tbody>
</table>
</body></html>
"""


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def test_fetch_index_table_parses_wikitable(monkeypatch):
    def fake_get(url, timeout=None, headers=None):
        return _FakeResponse(_FAKE_HTML)

    monkeypatch.setattr(wiki_universe.requests, "get", fake_get)

    df = wiki_universe.fetch_index_table("https://en.wikipedia.org/wiki/fake")

    assert list(df["ticker"]) == ["AAPL", "MSFT", "BRK.B"]
    assert "name" in df.columns
    assert df.loc[df["ticker"] == "AAPL", "name"].iloc[0] == "Apple Inc."


def test_get_universe_combines_and_dedupes(monkeypatch, tmp_path):
    def fake_fetch(url, symbol_col_candidates=None):
        if "500" in url:
            return pd.DataFrame({"ticker": ["AAPL", "MSFT"], "name": ["Apple Inc.", "Microsoft Corp."], "sector": ["Technology", "Technology"]})
        if "400" in url:
            return pd.DataFrame({"ticker": ["AAPL", "ZZZ"], "name": ["Apple Inc.", "Zzz Corp"], "sector": ["Technology", "Industrials"]})
        return pd.DataFrame({"ticker": ["WWW"], "name": ["Www Corp"], "sector": ["Energy"]})

    monkeypatch.setattr(wiki_universe, "fetch_index_table", fake_fetch)
    monkeypatch.setattr(wiki_universe, "UNIVERSE_CACHE", tmp_path / "universe.parquet")

    df = wiki_universe.get_universe()

    assert set(df.index) == {"AAPL", "MSFT", "ZZZ", "WWW"}
    assert df.loc["AAPL", "name"] == "Apple Inc."


def test_get_universe_uses_cache_when_fresh(monkeypatch, tmp_path):
    cache_path = tmp_path / "universe.parquet"
    cached = pd.DataFrame({"ticker": ["CACHED"], "name": ["Cached Corp"], "sector": ["Technology"]})
    cached.to_parquet(cache_path, index=False)

    def fail_fetch(url, symbol_col_candidates=None):
        raise AssertionError("캐시가 신선한데도 위키피디아를 다시 조회함")

    monkeypatch.setattr(wiki_universe, "fetch_index_table", fail_fetch)
    monkeypatch.setattr(wiki_universe, "UNIVERSE_CACHE", cache_path)

    df = wiki_universe.get_universe(max_age_days=7)

    assert list(df.index) == ["CACHED"]


def test_get_universe_force_refresh_ignores_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "universe.parquet"
    cached = pd.DataFrame({"ticker": ["OLD"], "name": ["Old Corp"], "sector": ["Technology"]})
    cached.to_parquet(cache_path, index=False)

    def fake_fetch(url, symbol_col_candidates=None):
        return pd.DataFrame({"ticker": ["NEW"], "name": ["New Corp"], "sector": ["Technology"]})

    monkeypatch.setattr(wiki_universe, "fetch_index_table", fake_fetch)
    monkeypatch.setattr(wiki_universe, "UNIVERSE_CACHE", cache_path)

    df = wiki_universe.get_universe(force=True)

    assert list(df.index) == ["NEW"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_wiki_universe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki_universe'`

- [ ] **Step 3: Implement `screening/wiki_universe.py`**

```python
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
    sector_col_candidates = ["GICS Sector", "GICS Sub-Industry", "Sector"]

    r = requests.get(url, timeout=30, headers=_HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table", {"class": "wikitable"})
    if table is None:
        raise RuntimeError(f"위키피디아 페이지에서 constituents 표를 찾지 못했습니다: {url}")

    headers = [th.get_text(strip=True) for th in table.find("thead").find_all("th")]

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
    for tr in table.find("tbody").find_all("tr"):
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_wiki_universe.py -v`
Expected: all pass

- [ ] **Step 5: Live smoke check (manual, not automated)**

```bash
python -c "import wiki_universe; df = wiki_universe.get_universe(force=True); print(len(df)); print(df.head())"
```
Confirm it fetches ~1,400-1,600 rows (S&P 500+400+600 combined, minus overlaps) without error. Note: real
Wikipedia table headers may differ slightly from the test fixture — if this fails, inspect the actual page
HTML and adjust `symbol_col_candidates`/`name_col_candidates`/`sector_col_candidates` in
`fetch_index_table`. Report what you found.

- [ ] **Step 6: Commit**

```bash
git add screening/wiki_universe.py screening/tests/test_wiki_universe.py
git commit -m "feat: add Wikipedia-based S&P 500+400+600 constituent list scraper"
```

---

### Task 3: Rewrite `data_pipeline.py` for Finnhub + Wikipedia

**Files:**
- Modify: `screening/data_pipeline.py` (full rewrite of the FMP-specific parts; keep `compute_return_and_drawdown` unchanged — it's data-source-agnostic)
- Modify: `screening/tests/test_data_pipeline.py`

**Interfaces:**
- Consumes: `finnhub_client.get_basic_financials`, `finnhub_client.get_quote`, `finnhub_client.get_company_profile` (Task 1); `wiki_universe.get_universe` (Task 2).
- Produces (unchanged from before, so `us_alpha.py` needs no changes beyond Task 4's price-history swap): `FINANCE_CACHE: Path`, `fetch_finance_one(ticker: str) -> dict` (same output schema as before: `ticker, roe_3y_avg, roe_3y_std, debt_ratio, op_margin, op_ttm, op_yoy, rev_yoy, rev_cagr_3y, years_no_rev_decline, net_income_ttm, revenue_ttm, total_equity, cash_dividend_total, payout_ratio, per, pbr, div_yield, fcf_yield, net_cash_to_mktcap, treasury_ratio`), `build_finance_cache(force: bool = False, sleep_sec: float = 1.1) -> DataFrame`, `get_full_universe() -> DataFrame` (index `ticker`, columns `name, sector, price, market_cap, avg_volume`).
- **Note the `sleep_sec` default change from `0.2` (FMP) to `1.1`**: Finnhub free tier is 60 calls/min = 1 call/sec; `fetch_finance_one` makes 3 calls per ticker (quote, basic_financials, profile), so pacing at ~1.1s between *tickers* (not between the 3 calls within one ticker) keeps total throughput near but under the 60/min ceiling with margin. Do the 3 per-ticker calls back-to-back, then sleep before the next ticker.

**⚠️ Live-verification required before Step 3:** Read Task 1's report (or run the live check yourself if Task 1's implementer could not) to get Finnhub's actual `company_basic_financials` field names. The code below uses placeholder/hypothesized field names (`roeTTM`, `totalDebt/totalEquityAnnual` or similar, `operatingMarginTTM`, `peTTM`, `pbAnnual`, `dividendYieldIndicatedAnnual`, `payoutRatioTTM`, `revenueGrowthTTMYoy`) — **you must confirm these against a real API response and correct them if wrong** before finalizing this task. If a needed metric genuinely isn't available from Finnhub's free `metric=all` response, leave it `np.nan` (same graceful-degradation pattern the FMP version used) rather than guessing.

- [ ] **Step 1: Write the failing test**

```python
# screening/tests/test_data_pipeline.py (replace FMP-specific test with Finnhub-mocked version;
# keep test_compute_return_and_drawdown from before unchanged)
import numpy as np
import pandas as pd

from data_pipeline import compute_return_and_drawdown, fetch_finance_one


def test_compute_return_and_drawdown_from_price_series():
    dates = pd.date_range("2025-08-01", periods=260, freq="B")
    closes = np.linspace(100, 130, len(dates))
    closes[-20:] = closes[-20:] * 0.80
    df = pd.DataFrame({"date": dates, "close": closes})

    ret_3m, ret_12m, drawdown_52w = compute_return_and_drawdown(df)

    assert ret_3m < 0
    assert ret_12m > -0.5
    assert drawdown_52w > 0


def test_fetch_finance_one_computes_op_margin_and_debt_ratio(monkeypatch):
    import finnhub_client

    monkeypatch.setattr(
        finnhub_client, "get_basic_financials",
        lambda ticker: {
            "roeTTM": 0.15,
            "totalDebt/totalEquityAnnual": 0.8,
            "operatingMarginTTM": 0.22,
            "peTTM": 18.0,
            "pbAnnual": 6.0,
            "dividendYieldIndicatedAnnual": 0.5,
            "payoutRatioTTM": 0.15,
            "revenueGrowthTTMYoy": 0.08,
        },
    )
    monkeypatch.setattr(finnhub_client, "get_quote", lambda ticker: {"c": 230.0, "pc": 225.0})
    monkeypatch.setattr(finnhub_client, "get_company_profile", lambda ticker: {"finnhubIndustry": "Technology"})

    row = fetch_finance_one("AAPL")

    assert row["ticker"] == "AAPL"
    assert row["roe_3y_avg"] == 15.0
    assert row["debt_ratio"] == 80.0
    assert row["op_margin"] == 22.0
    assert row["per"] == 18.0
    assert row["pbr"] == 6.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_data_pipeline.py -v`
Expected: FAIL (old test referenced `fmp_client`, which no longer has the mocked functions used, or the new assertions don't match old behavior)

- [ ] **Step 3: Rewrite `screening/data_pipeline.py`**

```python
"""
data_pipeline.py — 미국 주식 재무데이터 캐싱 레이어 (Finnhub + Wikipedia 기반)
================================================================
Finnhub API로 개별 종목 시세·재무비율을 매일 받아 로컬 parquet에 캐싱하고,
위키피디아(wiki_universe.py)에서 받은 유니버스(S&P 500+400+600)와 결합한다.

사용법:
    python data_pipeline.py --build          # 캐시 새로 만들기 (최초 1회, 시간 걸림)
    python data_pipeline.py --build --force  # 캐시 무시하고 전부 새로 받기
    python data_pipeline.py --status         # 캐시 현황 확인

캐시 파일:
    .cache/finance.parquet   — 종목별 재무비율 (매일 갱신)
    .cache/universe.parquet  — 지수 구성종목 명단 (주 1회 갱신, wiki_universe.py가 관리)
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

import finnhub_client
import wiki_universe

CACHE_DIR = Path(".cache")
CACHE_DIR.mkdir(exist_ok=True)
FINANCE_CACHE = CACHE_DIR / "finance.parquet"


def compute_return_and_drawdown(price_df: pd.DataFrame) -> tuple[float, float, float]:
    """price_df: columns=[date, close], 오름차순(과거→최근) 정렬됨.
    반환: (3개월 수익률, 12개월 수익률, 52주 고점 대비 낙폭[양수=고점보다 낮음])."""
    closes = price_df["close"].to_numpy()
    if len(closes) < 2:
        return (np.nan, np.nan, np.nan)

    last = closes[-1]
    idx_3m = max(0, len(closes) - 1 - 63)
    idx_12m = 0
    ret_3m = last / closes[idx_3m] - 1.0
    ret_12m = last / closes[idx_12m] - 1.0

    peak_52w = closes.max()
    drawdown_52w = (peak_52w - last) / peak_52w if peak_52w > 0 else np.nan

    return (float(ret_3m), float(ret_12m), float(drawdown_52w))


def fetch_finance_one(ticker: str) -> dict:
    """Finnhub 여러 엔드포인트를 조합해 스코어링에 필요한 한 종목의 재무 행을 만든다.
    ⚠️ Finnhub 필드명(roeTTM 등)은 Task 1 Step 6의 라이브 확인 결과에 맞춰 아래 매핑을
    조정할 것 — 이 함수가 Finnhub 원본 필드명과 내부 컬럼명 사이의 유일한 변환 지점이다."""
    metric = finnhub_client.get_basic_financials(ticker)
    quote = finnhub_client.get_quote(ticker)

    def g(key):
        v = metric.get(key)
        return np.nan if v is None else v

    roe = g("roeTTM")
    debt_equity = g("totalDebt/totalEquityAnnual")
    op_margin = g("operatingMarginTTM")
    per = g("peTTM")
    pbr = g("pbAnnual")
    div_yield = g("dividendYieldIndicatedAnnual")
    payout_ratio = g("payoutRatioTTM")
    rev_yoy = g("revenueGrowthTTMYoy")

    price = quote.get("c")
    prev_close = quote.get("pc")
    op_yoy = np.nan  # Finnhub의 무료 'metric=all'은 영업이익 YoY를 직접 주지 않음 — 매출성장률로 근사
    if not np.isnan(rev_yoy):
        op_yoy = rev_yoy  # 근사치: 매출성장률을 영업이익 모멘텀 프록시로 사용 (게이트 판정용)

    return {
        "ticker": ticker,
        "roe_3y_avg": np.nan if np.isnan(roe) else roe * 100,
        "roe_3y_std": np.nan,
        "debt_ratio": np.nan if np.isnan(debt_equity) else debt_equity * 100,
        "op_margin": np.nan if np.isnan(op_margin) else op_margin * 100,
        "op_ttm": op_margin,   # 부호만 사용하는 흑자/적자 판별용 프록시 (KOSPI판 이식 시 동일 패턴)
        "op_yoy": op_yoy,
        "rev_yoy": rev_yoy,
        "rev_cagr_3y": np.nan,
        "years_no_rev_decline": 0,
        "net_income_ttm": np.nan,
        "revenue_ttm": np.nan,
        "total_equity": np.nan,
        "cash_dividend_total": np.nan,
        "payout_ratio": np.nan if np.isnan(payout_ratio) else max(payout_ratio, 0.0),
        "per": per,
        "pbr": pbr,
        "div_yield": div_yield,
        "fcf_yield": np.nan,
        "net_cash_to_mktcap": np.nan,
        "treasury_ratio": np.nan,
    }


def build_finance_cache(force: bool = False, sleep_sec: float = 1.1) -> pd.DataFrame:
    universe = wiki_universe.get_universe().reset_index()
    print(f"[universe] S&P 500+400+600 합산 {len(universe)}개 종목 (Wikipedia)")

    existing = pd.DataFrame()
    done_tickers: set[str] = set()
    if FINANCE_CACHE.exists() and not force:
        existing = pd.read_parquet(FINANCE_CACHE)
        done_tickers = set(existing["ticker"]) if "ticker" in existing.columns else set()
        print(f"[cache] 기존 캐시 {len(done_tickers)}개 종목 재사용")

    todo = universe[~universe["ticker"].isin(done_tickers)]
    print(f"[fetch] 신규로 받아올 종목: {len(todo)}개 (분당 60건 제한, 예상 소요 약 {len(todo) * sleep_sec / 60:.1f}분)")

    rows = []
    for i, (_, r) in enumerate(todo.iterrows(), 1):
        try:
            rows.append(fetch_finance_one(r["ticker"]))
        except Exception as e:
            print(f"  [WARN] {r['ticker']} 재무데이터 조회 실패: {e}")
        if i % 50 == 0:
            print(f"  진행 {i}/{len(todo)}")
        time.sleep(sleep_sec)

    new_df = pd.DataFrame(rows)
    combined = pd.concat([existing, new_df], ignore_index=True) if len(existing) else new_df
    combined = combined.drop_duplicates(subset=["ticker"], keep="last")
    combined.to_parquet(FINANCE_CACHE, index=False)
    print(f"[done] 재무캐시 저장 완료: {len(combined)}행 → {FINANCE_CACHE}")
    return combined


def get_full_universe() -> pd.DataFrame:
    """유니버스 종목의 실시간 시세(quote)를 결합한 DataFrame. index=ticker.
    columns=[name, sector, price, market_cap, avg_volume]."""
    idx = wiki_universe.get_universe()

    rows = []
    for ticker in idx.index:
        try:
            profile = finnhub_client.get_company_profile(ticker)
            quote = finnhub_client.get_quote(ticker)
            rows.append({
                "ticker": ticker,
                "price": quote.get("c", np.nan),
                "market_cap": (profile.get("marketCapitalization") or np.nan) * 1_000_000
                    if profile.get("marketCapitalization") else np.nan,
                "avg_volume": np.nan,  # Finnhub 무료 profile2/quote는 평균거래량을 직접 주지 않음 —
                                       # 유동성 필터는 시가총액 하한으로 대부분 걸러지므로 당장은 무제한 통과 처리
            })
        except Exception as e:
            print(f"  [WARN] {ticker} 시세 조회 실패: {e}")

    quotes_df = pd.DataFrame(rows).set_index("ticker")
    return idx.join(quotes_df, how="inner")


def status():
    if FINANCE_CACHE.exists():
        fc = pd.read_parquet(FINANCE_CACHE)
        print(f"finance 캐시: {len(fc)}행")
    else:
        print("finance 캐시 없음")
    if wiki_universe.UNIVERSE_CACHE.exists():
        uc = pd.read_parquet(wiki_universe.UNIVERSE_CACHE)
        print(f"universe 캐시: {len(uc)}행")
    else:
        print("universe 캐시 없음")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    if a.status:
        status()
    elif a.build:
        build_finance_cache(force=a.force)
    else:
        print("사용법: python data_pipeline.py --build  또는  --status")
```

**Note on `avg_volume`:** the plan's `Config.min_avg_volume_usd` liquidity filter now has no real data to filter
on (Finnhub's free `quote`/`profile2` don't include average volume). Set `avg_volume = np.nan` and rely on
`pct_rank`'s existing NaN→0.5 fallback... **but `apply_hard_filters`'s hard cut (`avg_volume_usd < min`) does
NOT use `pct_rank`, it's a raw comparison, so NaN would fail the comparison and silently exclude every stock.**
To avoid this, in this task also change `us_alpha.Config`'s `min_avg_volume_usd` default to `0.0` (effectively
disabling this specific hard filter) OR make `get_full_universe()` return a very large placeholder (e.g.
`avg_volume = np.inf`) so the filter always passes until a real volume data source is added. **Pick the
`Config` default change (set `min_avg_volume_usd: float = 0.0`)** — it's the more honest fix (the filter is
explicitly disabled with a code comment explaining why, rather than faked with an infinite placeholder value).
Make this one-line change to `screening/us_alpha.py`'s `Config` dataclass as part of this task, with a comment:
`# Finnhub 무료 티어는 평균거래량을 제공하지 않아 이 필터는 현재 비활성화됨 (실제 거래대금 데이터 소스 추가 시 복원)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_data_pipeline.py -v`
Expected: 2 passed

- [ ] **Step 5: Live smoke check (manual, not automated)**

```bash
python -c "import data_pipeline; print(data_pipeline.fetch_finance_one('AAPL'))"
```
Confirm no exceptions, and that the printed dict's `roe_3y_avg`, `debt_ratio`, `per`, `pbr` look like
plausible numbers (not all NaN — if they are, the field names in Step 3 need correcting per the live
response you saw).

- [ ] **Step 6: Commit**

```bash
git add screening/data_pipeline.py screening/tests/test_data_pipeline.py screening/us_alpha.py
git commit -m "feat: rewrite finance data pipeline to use Finnhub + Wikipedia"
```

---

### Task 4: Update `us_alpha.py`'s price-history fetch to use Finnhub

**Files:**
- Modify: `screening/us_alpha.py` (only the `get_historical_prices_batch` function)
- Modify: `screening/tests/test_load_real.py` (update the monkeypatch target if it referenced `fmp_client`)

**Interfaces:**
- Consumes: `finnhub_client.get_candles` (Task 1).
- Produces: `get_historical_prices_batch(tickers: list[str], sleep_sec: float = 1.1) -> dict[str, dict]` — same signature/behavior as before, just calls `finnhub_client.get_candles` instead of `fmp_client.get_historical_prices`, with the throttle default raised to match Finnhub's per-minute limit (see Task 3's rate-limiting rationale).

- [ ] **Step 1: Locate and replace the function**

In `screening/us_alpha.py`, find `get_historical_prices_batch` (added in the original FMP-based Task 8) and
replace its body to import `finnhub_client` instead of `fmp_client`, calling `finnhub_client.get_candles`
instead of `fmp_client.get_historical_prices`, and add the `time.sleep(sleep_sec)` throttle between tickers
(matching the rate-limiting pattern from Task 3):

```python
def get_historical_prices_batch(tickers: list[str], sleep_sec: float = 1.1) -> dict[str, dict]:
    """티커 리스트에 대해 (3개월수익률, 12개월수익률, 52주낙폭)을 계산해 dict로 반환한다.
    개별 종목 조회 실패는 건너뛰고 계속 진행한다. Finnhub 무료 티어(분당 60건) 한도를
    지키기 위해 종목 사이에 sleep_sec만큼 대기한다."""
    import time

    import finnhub_client
    from data_pipeline import compute_return_and_drawdown

    out: dict[str, dict] = {}
    for ticker in tickers:
        try:
            prices = finnhub_client.get_candles(ticker, days=380)
            ret_3m, ret_12m, drawdown_52w = compute_return_and_drawdown(prices)
            out[ticker] = {"ret_3m": ret_3m, "ret_12m": ret_12m, "drawdown_52w": drawdown_52w}
        except Exception as e:
            print(f"  [WARN] {ticker} 가격 히스토리 조회 실패: {e}")
        time.sleep(sleep_sec)
    return out
```

- [ ] **Step 2: Update `screening/tests/test_load_real.py` if needed**

Check whether this test file monkeypatches `"us_alpha.get_historical_prices_batch"` directly (in which case
no change needed — the monkeypatch replaces the whole function regardless of what it calls internally) or
whether it patches `fmp_client` functions used inside `load_real()`/`get_historical_prices_batch` (in which
case change those patch targets to `finnhub_client` equivalents, or `data_pipeline` functions as
appropriate). Read the current file before editing — it was last modified in the original Task 8 and may
already be robust to this change since it monkeypatches at the `us_alpha.get_historical_prices_batch` level.

- [ ] **Step 3: Run the full test suite**

Run (from `screening/`): `python -m pytest -v`
Expected: all tests pass, zero references to `fmp_client` remain anywhere in a passing test (there should
be no more `import fmp_client` succeeding calls once Task 5 deletes that file — but if this task runs before
Task 5, `fmp_client.py` may still exist harmlessly; that's fine, Task 5 removes it).

- [ ] **Step 4: Commit**

```bash
git add screening/us_alpha.py screening/tests/test_load_real.py
git commit -m "feat: switch price-history fetch from FMP to Finnhub"
```

---

### Task 5: Remove the old FMP client and its tests

**Files:**
- Delete: `screening/fmp_client.py`
- Delete: `screening/tests/test_fmp_client.py`

**Interfaces:** None — pure removal, now that Tasks 1-4 have replaced every caller.

- [ ] **Step 1: Confirm no remaining references**

Run (from `screening/`): search for `fmp_client` across all `.py` files (e.g. `grep -rn "fmp_client" .` or
equivalent). Expected: zero matches outside this task's own deletion. If any remain, STOP and report
BLOCKED/NEEDS_CONTEXT — do not delete a file something still imports.

- [ ] **Step 2: Delete the files**

```bash
git rm screening/fmp_client.py screening/tests/test_fmp_client.py
```

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest -v`
Expected: all remaining tests pass (should be roughly the same count as before minus the ~7 FMP-specific
tests, plus the new Finnhub/Wikipedia tests added in Tasks 1-2 — net count should be similar or higher).

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: remove FMP client, replaced by Finnhub + Wikipedia"
```

---

### Task 6: Web — swap `/api/prices` from FMP to Finnhub

**Files:**
- Modify: `web/app/api/prices/route.ts`

**Interfaces:**
- Consumes: `FINNHUB_API_KEY` (Vercel env var, replaces `FMP_API_KEY` for this route — server-side only).
- Produces: same response shape as before — `GET /api/prices?tickers=A,B,C` → `{ as_of: string, prices: { [ticker]: { price: number } } }`. The `tickers` param name and validation regex added in the earlier final-review fix pass are UNCHANGED — only the upstream API call changes.

- [ ] **Step 1: Rewrite the route**

Finnhub's `/quote` endpoint is single-symbol only (no batch endpoint on the free tier), unlike FMP's
comma-separated batch quote. Fetch each ticker's quote with a small concurrency cap (Finnhub allows 60/min;
Promise.all-ing a modest batch, e.g. 10 at a time with a short delay between batches, keeps this well under
the limit for the typical ≤50-ticker page of results shown to a user):

```ts
import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const TICKERS_PATTERN = /^[A-Z.\-]{1,6}(,[A-Z.\-]{1,6}){0,99}$/;

async function fetchOneQuote(ticker: string, key: string): Promise<[string, number | null]> {
  try {
    const res = await fetch(
      `https://finnhub.io/api/v1/quote?symbol=${encodeURIComponent(ticker)}&token=${key}`,
      { cache: "no-store" }
    );
    if (!res.ok) return [ticker, null];
    const data = await res.json();
    return [ticker, typeof data.c === "number" ? data.c : null];
  } catch {
    return [ticker, null];
  }
}

export async function GET(req: NextRequest) {
  const tickersParam = req.nextUrl.searchParams.get("tickers");
  if (!tickersParam || !TICKERS_PATTERN.test(tickersParam)) {
    return Response.json({ error: "잘못된 티커 형식입니다." }, { status: 400 });
  }

  const key = process.env.FINNHUB_API_KEY;
  if (!key) {
    return Response.json({ error: "서버에 FINNHUB_API_KEY 환경변수가 설정되어 있지 않습니다." }, { status: 500 });
  }

  const tickers = tickersParam.split(",");
  const prices: Record<string, { price: number }> = {};

  const BATCH_SIZE = 10;
  for (let i = 0; i < tickers.length; i += BATCH_SIZE) {
    const batch = tickers.slice(i, i + BATCH_SIZE);
    const results = await Promise.all(batch.map((t) => fetchOneQuote(t, key)));
    for (const [ticker, price] of results) {
      if (price !== null) prices[ticker] = { price };
    }
  }

  return Response.json({ as_of: new Date().toISOString(), prices });
}
```

- [ ] **Step 2: Run the build**

Run (from `web/`): `npm run build`
Expected: succeeds with no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add web/app/api/prices/route.ts
git commit -m "feat: switch live price refresh from FMP to Finnhub"
```

---

### Task 7: GitHub Actions workflow + README — swap secret name and signup instructions

**Files:**
- Modify: `.github/workflows/daily-screen.yml`
- Modify: `README.md`

**Interfaces:** None — configuration/documentation only.

- [ ] **Step 1: Update `.github/workflows/daily-screen.yml`**

Replace every occurrence of `FMP_API_KEY` with `FINNHUB_API_KEY` (both in the `env:` blocks for the
"재무데이터 새로 받기" and "스크리닝 실행" steps). Read the current file first to find the exact lines —
do not guess line numbers.

- [ ] **Step 2: Update `README.md`**

Read the current file. Make these changes:
- §1 ("Financial Modeling Prep(FMP) 계정 + API 키"): replace with Finnhub signup instructions —
  `https://finnhub.io` 접속 → 무료 회원가입 → 대시보드에서 API 키 복사. Add a short note that Finnhub's
  free tier has no daily call cap (only a per-minute rate limit), so daily automated runs work fine at no cost.
- Every other occurrence of `FMP_API_KEY` (GitHub Secrets step, Vercel Environment Variables step, local
  `.env.local` example, local testing `setx` command): rename to `FINNHUB_API_KEY`.
- In the "참고 사항" section at the end, add one sentence noting that the S&P 500/400/600 constituent list
  is sourced from Wikipedia (no API key needed, refreshed weekly) while per-ticker data comes from Finnhub
  (refreshed daily), per `docs/superpowers/specs/2026-08-14-us-stock-screening-design.md` §10.
- Do not change anything about the Anthropic/GitHub/Vercel/admin-password steps — those are unaffected.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/daily-screen.yml README.md
git commit -m "docs: update workflow secrets and setup guide for Finnhub + Wikipedia"
```

---

### Task 8: End-to-end local verification

**Files:** none (verification only)

**Interfaces:** none.

- [ ] **Step 1: Run the full Python test suite**

```bash
cd screening && python -m pytest -v
```
Expected: all tests pass, and `fmp_client` no longer appears anywhere.

- [ ] **Step 2: Run demo mode**

```bash
python us_alpha.py --demo
```
Expected: unaffected by this plan (demo mode uses synthetic data, no live API calls) — should still pass cleanly, confirming the algorithm code itself was untouched.

- [ ] **Step 3: Build the web app**

```bash
cd ../web && npm run build
```
Expected: builds successfully.

- [ ] **Step 4: Report status to the user**

Summarize: all code changes are complete and tested against mocked/synthetic data. The Finnhub field-name
mapping in `data_pipeline.fetch_finance_one()` is the one piece that depends on a live API call the
implementer may or may not have been able to make (depends on whether a real `FINNHUB_API_KEY` was
available during implementation) — flag clearly whether the live smoke checks from Tasks 1, 2, and 3 were
actually run with a real key, and what was found, so the user knows whether this still needs a first-run
sanity check once they have their own key.

- [ ] **Step 5: No commit needed** unless Step 1-3 surfaced a bug, in which case fix it in the relevant
  task's files and commit a fix referencing which task it belongs to.
