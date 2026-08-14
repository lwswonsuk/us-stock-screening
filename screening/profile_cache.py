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
