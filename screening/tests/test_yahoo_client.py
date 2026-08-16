import pandas as pd

import yahoo_client


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_normalize_ticker_replaces_dot_with_hyphen():
    assert yahoo_client._normalize_ticker("BRK.B") == "BRK-B"
    assert yahoo_client._normalize_ticker("AAPL") == "AAPL"


def test_get_daily_prices_returns_dataframe_sorted_ascending(monkeypatch):
    payload = {
        "chart": {
            "result": [{
                "timestamp": [1786368600, 1786455000],
                "indicators": {"quote": [{"close": [228.0, 230.0]}]},
            }]
        }
    }

    def fake_get(url, params=None, headers=None, timeout=None):
        assert url.endswith("/AAPL")
        assert params["interval"] == "1d"
        return _FakeResponse(payload)

    monkeypatch.setattr(yahoo_client.requests, "get", fake_get)

    df = yahoo_client.get_daily_prices("AAPL", days=380)
    assert list(df["close"]) == [228.0, 230.0]
    assert list(df.columns) == ["date", "close"]


def test_get_daily_prices_normalizes_dotted_ticker_in_url(monkeypatch):
    payload = {"chart": {"result": [{"timestamp": [1786368600], "indicators": {"quote": [{"close": [450.0]}]}}]}}

    def fake_get(url, params=None, headers=None, timeout=None):
        assert url.endswith("/BRK-B")
        return _FakeResponse(payload)

    monkeypatch.setattr(yahoo_client.requests, "get", fake_get)

    df = yahoo_client.get_daily_prices("BRK.B")
    assert list(df["close"]) == [450.0]


def test_get_daily_prices_returns_empty_dataframe_when_no_result(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse({"chart": {"result": None}})

    monkeypatch.setattr(yahoo_client.requests, "get", fake_get)

    df = yahoo_client.get_daily_prices("ZZZZ")
    assert df.empty
    assert list(df.columns) == ["date", "close"]


def test_get_daily_prices_returns_empty_dataframe_when_no_timestamps(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse({"chart": {"result": [{"timestamp": None, "indicators": {"quote": [{}]}}]}})

    monkeypatch.setattr(yahoo_client.requests, "get", fake_get)

    df = yahoo_client.get_daily_prices("ZZZZ")
    assert df.empty


def test_get_daily_prices_drops_rows_with_null_close(monkeypatch):
    payload = {
        "chart": {
            "result": [{
                "timestamp": [1786368600, 1786455000, 1786541400],
                "indicators": {"quote": [{"close": [228.0, None, 230.0]}]},
            }]
        }
    }

    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse(payload)

    monkeypatch.setattr(yahoo_client.requests, "get", fake_get)

    df = yahoo_client.get_daily_prices("AAPL")
    assert list(df["close"]) == [228.0, 230.0]
