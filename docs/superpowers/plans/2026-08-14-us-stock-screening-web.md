# 미국 주식 스크리닝 웹 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the existing KOSPI stock-screening web app (`stock_screen_web`, at `C:\Users\lwswo\OneDrive\1. WS\2. Projects\stock_screen_web`) to a US-stock version (S&P 500+400+600 universe) using Financial Modeling Prep (FMP) as the single data source, keeping the same 4-factor screening algorithm, the same Next.js/Korean-language UI, and the same GitHub Actions + Vercel static-deploy architecture.

**Architecture:** Three-part repo identical in shape to the source project: `screening/` (Python engine that pulls data from FMP, scores stocks, writes `web/data/results.json` + `filtered_full.json`), `web/` (Next.js 15 app that statically reads that JSON at build time), `.github/workflows/` (daily cron + on-demand `workflow_dispatch`, committing fresh JSON so Vercel auto-redeploys). No database.

**Tech Stack:** Python 3.13 (pandas, numpy, requests, pyarrow, pytest, anthropic), Next.js 15 / React 19 / TypeScript / Tailwind v4 / shadcn-ui (`new-york` style), FMP REST API, Anthropic API (Claude Haiku 4.5), GitHub Actions, Vercel.

## Global Constraints

- Source project to port from (read-only reference, do not modify): `C:\Users\lwswo\OneDrive\1. WS\2. Projects\stock_screen_web`
- Target project root: `C:\Users\lwswo\OneDrive\1. WS\2. Projects\us_stock_screen_web` (already a git repo, first commit is the design spec at `docs/superpowers/specs/2026-08-14-us-stock-screening-design.md`)
- UI language: Korean (all visible copy). Stock identifiers shown as **tickers** (e.g. `AAPL`), not company names in Korean.
- Universe: S&P 500 + S&P 400 (mid-cap) + S&P 600 (small-cap), deduplicated (~1,500 tickers).
- Hard-filter market cap: **>= $100,000,000, no upper bound** (per user decision — overrides the KOSPI mega-cap exclusion).
- All other hard-filter and factor-weight *ratios* are unchanged from the KOSPI algorithm (see Task 6/7 tables) — only currency-denominated thresholds are converted to USD.
- Sector tilt (KOSPI "한국 특산품" sector bonus/penalty) is **removed** — ranking uses the 4 factor scores only.
- AI profile card feature (Claude Haiku company profile) is **kept**, adapted for US companies/tickers.
- "이번주의 명언" is **kept**, replaced with a general (non-Korean-notebook-specific) investing-quotes list.
- Data source: Financial Modeling Prep (`FMP_API_KEY`) replaces KRX+DART. Anthropic (`ANTHROPIC_API_KEY`) unchanged in role.
- Every new Python module must have a pytest test file; run `pytest` from `screening/` after each task that touches Python.
- Every commit must be a real, working checkpoint — run the relevant test/build command before committing.

---

### Task 1: Repo scaffold + placeholder data

**Files:**
- Create: `.gitignore`
- Create: `screening/requirements.txt`
- Create: `web/data/results.json`
- Create: `web/data/filtered_full.json`
- Create: `screening/__init__.py` is NOT needed (flat script layout, matches source project)

**Interfaces:**
- Produces: `web/data/results.json` / `filtered_full.json` empty-state shape that `page.tsx` (Task 11) will read via `fs.readFileSync`.

- [ ] **Step 1: Create `.gitignore`**

```
# Python
__pycache__/
*.pyc
screening/.cache/
screening/screening_result*.xlsx

# Node / Next.js
web/node_modules/
web/.next/
web/out/

# 환경변수 (로컬 테스트용, 절대 커밋 금지)
.env
.env.local
```

- [ ] **Step 2: Create `screening/requirements.txt`**

```
pandas
numpy
requests
pyarrow
pytest
anthropic
```

(No `opendartreader` — FMP replaces both KRX and DART, accessed via plain `requests`.)

- [ ] **Step 3: Create placeholder result JSON files**

`web/data/results.json`:
```json
{
  "as_of_date": null,
  "financial_year": null,
  "generated_at": null,
  "quote_text": null,
  "quote_author": null,
  "universe_total": 0,
  "universe_passed": 0,
  "columns": [],
  "column_labels_ko": {},
  "results": []
}
```

`web/data/filtered_full.json`:
```json
{
  "as_of_date": null,
  "financial_year": null,
  "generated_at": null,
  "columns": [],
  "column_labels_ko": {},
  "results": []
}
```

- [ ] **Step 4: Commit**

```bash
git add .gitignore screening/requirements.txt web/data/results.json web/data/filtered_full.json
git commit -m "chore: scaffold repo structure and placeholder data files"
```

---

### Task 2: Investing quotes module (`quotes.py`)

**Files:**
- Create: `screening/quotes.py`
- Test: `screening/tests/test_quotes.py`

**Interfaces:**
- Produces: `QUOTES: list[dict]` (each `{"text": str, "author": str}`), `pick_quote_for_week(today: date | None = None) -> dict`. Consumed by Task 8's `run_real()` export.

- [ ] **Step 1: Write the failing tests**

```python
# screening/tests/test_quotes.py
from datetime import date

from quotes import QUOTES, pick_quote_for_week


def test_quote_count_is_at_least_ten():
    assert len(QUOTES) >= 10


def test_same_iso_week_returns_same_quote():
    mon = date(2026, 8, 10)
    fri = date(2026, 8, 14)
    assert pick_quote_for_week(mon) == pick_quote_for_week(fri)


def test_different_iso_week_can_return_different_quote():
    idx33 = (2026 * 53 + 33) % len(QUOTES)
    idx34 = (2026 * 53 + 34) % len(QUOTES)
    assert idx33 != idx34
    assert pick_quote_for_week(date(2026, 8, 10)) == QUOTES[idx33]


def test_returns_text_and_author_keys():
    q = pick_quote_for_week(date(2026, 1, 1))
    assert set(q.keys()) == {"text", "author"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `screening/`): `python -m pytest tests/test_quotes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quotes'`

- [ ] **Step 3: Implement `screening/quotes.py`**

```python
"""
quotes.py — 소제목에 표시할 투자자 명언 (ISO 주차 기준 매주 전환)
"""

from __future__ import annotations

from datetime import date

QUOTES: list[dict] = [
    {"text": "가격은 당신이 지불하는 것이고, 가치는 당신이 얻는 것이다.", "author": "Warren Buffett"},
    {"text": "위험은 가격에서 온다. 좋은 자산도 비싸게 사면 위험해진다.", "author": "Howard Marks"},
    {"text": "인생에서 몇 번의 위대한 결정만 내리고 나머지는 인내하면 된다.", "author": "Mohnish Pabrai"},
    {"text": "훌륭한 회사를 적정한 가격에 사는 것이, 적당한 회사를 훌륭한 가격에 사는 것보다 낫다.", "author": "Charlie Munger"},
    {"text": "확신이 있는 소수의 아이디어에 집중하고, 나머지는 무시하라.", "author": "Bill Ackman"},
    {"text": "당신이 아는 것에 투자하라. 모르는 것에 투자하지 마라.", "author": "Peter Lynch"},
    {"text": "안전마진이 있는 곳에서만 투자하라. 나머지는 투기다.", "author": "Seth Klarman"},
    {"text": "훌륭한 경영진이 이끄는 성장 기업을 찾아, 오래 보유하라.", "author": "Philip Fisher"},
    {"text": "시장의 변덕이 아니라 기업의 가치를 사라.", "author": "Benjamin Graham"},
    {"text": "10년을 보유할 생각이 없다면 단 10분도 보유하지 마라.", "author": "Warren Buffett"},
    {"text": "장기적으로 시장을 이기는 유일한 방법은 남들과 다르게 행동하는 것이다.", "author": "John Templeton"},
    {"text": "복리는 세계 8대 불가사의다. 이해하는 자는 이익을 얻고, 모르는 자는 대가를 치른다.", "author": "Albert Einstein"},
]


def pick_quote_for_week(today: date | None = None) -> dict:
    """ISO 주차(연도+주차) 기준으로 명언을 결정적으로 선택한다.
    같은 주 안에는 매일 갱신이 돌아도 동일한 명언이 유지된다."""
    if today is None:
        today = date.today()
    iso_year, iso_week, _ = today.isocalendar()
    idx = (iso_year * 53 + iso_week) % len(QUOTES)
    return QUOTES[idx]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_quotes.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add screening/quotes.py screening/tests/test_quotes.py
git commit -m "feat: add general investing-quotes module"
```

---

### Task 3: Profile cache + AI stock-profile module

**Files:**
- Create: `screening/profile_cache.py` (verbatim copy — logic is data-agnostic, no Korea-specific content)
- Create: `screening/stock_profile.py` (adapted prompt: US company, ticker-keyed)
- Test: `screening/tests/test_profile_cache.py` (verbatim copy)
- Test: `screening/tests/test_stock_profile.py` (adapted field names)

**Interfaces:**
- Produces: `generate_all_profiles(records: list[dict], cache_path: Path = profile_cache.CACHE_PATH, max_workers: int = 5) -> dict[str, dict | None]`, keyed by **ticker** (was `stock_code` in the KOSPI version — for the US port the same dict key is reused but always holds the ticker string, e.g. `"AAPL"`). Each non-`None` value is `{"business": str, "sector": str, "products": str, "competitors": list[str]}`. Consumed by Task 8's `run_real()`.
- Consumes: `records` must each contain at least `{"stock_code": <ticker str>, "name": <ticker str>, ...metric fields...}` — this plan keeps the field name `stock_code` for the ticker to minimize downstream (web) changes, even though "code" now means "ticker".

- [ ] **Step 1: Write the failing tests**

`screening/tests/test_profile_cache.py` (identical to KOSPI version — copy verbatim, no Korea-specific content):

```python
from datetime import datetime, timedelta, timezone

from profile_cache import get_fresh, load_cache, put, save_cache


def test_load_cache_missing_file_returns_empty_dict(tmp_path):
    result = load_cache(tmp_path / "nope" / "profile_cache.json")
    assert result == {}


def test_load_cache_corrupted_file_returns_empty_dict(tmp_path):
    path = tmp_path / "profile_cache.json"
    path.write_text("이건 JSON이 아닙니다", encoding="utf-8")
    result = load_cache(path)
    assert result == {}


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "sub" / "profile_cache.json"
    cache = {"AAPL": {"name": "AAPL", "profile": {"business": "..."}, "generated_at": "2026-08-14T00:00:00+00:00"}}
    save_cache(cache, path)
    assert load_cache(path) == cache


def test_get_fresh_returns_none_when_missing():
    assert get_fresh({}, "AAPL", "AAPL") is None


def test_get_fresh_returns_none_when_name_mismatch():
    cache = {"AAPL": {"name": "다른회사", "profile": {"business": "x"}, "generated_at": _now_iso()}}
    assert get_fresh(cache, "AAPL", "AAPL") is None


def test_get_fresh_returns_profile_when_within_max_age():
    profile = {"business": "x", "sector": "y", "products": "z", "competitors": ["w"]}
    cache = {"AAPL": {"name": "AAPL", "profile": profile, "generated_at": _now_iso()}}
    assert get_fresh(cache, "AAPL", "AAPL", max_age_days=90) == profile


def test_get_fresh_returns_none_when_stale():
    old = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
    cache = {"AAPL": {"name": "AAPL", "profile": {"business": "x"}, "generated_at": old}}
    assert get_fresh(cache, "AAPL", "AAPL", max_age_days=90) is None


def test_get_fresh_returns_none_when_generated_at_malformed():
    cache = {"AAPL": {"name": "AAPL", "profile": {"business": "x"}, "generated_at": "not-a-date"}}
    assert get_fresh(cache, "AAPL", "AAPL") is None


def test_put_adds_entry_with_name_profile_and_timestamp():
    cache = {}
    profile = {"business": "x", "sector": "y", "products": "z", "competitors": ["w"]}
    put(cache, "AAPL", "AAPL", profile)
    assert cache["AAPL"]["name"] == "AAPL"
    assert cache["AAPL"]["profile"] == profile
    assert "generated_at" in cache["AAPL"]
    assert get_fresh(cache, "AAPL", "AAPL") == profile


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
```

`screening/tests/test_stock_profile.py`:

