import json

import numpy as np
import pandas as pd
import pytest

from us_alpha import _build_records, load_real, run_real


def test_build_records_preserves_export_conversions_and_ticker_name():
    df = pd.DataFrame(
        [{"name": "Apple Inc.", "mktcap_usd": 3_500_000_000_000.0, "score": np.nan}],
        index=pd.Index(["AAPL"], name="ticker"),
    )

    records = _build_records(df, ["name", "mktcap_usd", "score"])

    assert records == [{
        "stock_code": "AAPL",
        "name": "AAPL",
        "mktcap_usd": 3_500_000.0,
        "score": None,
    }]


def test_load_real_rejects_legacy_finance_cache_before_fetching_quotes(monkeypatch, tmp_path):
    import data_pipeline

    cache_path = tmp_path / "finance.parquet"
    pd.DataFrame([{"ticker": "AAPL", "roe_3y_avg": 15.0}]).to_parquet(cache_path, index=False)
    monkeypatch.setattr(data_pipeline, "FINANCE_CACHE", cache_path)
    monkeypatch.setattr(
        data_pipeline,
        "get_full_universe",
        lambda: pytest.fail("quotes must not be fetched for an incompatible finance cache"),
    )

    with pytest.raises(RuntimeError, match=r"share_outstanding.*python data_pipeline\.py --build --force"):
        load_real()


def test_load_real_rejects_legacy_universe_cache_missing_sub_industry(monkeypatch, tmp_path):
    """sub_industry(REIT 판별용) 컬럼이 없는 구버전 유니버스 캐시는 명확한 오류로 거부해야 한다."""
    import data_pipeline

    cache_path = tmp_path / "finance.parquet"
    pd.DataFrame([{
        "ticker": "AAPL", "share_outstanding": 15_200.0, "interest_coverage": 12.0,
        "buyback_rate": 0.01, "eps_growth_5y": 10.0,
    }]).to_parquet(cache_path, index=False)
    monkeypatch.setattr(data_pipeline, "FINANCE_CACHE", cache_path)

    legacy_universe = pd.DataFrame(
        {"name": ["Apple Inc."], "sector": ["Technology"], "price": [230.0],
         "market_cap": [3_500_000_000_000], "avg_volume": [50_000_000]},
        index=pd.Index(["AAPL"], name="ticker"),
    )
    monkeypatch.setattr(data_pipeline, "get_full_universe", lambda: legacy_universe)

    with pytest.raises(RuntimeError, match="sub_industry"):
        load_real()


