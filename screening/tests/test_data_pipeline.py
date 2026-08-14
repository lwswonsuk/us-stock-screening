# screening/tests/test_data_pipeline.py
import numpy as np
import pandas as pd

from data_pipeline import compute_return_and_drawdown, fetch_finance_one


def test_compute_return_and_drawdown_from_price_series():
    dates = pd.date_range("2025-08-01", periods=260, freq="B")
    # 꾸준히 100 -> 130으로 상승하다가 최근에 20% 조정
    closes = np.linspace(100, 130, len(dates))
    closes[-20:] = closes[-20:] * 0.80
    df = pd.DataFrame({"date": dates, "close": closes})

    ret_3m, ret_12m, drawdown_52w = compute_return_and_drawdown(df)

    assert ret_3m < 0          # 최근 3개월은 조정으로 하락
    assert ret_12m > -0.5      # 그래도 1년 전보다는 크게 나쁘지 않음
    assert drawdown_52w > 0    # 52주 고점 대비 낙폭은 양수로 표현


def test_fetch_finance_one_computes_op_margin_and_debt_ratio(monkeypatch):
    import fmp_client

    monkeypatch.setattr(
        fmp_client, "get_ratios_ttm",
        lambda ticker: {"returnOnEquityTTM": 0.15, "debtEquityRatioTTM": 0.8,
                         "operatingProfitMarginTTM": 0.22, "priceEarningsRatioTTM": 18.0,
                         "priceToBookRatioTTM": 6.0, "dividendYielTTM": 0.005,
                         "payoutRatioTTM": 0.15},
    )
    monkeypatch.setattr(
        fmp_client, "get_key_metrics_ttm",
        lambda ticker: {"netIncomePerShareTTM": 6.0, "freeCashFlowYieldTTM": 0.03,
                         "netDebtToEBITDATTM": -0.5},
    )
    monkeypatch.setattr(
        fmp_client, "get_income_statement_growth",
        lambda ticker, period="quarter", limit=4: [
            {"growthRevenue": 0.08, "growthOperatingIncome": 0.12},
        ],
    )

    row = fetch_finance_one("AAPL")

    assert row["ticker"] == "AAPL"
    assert row["roe_3y_avg"] == 0.15 * 100
    assert row["debt_ratio"] == 0.8 * 100
    assert row["op_margin"] == 0.22 * 100
    assert row["op_yoy"] == 0.12
    assert row["rev_yoy"] == 0.08