```python
from stock_profile import build_prompt, PROFILE_FIELDS, SYSTEM_PROMPT, generate_profile, generate_all_profiles


def test_profile_fields_has_four_keys():
    assert PROFILE_FIELDS == ["business", "sector", "products", "competitors"]


def test_system_prompt_defined():
    assert len(SYSTEM_PROMPT) > 0


def test_build_prompt_includes_ticker():
    row = {"name": "AAPL", "per": 28.3, "pbr": 45.1}
    prompt = build_prompt(row)
    assert "AAPL" in prompt
    assert "28.3" in prompt


def test_build_prompt_works_without_optional_metrics():
    row = {"name": "AAPL"}
    prompt = build_prompt(row)
    assert "AAPL" in prompt


class _RaisingClient:
    class messages:
        @staticmethod
        def create(**kwargs):
            raise RuntimeError("네트워크 오류 시뮬레이션")


def test_generate_profile_returns_none_on_api_failure():
    row = {"name": "AAPL", "per": 28.3}
    result = generate_profile(row, client=_RaisingClient())
    assert result is None


class _TextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_TextBlock(text)]


class _FakeClient:
    def __init__(self, text):
        self.messages = self._Messages(text)

    class _Messages:
        def __init__(self, text):
            self._text = text

        def create(self, **kwargs):
            return _FakeResponse(self._text)


_VALID_JSON = (
    '{"business": "아이폰, 맥, 아이패드 등을 설계·판매한다.", "sector": "Technology", '
    '"products": "iPhone, Mac, iPad", "competitors": ["Samsung", "Google"]}'
)
_VALID_RESULT = {
    "business": "아이폰, 맥, 아이패드 등을 설계·판매한다.",
    "sector": "Technology",
    "products": "iPhone, Mac, iPad",
    "competitors": ["Samsung", "Google"],
}


def test_generate_profile_returns_dict_on_valid_json():
    row = {"name": "AAPL", "per": 28.3}
    result = generate_profile(row, client=_FakeClient(_VALID_JSON))
    assert result == _VALID_RESULT


def test_generate_profile_returns_none_on_malformed_json():
    row = {"name": "AAPL", "per": 28.3}
    result = generate_profile(row, client=_FakeClient("이건 JSON이 아닙니다"))
    assert result is None


def test_generate_profile_returns_none_when_competitors_list_is_empty():
    row = {"name": "AAPL", "per": 28.3}
    empty_list_json = (
        '{"business": "설명", "sector": "Technology", "products": "iPhone", "competitors": []}'
    )
    result = generate_profile(row, client=_FakeClient(empty_list_json))
    assert result is None


def test_generate_profile_strips_markdown_code_fence():
    row = {"name": "AAPL", "per": 28.3}
    fenced_json = f"```json\n{_VALID_JSON}\n```"
    result = generate_profile(row, client=_FakeClient(fenced_json))
    assert result == _VALID_RESULT


def test_generate_all_profiles_skips_when_no_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    records = [{"stock_code": "AAPL", "name": "AAPL", "per": 28.3}]
    result = generate_all_profiles(records)
    assert result == {"AAPL": None}


def test_generate_all_profiles_calls_api_and_writes_cache_when_no_entry(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda: _FakeClient(_VALID_JSON))

    cache_path = tmp_path / "profile_cache.json"
    records = [{"stock_code": "AAPL", "name": "AAPL", "per": 28.3}]
    result = generate_all_profiles(records, cache_path=cache_path)

    assert result == {"AAPL": _VALID_RESULT}

    from profile_cache import get_fresh, load_cache
    saved_cache = load_cache(cache_path)
    assert get_fresh(saved_cache, "AAPL", "AAPL") == _VALID_RESULT


class _RaisingIfCalledClient:
    class messages:
        @staticmethod
        def create(**kwargs):
            raise AssertionError("캐시가 신선한데도 API가 호출됨")


def test_generate_all_profiles_reuses_fresh_cache_without_calling_api(monkeypatch, tmp_path):
    from profile_cache import load_cache, put, save_cache

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda: _RaisingIfCalledClient())

    cache_path = tmp_path / "profile_cache.json"
    cached_profile = {
        "business": "캐시된 사업 내용", "sector": "Technology",
        "products": "캐시된 상품", "competitors": ["캐시된 경쟁사A"],
    }
    cache = load_cache(cache_path)
    put(cache, "AAPL", "AAPL", cached_profile)
    save_cache(cache, cache_path)

    records = [{"stock_code": "AAPL", "name": "AAPL", "per": 28.3}]
    result = generate_all_profiles(records, cache_path=cache_path)

    assert result == {"AAPL": cached_profile}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_profile_cache.py tests/test_stock_profile.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `screening/profile_cache.py`**

```python
"""
profile_cache.py — 종목 프로필 생성 결과를 로컬 캐시에 저장해 재사용한다.
================================================================
GitHub Actions 워크플로우는 screening/.cache 디렉터리를 actions/cache로 주 단위 복원하므로,
프로필 캐시도 이 디렉터리에 두면 매일 실행 간에도 유지된다. 사업 내용·섹터 같은 정보는
하루 만에 바뀌지 않으므로, 같은 종목이 상위 순위에 계속 남아있어도 캐시가 신선하면
API를 다시 호출하지 않고 재사용한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

CACHE_PATH = Path(".cache") / "profile_cache.json"
MAX_AGE_DAYS = 90


def load_cache(path: Path = CACHE_PATH) -> dict:
    """캐시 파일을 읽어 dict로 반환한다. 파일이 없거나 손상됐으면 빈 dict를 반환한다."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cache(cache: dict, path: Path = CACHE_PATH) -> None:
    """캐시 dict를 파일에 저장한다. 부모 디렉터리가 없으면 생성한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def get_fresh(cache: dict, stock_code: str, name: str, max_age_days: int = MAX_AGE_DAYS) -> dict | None:
    """캐시에 stock_code 항목이 있고, 종목명이 일치하며, max_age_days 이내에 생성됐으면
    그 profile을 반환한다. 없거나 오래됐거나 종목명이 바뀌었으면 None."""
    entry = cache.get(stock_code)
    if not entry or entry.get("name") != name:
        return None
    try:
        generated_at = datetime.fromisoformat(entry["generated_at"])
    except (KeyError, ValueError, TypeError):
        return None
    age_days = (datetime.now(timezone.utc) - generated_at).total_seconds() / 86400
    if age_days > max_age_days:
        return None
    return entry.get("profile")


def put(cache: dict, stock_code: str, name: str, profile: dict) -> None:
    """새로 생성한 profile을 생성 시각과 함께 캐시에 기록한다."""
    cache[stock_code] = {
        "name": name,
        "profile": profile,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
```

- [ ] **Step 4: Implement `screening/stock_profile.py`**

```python
"""
stock_profile.py — 종목별 프로필(사업 내용/섹터/대표 상품·브랜드/주요 경쟁사) 생성
================================================================
매일 스크리닝 파이프라인이 상위 종목을 확정한 직후 호출된다. Claude Haiku 4.5로
종목당 최대 2회(1회 실패 시 재시도) 호출하며, 실패한 종목은 profile을 None으로 남기고
전체 파이프라인은 계속 진행한다. ANTHROPIC_API_KEY가 없으면 전체 생성 단계를 건너뛴다.
캐시에 없는 종목들은 스레드풀로 동시에 호출해 전체 실행 시간을 줄인다.

주의: 모듈명을 `profile.py`가 아닌 `stock_profile.py`로 둔 이유는 파이썬 표준 라이브러리의
`profile`(cProfile 짝) 모듈과 이름이 겹쳐 `screening/`이 `sys.path`에 있는 동안 표준
프로파일러를 가져올 수 없게 되는 문제를 피하기 위함이다.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import profile_cache

PROFILE_FIELDS: list[str] = ["business", "sector", "products", "competitors"]

SYSTEM_PROMPT = (
    "당신은 미국 주식시장에 정통한 애널리스트입니다. 티커를 보고 알고 있는 사실에 "
    "근거해 간결한 한국어로 설명합니다. 모르는 내용은 추측하지 말고 일반적인 수준에서만 "
    "설명하세요. 반드시 요청받은 JSON 형식으로만 응답하세요."
)

_METRIC_LABELS = {
    "per": "PER", "pbr": "PBR", "roe_3y_avg": "ROE(3년평균%)",
    "debt_ratio": "부채비율(%)", "div_yield": "배당수익률(%)",
    "payout_ratio_pct": "배당성향(%)", "score": "종합점수",
}

MAX_ATTEMPTS = 2
MAX_WORKERS = 5


def build_prompt(row: dict) -> str:
    """종목 지표 딕셔너리로 사용자 프롬프트 문자열을 조립한다. row['name']에는 티커가 들어간다."""
    name = row.get("name", "이 종목")
    lines = [f"티커: {name}"]
    for key, label in _METRIC_LABELS.items():
        if key in row and row[key] is not None:
            lines.append(f"{label}: {row[key]}")
    metrics_block = "\n".join(lines)

    return (
        f"다음은 미국 상장 종목입니다.\n\n{metrics_block}\n\n"
        "이 종목에 대해 아래 JSON 형식으로만 응답해주세요. 다른 설명 문구는 포함하지 마세요.\n"
        '{"business": "사업 내용 2~3문장", "sector": "섹터/업종", '
        '"products": "대표 상품 또는 브랜드", "competitors": ["경쟁사1", "경쟁사2", "경쟁사3"]}'
    )


def _strip_code_fence(text: str) -> str:
    """마크다운 코드펜스(```json ... ``` 또는 ``` ... ```)로 감싸인 응답에서
    펜스를 제거한다. 펜스가 없으면 입력을 그대로 반환한다."""
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()
    return text


