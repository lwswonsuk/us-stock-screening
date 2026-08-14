import pandas as pd

from us_alpha import score_payout


def test_lower_payout_ratio_scores_higher_on_s_payout():
    """score_payout()은 '배당성향이 낮을수록(=여력이 많을수록) 우대'하는 로직이다.
    payout_ratio는 fraction 단위(0.05 = 5%)로 맞춰져 있어야 하며, score_payout()
    내부의 room 임계값(0.50)도 같은 단위를 전제한다."""
    df = pd.DataFrame(
        {
            "payout_ratio": [0.05, 0.40],
            "net_cash_to_mktcap": [0.10, 0.10],
            "roe_3y_avg": [10.0, 10.0],
            "treasury_ratio": [0.02, 0.02],
        },
        index=["low_payout", "high_payout"],
    )

    scores = score_payout(df)

    assert scores["low_payout"] > scores["high_payout"]
