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


def test_get_quotes_chunks_large_ticker_lists(monkeypatch):
    tickers = [f"TCK{i:04d}" for i in range(250)]  # > 2 batches of 100
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        # Extract the batch of symbols requested from the URL path.
        batch_str = url.split("quote/", 1)[1]
        symbols = batch_str.split(",")
        payload = [
            {"symbol": s, "price": 1.0, "marketCap": 1_000_000, "avgVolume": 1_000}
            for s in symbols
        ]
        return _FakeResponse(payload)

    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setattr(fmp_client.requests, "get", fake_get)

    df = fmp_client.get_quotes(tickers)

    assert len(calls) == 3  # 100 + 100 + 50
    assert len(df) == 250
    assert set(df.index) == set(tickers)


def test_get_quotes_warns_on_partial_coverage(monkeypatch):
    tickers = ["AAPL", "MSFT", "GOOG"]

    def fake_get(url, params=None, timeout=None):
        # Simulate FMP dropping one symbol from the response.
        payload = [
            {"symbol": "AAPL", "price": 1.0, "marketCap": 1_000_000, "avgVolume": 1_000},
            {"symbol": "MSFT", "price": 2.0, "marketCap": 2_000_000, "avgVolume": 2_000},
        ]
        return _FakeResponse(payload)

    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setattr(fmp_client.requests, "get", fake_get)

    with pytest.warns(UserWarning, match="부분 커버리지"):
        df = fmp_client.get_quotes(tickers)
    assert len(df) == 2


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
