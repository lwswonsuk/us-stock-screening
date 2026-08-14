"""
us_alpha.py — 4팩터 종목 선정 알고리즘 (KOSPI판 이식, S&P 500+400+600 대상)
================================================================
핵심 명제 (KOSPI판과 동일한 원칙):
  "회사 실적, 점유율, 턴어라운드 체력, 브랜드가 괜찮은데
   주가는 안 올라가는 종목을 고르고 모아가면서 기다리면 나중에 오름"

실행:
    python us_alpha.py --demo              # 합성 데이터로 로직 검증
    python us_alpha.py --run --top 50       # 실데이터 (FMP 필요)

의존:
    pip install -r requirements.txt
    setx FMP_API_KEY "..."
    setx ANTHROPIC_API_KEY "..."   (프로필 카드용, 없으면 프로필만 생략됨)
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quotes import pick_quote_for_week
from stock_profile import generate_all_profiles


# ═══════════════════════════════════════════════════════════════
# 1. 설정 — KOSPI판 비율과 동일, 금액 기준만 USD
# ═══════════════════════════════════════════════════════════════

@dataclass
class Config:
    # ---- 유니버스 (사용자 지정: 시총 하한만 있고 상한 없음)
    min_mktcap_usd: float = 100_000_000       # $100M 이상
    min_avg_volume_usd: float = 230_000       # 일평균 거래대금 하한 (KOSPI 3억원 환산)

    # ---- 하드 필터 (KOSPI판과 동일 비율)
    max_debt_ratio: float = 200.0             # 부채비율(부채/자본) 200% 초과 배제
    min_roe: float = 5.0                      # ROE 5% 미만 배제
    require_positive_op: bool = True          # 최근 4분기 누적 영업이익 > 0
    max_3m_return: float = 0.60               # 3개월 +60% 이상 = 테마 급등 → 신규진입 금지

    # ---- 4대 팩터 가중치 (KOSPI판과 동일)
    w_quality: float = 0.30
    w_value: float = 0.28
    w_gap: float = 0.27
    w_payout: float = 0.15

    # ---- 포지션 사이징 참고값 (스크리닝 화면에는 미노출, 향후 포트폴리오 기능용)
    max_weight_single: float = 0.10
    max_weight_sector: float = 0.25
    target_positions: int = 20


CFG = Config()


# ═══════════════════════════════════════════════════════════════
# 2. 유틸 — 횡단면 백분위 스코어
# ═══════════════════════════════════════════════════════════════

def pct_rank(s: pd.Series, ascending: bool = True) -> pd.Series:
    """결측은 중앙값(0.5) 처리. 0~1 백분위."""
    r = s.rank(pct=True, ascending=ascending, na_option="keep")
    return r.fillna(0.5)


def winsor(s: pd.Series, lo=0.01, hi=0.99) -> pd.Series:
    return s.clip(s.quantile(lo), s.quantile(hi))


# ═══════════════════════════════════════════════════════════════
# 3. 4대 팩터 스코어러 (KOSPI판과 동일 가중치·로직)
# ═══════════════════════════════════════════════════════════════

def score_quality(df: pd.DataFrame) -> pd.Series:
    """체력. ROE 수준·안정성, 영업이익률, 부채비율, 매출 성장."""
    s = (
        0.30 * pct_rank(winsor(df["roe_3y_avg"]))
        + 0.20 * pct_rank(-winsor(df["roe_3y_std"]))
        + 0.20 * pct_rank(winsor(df["op_margin"]))
        + 0.20 * pct_rank(-winsor(df["debt_ratio"]))
        + 0.10 * pct_rank(winsor(df["rev_cagr_3y"]))
    )
    s = s + 0.05 * df["years_no_rev_decline"].clip(0, 5) / 5
    return s


def score_value(df: pd.DataFrame) -> pd.Series:
    """가격. 이익수익률(1/PER), 순자산수익률(1/PBR), 배당수익률, FCF수익률."""
    ep = 1.0 / df["per"].replace([0, np.inf, -np.inf], np.nan)
    bp = 1.0 / df["pbr"].replace([0, np.inf, -np.inf], np.nan)
    s = (
        0.40 * pct_rank(winsor(ep))
        + 0.30 * pct_rank(winsor(bp))
        + 0.20 * pct_rank(winsor(df["div_yield"]))
        + 0.10 * pct_rank(winsor(df["fcf_yield"]))
    )
    return s


def score_gap(df: pd.DataFrame) -> pd.Series:
    """★ 핵심 팩터: '실적-주가 괴리'. 이익 모멘텀 양호 + 주가 모멘텀 부진일수록 고득점.
    영업이익 YoY가 -10% 미만이면 게이트로 차단(펀더멘털 훼손과 구분)."""
    gate = (df["op_yoy"] > -0.10).astype(float)

    s = (
        0.35 * pct_rank(-winsor(df["ret_12m"]))
        + 0.25 * pct_rank(winsor(df["drawdown_52w"]))
        + 0.25 * pct_rank(winsor(df["op_yoy"]))
        + 0.15 * pct_rank(winsor(df["rev_yoy"]))
    )
    return s * gate + (1 - gate) * 0.15


def score_payout(df: pd.DataFrame) -> pd.Series:
    """주주환원 여력. '이미 많이 주는 회사'가 아니라 '줄 여력이 있는데 안 주는 회사'가 정답."""
    room = (0.50 - df["payout_ratio"]).clip(lower=0)
    s = (
        0.40 * pct_rank(winsor(room))
        + 0.30 * pct_rank(winsor(df["net_cash_to_mktcap"]))
        + 0.20 * pct_rank(winsor(df["roe_3y_avg"]))
        + 0.10 * pct_rank(winsor(df["treasury_ratio"]))
    )
    return s
