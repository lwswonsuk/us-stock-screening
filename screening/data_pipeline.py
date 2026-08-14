"""
data_pipeline.py — 미국 주식 재무데이터 캐싱 레이어
================================================================
FMP API를 매번 호출하지 않도록, 종목별 재무데이터를 로컬 parquet에 저장해두고
재사용한다. KOSPI판의 DART 캐시(연 1회 사업보고서 + 분기 TTM 보정)와 달리, FMP의
TTM 엔드포인트가 이미 최근 4분기 합산값을 직접 제공하므로 여기서는 그 값을 그대로 쓴다.

사용법:
    python data_pipeline.py --build          # 캐시 새로 만들기 (최초 1회, 시간 걸림)
    python data_pipeline.py --build --force  # 캐시 무시하고 전부 새로 받기
    python data_pipeline.py --status         # 캐시 현황 확인

캐시 파일:
    .cache/finance.parquet      — 종목별 재무비율 (ROE, 부채비율 등)
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

import fmp_client

CACHE_DIR = Path(".cache")
CACHE_DIR.mkdir(exist_ok=True)
FINANCE_CACHE = CACHE_DIR / "finance.parquet"


def compute_return_and_drawdown(price_df: pd.DataFrame) -> tuple[float, float, float]:
    """price_df: columns=[date, close], 오름차순(과거→최근) 정렬됨.
    반환: (3개월 수익률, 12개월 수익률, 52주 고점 대비 낙폭[양수=고점보다 낮음])."""
    closes = price_df["close"].to_numpy()
    if len(closes) < 2:
        return (np.nan, np.nan, np.nan)

    last = closes[-1]
    idx_3m = max(0, len(closes) - 1 - 63)   # 영업일 기준 약 3개월
    idx_12m = 0                              # 시리즈 시작이 약 1년 전이라고 가정(호출 시 days=380)
    ret_3m = last / closes[idx_3m] - 1.0
    ret_12m = last / closes[idx_12m] - 1.0

    peak_52w = closes.max()
    drawdown_52w = (peak_52w - last) / peak_52w if peak_52w > 0 else np.nan

    return (float(ret_3m), float(ret_12m), float(drawdown_52w))


def fetch_finance_one(ticker: str) -> dict:
    """FMP 여러 엔드포인트를 조합해 스코어링에 필요한 한 종목의 재무 행을 만든다.
    ⚠️ FMP 필드명(returnOnEquityTTM 등)은 Task 4 Step 5의 라이브 확인 결과에 맞춰
    아래 매핑을 조정할 것 — 이 함수가 FMP 원본 필드명과 내부 컬럼명 사이의 유일한
    변환 지점이다."""
    ratios = fmp_client.get_ratios_ttm(ticker)
    metrics = fmp_client.get_key_metrics_ttm(ticker)
    growth = fmp_client.get_income_statement_growth(ticker, period="quarter", limit=4)

    roe = ratios.get("returnOnEquityTTM")
    debt_equity = ratios.get("debtEquityRatioTTM")
    op_margin = ratios.get("operatingProfitMarginTTM")
    per = ratios.get("priceEarningsRatioTTM")
    pbr = ratios.get("priceToBookRatioTTM")
    div_yield = ratios.get("dividendYielTTM")
    payout_ratio = ratios.get("payoutRatioTTM")
    fcf_yield = metrics.get("freeCashFlowYieldTTM")

    latest_growth = growth[0] if growth else {}
    rev_yoy = latest_growth.get("growthRevenue")
    op_yoy = latest_growth.get("growthOperatingIncome")

    return {
        "ticker": ticker,
        "roe_3y_avg": None if roe is None else roe * 100,
        "roe_3y_std": np.nan,   # FMP TTM 엔드포인트는 단일 시점값만 제공 — 3개년 변동성은 계산 불가, 중립값(0.5 percentile) 처리는 score_quality의 pct_rank가 알아서 함
        "debt_ratio": None if debt_equity is None else debt_equity * 100,
        "op_margin": None if op_margin is None else op_margin * 100,
        # op_ttm: FMP TTM 엔드포인트는 영업이익 실액을 직접 제공하지 않으므로, 여기서는
        # 실제 금액이 아니라 흑자/적자 부호 판별용 플레이스홀더만 넣는다. 최종 부호는
        # us_alpha.load_real()에서 op_margin(영업이익률)으로 덮어써, apply_hard_filters의
        # "적자 배제" 필터가 부호만으로 판단하게 한다 — 값 자체를 금액으로 쓰면 안 된다.
        "op_ttm": None,
        "op_yoy": op_yoy,
        "rev_yoy": rev_yoy,
        "rev_cagr_3y": np.nan,
        "years_no_rev_decline": 0,
        "net_income_ttm": np.nan,
        "revenue_ttm": np.nan,
        "total_equity": np.nan,
        "cash_dividend_total": np.nan,
        "payout_ratio": None if payout_ratio is None else max(payout_ratio, 0.0),
        "per": per,
        "pbr": pbr,
        "div_yield": None if div_yield is None else div_yield * 100,
        "fcf_yield": fcf_yield,
        "net_cash_to_mktcap": np.nan,
        "treasury_ratio": np.nan,
    }


def build_finance_cache(force: bool = False, sleep_sec: float = 0.2) -> pd.DataFrame:
    universe = fmp_client.get_index_universe().reset_index()
    print(f"[universe] S&P 500+400+600 합산 {len(universe)}개 종목")

    existing = pd.DataFrame()
    done_tickers: set[str] = set()
    if FINANCE_CACHE.exists() and not force:
        existing = pd.read_parquet(FINANCE_CACHE)
        done_tickers = set(existing["ticker"]) if "ticker" in existing.columns else set()
        print(f"[cache] 기존 캐시 {len(done_tickers)}개 종목 재사용")

    todo = universe[~universe["ticker"].isin(done_tickers)]
    print(f"[fetch] 신규로 받아올 종목: {len(todo)}개")

    rows = []
    for i, (_, r) in enumerate(todo.iterrows(), 1):
        try:
            rows.append(fetch_finance_one(r["ticker"]))
        except Exception as e:
            print(f"  [WARN] {r['ticker']} 재무데이터 조회 실패: {e}")
        if i % 50 == 0:
            print(f"  진행 {i}/{len(todo)}")
        time.sleep(sleep_sec)

    new_df = pd.DataFrame(rows)
    combined = pd.concat([existing, new_df], ignore_index=True) if len(existing) else new_df
    combined = combined.drop_duplicates(subset=["ticker"], keep="last")
    combined.to_parquet(FINANCE_CACHE, index=False)
    print(f"[done] 재무캐시 저장 완료: {len(combined)}행 → {FINANCE_CACHE}")
    return combined


def get_full_universe() -> pd.DataFrame:
    """유니버스 종목의 실시간 시세(quote)를 결합한 DataFrame. index=ticker."""
    idx = fmp_client.get_index_universe()
    quotes = fmp_client.get_quotes(list(idx.index))
    return idx.join(quotes, how="inner")


def status():
    if FINANCE_CACHE.exists():
        fc = pd.read_parquet(FINANCE_CACHE)
        print(f"finance 캐시: {len(fc)}행")
    else:
        print("finance 캐시 없음")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    if a.status:
        status()
    elif a.build:
        build_finance_cache(force=a.force)
    else:
        print("사용법: python data_pipeline.py --build  또는  --status")
