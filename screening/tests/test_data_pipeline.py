# screening/tests/test_data_pipeline.py
import numpy as np
import pandas as pd
import pytest

from data_pipeline import (
    _compute_buyback_rate,
    build_finance_cache,
    compute_return_and_drawdown,
    fetch_finance_one,
    get_full_universe,
)


def test_compute_return_and_drawdown_from_price_series():
    dates = pd.date_range("2025-08-01", periods=260, freq="B")
    closes = np.linspace(100, 130, len(dates))
    closes[-20:] = closes[-20:] * 0.80
    df = pd.DataFrame({"date": dates, "close": closes})

    ret_3m, ret_12m, drawdown_52w, pct_above_52w_low = compute_return_and_drawdown(df)

    assert ret_3m < 0
    assert ret_12m > -0.5
    assert drawdown_52w > 0
    assert pct_above_52w_low >= 0


def test_compute_buyback_rate_positive_when_shares_decline():
    assert _compute_buyback_rate(shares=95.0, prev_shares=100.0) == pytest.approx(0.05)


def test_compute_buyback_rate_nan_when_no_prior_value():
    assert np.isnan(_compute_buyback_rate(shares=95.0, prev_shares=None))
    assert np.isnan(_compute_buyback_rate(shares=95.0, prev_shares=np.nan))


def test_fetch_finance_one_computes_op_margin_and_debt_ratio(monkeypatch):
    """필드 값은 2026-08-14 실제 Finnhub API 응답(AAPL)으로 검증된 실제 스케일을 반영한다:
    roeTTM/operatingMarginTTM/payoutRatioTTM/revenueGrowthTTMYoy는 이미 퍼센트 값이고,
    totalDebt/totalEquityAnnual만 소수다."""
    import finnhub_client

    monkeypatch.setattr(
        finnhub_client, "get_company_profile",
        lambda ticker: {"shareOutstanding": 15_200.0},
    )
    monkeypatch.setattr(
        finnhub_client, "get_basic_financials",
        lambda ticker: {
            "roeTTM": 15.0,                          # 이미 퍼센트
            "totalDebt/totalEquityAnnual": 0.8,        # 소수
            "operatingMarginTTM": 22.0,               # 이미 퍼센트
            "peTTM": 18.0,
            "pbAnnual": 6.0,
            "dividendYieldIndicatedAnnual": 0.5,
            "payoutRatioTTM": 15.0,                   # 이미 퍼센트
            "revenueGrowthTTMYoy": 8.0,                # 이미 퍼센트
            "netInterestCoverageTTM": 12.5,            # 배수, 변환 불필요
            "epsGrowth5Y": 17.91,                      # 5년 EPS CAGR(%), 변환 불필요
        },
    )
    row = fetch_finance_one("AAPL")

    assert row["ticker"] == "AAPL"
    assert row["roe_3y_avg"] == 15.0
    assert row["debt_ratio"] == 80.0
    assert row["interest_coverage"] == 12.5
    assert row["eps_growth_5y"] == 17.91
    assert row["op_margin"] == 22.0
    assert row["per"] == 18.0
    assert row["pbr"] == 6.0
    assert row["payout_ratio"] == pytest.approx(0.15)
    assert row["rev_yoy"] == pytest.approx(0.08)
    assert row["op_yoy"] == pytest.approx(0.08)
    assert row["share_outstanding"] == 15_200.0
    assert np.isnan(row["buyback_rate"])


def test_build_finance_cache_reuses_cached_share_outstanding(monkeypatch, tmp_path):
    import data_pipeline
    import wiki_universe

    cache_path = tmp_path / "finance.parquet"
    pd.DataFrame([{"ticker": "AAPL", "share_outstanding": 15_200.0}]).to_parquet(cache_path, index=False)
    universe = pd.DataFrame(
        {"name": ["Apple Inc."], "sector": ["Technology"]},
        index=pd.Index(["AAPL"], name="ticker"),
    )
    monkeypatch.setattr(data_pipeline, "FINANCE_CACHE", cache_path)
    monkeypatch.setattr(wiki_universe, "get_universe", lambda: universe)
    monkeypatch.setattr(
        data_pipeline, "fetch_finance_one",
        lambda ticker: pytest.fail("fresh profile data should not be fetched on a cache hit"),
    )

    result = build_finance_cache(sleep_sec=0)

    assert result.loc[result["ticker"] == "AAPL", "share_outstanding"].item() == 15_200.0


