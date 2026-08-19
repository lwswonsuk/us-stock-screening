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
