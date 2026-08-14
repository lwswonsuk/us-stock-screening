import pytest
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


def test_get_universe_raises_on_empty_fetch(monkeypatch, tmp_path):
    """Verify that empty fetch result (structural regression) raises RuntimeError instead of silently continuing."""
    def fake_fetch(url, symbol_col_candidates=None):
        if "400" in url:
            # Simulate structural regression: fetch returns 0 rows
            return pd.DataFrame({"ticker": [], "name": [], "sector": []})
        if "500" in url:
            return pd.DataFrame({"ticker": ["AAPL", "MSFT"], "name": ["Apple Inc.", "Microsoft Corp."], "sector": ["Technology", "Technology"]})
        return pd.DataFrame({"ticker": ["WWW"], "name": ["Www Corp"], "sector": ["Energy"]})

    monkeypatch.setattr(wiki_universe, "fetch_index_table", fake_fetch)
    monkeypatch.setattr(wiki_universe, "UNIVERSE_CACHE", tmp_path / "universe.parquet")

    with pytest.raises(RuntimeError, match="fetch_index_table returned 0 rows"):
        wiki_universe.get_universe(force=True)