def test_build_finance_cache_refreshes_row_missing_share_outstanding(monkeypatch, tmp_path):
    import data_pipeline
    import wiki_universe

    cache_path = tmp_path / "finance.parquet"
    pd.DataFrame([{"ticker": "AAPL", "roe_3y_avg": 15.0}]).to_parquet(cache_path, index=False)
    universe = pd.DataFrame(
        {"name": ["Apple Inc."], "sector": ["Technology"]},
        index=pd.Index(["AAPL"], name="ticker"),
    )
    monkeypatch.setattr(data_pipeline, "FINANCE_CACHE", cache_path)
    monkeypatch.setattr(wiki_universe, "get_universe", lambda: universe)
    monkeypatch.setattr(
        data_pipeline, "fetch_finance_one",
        lambda ticker: {"ticker": ticker, "roe_3y_avg": 16.0, "share_outstanding": 15_300.0},
    )

    result = build_finance_cache(sleep_sec=0)

    row = result.set_index("ticker").loc["AAPL"]
    assert row["roe_3y_avg"] == 16.0
    assert row["share_outstanding"] == 15_300.0


def test_build_finance_cache_computes_buyback_rate_from_prior_shares_even_when_forced(monkeypatch, tmp_path):
    """force=True로 전량 재조회해도, 직전 캐시의 발행주식수는 buyback_rate 계산을 위해 먼저 읽혀야 한다."""
    import data_pipeline
    import wiki_universe

    cache_path = tmp_path / "finance.parquet"
    pd.DataFrame([{"ticker": "AAPL", "share_outstanding": 100.0}]).to_parquet(cache_path, index=False)
    universe = pd.DataFrame(
        {"name": ["Apple Inc."], "sector": ["Technology"]},
        index=pd.Index(["AAPL"], name="ticker"),
    )
    monkeypatch.setattr(data_pipeline, "FINANCE_CACHE", cache_path)
    monkeypatch.setattr(wiki_universe, "get_universe", lambda: universe)
    monkeypatch.setattr(
        data_pipeline, "fetch_finance_one",
        lambda ticker: {"ticker": ticker, "share_outstanding": 95.0},
    )

    result = build_finance_cache(force=True, sleep_sec=0)

    row = result.set_index("ticker").loc["AAPL"]
    assert row["buyback_rate"] == pytest.approx(0.05)


def test_get_full_universe_computes_market_cap_from_quote_and_cached_shares(monkeypatch, tmp_path):
    import data_pipeline
    import wiki_universe

    universe = pd.DataFrame(
        {"name": ["Apple Inc."], "sector": ["Technology"]},
        index=pd.Index(["AAPL"], name="ticker"),
    )
    cache_path = tmp_path / "finance.parquet"
    pd.DataFrame([{"ticker": "AAPL", "share_outstanding": 15_200.0}]).to_parquet(cache_path, index=False)
    monkeypatch.setattr(data_pipeline, "FINANCE_CACHE", cache_path)
    monkeypatch.setattr(wiki_universe, "get_universe", lambda: universe)
    monkeypatch.setattr(data_pipeline.finnhub_client, "get_quote", lambda ticker: {"c": 200.0})
    monkeypatch.setattr(
        data_pipeline.finnhub_client, "get_company_profile",
        lambda ticker: pytest.fail("daily universe loading must not fetch company profiles"),
    )

    result = get_full_universe(sleep_sec=0)

    assert result.loc["AAPL", "market_cap"] == 3_040_000_000_000.0


def test_get_full_universe_raises_when_quote_success_rate_too_low(monkeypatch, tmp_path):
    import data_pipeline
    import wiki_universe

    universe = pd.DataFrame(
        {"name": [f"Company {i}" for i in range(10)], "sector": ["Technology"] * 10},
        index=pd.Index([f"TCK{i}" for i in range(10)], name="ticker"),
    )
    monkeypatch.setattr(wiki_universe, "get_universe", lambda: universe)

    def flaky_get_quote(ticker):
        if ticker == "TCK0":
            return {"c": 100.0}
        raise RuntimeError("429 rate limited")

    monkeypatch.setattr(data_pipeline.finnhub_client, "get_quote", flaky_get_quote)
    cache_path = tmp_path / "finance.parquet"
    pd.DataFrame({"ticker": universe.index, "share_outstanding": [10.0] * len(universe)}).to_parquet(
        cache_path, index=False,
    )
    monkeypatch.setattr(data_pipeline, "FINANCE_CACHE", cache_path)

    with pytest.raises(RuntimeError, match="시세 조회 성공률"):
        get_full_universe(sleep_sec=0)
