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
    "interest_coverage": "이자보상배율(배)", "div_yield": "배당수익률(%)",
    "payout_ratio_pct": "배당성향(%)", "buyback_rate_pct": "자사주매입률(%)",
    "score": "종합점수",
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
