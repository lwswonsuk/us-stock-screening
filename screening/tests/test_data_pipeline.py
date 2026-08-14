# screening/tests/test_data_pipeline.py
import numpy as np
import pandas as pd
import pytest

from data_pipeline import compute_return_and_drawdown, fetch_finance_one, get_full_universe


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
    """필드 값은 2026-08-14 실제 Finnhub API 응답(AAPL)으로 검증된 실제 스케일을 반영한다:
    roeTTM/operatingMarginTTM/payoutRatioTTM/revenueGrowthTTMYoy는 이미 퍼센트 값이고,
    totalDebt/totalEquityAnnual만 소수다."""
    import finnhub_client

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
        },
    )
    row = fetch_finance_one("AAPL")

    assert row["ticker"] == "AAPL"
    assert row["roe_3y_avg"] == 15.0
    assert row["debt_ratio"] == 80.0
    assert row["op_margin"] == 22.0
    assert row["per"] == 18.0
    assert row["pbr"] == 6.0
    assert row["payout_ratio"] == pytest.approx(0.15)
    assert row["rev_yoy"] == pytest.approx(0.08)
    assert row["op_yoy"] == pytest.approx(0.08)


def test_get_full_universe_raises_when_quote_success_rate_too_low(monkeypatch):
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
    monkeypatch.setattr(
        data_pipeline.finnhub_client, "get_company_profile",
        lambda ticker: {"marketCapitalization": 1000.0},
    )

    with pytest.raises(RuntimeError, match="시세 조회 성공률"):
        get_full_universe(sleep_sec=0)