def test_run_real_writes_expected_json_shape(monkeypatch, tmp_path):
    import data_pipeline

    universe = pd.DataFrame(
        {"name": ["Apple Inc."], "sector": ["Technology"], "sub_industry": ["Technology Hardware"],
         "price": [230.0], "market_cap": [3_500_000_000_000], "avg_volume": [50_000_000]},
        index=pd.Index(["AAPL"], name="ticker"),
    )
    finance = pd.DataFrame([{
        "ticker": "AAPL", "share_outstanding": 15_200.0,
        "roe_3y_avg": 150.0, "roe_3y_std": np.nan, "debt_ratio": 180.0,
        "interest_coverage": 12.0, "eps_growth_5y": 15.0,
        "op_margin": 30.0, "op_ttm": 100_000_000_000, "op_yoy": 0.1, "rev_yoy": 0.05,
        "rev_cagr_3y": np.nan, "years_no_rev_decline": 0, "net_income_ttm": np.nan,
        "revenue_ttm": np.nan, "total_equity": np.nan, "cash_dividend_total": np.nan,
        "payout_ratio": 0.15, "per": 28.0, "pbr": 45.0, "div_yield": 0.5,
        "fcf_yield": 0.03, "net_cash_to_mktcap": 0.02, "buyback_rate": 0.01,
    }])

    monkeypatch.setattr(data_pipeline, "get_full_universe", lambda: universe)
    monkeypatch.setattr(data_pipeline, "FINANCE_CACHE", tmp_path / "finance.parquet")
    finance.to_parquet(tmp_path / "finance.parquet", index=False)

    monkeypatch.setattr(
        "us_alpha.get_historical_prices_batch",
        lambda tickers: {
            "AAPL": {"ret_3m": 0.05, "ret_12m": 0.12, "drawdown_52w": 0.10, "pct_above_52w_low": 0.05},
        },
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    out_json = tmp_path / "results.json"
    filtered_json = tmp_path / "filtered_full.json"

    run_real(top_n=10, export_json=str(out_json), filtered_json=str(filtered_json))

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["universe_total"] == 1
    assert payload["results"][0]["stock_code"] == "AAPL"
    assert payload["results"][0]["profile"] is None
    assert "column_labels_ko" in payload
    assert "quote_text" in payload

    # mktcap_usd is exported in millions to match its "시가총액(백만$)" label,
    # while the raw-dollar value stays untouched for hard-filter comparisons.
    assert payload["results"][0]["mktcap_usd"] == 3_500_000.0

    # payout_ratio is kept as a 0-1 fraction internally (used by score_payout),
    # but the exported/displayed column is the ×100 percent value.
    assert "payout_ratio_pct" in payload["columns"]
    assert "payout_ratio" not in payload["columns"]
    assert payload["results"][0]["payout_ratio_pct"] == 15.0
    assert payload["column_labels_ko"]["payout_ratio_pct"] == "배당성향(%)"

    # "name" is overwritten with the ticker for on-screen display (design decision),
    # but the real Wikipedia company name survives separately as "company_name" —
    # it replaces the old (unreliable) "sector" column in the exported table.
    assert payload["results"][0]["name"] == "AAPL"
    assert payload["results"][0]["company_name"] == "Apple Inc."
    assert "sector" not in payload["columns"]
    assert "company_name" in payload["columns"]
    assert payload["column_labels_ko"]["company_name"] == "회사명"

    # 부채비율 하드필터는 제거됨 -> 화면엔 이자보상배율이 표시되고 debt_ratio는 노출되지 않는다.
    assert "interest_coverage" in payload["columns"]
    assert "debt_ratio" not in payload["columns"]
    assert payload["column_labels_ko"]["interest_coverage"] == "이자보상배율(배)"

    # 자사주매입률·52주 저점대비 컬럼도 새로 노출된다.
    assert "buyback_rate_pct" in payload["columns"]
    assert payload["results"][0]["buyback_rate_pct"] == pytest.approx(1.0)
    assert "pct_above_52w_low_pct" in payload["columns"]
    assert payload["results"][0]["pct_above_52w_low_pct"] == pytest.approx(5.0)

    # 별도의 '52주 신저가' 리스트는 더 이상 export되지 않는다 — 대신 3가지 조건
    # (52주 저점 10% 이내 + 5년전보다 이익 증가 + REIT 제외)이 메인 목록의 하드필터가 되었다.
    assert "near_52w_low" not in payload


def test_run_real_raises_when_nothing_passes_hard_filters(monkeypatch, tmp_path):
    import data_pipeline

    universe = pd.DataFrame(
        {"name": ["Apple Inc."], "sector": ["Technology"], "sub_industry": ["Technology Hardware"],
         "price": [230.0], "market_cap": [3_500_000_000_000], "avg_volume": [50_000_000]},
        index=pd.Index(["AAPL"], name="ticker"),
    )
    # ROE가 하드필터 하한(5.0) 밑으로 -> 유일한 종목이 배제되어 통과 0개
    finance = pd.DataFrame([{
        "ticker": "AAPL", "share_outstanding": 15_200.0,
        "roe_3y_avg": 1.0, "roe_3y_std": np.nan, "debt_ratio": 80.0,
        "interest_coverage": 12.0, "eps_growth_5y": 15.0,
        "op_margin": 30.0, "op_ttm": 100_000_000_000, "op_yoy": 0.1, "rev_yoy": 0.05,
        "rev_cagr_3y": np.nan, "years_no_rev_decline": 0, "net_income_ttm": np.nan,
        "revenue_ttm": np.nan, "total_equity": np.nan, "cash_dividend_total": np.nan,
        "payout_ratio": 0.15, "per": 28.0, "pbr": 45.0, "div_yield": 0.5,
        "fcf_yield": 0.03, "net_cash_to_mktcap": 0.02, "buyback_rate": 0.01,
    }])

    monkeypatch.setattr(data_pipeline, "get_full_universe", lambda: universe)
    monkeypatch.setattr(data_pipeline, "FINANCE_CACHE", tmp_path / "finance.parquet")
    finance.to_parquet(tmp_path / "finance.parquet", index=False)

    monkeypatch.setattr(
        "us_alpha.get_historical_prices_batch",
        lambda tickers: {
            "AAPL": {"ret_3m": 0.05, "ret_12m": 0.12, "drawdown_52w": 0.10, "pct_above_52w_low": 0.05},
        },
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="하드 필터를 통과한 종목이 0개"):
        run_real(top_n=10)
