import pandas as pd

from us_alpha import apply_hard_filters, composite, Config


def _base_row(**overrides):
    row = {
        "mktcap_usd": 5_000_000_000, "avg_volume_usd": 50_000_000,
        "interest_coverage": 10.0, "roe_3y_avg": 15.0, "roe_3y_std": 3.0,
        "op_margin": 20.0, "op_ttm": 500_000_000, "ret_3m": 0.02,
        "per": 15.0, "pbr": 3.0, "div_yield": 1.0, "fcf_yield": 0.04,
        "ret_12m": 0.05, "drawdown_52w": 0.15, "op_yoy": 0.08, "rev_yoy": 0.05,
        "rev_cagr_3y": 0.06, "years_no_rev_decline": 3,
        "payout_ratio": 0.20, "net_cash_to_mktcap": 0.05, "buyback_rate": 0.01,
        "sector": "Technology",
    }
    row.update(overrides)
    return row


def test_apply_hard_filters_excludes_small_market_cap():
    df = pd.DataFrame([_base_row(mktcap_usd=50_000_000)], index=["TINY"])
    out = apply_hard_filters(df, Config())
    assert out.loc["TINY", "passed"] is False or out.loc["TINY", "passed"] == False
    assert out.loc["TINY", "filter_reason"] == "시총하한"


def test_apply_hard_filters_no_longer_excludes_high_debt_stocks():
    """부채비율 하드필터는 제거됨 — 이자보상배율은 score_quality 랭킹에만 반영되고,
    interest_coverage가 아무리 낮아도(부채 상환여력이 나빠도) 하드필터로 배제되지 않는다."""
    df = pd.DataFrame([_base_row(interest_coverage=0.1)], index=["HIGH_DEBT"])
    out = apply_hard_filters(df, Config())
    assert out.loc["HIGH_DEBT", "passed"] == True


def test_apply_hard_filters_excludes_theme_spike():
    df = pd.DataFrame([_base_row(ret_3m=0.75)], index=["SPIKE"])
    out = apply_hard_filters(df, Config())
    assert out.loc["SPIKE", "passed"] == False
    assert out.loc["SPIKE", "filter_reason"] == "테마급등"


def test_apply_hard_filters_passes_healthy_stock():
    df = pd.DataFrame([_base_row()], index=["OK"])
    out = apply_hard_filters(df, Config())
    assert out.loc["OK", "passed"] == True


def test_composite_ranks_higher_quality_stock_first():
    good = _base_row()
    bad = _base_row(roe_3y_avg=5.0, op_margin=2.0, interest_coverage=1.0, per=60.0, pbr=15.0,
                     div_yield=0.0, drawdown_52w=0.02, op_yoy=-0.05)
    df = pd.DataFrame([good, bad], index=["GOOD", "BAD"])
    filt = apply_hard_filters(df, Config())
    ranked = composite(filt, Config())
    assert ranked.index[0] == "GOOD"
    assert ranked.loc["GOOD", "score"] > ranked.loc["BAD", "score"]