def _is_valid_profile(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    for field in ("business", "sector", "products"):
        if not (isinstance(data.get(field), str) and data[field].strip()):
            return False
    competitors = data.get("competitors")
    return (
        isinstance(competitors, list)
        and len(competitors) > 0
        and all(isinstance(c, str) and c.strip() for c in competitors)
    )


def generate_profile(row: dict, client=None, max_attempts: int = MAX_ATTEMPTS) -> dict | None:
    """단일 종목에 대해 Claude Haiku 4.5로 프로필을 생성한다. 응답이 비어있거나 JSON
    파싱/필드 검증에 실패하면 최대 max_attempts회까지 재시도하고, 그래도 실패하거나
    네트워크/API 오류가 나면 예외를 삼키고 None을 반환한다.
    client를 주입하면(테스트용) 그 client를 사용하고, 없으면 anthropic.Anthropic()을 새로 만든다."""
    try:
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
    except Exception as e:
        print(f"  [WARN] 프로필 생성 실패 ({row.get('name', '?')}): {e}")
        return None

    prompt = build_prompt(row)
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=400,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = None
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    text = block.text.strip()
                    break
            if text is None:
                raise ValueError("응답에 텍스트 블록이 없음")

            text = _strip_code_fence(text)
            data = json.loads(text)
            if not _is_valid_profile(data):
                raise ValueError("필드 검증 실패 (타입 또는 빈 값)")

            return {
                "business": data["business"].strip(),
                "sector": data["sector"].strip(),
                "products": data["products"].strip(),
                "competitors": [c.strip() for c in data["competitors"]],
            }
        except Exception as e:
            last_error = e

    print(f"  [WARN] 프로필 생성 실패 ({row.get('name', '?')}, {max_attempts}회 시도 모두 실패): {last_error}")
    return None


def generate_all_profiles(
    records: list[dict],
    cache_path: Path = profile_cache.CACHE_PATH,
    max_workers: int = MAX_WORKERS,
) -> dict[str, dict | None]:
    """상위 종목 레코드 리스트(각 dict는 최소 stock_code[=티커], name[=티커], per, pbr, ... 포함)를
    받아 티커별로 프로필을 생성한다. ANTHROPIC_API_KEY가 없으면 전체를 건너뛰고
    모든 값을 None으로 채운다. 캐시가 신선하면 재사용, 없는 종목은 스레드풀로 동시 생성."""
    result: dict[str, dict | None] = {}

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[profile] ANTHROPIC_API_KEY 없음 — 프로필 생성을 건너뜁니다.")
        for rec in records:
            result[rec["stock_code"]] = None
        return result

    try:
        import anthropic
        client = anthropic.Anthropic()
    except Exception as e:
        print(f"[profile] anthropic 클라이언트 초기화 실패, 프로필 생성을 건너뜁니다: {e}")
        for rec in records:
            result[rec["stock_code"]] = None
        return result

    cache = profile_cache.load_cache(cache_path)

    to_generate: list[dict] = []
    for rec in records:
        code = rec["stock_code"]
        name = rec.get("name", "")
        cached_profile = profile_cache.get_fresh(cache, code, name)
        if cached_profile is not None and _is_valid_profile(cached_profile):
            result[code] = cached_profile
        else:
            to_generate.append(rec)

    cache_hits = len(records) - len(to_generate)
    total_to_generate = len(to_generate)
    done = 0

    if to_generate:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_rec = {executor.submit(generate_profile, rec, client): rec for rec in to_generate}
            for future in as_completed(future_to_rec):
                rec = future_to_rec[future]
                code = rec["stock_code"]
                name = rec.get("name", "")
                profile = future.result()
                result[code] = profile
                if profile is not None:
                    profile_cache.put(cache, code, name, profile)
                done += 1
                if done % 10 == 0:
                    print(f"  [profile] 진행 {done}/{total_to_generate}")

    profile_cache.save_cache(cache, cache_path)
    print(
        f"[profile] 프로필 생성 완료: {len(records)}종목 "
        f"(캐시 재사용 {cache_hits}건, 신규 생성 {total_to_generate}건)"
    )
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_profile_cache.py tests/test_stock_profile.py -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add screening/profile_cache.py screening/stock_profile.py screening/tests/test_profile_cache.py screening/tests/test_stock_profile.py
git commit -m "feat: add AI stock-profile generation for US tickers"
```

---

### Task 4: FMP API client

**Files:**
- Create: `screening/fmp_client.py`
- Test: `screening/tests/test_fmp_client.py`

**Interfaces:**
- Consumes: `FMP_API_KEY` environment variable.
- Produces (all consumed by Task 5's `data_pipeline.py`):
  - `get_index_universe() -> pandas.DataFrame` — index `ticker`, columns at least `name, sector`. Combines S&P 500 + S&P 400 + S&P 600 constituent lists, deduplicated.
  - `get_quotes(tickers: list[str]) -> pandas.DataFrame` — index `ticker`, columns `price, market_cap, avg_volume` (or equivalent) for the given tickers, batched.
  - `get_ratios_ttm(ticker: str) -> dict` — single-ticker TTM ratios payload (raw, unparsed FMP JSON — parsing into our column names happens in `data_pipeline.py`, not here, so a future FMP field rename only touches one function).
  - `get_key_metrics_ttm(ticker: str) -> dict`
  - `get_income_statement_growth(ticker: str, period: str = "quarter", limit: int = 4) -> list[dict]`
  - `get_historical_prices(ticker: str, days: int = 380) -> pandas.DataFrame` — daily OHLC, used for 12-month return and 52-week drawdown.
  - `get_dividends(ticker: str) -> list[dict]`

**⚠️ Live-verification requirement (do this before writing Step 3):** FMP's exact JSON field names can change between API versions. Before implementing, run these against a real ticker with your `FMP_API_KEY` and read the actual response shape:

```bash
curl "https://financialmodelingprep.com/api/v3/quote/AAPL?apikey=$FMP_API_KEY"
curl "https://financialmodelingprep.com/api/v3/ratios-ttm/AAPL?apikey=$FMP_API_KEY"
curl "https://financialmodelingprep.com/api/v3/key-metrics-ttm/AAPL?apikey=$FMP_API_KEY"
curl "https://financialmodelingprep.com/api/v3/income-statement-growth/AAPL?period=quarter&limit=4&apikey=$FMP_API_KEY"
curl "https://financialmodelingprep.com/api/v3/profile/AAPL?apikey=$FMP_API_KEY"
curl "https://financialmodelingprep.com/api/v3/sp500_constituent?apikey=$FMP_API_KEY"
```

Confirm in particular: (a) the debt-ratio field that means **total debt ÷ total equity** (KOSPI's `debt_ratio` definition — likely `debtEquityRatioTTM`, NOT `debtRatioTTM` which is usually debt÷assets), (b) the ROE field (`returnOnEquityTTM`), (c) whether `sp500_constituent`-style endpoints exist for S&P 400/600 on your plan tier — if not, fall back to `stock-screener` with `exchange=NYSE,NASDAQ&marketCapMoreThan=100000000&isActivelyTrading=true&limit=3000` as the universe source instead of true index membership, and note this substitution in `README.md` (Task 15). Adjust the field names used in Step 3 below to match what you actually observe — the test in Step 1 mocks `requests.get` so it is unaffected by this choice, but Step 3's field-mapping must match reality.

- [ ] **Step 1: Write the failing tests (mocked HTTP, no live calls)**

```python
# screening/tests/test_fmp_client.py
import pandas as pd
import pytest

import fmp_client


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_get_quotes_returns_dataframe_indexed_by_ticker(monkeypatch):
    payload = [
        {"symbol": "AAPL", "price": 227.5, "marketCap": 3_400_000_000_000, "avgVolume": 55_000_000},
        {"symbol": "MSFT", "price": 415.2, "marketCap": 3_100_000_000_000, "avgVolume": 20_000_000},
    ]

    def fake_get(url, params=None, timeout=None):
        assert "quote/AAPL,MSFT" in url
        assert params["apikey"] == "test-key"
        return _FakeResponse(payload)

    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setattr(fmp_client.requests, "get", fake_get)

    df = fmp_client.get_quotes(["AAPL", "MSFT"])

    assert list(df.index) == ["AAPL", "MSFT"]
    assert df.loc["AAPL", "price"] == 227.5
    assert df.loc["AAPL", "market_cap"] == 3_400_000_000_000


def test_get_quotes_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FMP_API_KEY"):
        fmp_client.get_quotes(["AAPL"])


def test_get_ratios_ttm_returns_first_element_as_dict(monkeypatch):
    payload = [{"symbol": "AAPL", "returnOnEquityTTM": 1.5, "debtEquityRatioTTM": 1.8}]

    def fake_get(url, params=None, timeout=None):
        assert "ratios-ttm/AAPL" in url
        return _FakeResponse(payload)

    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setattr(fmp_client.requests, "get", fake_get)

    result = fmp_client.get_ratios_ttm("AAPL")
    assert result["returnOnEquityTTM"] == 1.5


def test_get_ratios_ttm_returns_empty_dict_on_empty_response(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse([])

    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setattr(fmp_client.requests, "get", fake_get)

    assert fmp_client.get_ratios_ttm("ZZZZ") == {}


def test_get_historical_prices_returns_dataframe_sorted_ascending(monkeypatch):
    payload = {
        "symbol": "AAPL",
        "historical": [
            {"date": "2026-08-14", "close": 230.0},
            {"date": "2026-08-13", "close": 228.0},
        ],
    }

    def fake_get(url, params=None, timeout=None):
        assert "historical-price-full/AAPL" in url
        return _FakeResponse(payload)

    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setattr(fmp_client.requests, "get", fake_get)

    df = fmp_client.get_historical_prices("AAPL", days=2)
    assert list(df["close"]) == [228.0, 230.0]  # oldest first
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_fmp_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fmp_client'`

- [ ] **Step 3: Implement `screening/fmp_client.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_fmp_client.py -v`
Expected: all pass

- [ ] **Step 5: Live smoke check (manual, not automated)**

With a real `FMP_API_KEY` set, run:
```bash
python -c "import fmp_client; print(fmp_client.get_quotes(['AAPL','MSFT']))"
python -c "import fmp_client; print(fmp_client.get_ratios_ttm('AAPL'))"
```
Confirm no exceptions and that `get_ratios_ttm` includes a debt-to-equity field and a ROE field. Note the exact field names you see — Task 5 depends on them.

- [ ] **Step 6: Commit**

```bash
git add screening/fmp_client.py screening/tests/test_fmp_client.py
git commit -m "feat: add FMP API client for US market data"
```

---

### Task 5: Finance-data pipeline (universe + cache)

**Files:**
- Create: `screening/data_pipeline.py`
- Test: `screening/tests/test_data_pipeline.py`

**Interfaces:**
- Consumes: `fmp_client.get_index_universe`, `get_quotes`, `get_ratios_ttm`, `get_key_metrics_ttm`, `get_income_statement_growth`, `get_historical_prices`, `get_dividends` (Task 4).
- Produces: `FINANCE_CACHE: Path` (`.cache/finance.parquet`), `build_finance_cache(force: bool = False, sleep_sec: float = 0.2) -> pandas.DataFrame`, `get_full_universe() -> pandas.DataFrame` (index `ticker`, columns include `name, sector, price, market_cap, avg_volume`). Row schema of the cache matches the KOSPI version's `fetch_finance_one()` output shape, with these columns: `ticker, roe_3y_avg, roe_3y_std, debt_ratio, op_margin, op_ttm, op_yoy, rev_yoy, rev_cagr_3y, years_no_rev_decline, net_income_ttm, revenue_ttm, total_equity, cash_dividend_total, payout_ratio, per, pbr, div_yield, ret_3m, ret_12m, drawdown_52w, fcf_yield, net_cash_to_mktcap, treasury_ratio`.
- Consumed by: Task 7's `load_real()`.

- [ ] **Step 1: Write the failing test**

```python
# screening/tests/test_data_pipeline.py
import numpy as np
import pandas as pd

from data_pipeline import compute_return_and_drawdown, fetch_finance_one


def test_compute_return_and_drawdown_from_price_series():
    dates = pd.date_range("2025-08-01", periods=260, freq="B")
    # 꾸준히 100 -> 130으로 상승하다가 최근에 20% 조정
    closes = np.linspace(100, 130, len(dates))
    closes[-20:] = closes[-20:] * 0.80
    df = pd.DataFrame({"date": dates, "close": closes})

    ret_3m, ret_12m, drawdown_52w = compute_return_and_drawdown(df)

    assert ret_3m < 0          # 최근 3개월은 조정으로 하락
    assert ret_12m > -0.5      # 그래도 1년 전보다는 크게 나쁘지 않음
    assert drawdown_52w > 0    # 52주 고점 대비 낙폭은 양수로 표현


def test_fetch_finance_one_computes_op_margin_and_debt_ratio(monkeypatch):
    import fmp_client

    monkeypatch.setattr(
        fmp_client, "get_ratios_ttm",
        lambda ticker: {"returnOnEquityTTM": 0.15, "debtEquityRatioTTM": 0.8,
                         "operatingProfitMarginTTM": 0.22, "priceEarningsRatioTTM": 18.0,
                         "priceToBookRatioTTM": 6.0, "dividendYielTTM": 0.005,
                         "payoutRatioTTM": 0.15},
    )
    monkeypatch.setattr(
        fmp_client, "get_key_metrics_ttm",
        lambda ticker: {"netIncomePerShareTTM": 6.0, "freeCashFlowYieldTTM": 0.03,
                         "netDebtToEBITDATTM": -0.5},
    )
    monkeypatch.setattr(
        fmp_client, "get_income_statement_growth",
        lambda ticker, period="quarter", limit=4: [
            {"growthRevenue": 0.08, "growthOperatingIncome": 0.12},
        ],
    )

    row = fetch_finance_one("AAPL")

    assert row["ticker"] == "AAPL"
    assert row["roe_3y_avg"] == 0.15 * 100
    assert row["debt_ratio"] == 0.8 * 100
    assert row["op_margin"] == 0.22 * 100
    assert row["op_yoy"] == 0.12
    assert row["rev_yoy"] == 0.08
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_data_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_pipeline'`

- [ ] **Step 3: Implement `screening/data_pipeline.py`**

```python
"""
data_pipeline.py — 미국 주식 재무데이터 캐싱 레이어
================================================================
FMP API를 매번 호출하지 않도록, 종목별 재무데이터를 로컬 parquet에 저장해두고
재사용한다. KOSPI판의 DART 캐시(연 1회 사업보고서 + 분기 TTM 보정)와 달리, FMP의
TTM 엔드포인트가 이미 최근 4분기 합산값을 직접 제공하므로 여기서는 그 값을 그대로 쓴다.

사용법:
    python data_pipeline.py --build          # 캐시 새로 만들기 (최초 1회, 시간 걸림)
    python data_pipeline.py --build --force  # 캐시 무시하고 전부 새로 받기
    python data_pipeline.py --status         # 캐시 현황 확인

캐시 파일:
    .cache/finance.parquet      — 종목별 재무비율 (ROE, 부채비율 등)
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

import fmp_client

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
    idx_3m = max(0, len(closes) - 1 - 63)   # 영업일 기준 약 3개월
    idx_12m = 0                              # 시리즈 시작이 약 1년 전이라고 가정(호출 시 days=380)
    ret_3m = last / closes[idx_3m] - 1.0
    ret_12m = last / closes[idx_12m] - 1.0

    peak_52w = closes.max()
    drawdown_52w = (peak_52w - last) / peak_52w if peak_52w > 0 else np.nan

    return (float(ret_3m), float(ret_12m), float(drawdown_52w))


def fetch_finance_one(ticker: str) -> dict:
    """FMP 여러 엔드포인트를 조합해 스코어링에 필요한 한 종목의 재무 행을 만든다.
    ⚠️ FMP 필드명(returnOnEquityTTM 등)은 Task 4 Step 5의 라이브 확인 결과에 맞춰
    아래 매핑을 조정할 것 — 이 함수가 FMP 원본 필드명과 내부 컬럼명 사이의 유일한
    변환 지점이다."""
    ratios = fmp_client.get_ratios_ttm(ticker)
    metrics = fmp_client.get_key_metrics_ttm(ticker)
    growth = fmp_client.get_income_statement_growth(ticker, period="quarter", limit=4)

    roe = ratios.get("returnOnEquityTTM")
    debt_equity = ratios.get("debtEquityRatioTTM")
    op_margin = ratios.get("operatingProfitMarginTTM")
    per = ratios.get("priceEarningsRatioTTM")
    pbr = ratios.get("priceToBookRatioTTM")
    div_yield = ratios.get("dividendYielTTM")
    payout_ratio = ratios.get("payoutRatioTTM")
    fcf_yield = metrics.get("freeCashFlowYieldTTM")

    latest_growth = growth[0] if growth else {}
    rev_yoy = latest_growth.get("growthRevenue")
    op_yoy = latest_growth.get("growthOperatingIncome")

    return {
        "ticker": ticker,
        "roe_3y_avg": None if roe is None else roe * 100,
        "roe_3y_std": np.nan,   # FMP TTM 엔드포인트는 단일 시점값만 제공 — 3개년 변동성은 계산 불가, 중립값(0.5 percentile) 처리는 score_quality의 pct_rank가 알아서 함
        "debt_ratio": None if debt_equity is None else debt_equity * 100,
        "op_margin": None if op_margin is None else op_margin * 100,
        "op_ttm": None,   # apply_hard_filters에서 rev/op 부호 판단용 — get_quotes 이후 시총*op_margin으로 근사
        "op_yoy": op_yoy,
        "rev_yoy": rev_yoy,
        "rev_cagr_3y": np.nan,
        "years_no_rev_decline": 0,
        "net_income_ttm": np.nan,
        "revenue_ttm": np.nan,
        "total_equity": np.nan,
        "cash_dividend_total": np.nan,
        "payout_ratio": None if payout_ratio is None else max(payout_ratio, 0.0),
        "per": per,
        "pbr": pbr,
        "div_yield": None if div_yield is None else div_yield * 100,
        "fcf_yield": fcf_yield,
        "net_cash_to_mktcap": np.nan,
        "treasury_ratio": np.nan,
    }


def build_finance_cache(force: bool = False, sleep_sec: float = 0.2) -> pd.DataFrame:
    universe = fmp_client.get_index_universe().reset_index()
    print(f"[universe] S&P 500+400+600 합산 {len(universe)}개 종목")

    existing = pd.DataFrame()
    done_tickers: set[str] = set()
    if FINANCE_CACHE.exists() and not force:
        existing = pd.read_parquet(FINANCE_CACHE)
        done_tickers = set(existing["ticker"]) if "ticker" in existing.columns else set()
        print(f"[cache] 기존 캐시 {len(done_tickers)}개 종목 재사용")

    todo = universe[~universe["ticker"].isin(done_tickers)]
    print(f"[fetch] 신규로 받아올 종목: {len(todo)}개")

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
    """유니버스 종목의 실시간 시세(quote)를 결합한 DataFrame. index=ticker."""
    idx = fmp_client.get_index_universe()
    quotes = fmp_client.get_quotes(list(idx.index))
    return idx.join(quotes, how="inner")


def status():
    if FINANCE_CACHE.exists():
        fc = pd.read_parquet(FINANCE_CACHE)
        print(f"finance 캐시: {len(fc)}행")
    else:
        print("finance 캐시 없음")


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

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_data_pipeline.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add screening/data_pipeline.py screening/tests/test_data_pipeline.py
git commit -m "feat: add FMP-backed finance data pipeline with local cache"
```

---

### Task 6: Scoring engine — config + 4-factor scorers

**Files:**
- Create: `screening/us_alpha.py` (part 1 of 3 — this task + Task 7 + Task 8 build up the same file)
- Test: `screening/tests/test_scoring.py`

**Interfaces:**
- Produces: `Config` dataclass, `CFG` instance, `pct_rank(s, ascending=True)`, `winsor(s, lo=0.01, hi=0.99)`, `score_quality(df)`, `score_value(df)`, `score_gap(df)`, `score_payout(df)`. All take/return `pandas.Series`/`DataFrame` with the column names listed in each docstring.

- [ ] **Step 1: Write the failing test**

```python
# screening/tests/test_scoring.py
import pandas as pd

from us_alpha import score_payout


def test_lower_payout_ratio_scores_higher_on_s_payout():
    """score_payout()은 '배당성향이 낮을수록(=여력이 많을수록) 우대'하는 로직이다.
    payout_ratio는 fraction 단위(0.05 = 5%)로 맞춰져 있어야 하며, score_payout()
    내부의 room 임계값(0.50)도 같은 단위를 전제한다."""
    df = pd.DataFrame(
        {
            "payout_ratio": [0.05, 0.40],
            "net_cash_to_mktcap": [0.10, 0.10],
            "roe_3y_avg": [10.0, 10.0],
            "treasury_ratio": [0.02, 0.02],
        },
        index=["low_payout", "high_payout"],
    )

    scores = score_payout(df)

    assert scores["low_payout"] > scores["high_payout"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scoring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'us_alpha'`

- [ ] **Step 3: Implement `screening/us_alpha.py` (Config + scorers section)**

```python
"""
us_alpha.py — 4팩터 종목 선정 알고리즘 (KOSPI판 이식, S&P 500+400+600 대상)
================================================================
핵심 명제 (KOSPI판과 동일한 원칙):
  "회사 실적, 점유율, 턴어라운드 체력, 브랜드가 괜찮은데
   주가는 안 올라가는 종목을 고르고 모아가면서 기다리면 나중에 오름"

실행:
    python us_alpha.py --demo              # 합성 데이터로 로직 검증
    python us_alpha.py --run --top 50       # 실데이터 (FMP 필요)

의존:
    pip install -r requirements.txt
    setx FMP_API_KEY "..."
    setx ANTHROPIC_API_KEY "..."   (프로필 카드용, 없으면 프로필만 생략됨)
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quotes import pick_quote_for_week
from stock_profile import generate_all_profiles


# ═══════════════════════════════════════════════════════════════
# 1. 설정 — KOSPI판 비율과 동일, 금액 기준만 USD
# ═══════════════════════════════════════════════════════════════

@dataclass
class Config:
    # ---- 유니버스 (사용자 지정: 시총 하한만 있고 상한 없음)
    min_mktcap_usd: float = 100_000_000       # $100M 이상
    min_avg_volume_usd: float = 230_000       # 일평균 거래대금 하한 (KOSPI 3억원 환산)

    # ---- 하드 필터 (KOSPI판과 동일 비율)
    max_debt_ratio: float = 200.0             # 부채비율(부채/자본) 200% 초과 배제
    min_roe: float = 5.0                      # ROE 5% 미만 배제
    require_positive_op: bool = True          # 최근 4분기 누적 영업이익 > 0
    max_3m_return: float = 0.60               # 3개월 +60% 이상 = 테마 급등 → 신규진입 금지

    # ---- 4대 팩터 가중치 (KOSPI판과 동일)
    w_quality: float = 0.30
    w_value: float = 0.28
    w_gap: float = 0.27
    w_payout: float = 0.15

    # ---- 포지션 사이징 참고값 (스크리닝 화면에는 미노출, 향후 포트폴리오 기능용)
    max_weight_single: float = 0.10
    max_weight_sector: float = 0.25
    target_positions: int = 20


CFG = Config()


# ═══════════════════════════════════════════════════════════════
# 2. 유틸 — 횡단면 백분위 스코어
# ═══════════════════════════════════════════════════════════════

def pct_rank(s: pd.Series, ascending: bool = True) -> pd.Series:
    """결측은 중앙값(0.5) 처리. 0~1 백분위."""
    r = s.rank(pct=True, ascending=ascending, na_option="keep")
    return r.fillna(0.5)


def winsor(s: pd.Series, lo=0.01, hi=0.99) -> pd.Series:
    return s.clip(s.quantile(lo), s.quantile(hi))


# ═══════════════════════════════════════════════════════════════
# 3. 4대 팩터 스코어러 (KOSPI판과 동일 가중치·로직)
# ═══════════════════════════════════════════════════════════════

def score_quality(df: pd.DataFrame) -> pd.Series:
    """체력. ROE 수준·안정성, 영업이익률, 부채비율, 매출 성장."""
    s = (
        0.30 * pct_rank(winsor(df["roe_3y_avg"]))
        + 0.20 * pct_rank(-winsor(df["roe_3y_std"]))
        + 0.20 * pct_rank(winsor(df["op_margin"]))
        + 0.20 * pct_rank(-winsor(df["debt_ratio"]))
        + 0.10 * pct_rank(winsor(df["rev_cagr_3y"]))
    )
    s = s + 0.05 * df["years_no_rev_decline"].clip(0, 5) / 5
    return s


def score_value(df: pd.DataFrame) -> pd.Series:
    """가격. 이익수익률(1/PER), 순자산수익률(1/PBR), 배당수익률, FCF수익률."""
    ep = 1.0 / df["per"].replace([0, np.inf, -np.inf], np.nan)
    bp = 1.0 / df["pbr"].replace([0, np.inf, -np.inf], np.nan)
    s = (
        0.40 * pct_rank(winsor(ep))
        + 0.30 * pct_rank(winsor(bp))
        + 0.20 * pct_rank(winsor(df["div_yield"]))
        + 0.10 * pct_rank(winsor(df["fcf_yield"]))
    )
    return s


def score_gap(df: pd.DataFrame) -> pd.Series:
    """★ 핵심 팩터: '실적-주가 괴리'. 이익 모멘텀 양호 + 주가 모멘텀 부진일수록 고득점.
    영업이익 YoY가 -10% 미만이면 게이트로 차단(펀더멘털 훼손과 구분)."""
    gate = (df["op_yoy"] > -0.10).astype(float)

    s = (
        0.35 * pct_rank(-winsor(df["ret_12m"]))
        + 0.25 * pct_rank(winsor(df["drawdown_52w"]))
        + 0.25 * pct_rank(winsor(df["op_yoy"]))
        + 0.15 * pct_rank(winsor(df["rev_yoy"]))
    )
    return s * gate + (1 - gate) * 0.15


def score_payout(df: pd.DataFrame) -> pd.Series:
    """주주환원 여력. '이미 많이 주는 회사'가 아니라 '줄 여력이 있는데 안 주는 회사'가 정답."""
    room = (0.50 - df["payout_ratio"]).clip(lower=0)
    s = (
        0.40 * pct_rank(winsor(room))
        + 0.30 * pct_rank(winsor(df["net_cash_to_mktcap"]))
        + 0.20 * pct_rank(winsor(df["roe_3y_avg"]))
        + 0.10 * pct_rank(winsor(df["treasury_ratio"]))
    )
    return s
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scoring.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add screening/us_alpha.py screening/tests/test_scoring.py
git commit -m "feat: add 4-factor scoring config and scorers"
```

---

### Task 7: Scoring engine — hard filters, composite, demo mode

**Files:**
- Modify: `screening/us_alpha.py` (append to file from Task 6)
- Test: `screening/tests/test_filters_and_composite.py`

**Interfaces:**
- Consumes: `Config`, `CFG`, `score_quality/value/gap/payout` (Task 6).
- Produces: `apply_hard_filters(df, cfg=CFG) -> DataFrame` (adds `passed: bool`, `filter_reason: str`), `composite(df, cfg=CFG) -> DataFrame` (adds `s_quality, s_value, s_gap, s_payout, score`, sorted descending by `score`), `make_demo(n=300, seed=7) -> DataFrame`, `run_demo() -> None`.

- [ ] **Step 1: Write the failing test**

```python
# screening/tests/test_filters_and_composite.py
import pandas as pd

from us_alpha import apply_hard_filters, composite, Config


def _base_row(**overrides):
    row = {
        "mktcap_usd": 5_000_000_000, "avg_volume_usd": 50_000_000,
        "debt_ratio": 80.0, "roe_3y_avg": 15.0, "roe_3y_std": 3.0,
        "op_margin": 20.0, "op_ttm": 500_000_000, "ret_3m": 0.02,
        "per": 15.0, "pbr": 3.0, "div_yield": 1.0, "fcf_yield": 0.04,
        "ret_12m": 0.05, "drawdown_52w": 0.15, "op_yoy": 0.08, "rev_yoy": 0.05,
        "rev_cagr_3y": 0.06, "years_no_rev_decline": 3,
        "payout_ratio": 0.20, "net_cash_to_mktcap": 0.05, "treasury_ratio": 0.01,
        "sector": "Technology",
    }
    row.update(overrides)
    return row


def test_apply_hard_filters_excludes_small_market_cap():
    df = pd.DataFrame([_base_row(mktcap_usd=50_000_000)], index=["TINY"])
    out = apply_hard_filters(df, Config())
    assert out.loc["TINY", "passed"] is False or out.loc["TINY", "passed"] == False
    assert out.loc["TINY", "filter_reason"] == "시총하한"


def test_apply_hard_filters_excludes_high_debt_ratio():
    df = pd.DataFrame([_base_row(debt_ratio=250.0)], index=["DEBT"])
    out = apply_hard_filters(df, Config())
    assert out.loc["DEBT", "passed"] == False
    assert out.loc["DEBT", "filter_reason"] == "부채과다"


def test_apply_hard_filters_excludes_theme_spike():
    df = pd.DataFrame([_base_row(ret_3m=0.75)], index=["SPIKE"])
    out = apply_hard_filters(df, Config())
    assert out.loc["SPIKE", "passed"] == False
    assert out.loc["SPIKE", "filter_reason"] == "테마급등"


def test_apply_hard_filters_passes_healthy_stock():
    df = pd.DataFrame([_base_row()], index=["OK"])
    out = apply_hard_filters(df, Config())
    assert out.loc["OK", "passed"] == True


def test_composite_ranks_higher_quality_stock_first():
    good = _base_row()
    bad = _base_row(roe_3y_avg=5.0, op_margin=2.0, debt_ratio=190.0, per=60.0, pbr=15.0,
                     div_yield=0.0, drawdown_52w=0.02, op_yoy=-0.05)
    df = pd.DataFrame([good, bad], index=["GOOD", "BAD"])
    filt = apply_hard_filters(df, Config())
    ranked = composite(filt, Config())
    assert ranked.index[0] == "GOOD"
    assert ranked.loc["GOOD", "score"] > ranked.loc["BAD", "score"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_filters_and_composite.py -v`
Expected: FAIL with `ImportError: cannot import name 'apply_hard_filters'`

- [ ] **Step 3: Append to `screening/us_alpha.py`**

```python

# ═══════════════════════════════════════════════════════════════
# 4. 필터 & 합성
# ═══════════════════════════════════════════════════════════════

def apply_hard_filters(df: pd.DataFrame, cfg: Config = CFG) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    reasons = pd.Series("", index=df.index)

    def cut(cond: pd.Series, label: str):
        nonlocal m, reasons
        bad = cond & m
        reasons[bad] = label
        m = m & ~cond

    cut(df["mktcap_usd"] < cfg.min_mktcap_usd, "시총하한")
    cut(df["avg_volume_usd"] < cfg.min_avg_volume_usd, "유동성")
    cut(df["debt_ratio"] > cfg.max_debt_ratio, "부채과다")
    cut(df["roe_3y_avg"] < cfg.min_roe, "ROE미달")
    if cfg.require_positive_op:
        cut(df["op_ttm"] <= 0, "적자")
    cut(df["ret_3m"] > cfg.max_3m_return, "테마급등")

    out = df.copy()
    out["passed"] = m
    out["filter_reason"] = reasons
    return out


def composite(df: pd.DataFrame, cfg: Config = CFG) -> pd.DataFrame:
    d = df.copy()
    d["s_quality"] = score_quality(d)
    d["s_value"] = score_value(d)
    d["s_gap"] = score_gap(d)
    d["s_payout"] = score_payout(d)

    d["score"] = (
        cfg.w_quality * d["s_quality"]
        + cfg.w_value * d["s_value"]
        + cfg.w_gap * d["s_gap"]
        + cfg.w_payout * d["s_payout"]
    )
    return d.sort_values("score", ascending=False)


# ═══════════════════════════════════════════════════════════════
# 5. 데모 — 합성 데이터로 로직 검증
# ═══════════════════════════════════════════════════════════════

def make_demo(n: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    sectors = ["Technology", "Health Care", "Financials", "Industrials", "Consumer Discretionary",
               "Consumer Staples", "Energy", "Materials", "Utilities", "Real Estate"]
    df = pd.DataFrame(index=[f"TCK{i:04d}" for i in range(n)])
    df["name"] = df.index
    df["sector"] = rng.choice(sectors, n)
    df["mktcap_usd"] = rng.lognormal(21.0, 1.5, n)
    df["avg_volume_usd"] = rng.lognormal(13.0, 1.5, n)
    df["roe_3y_avg"] = rng.normal(10, 8, n)
    df["roe_3y_std"] = np.abs(rng.normal(4, 2.5, n))
    df["op_margin"] = rng.normal(12, 8, n)
    df["debt_ratio"] = np.abs(rng.normal(90, 60, n))
    df["rev_cagr_3y"] = rng.normal(0.06, 0.10, n)
    df["years_no_rev_decline"] = rng.integers(0, 6, n)
    df["per"] = np.abs(rng.lognormal(2.6, 0.6, n))
    df["pbr"] = np.abs(rng.lognormal(0.5, 0.7, n))
    df["div_yield"] = np.abs(rng.normal(1.2, 1.2, n))
    df["fcf_yield"] = rng.normal(0.04, 0.05, n)
    df["ret_12m"] = rng.normal(0.08, 0.35, n)
    df["ret_3m"] = rng.normal(0.02, 0.20, n)
    df["drawdown_52w"] = np.abs(rng.normal(0.25, 0.15, n))
    df["op_yoy"] = rng.normal(0.06, 0.30, n)
    df["rev_yoy"] = rng.normal(0.05, 0.15, n)
    df["op_ttm"] = rng.normal(200_000_000, 400_000_000, n)
    df["payout_ratio"] = np.abs(rng.normal(0.20, 0.15, n))
    df["net_cash_to_mktcap"] = rng.normal(0.05, 0.20, n)
    df["treasury_ratio"] = np.abs(rng.normal(0.02, 0.03, n))
    return df


def run_demo():
    pd.set_option("display.width", 200, "display.max_columns", 50)
    df = make_demo()
    filt = apply_hard_filters(df)
    ranked = composite(filt)

    print("=" * 78)
    print("STEP 1 — 하드 필터")
    print("=" * 78)
    print(f"유니버스 {len(df)} → 통과 {int(filt['passed'].sum())}")
    print(filt.loc[~filt["passed"], "filter_reason"].value_counts().to_string())

    print("\n" + "=" * 78)
    print("STEP 2 — 종합 랭킹 상위 15")
    print("=" * 78)
    cols = ["name", "sector", "per", "pbr", "roe_3y_avg", "debt_ratio",
            "ret_12m", "op_yoy", "s_quality", "s_value", "s_gap", "s_payout", "score"]
    top = ranked[ranked["passed"]].head(15)[cols]
    print(top.round(3).to_string())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_filters_and_composite.py -v`
Expected: 5 passed

- [ ] **Step 5: Run demo mode manually to sanity-check output**

Run: `python us_alpha.py --demo`
Expected: prints filter counts and a top-15 ranking table without errors.

- [ ] **Step 6: Commit**

```bash
git add screening/us_alpha.py screening/tests/test_filters_and_composite.py
git commit -m "feat: add hard filters, composite ranking, and demo mode"
```

---

### Task 8: Real-data adapter + JSON export

**Files:**
- Modify: `screening/us_alpha.py` (append final section)
- Test: `screening/tests/test_load_real.py`

**Interfaces:**
- Consumes: `data_pipeline.get_full_universe()`, `data_pipeline.FINANCE_CACHE` (Task 5); `generate_all_profiles` (Task 3); `pick_quote_for_week` (Task 2); `apply_hard_filters`, `composite` (Task 7).
- Produces: `load_real() -> pd.DataFrame`, `run_real(top_n: int, export_json: str, filtered_json: str) -> pd.DataFrame`. Writes `web/data/results.json` and `web/data/filtered_full.json` in the same shape as the placeholders from Task 1, using **English column keys with a `column_labels_ko` dict** for display (mirrors KOSPI's `column_labels_ko`, reused verbatim as the field name so Task 11's frontend needs zero renaming).

- [ ] **Step 1: Write the failing test**

```python
# screening/tests/test_load_real.py
import json

import numpy as np
import pandas as pd

from us_alpha import run_real


def test_run_real_writes_expected_json_shape(monkeypatch, tmp_path):
    import data_pipeline

    universe = pd.DataFrame(
        {"name": ["Apple Inc."], "sector": ["Technology"], "price": [230.0],
         "market_cap": [3_500_000_000_000], "avg_volume": [50_000_000]},
        index=pd.Index(["AAPL"], name="ticker"),
    )
    finance = pd.DataFrame([{
        "ticker": "AAPL", "roe_3y_avg": 150.0, "roe_3y_std": np.nan, "debt_ratio": 180.0,
        "op_margin": 30.0, "op_ttm": 100_000_000_000, "op_yoy": 0.1, "rev_yoy": 0.05,
        "rev_cagr_3y": np.nan, "years_no_rev_decline": 0, "net_income_ttm": np.nan,
        "revenue_ttm": np.nan, "total_equity": np.nan, "cash_dividend_total": np.nan,
        "payout_ratio": 0.15, "per": 28.0, "pbr": 45.0, "div_yield": 0.5,
        "fcf_yield": 0.03, "net_cash_to_mktcap": 0.02, "treasury_ratio": 0.0,
    }])

    monkeypatch.setattr(data_pipeline, "get_full_universe", lambda: universe)
    monkeypatch.setattr(data_pipeline, "FINANCE_CACHE", tmp_path / "finance.parquet")
    finance.to_parquet(tmp_path / "finance.parquet", index=False)

    monkeypatch.setattr(
        "us_alpha.get_historical_prices_batch",
        lambda tickers: {"AAPL": {"ret_3m": 0.05, "ret_12m": 0.12, "drawdown_52w": 0.10}},
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    out_json = tmp_path / "results.json"
    filtered_json = tmp_path / "filtered_full.json"

    run_real(top_n=10, export_json=str(out_json), filtered_json=str(filtered_json))

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["universe_total"] == 1
    assert payload["results"][0]["stock_code"] == "AAPL"
    assert payload["results"][0]["profile"] is None
    assert "column_labels_ko" in payload
    assert "quote_text" in payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_load_real.py -v`
Expected: FAIL with `ImportError: cannot import name 'run_real'`

- [ ] **Step 3: Append to `screening/us_alpha.py`**

```python

# ═══════════════════════════════════════════════════════════════
# 6. 실데이터 어댑터
# ═══════════════════════════════════════════════════════════════

def get_historical_prices_batch(tickers: list[str]) -> dict[str, dict]:
    """티커 리스트에 대해 (3개월수익률, 12개월수익률, 52주낙폭)을 계산해 dict로 반환한다.
    개별 종목 조회 실패는 건너뛰고 계속 진행한다."""
    import fmp_client
    from data_pipeline import compute_return_and_drawdown

    out: dict[str, dict] = {}
    for ticker in tickers:
        try:
            prices = fmp_client.get_historical_prices(ticker, days=380)
            ret_3m, ret_12m, drawdown_52w = compute_return_and_drawdown(prices)
            out[ticker] = {"ret_3m": ret_3m, "ret_12m": ret_12m, "drawdown_52w": drawdown_52w}
        except Exception as e:
            print(f"  [WARN] {ticker} 가격 히스토리 조회 실패: {e}")
    return out


def load_real() -> pd.DataFrame:
    """FMP 유니버스 + 재무 캐시 + 가격히스토리를 조립해 스코어링용 DataFrame을 만든다.
    사전 준비: python data_pipeline.py --build 로 .cache/finance.parquet 만들어둘 것."""
    import data_pipeline

    if not data_pipeline.FINANCE_CACHE.exists():
        raise RuntimeError(
            "재무 캐시가 없습니다. 먼저 실행하세요: python data_pipeline.py --build"
        )

    universe = data_pipeline.get_full_universe()
    universe = universe.rename(columns={"market_cap": "mktcap_usd", "avg_volume": "avg_volume_usd"})

    fin = pd.read_parquet(data_pipeline.FINANCE_CACHE).set_index("ticker")
    df = universe.join(fin, how="inner")

    price_hist = get_historical_prices_batch(list(df.index))
    df["ret_3m"] = df.index.map(lambda t: price_hist.get(t, {}).get("ret_3m", np.nan))
    df["ret_12m"] = df.index.map(lambda t: price_hist.get(t, {}).get("ret_12m", np.nan))
    df["drawdown_52w"] = df.index.map(lambda t: price_hist.get(t, {}).get("drawdown_52w", np.nan))

    # op_ttm은 하드필터(적자 배제)에만 쓰이므로, 영업이익률 × 매출총계 근사가 없으면
    # 시가총액 × 영업이익률 부호만으로 흑자/적자를 판별한다 (부호만 필요).
    df["op_ttm"] = df["op_margin"]

    return df


# ═══════════════════════════════════════════════════════════════
# 7. 실행 — 스크리닝 + JSON export
# ═══════════════════════════════════════════════════════════════

KOR_NAMES = {
    "name": "종목명", "sector": "섹터", "mktcap_usd": "시가총액(백만$)",
    "price": "현재가", "per": "PER", "pbr": "PBR", "roe_3y_avg": "ROE(%)",
    "debt_ratio": "부채비율(%)", "div_yield": "배당수익률(%)", "payout_ratio": "배당성향(%)",
    "score": "종합점수",
}


def run_real(top_n: int = 50, export_json: str | None = None, filtered_json: str | None = None) -> pd.DataFrame:
    d = load_real()
    filt = apply_hard_filters(d)
    ranked = composite(filt)

    print(f"유니버스 {len(d)} → 통과 {int(filt['passed'].sum())}")

    cols = ["name", "sector", "mktcap_usd", "price", "per", "pbr", "roe_3y_avg",
            "debt_ratio", "div_yield", "payout_ratio", "score"]
    cols = [c for c in cols if c in ranked.columns]

    top = ranked[ranked["passed"]].head(top_n)[cols]

    if export_json:
        import json
        from pathlib import Path as _Path

        records = []
        for ticker, row in top.iterrows():
            rec = {"stock_code": str(ticker)}
            for c in cols:
                v = row[c]
                if pd.isna(v):
                    rec[c] = None
                elif isinstance(v, (int, float, np.floating, np.integer)):
                    rec[c] = round(float(v), 4)
                else:
                    rec[c] = str(v)
            rec["name"] = rec["stock_code"]   # 화면에는 회사 전체명 대신 티커를 표시 (설계 결정)
            records.append(rec)

        quote = pick_quote_for_week()

        def _build_payload(recs):
            return {
                "as_of_date": pd.Timestamp.now("UTC").strftime("%Y%m%d"),
                "financial_year": None,
                "generated_at": pd.Timestamp.now("UTC").isoformat(),
                "quote_text": quote["text"],
                "quote_author": quote["author"],
                "universe_total": int(len(d)),
                "universe_passed": int(filt["passed"].sum()),
                "columns": cols,
                "column_labels_ko": {c: KOR_NAMES.get(c, c) for c in cols},
                "results": recs,
            }

        out_path = _Path(export_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        for rec in records:
            rec["profile"] = None
        out_path.write_text(json.dumps(_build_payload(records), ensure_ascii=False, indent=2), encoding="utf-8")

        profile_map = generate_all_profiles(records)
        for rec in records:
            rec["profile"] = profile_map.get(rec["stock_code"])

        out_path.write_text(json.dumps(_build_payload(records), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[export] JSON 저장 완료 → {export_json} ({len(records)}종목)")

    if filtered_json:
        import json
        from pathlib import Path as _Path

        passed_all = ranked[ranked["passed"]][cols]
        records = []
        for ticker, row in passed_all.iterrows():
            rec = {"stock_code": str(ticker)}
            for c in cols:
                v = row[c]
                rec[c] = None if pd.isna(v) else (round(float(v), 4) if isinstance(v, (int, float, np.floating, np.integer)) else str(v))
            rec["name"] = rec["stock_code"]   # 화면에는 회사 전체명 대신 티커를 표시 (설계 결정)
            records.append(rec)

        payload = {
            "as_of_date": pd.Timestamp.now("UTC").strftime("%Y%m%d"),
            "financial_year": None,
            "generated_at": pd.Timestamp.now("UTC").isoformat(),
            "columns": cols,
            "column_labels_ko": {c: KOR_NAMES.get(c, c) for c in cols},
            "results": records,
        }
        out_path = _Path(filtered_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[export] 필터통과 전체 JSON 저장 완료 → {filtered_json} ({len(records)}종목)")

    return ranked


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--export-json", default="", help="예: ../web/data/results.json")
    ap.add_argument("--filtered-json", default="", help="예: ../web/data/filtered_full.json")
    a = ap.parse_args()
    if a.run:
        run_real(a.top, a.export_json if a.export_json else None, a.filtered_json if a.filtered_json else None)
    else:
        run_demo()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_load_real.py -v`
Expected: 1 passed

- [ ] **Step 5: Run full Python test suite**

Run (from `screening/`): `python -m pytest -v`
Expected: all tests across all modules pass.

- [ ] **Step 6: Commit**

```bash
git add screening/us_alpha.py screening/tests/test_load_real.py
git commit -m "feat: add real-data adapter and JSON export for screening results"
```

---

### Task 9: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/daily-screen.yml`

**Interfaces:**
- Consumes: `FMP_API_KEY`, `ANTHROPIC_API_KEY` (GitHub Secrets, set manually by the user later — see Task 15).
- Produces: commits to `web/data/results.json` / `filtered_full.json` on `main`, triggering Vercel redeploy. Dispatchable via `workflow_dispatch` (used by Task 12's `/api/update-finance` route).

- [ ] **Step 1: Create the workflow file**

```yaml
name: 일일 스크리닝 (미국 주식)

permissions:
  contents: write   # 워크플로우가 결과 파일을 저장소에 다시 커밋할 수 있도록 쓰기 권한 부여

on:
  schedule:
    # 매일 미국 동부시간(ET) 장마감 후 오후 6시 = UTC 22:00 (서머타임 기준, 표준시엔 23:00과 1h 차이 발생 가능 — 오차 허용)
    - cron: "0 22 * * 2-6"   # 화~토 UTC (=월~금 미국장 마감 다음)
    # 분기 실적시즌 재무 강제갱신 (10-Q/10-K 몰림 시기 다음날) — 대략적 기준, 필요시 조정
    - cron: "0 12 20 2,5,8,11 *"
  workflow_dispatch:
    inputs:
      force_finance:
        description: "재무데이터를 캐시 무시하고 강제로 새로 받기"
        type: boolean
        default: false

jobs:
  screen:
    runs-on: ubuntu-latest
    steps:
      - name: 저장소 체크아웃
        uses: actions/checkout@v4

      - name: Python 설치
        uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: 패키지 설치
        run: pip install -r screening/requirements.txt

      - name: 주차(연도-주) 계산
        id: week
        run: echo "value=$(date +%G-W%V)" >> "$GITHUB_OUTPUT"

      - name: 재무데이터 캐시 복원 (주 단위)
        uses: actions/cache@v4
        id: finance-cache
        with:
          path: screening/.cache
          key: finance-cache-us-v1-${{ steps.week.outputs.value }}
          restore-keys: |
            finance-cache-us-v1-

      - name: 재무데이터 없거나 강제갱신 요청 시 새로 받기
        if: >-
          steps.finance-cache.outputs.cache-hit != 'true' ||
          github.event.inputs.force_finance == 'true'
        working-directory: screening
        env:
          FMP_API_KEY: ${{ secrets.FMP_API_KEY }}
        run: python data_pipeline.py --build --force

      - name: 스크리닝 실행 + JSON 저장
        working-directory: screening
        env:
          FMP_API_KEY: ${{ secrets.FMP_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python us_alpha.py --run --top 50 \
            --export-json "../web/data/results.json" \
            --filtered-json "../web/data/filtered_full.json"

      - name: 결과를 저장소에 커밋 (→ Vercel 자동 재배포 트리거)
        run: |
          git config user.name "screening-bot"
          git config user.email "screening-bot@users.noreply.github.com"
          git add web/data/results.json web/data/filtered_full.json
          git diff --cached --quiet || git commit -m "chore: 스크리닝 결과 자동 갱신 $(date +%Y-%m-%d)"
          git push
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/daily-screen.yml
git commit -m "ci: add daily US screening workflow"
```

(This workflow cannot be tested locally — it will be exercised for the first time after the GitHub repo + secrets are set up in Task 15.)

---

### Task 10: Web scaffold — copy portable files from the KOSPI project

**Files:**
- Copy: `web/app/globals.css`, `web/lib/utils.ts`, `web/tsconfig.json`, `web/next.config.js`, `web/components.json`, `web/components/ui/*.tsx` (9 files) — byte-for-byte from the source project, no US/Korea-specific content in any of them.
- Create: `web/package.json` (same deps, renamed package name)

**Interfaces:**
- Produces: a working `npm install` + buildable Next.js shell for Task 11 to fill in.

- [ ] **Step 1: Copy unchanged files**

```bash
SRC="C:/Users/lwswo/OneDrive/1. WS/2. Projects/stock_screen_web/web"
DST="C:/Users/lwswo/OneDrive/1. WS/2. Projects/us_stock_screen_web/web"
mkdir -p "$DST/app" "$DST/lib" "$DST/components/ui"

cp "$SRC/app/globals.css" "$DST/app/globals.css"
cp "$SRC/lib/utils.ts" "$DST/lib/utils.ts"
cp "$SRC/tsconfig.json" "$DST/tsconfig.json"
cp "$SRC/next.config.js" "$DST/next.config.js"
cp "$SRC/components.json" "$DST/components.json"
cp "$SRC"/components/ui/*.tsx "$DST/components/ui/"
```

- [ ] **Step 2: Create `web/package.json`**

```json
{
  "name": "us-stock-screening-web",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  },
  "dependencies": {
    "class-variance-authority": "^0.7.1",
    "clsx": "^2.1.1",
    "lucide-react": "^0.469.0",
    "next": "15.5.18",
    "radix-ui": "^1.1.3",
    "react": "19.1.0",
    "react-dom": "19.1.0",
    "tailwind-merge": "^3.0.2",
    "xlsx": "^0.18.5"
  },
  "devDependencies": {
    "@tailwindcss/postcss": "^4",
    "@types/node": "^20",
    "@types/react": "^19",
    "tailwindcss": "^4",
    "tw-animate-css": "^1.2.4",
    "typescript": "^5"
  }
}
```

- [ ] **Step 3: Install and verify**

```bash
cd web && npm install
```
Expected: installs without errors (warnings OK).

- [ ] **Step 4: Commit**

```bash
git add web/app/globals.css web/lib/utils.ts web/tsconfig.json web/next.config.js web/components.json web/components/ui web/package.json web/package-lock.json
git commit -m "chore: scaffold Next.js web app (ported shadcn/ui boilerplate)"
```

---

### Task 11: Web — results page + table + date formatting

**Files:**
- Create: `web/app/layout.tsx`
- Create: `web/lib/format.ts`
- Create: `web/app/page.tsx`
- Create: `web/app/ScreeningTable.tsx`
- Create: `web/app/StockProfileDialog.tsx` (verbatim port — no Korea-specific content)

**Interfaces:**
- Consumes: `web/data/results.json` shape from Task 8 (`stock_code, name, sector, mktcap_usd, price, per, pbr, roe_3y_avg, debt_ratio, div_yield, payout_ratio, score, profile`).
- Produces: renders the results table at `/`.

- [ ] **Step 1: Create `web/app/layout.tsx`**

```tsx
import "./globals.css";

export const metadata = {
  title: "미국 주식 스크리닝 — US Stock Alpha",
  description: "S&P 500+400+600 종목 스크리닝 결과",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" className="dark">
      <body className="min-h-screen bg-background font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
```

- [ ] **Step 2: Create `web/lib/format.ts`**

```ts
export function formatAsOfDate(yyyymmdd: string | null): string {
  if (!yyyymmdd || yyyymmdd.length !== 8) return yyyymmdd ?? "-";
  const year = yyyymmdd.slice(0, 4);
  const month = yyyymmdd.slice(4, 6);
  const day = yyyymmdd.slice(6, 8);
  return `${year}년 ${month}월 ${day}일`;
}
```

- [ ] **Step 3: Create `web/app/StockProfileDialog.tsx`** (verbatim port, no changes needed)

```tsx
"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";

export interface StockProfile {
  business: string;
  sector: string;
  products: string;
  competitors: string[];
}

const TEXT_SECTIONS: { key: "business" | "sector" | "products"; label: string }[] = [
  { key: "business", label: "사업 내용" },
  { key: "sector", label: "섹터" },
  { key: "products", label: "대표 상품·브랜드" },
];

function normalizeCompetitors(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((v): v is string => typeof v === "string" && v.trim().length > 0);
  }
  if (typeof value === "string") {
    return value.split(/,\s*/).map((s) => s.trim()).filter(Boolean);
  }
  return [];
}

export default function StockProfileDialog({
  open,
  onOpenChange,
  stockName,
  profile,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  stockName: string;
  profile: StockProfile | null | undefined;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{stockName} — 종목 프로필</DialogTitle>
        </DialogHeader>

        <div className="mt-2 rounded-2xl rounded-tl-none bg-muted p-4 text-sm leading-relaxed">
          {profile ? (
            <div className="space-y-3">
              {TEXT_SECTIONS.map(({ key, label }) => (
                <div key={key}>
                  <div className="font-medium text-foreground">{label}</div>
                  <div className="mt-0.5 text-muted-foreground">{profile[key]}</div>
                </div>
              ))}
              <div>
                <div className="font-medium text-foreground">주요 경쟁사</div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {normalizeCompetitors(profile.competitors).map((competitor) => (
                    <Badge key={competitor} variant="secondary">
                      {competitor}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            "아직 분석이 준비되지 않았습니다."
          )}
        </div>

        {profile && (
          <p className="mt-1 text-xs text-muted-foreground">
            AI가 생성한 정보로 부정확하거나 최신이 아닐 수 있습니다.
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: Create `web/app/ScreeningTable.tsx`**

```tsx
"use client";

import { useMemo, useState } from "react";
import { ArrowUpDown, ArrowUp, ArrowDown, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import StockProfileDialog, { StockProfile } from "./StockProfileDialog";

type ResultRow = Record<string, string | number | null> & { profile?: StockProfile | null };

const TWO_DECIMAL_RIGHT_ALIGN = new Set(["per", "pbr", "roe_3y_avg", "debt_ratio", "div_yield", "payout_ratio"]);
const FOUR_DECIMAL_RIGHT_ALIGN = new Set(["score"]);
const RIGHT_ALIGN_ONLY = new Set(["price", "mktcap_usd"]);

export default function ScreeningTable({
  columns,
  labels,
  rows,
}: {
  columns: string[];
  labels: Record<string, string>;
  rows: ResultRow[];
}) {
  const [sortKey, setSortKey] = useState<string>("score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [liveRows, setLiveRows] = useState<ResultRow[]>(rows);
  const [priceAsOf, setPriceAsOf] = useState<string | null>(null);
  const [priceLoading, setPriceLoading] = useState(false);
  const [priceError, setPriceError] = useState<string | null>(null);
  const [dialogRow, setDialogRow] = useState<ResultRow | null>(null);

  async function refreshPrices() {
    setPriceLoading(true);
    setPriceError(null);
    try {
      const tickers = rows.map((r) => String(r.stock_code)).join(",");
      const res = await fetch(`/api/prices?tickers=${tickers}`, { cache: "no-store" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "시세 조회 실패");

      setLiveRows(
        rows.map((r) => {
          const ticker = String(r.stock_code);
          const live = data.prices[ticker];
          if (!live) return r;
          return { ...r, price: live.price } as ResultRow;
        })
      );
      setPriceAsOf(data.as_of);
    } catch (e: any) {
      setPriceError(e.message ?? String(e));
    } finally {
      setPriceLoading(false);
    }
  }

  const sorted = useMemo(() => {
    const copy = [...liveRows];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "asc" ? av - bv : bv - av;
      }
      return sortDir === "asc"
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
    return copy.slice(0, 50);
  }, [liveRows, sortKey, sortDir]);

  function onSort(col: string) {
    if (col === sortKey) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(col);
      setSortDir("desc");
    }
  }

  function SortIcon({ col }: { col: string }) {
    if (sortKey !== col) return <ArrowUpDown className="ml-1 inline size-3 opacity-40" />;
    return sortDir === "asc" ? <ArrowUp className="ml-1 inline size-3" /> : <ArrowDown className="ml-1 inline size-3" />;
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" onClick={refreshPrices} disabled={priceLoading}>
          <RefreshCw className={cn("size-3.5", priceLoading && "animate-spin")} />
          {priceLoading ? "불러오는 중…" : "최신 종가 새로고침"}
        </Button>
        {priceAsOf && (
          <span className="text-xs text-muted-foreground">시세 기준일: {priceAsOf}</span>
        )}
        {priceError && <span className="text-xs text-destructive">{priceError}</span>}
      </div>

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-10">#</TableHead>
              {columns.map((col) => (
                <TableHead key={col} className={cn("cursor-pointer select-none", alignClass(col))} onClick={() => onSort(col)}>
                  {labels[col] ?? col}
                  <SortIcon col={col} />
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((row, i) => (
              <TableRow key={(row.stock_code as string) ?? i}>
                <TableCell className="text-muted-foreground">{i + 1}</TableCell>
                {columns.map((col) => (
                  <TableCell key={col} className={alignClass(col)}>
                    {col === "name" ? (
                      <button
                        type="button"
                        className="underline decoration-dotted underline-offset-2 hover:text-primary"
                        onClick={() => setDialogRow(row)}
                      >
                        {formatValue(row[col], col)}
                      </button>
                    ) : (
                      formatValue(row[col], col)
                    )}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <StockProfileDialog
        open={dialogRow !== null}
        onOpenChange={(open) => !open && setDialogRow(null)}
        stockName={dialogRow ? String(dialogRow.stock_code ?? "") : ""}
        profile={dialogRow?.profile}
      />
    </div>
  );
}

function alignClass(col: string): string {
  if (TWO_DECIMAL_RIGHT_ALIGN.has(col) || FOUR_DECIMAL_RIGHT_ALIGN.has(col) || RIGHT_ALIGN_ONLY.has(col)) {
    return "text-right";
  }
  return "";
}

function formatValue(v: string | number | null, col?: string) {
  if (v === null || v === undefined) return "-";
  if (typeof v === "number") {
    if (col === "mktcap_usd") {
      return "$" + v.toLocaleString("en-US", { maximumFractionDigits: 0 });
    }
    if (col === "price") {
      return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    if (col && FOUR_DECIMAL_RIGHT_ALIGN.has(col)) {
      return v.toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 });
    }
    if (col && TWO_DECIMAL_RIGHT_ALIGN.has(col)) {
      return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    return Number.isInteger(v) ? v.toLocaleString("en-US") : v.toFixed(3);
  }
  return v;
}
```

- [ ] **Step 5: Create `web/app/page.tsx`**

```tsx
import fs from "fs";
import path from "path";
import ScreeningTable from "./ScreeningTable";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatAsOfDate } from "@/lib/format";
import { StockProfile } from "./StockProfileDialog";

export const dynamic = "force-static";

type ResultRow = Record<string, string | number | null> & { profile?: StockProfile | null };

interface ResultsPayload {
  as_of_date: string | null;
  generated_at: string | null;
  quote_text: string | null;
  quote_author: string | null;
  universe_total: number;
  universe_passed: number;
  columns: string[];
  column_labels_ko: Record<string, string>;
  results: ResultRow[];
}

function loadResults(): ResultsPayload {
  const filePath = path.join(process.cwd(), "data", "results.json");
  const raw = fs.readFileSync(filePath, "utf-8");
  return JSON.parse(raw);
}

export default function Home() {
  const data = loadResults();

  return (
    <main className="mx-auto max-w-6xl px-5 py-10">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">미국 가치투자 스크리닝</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {data.quote_text ? `"${data.quote_text}" — ${data.quote_author}` : "S&P 500+400+600 종목 스크리닝"}
        </p>
      </div>

      {data.results.length === 0 ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">
            아직 결과가 없습니다. GitHub Actions가 처음 실행되면 자동으로 채워집니다.
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="mb-5 flex flex-wrap items-center gap-2">
            <Badge variant="secondary">가격 기준일 {formatAsOfDate(data.as_of_date)}</Badge>
            <Badge variant="outline">
              갱신 {data.generated_at ? new Date(data.generated_at).toLocaleString("ko-KR") : "-"}
            </Badge>
          </div>

          <ScreeningTable columns={data.columns} labels={data.column_labels_ko} rows={data.results} />
        </>
      )}
    </main>
  );
}
```

- [ ] **Step 6: Manual verification**

```bash
cd web && npm run dev
```
Open `http://localhost:3000` — expect the empty-state card ("아직 결과가 없습니다...") since `web/data/results.json` still has the Task 1 placeholder. No console errors.

- [ ] **Step 7: Commit**

```bash
git add web/app/layout.tsx web/lib/format.ts web/app/page.tsx web/app/ScreeningTable.tsx web/app/StockProfileDialog.tsx
git commit -m "feat: add results page and sortable screening table"
```

---

### Task 12: Web — admin gate + update-finance trigger

**Files:**
- Create: `web/app/AdminGate.tsx` (verbatim port)
- Create: `web/app/UpdateControls.tsx` (adapted — drops the "재무데이터도 강제로 새로 받기" checkbox copy that referenced KOSPI-specific TTM quarter logic, keeps the force-refresh checkbox)
- Create: `web/app/api/admin-login/route.ts` (verbatim port)
- Create: `web/app/api/update-finance/route.ts` (adapted — no `ttm_quarter` input, everything else identical)
- Modify: `web/app/page.tsx` (wrap `UpdateControls` in `AdminGate`)

**Interfaces:**
- Consumes: `ADMIN_PASSWORD`, `GH_PAT`, `GH_OWNER`, `GH_REPO` env vars (set in Vercel, Task 15).
- Produces: `POST /api/admin-login`, `POST /api/update-finance` — dispatches `.github/workflows/daily-screen.yml` (Task 9).

- [ ] **Step 1: Create `web/app/api/admin-login/route.ts`**

```ts
import { createHmac, timingSafeEqual } from "crypto";

function sessionToken(): string {
  const secret = process.env.ADMIN_PASSWORD ?? "";
  return createHmac("sha256", secret).update("admin").digest("hex");
}

export async function POST(req: Request) {
  const adminPassword = process.env.ADMIN_PASSWORD;
  if (!adminPassword) {
    return Response.json({ error: "서버에 ADMIN_PASSWORD 환경변수가 설정되어 있지 않습니다." }, { status: 500 });
  }

  const body = await req.json().catch(() => ({}));
  const password = String(body?.password ?? "");

  const a = Buffer.from(password);
  const b = Buffer.from(adminPassword);
  const match = a.length === b.length && timingSafeEqual(a, b);
  if (!match) {
    return Response.json({ error: "비밀번호가 일치하지 않습니다." }, { status: 401 });
  }

  const token = sessionToken();
  const res = Response.json({ ok: true });
  const secureFlag = process.env.NODE_ENV === "production" ? "; Secure" : "";
  res.headers.set(
    "Set-Cookie",
    `admin_session=${token}; Path=/; HttpOnly; Max-Age=86400; SameSite=Lax${secureFlag}`
  );
  return res;
}
```

- [ ] **Step 2: Create `web/app/api/update-finance/route.ts`**

```ts
import { createHmac, timingSafeEqual } from "crypto";

function isAdminRequest(req: Request): boolean {
  const adminPassword = process.env.ADMIN_PASSWORD;
  if (!adminPassword) return false;
  const cookieHeader = req.headers.get("cookie") ?? "";
  const match = cookieHeader.match(/admin_session=([^;]+)/);
  if (!match) return false;
  const expected = createHmac("sha256", adminPassword).update("admin").digest("hex");
  const a = Buffer.from(match[1]);
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

export async function POST(req: Request) {
  if (!isAdminRequest(req)) {
    return Response.json({ error: "관리자 인증이 필요합니다." }, { status: 401 });
  }

  const token = process.env.GH_PAT;
  const owner = process.env.GH_OWNER;
  const repo = process.env.GH_REPO;

  if (!token || !owner || !repo) {
    return Response.json(
      { error: "서버 환경변수(GH_PAT / GH_OWNER / GH_REPO)가 설정되어 있지 않습니다. Vercel 프로젝트 설정에서 등록해주세요." },
      { status: 500 }
    );
  }

  let forceFinance = false;
  try {
    const body = await req.json();
    forceFinance = Boolean(body?.forceFinance);
  } catch {
    // body 없이 호출된 경우 기본값 사용
  }

  const res = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/actions/workflows/daily-screen.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ ref: "main", inputs: { force_finance: String(forceFinance) } }),
    }
  );

  if (!res.ok) {
    const text = await res.text();
    return Response.json({ error: `GitHub 워크플로우 실행 요청 실패 (${res.status}): ${text}` }, { status: 502 });
  }

  return Response.json({
    ok: true,
    message: "업데이트가 요청되었습니다. GitHub Actions에서 실행 중이며, 완료 후 자동으로 사이트가 재배포됩니다 (보통 2~10분 정도 걸립니다).",
  });
}
```

- [ ] **Step 3: Create `web/app/AdminGate.tsx`** (verbatim port)

```tsx
"use client";

import { useState, type ReactNode } from "react";
import { ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

export default function AdminGate({ children }: { children: ReactNode }) {
  const [unlocked, setUnlocked] = useState(false);
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleLogin() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/admin-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "로그인 실패");
      setUnlocked(true);
      setOpen(false);
      setPassword("");
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }

  if (unlocked) {
    return <>{children}</>;
  }

  return (
    <div className="mt-10 flex justify-center border-t pt-6">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button variant="ghost" size="sm" className="text-muted-foreground">
            <ShieldCheck className="size-3.5" />
            관리자
          </Button>
        </DialogTrigger>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>관리자 로그인</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <Input
              type="password"
              placeholder="비밀번호"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleLogin()}
            />
            {error && <span className="text-xs text-destructive">{error}</span>}
            <Button onClick={handleLogin} disabled={loading || !password}>
              {loading ? "확인 중…" : "로그인"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
```

- [ ] **Step 4: Create `web/app/UpdateControls.tsx`**

```tsx
"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export default function UpdateControls() {
  const [forceFinance, setForceFinance] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);

  async function handleUpdate() {
    setLoading(true);
    setMessage(null);
    try {
      const res = await fetch("/api/update-finance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ forceFinance }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "요청 실패");
      setMessage({ text: data.message, error: false });
    } catch (e: any) {
      setMessage({ text: e.message ?? String(e), error: true });
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="mb-5 py-4">
      <CardContent className="flex flex-wrap items-center gap-4">
        <Button onClick={handleUpdate} disabled={loading} size="sm">
          <RefreshCw className={cn("size-3.5", loading && "animate-spin")} />
          {loading ? "요청 중…" : "스크리닝 업데이트 실행"}
        </Button>

        <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
          <Checkbox checked={forceFinance} onCheckedChange={(v) => setForceFinance(v === true)} />
          재무데이터도 강제로 새로 받기 (평소엔 체크 안 해도 됨, 몇 분 더 걸림)
        </label>

        {message && (
          <span className={cn("text-xs", message.error ? "text-destructive" : "text-green-500")}>
            {message.text}
          </span>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 5: Wire `UpdateControls` into `page.tsx` behind `AdminGate`**

In `web/app/page.tsx`, add imports and render at the bottom of `Home()`:

```tsx
import AdminGate from "./AdminGate";
import UpdateControls from "./UpdateControls";
```

and just before the closing `</main>`:

```tsx
      <AdminGate>
        <UpdateControls />
      </AdminGate>
```

- [ ] **Step 6: Manual verification**

```bash
cd web && npm run dev
```
Click "관리자" at the bottom of the page → dialog opens. (Login will fail until `ADMIN_PASSWORD` is set in `.env.local` — that's expected at this stage; full verification happens in Task 16.)

- [ ] **Step 7: Commit**

```bash
git add web/app/AdminGate.tsx web/app/UpdateControls.tsx web/app/api/admin-login web/app/api/update-finance web/app/page.tsx
git commit -m "feat: add admin-gated screening update trigger"
```

---

### Task 13: Web — live price refresh + filtered download

**Files:**
- Create: `web/app/api/prices/route.ts` (FMP-backed, replaces KRX date-walking logic)
- Create: `web/app/api/filtered/route.ts` (verbatim port)
- Create: `web/app/FilteredDownloadButton.tsx` (adapted filename/labels)
- Modify: `web/app/page.tsx` (render `FilteredDownloadButton`)

**Interfaces:**
- Consumes: `FMP_API_KEY` (Vercel env var, server-side only — never exposed to the browser).
- Produces: `GET /api/prices?tickers=A,B,C` → `{ as_of: string, prices: { [ticker]: { price: number } } }`. `GET /api/filtered` → serves `web/data/filtered_full.json`.

- [ ] **Step 1: Create `web/app/api/prices/route.ts`**

```ts
import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

/**
 * FMP의 실시간(지연) 시세 엔드포인트로 최신가를 다시 불러온다.
 * "최신 종가"가 아니라 FMP가 제공하는 최신 체결가/지연 시세임에 유의.
 */
export async function GET(req: NextRequest) {
  const tickersParam = req.nextUrl.searchParams.get("tickers");
  if (!tickersParam) {
    return Response.json({ error: "tickers 파라미터가 필요합니다." }, { status: 400 });
  }

  const key = process.env.FMP_API_KEY;
  if (!key) {
    return Response.json({ error: "서버에 FMP_API_KEY 환경변수가 설정되어 있지 않습니다." }, { status: 500 });
  }

  const url = `https://financialmodelingprep.com/api/v3/quote/${tickersParam}?apikey=${key}`;

  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      return Response.json({ error: `FMP 조회 실패 (${res.status})` }, { status: 502 });
    }
    const rows: any[] = await res.json();

    const prices: Record<string, { price: number }> = {};
    for (const r of rows) {
      prices[r.symbol] = { price: r.price };
    }

    return Response.json({ as_of: new Date().toISOString(), prices });
  } catch (e: any) {
    return Response.json({ error: e.message ?? String(e) }, { status: 500 });
  }
}
```

- [ ] **Step 2: Create `web/app/api/filtered/route.ts`** (verbatim port)

```ts
import fs from "fs";
import path from "path";

export const dynamic = "force-static";

export async function GET() {
  const filePath = path.join(process.cwd(), "data", "filtered_full.json");
  if (!fs.existsSync(filePath)) {
    return Response.json({ error: "필터통과 데이터가 아직 생성되지 않았습니다." }, { status: 404 });
  }
  const raw = fs.readFileSync(filePath, "utf-8");
  return new Response(raw, { headers: { "Content-Type": "application/json" } });
}
```

- [ ] **Step 3: Create `web/app/FilteredDownloadButton.tsx`**

```tsx
"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type FilteredRow = Record<string, string | number | null>;

interface FilteredPayload {
  columns: string[];
  column_labels_ko: Record<string, string>;
  results: FilteredRow[];
}

export default function FilteredDownloadButton({ passed, total }: { passed: number; total: number }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/filtered", { cache: "no-store" });
      if (!res.ok) throw new Error("필터통과 종목 데이터를 불러오지 못했습니다.");
      const data: FilteredPayload = await res.json();

      const XLSX = await import("xlsx");
      const rows = data.results.map((r) => {
        const out: Record<string, string | number | null> = {};
        for (const c of data.columns) {
          out[data.column_labels_ko[c] ?? c] = r[c];
        }
        return out;
      });
      const sheet = XLSX.utils.json_to_sheet(rows);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, sheet, "필터통과종목");
      XLSX.writeFile(wb, `필터통과종목_${data.results.length}종목.xlsx`);
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-1">
      <Badge variant="secondary" className={cn("cursor-pointer select-none", loading && "opacity-60")} onClick={loading ? undefined : handleClick}>
        <Download className="mr-1 size-3" />
        {loading ? "다운로드 중…" : `필터 통과 ${passed} / ${total}`}
      </Badge>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </span>
  );
}
```

- [ ] **Step 4: Wire into `page.tsx`**

Add `import FilteredDownloadButton from "./FilteredDownloadButton";` and, inside the badge row, add:
```tsx
<FilteredDownloadButton passed={data.universe_passed} total={data.universe_total} />
```

- [ ] **Step 5: Commit**

```bash
git add web/app/api/prices web/app/api/filtered web/app/FilteredDownloadButton.tsx web/app/page.tsx
git commit -m "feat: add live price refresh and filtered-list Excel download"
```

---

### Task 14: Web — algorithm explanation panel

**Files:**
- Create: `web/app/AlgorithmInfo.tsx`
- Modify: `web/app/page.tsx` (render it above the table)

**Interfaces:**
- Produces: static informational panel, no data dependencies.

- [ ] **Step 1: Create `web/app/AlgorithmInfo.tsx`**

```tsx
"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Info, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";

export default function AlgorithmInfo() {
  const [open, setOpen] = useState(false);

  return (
    <div className="mb-5 space-y-3">
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger asChild>
          <Button variant="outline" size="sm">
            <Info className="size-3.5" />
            이 스크리닝은 어떤 기준으로 종목을 골랐나요?
            {open ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          </Button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <Card className="mt-3 py-5">
            <CardContent className="space-y-4 text-sm leading-relaxed text-foreground/90">
              <p className="text-muted-foreground">
                핵심 아이디어:{" "}
                <b className="text-foreground">실적·경쟁력은 괜찮은데 주가만 안 오른 종목을 찾아서 모아두고 기다린다.</b>
              </p>

              <div>
                <h4 className="mb-2 font-semibold text-foreground">1단계 — 하드 필터 (자동 제외 기준)</h4>
                <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                  <li>시가총액 $100M 이상 (상한 없음)</li>
                  <li>일평균 거래대금 하한 (유동성 필터)</li>
                  <li>부채비율(부채/자본) 200% 초과 제외</li>
                  <li>ROE 5% 미만 제외</li>
                  <li>최근 영업이익(TTM 기준) 적자 제외</li>
                  <li>최근 3개월 수익률 +60% 이상인 테마 급등 종목 제외</li>
                </ul>
              </div>

              <div>
                <h4 className="mb-2 font-semibold text-foreground">2단계 — 4대 팩터 종합 점수</h4>
                <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                  <li><b className="text-foreground">체력 (30%)</b> — ROE 수준·안정성, 영업이익률, 부채비율, 매출 성장</li>
                  <li><b className="text-foreground">가격 (28%)</b> — PER·PBR 저평가 정도</li>
                  <li><b className="text-foreground">★괴리 (27%, 핵심 팩터)</b> — 실적은 개선되는데 주가는 빠진 정도</li>
                  <li><b className="text-foreground">환원여력 (15%)</b> — 배당 확대 여력 (낮은 배당성향 + 순현금 보유)</li>
                </ul>
                <p className="mt-2 text-muted-foreground">
                  각 팩터는 전체 종목 대비 백분위로 점수화되며, 위 가중치로 합산해{" "}
                  <b className="text-foreground">종합점수</b>를 만듭니다.
                </p>
              </div>

              <div>
                <h4 className="mb-2 font-semibold text-foreground">데이터 기준</h4>
                <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                  <li>시세/재무데이터: Financial Modeling Prep(FMP) API</li>
                  <li>대상: S&P 500 + S&P 400(중형) + S&P 600(소형) 종목</li>
                </ul>
              </div>
            </CardContent>
          </Card>
        </CollapsibleContent>
      </Collapsible>

      <Alert className="border-muted-foreground/20 bg-transparent py-2.5">
        <ShieldAlert />
        <AlertDescription className="text-xs text-muted-foreground">
          이 페이지의 정보는 참고용 데이터이며 투자 조언이 아닙니다. 종목 선정 기준과 점수는
          특정 투자 전략을 기계적으로 구현한 것으로, 정확성이나 완전성을 보장하지 않습니다.
          투자 판단과 그에 따른 손익에 대한 책임은 전적으로 투자자 본인에게 있습니다.
        </AlertDescription>
      </Alert>
    </div>
  );
}
```

- [ ] **Step 2: Wire into `page.tsx`**

Add `import AlgorithmInfo from "./AlgorithmInfo";` and render `<AlgorithmInfo />` right before `<ScreeningTable ... />`.

- [ ] **Step 3: Commit**

```bash
git add web/app/AlgorithmInfo.tsx web/app/page.tsx
git commit -m "feat: add algorithm explanation panel"
```

---

### Task 15: Non-developer setup guide (`README.md`)

**Files:**
- Create: `README.md`

**Interfaces:**
- No code interfaces — this is the human-facing setup checklist referenced by the design spec section 8.

- [ ] **Step 1: Write `README.md`**

```markdown
# 미국 주식 스크리닝 웹

S&P 500+400+600 종목을 4대 팩터(체력/가격/괴리/환원여력)로 매일 자동 스크리닝하는
웹사이트. GitHub Actions가 매일 자동으로 스크리닝을 돌려 `web/data/results.json`을
갱신하면, Vercel이 그 커밋을 감지해 자동으로 재배포한다. 별도 DB 없음.

## 구조

```
screening/          파이썬 스크리닝 엔진 (fmp_client.py, data_pipeline.py, us_alpha.py)
web/                 Next.js 웹사이트
.github/workflows/   매일 자동 실행 스케줄 (workflow_dispatch로 수동/웹 실행도 가능)
```

## 최초 설정 (한 번만) — 아래 순서대로 진행

### 1. Financial Modeling Prep(FMP) 계정 + API 키
1. https://site.financialmodelingprep.com 접속 → 무료 회원가입
2. 대시보드에서 API 키 복사해둔다

### 2. Anthropic API 키 (AI 종목 프로필 카드용)
1. https://console.anthropic.com 접속 → 계정 생성/로그인
2. API Keys 메뉴에서 새 키 발급, 복사해둔다

### 3. GitHub 저장소 만들기
이 폴더 전체를 새 GitHub 저장소에 push한다.

```bash
git remote add origin <본인의 GitHub 저장소 URL>
git push -u origin master:main
```

### 4. GitHub Secrets 등록
저장소 페이지 → Settings → Secrets and variables → Actions → New repository secret

- `FMP_API_KEY` : 1번에서 발급받은 키
- `ANTHROPIC_API_KEY` : 2번에서 발급받은 키

### 5. GitHub Personal Access Token 발급 (웹사이트가 Actions를 원격 실행시키기 위해 필요)
1. GitHub 우측 상단 프로필 → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token
2. Repository access: 이 저장소만 선택
3. Permissions → Actions: Read and write 로 설정
4. 생성된 토큰(ghp_로 시작)을 복사해둔다 (다시 못 봄, 꼭 메모)

### 6. GitHub Actions 활성화 확인
저장소 페이지 → Actions 탭 → 워크플로우가 보이는지 확인. 처음엔 수동으로 한 번
실행해서 잘 도는지 확인 (Actions → 일일 스크리닝 (미국 주식) → Run workflow).

### 7. Vercel 배포
1. https://vercel.com 가입 (GitHub 계정으로 로그인 추천)
2. "Add New… → Project" → 방금 만든 GitHub 저장소 선택
3. **Root Directory를 `web`으로 지정** (중요 — 안 하면 빌드 실패함)
4. Framework Preset은 Next.js가 자동 인식됨
5. **Environment Variables**에 아래 항목 추가 (Deploy 누르기 전에):
   - `FMP_API_KEY` : 1번 키 (최신 종가 새로고침용)
   - `GH_PAT` : 5번에서 발급받은 GitHub 토큰
   - `GH_OWNER` : GitHub 사용자명
   - `GH_REPO` : 저장소 이름
   - `ADMIN_PASSWORD` : 직접 정한 관리자 비밀번호 (사이트 하단 "관리자" 로그인용)
6. Deploy 클릭

이후로는:
- GitHub Actions가 매일 `results.json`을 커밋할 때마다 Vercel이 자동 재배포
- 웹사이트 하단 "관리자" 로그인 후 "스크리닝 업데이트 실행" 버튼을 누르면
  그 즉시 GitHub Actions가 실행되고, 끝나면 자동으로 사이트가 갱신됨

## 로컬에서 테스트하기

```bash
cd screening
pip install -r requirements.txt
setx FMP_API_KEY "발급받은키"
setx ANTHROPIC_API_KEY "발급받은키"
python data_pipeline.py --build
python us_alpha.py --run --top 50 --export-json "../web/data/results.json" --filtered-json "../web/data/filtered_full.json"
```

```bash
cd web
npm install
npm run dev
```

http://localhost:3000 에서 확인. `/api/prices`, `/api/update-finance`를 로컬에서
테스트하려면 `web/.env.local` 파일을 만들고 아래처럼 채워넣는다 (git에 올라가지 않음):

```
FMP_API_KEY=발급받은키
GH_PAT=발급받은토큰
GH_OWNER=본인깃헙아이디
GH_REPO=저장소이름
ADMIN_PASSWORD=원하는비밀번호
```

## 참고 사항

- 유니버스(S&P 500+400+600) 및 재무비율 필드명은 FMP 요금제/API 버전에 따라 조회
  방식이 달라질 수 있다. `screening/fmp_client.py`와 `screening/data_pipeline.py`의
  주석에 확인 방법이 적혀 있다.
- 하드 필터/팩터 가중치의 상세 근거는 `docs/superpowers/specs/2026-08-14-us-stock-screening-design.md` 참고.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add non-developer setup guide"
```

---

### Task 16: End-to-end local verification

**Files:** none (verification only)

**Interfaces:** none — this task confirms Tasks 1–15 integrate correctly before handing off to the user for external-account setup.

- [ ] **Step 1: Run the full Python test suite**

```bash
cd screening && python -m pytest -v
```
Expected: all tests pass (quotes, profile_cache, stock_profile, fmp_client, data_pipeline, scoring, filters_and_composite, load_real).

- [ ] **Step 2: Run demo mode**

```bash
python us_alpha.py --demo
```
Expected: prints filter stats and a top-15 table with no errors, using purely synthetic data (no API keys needed).

- [ ] **Step 3: Build the web app**

```bash
cd ../web && npm run build
```
Expected: builds successfully against the Task 1 placeholder `results.json` (empty-state).

- [ ] **Step 4: Run the dev server and manually click through**

```bash
npm run dev
```
Open `http://localhost:3000` and confirm:
- Page loads with the empty-state card (no `results.json` data yet)
- "이 스크리닝은 어떤 기준으로 종목을 골랐나요?" panel expands/collapses
- "관리자" dialog opens (login will fail without `ADMIN_PASSWORD` set — expected)

- [ ] **Step 5: Report status to the user**

Summarize: all code is written and tested locally with synthetic/mocked data; the only remaining work is the user's own account setup (FMP key, Anthropic key, GitHub repo + secrets + PAT, Vercel project + env vars) per `README.md`, after which the first live `python data_pipeline.py --build` + `python us_alpha.py --run` should be run once (locally or by manually triggering the GitHub Action) to populate real `results.json` and confirm the FMP field-name assumptions from Task 4/5 hold in practice — flag that this is the first point where real API responses get validated, and small field-mapping fixes in `data_pipeline.py` may be needed at that point.

- [ ] **Step 6: No commit needed** (verification only; if Step 4 surfaces bugs, fix them in the relevant task's files and commit a fix)
