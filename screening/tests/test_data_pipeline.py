# screening/tests/test_data_pipeline.py
import numpy as np
import pandas as pd

from data_pipeline import compute_return_and_drawdown, fetch_finance_one


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
    import finnhub_client

    monkeypatch.setattr(
        finnhub_client, "get_basic_financials",
        lambda ticker: {
            "roeTTM": 0.15,
            "totalDebt/totalEquityAnnual": 0.8,
            "operatingMarginTTM": 0.22,
            "peTTM": 18.0,
            "pbAnnual": 6.0,
            "dividendYieldIndicatedAnnual": 0.5,
            "payoutRatioTTM": 0.15,
            "revenueGrowthTTMYoy": 0.08,
        },
    )
    monkeypatch.setattr(finnhub_client, "get_quote", lambda ticker: {"c": 230.0, "pc": 225.0})
    monkeypatch.setattr(finnhub_client, "get_company_profile", lambda ticker: {"finnhubIndustry": "Technology"})

    row = fetch_finance_one("AAPL")

    assert row["ticker"] == "AAPL"
    assert row["roe_3y_avg"] == 15.0
    assert row["debt_ratio"] == 80.0
    assert row["op_margin"] == 22.0
    assert row["per"] == 18.0
    assert row["pbr"] == 6.0
