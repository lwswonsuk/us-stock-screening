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
