"""
data_pipeline.py — 미국 주식 재무데이터 캐싱 레이어 (Finnhub + Wikipedia 기반)
================================================================
Finnhub API로 개별 종목 재무비율·발행주식수를 분기별 로컬 parquet에 캐싱하고,
위키피디아(wiki_universe.py)에서 받은 유니버스(S&P 500+400+600)와 결합한다.

사용법:
    python data_pipeline.py --build          # 캐시 새로 만들기 (최초 1회, 시간 걸림)
    python data_pipeline.py --build --force  # 캐시 무시하고 전부 새로 받기
    python data_pipeline.py --status         # 캐시 현황 확인

캐시 파일:
    .cache/finance.parquet   — 종목별 재무비율·발행주식수 (분기별 갱신)
    .cache/universe.parquet  — 지수 구성종목 명단 (주 1회 갱신, wiki_universe.py가 관리)
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

import finnhub_client
import wiki_universe

CACHE_DIR = Path(".cache")
CACHE_DIR.mkdir(exist_ok=True)
FINANCE_CACHE = CACHE_DIR / "finance.parquet"


def compute_return_and_drawdown(price_df: pd.DataFrame) -> tuple[float, float, float, float]:
    """price_df: columns=[date, close], 오름차순(과거→최근) 정렬됨.
    반환: (3개월 수익률, 12개월 수익률, 52주 고점 대비 낙폭[양수=고점보다 낮음],
           52주 저점 대비 상승률[양수=저점보다 높음, 0에 가까울수록 신저가 근접])."""
    closes = price_df["close"].to_numpy()
    if len(closes) < 2:
        return (np.nan, np.nan, np.nan, np.nan)

    last = closes[-1]
    idx_3m = max(0, len(closes) - 1 - 63)
    idx_12m = 0
    ret_3m = last / closes[idx_3m] - 1.0
    ret_12m = last / closes[idx_12m] - 1.0

    peak_52w = closes.max()
    drawdown_52w = (peak_52w - last) / peak_52w if peak_52w > 0 else np.nan

    low_52w = closes.min()
    pct_above_52w_low = (last - low_52w) / low_52w if low_52w > 0 else np.nan

    return (float(ret_3m), float(ret_12m), float(drawdown_52w), float(pct_above_52w_low))


def fetch_finance_one(ticker: str) -> dict:
    """Finnhub 여러 엔드포인트를 조합해 스코어링에 필요한 한 종목의 재무 행을 만든다.

    ⚠️ 필드 스케일은 2026-08-14 실제 API 응답(AAPL)으로 라이브 검증 완료:
      - roeTTM, operatingMarginTTM: 이미 퍼센트 값(예: roeTTM=137.18 → "137.18%") — × 100 하지 않음
      - totalDebt/totalEquityAnnual: 소수(예: 1.3547 → "135.47%") — × 100 함
      - payoutRatioTTM, revenueGrowthTTMYoy: 이미 퍼센트 값 — score_payout/score_gap이 요구하는
        0~1 소수 스케일로 맞추기 위해 ÷ 100 함
      - dividendYieldIndicatedAnnual, peTTM, pbAnnual: 그대로 사용 (변환 없음, 검증 완료)
    이 함수가 Finnhub 원본 필드명과 내부 컬럼명 사이의 유일한 변환 지점이다."""
    metric = finnhub_client.get_basic_financials(ticker)
    profile = finnhub_client.get_company_profile(ticker)

    def g(key):
        v = metric.get(key)
        return np.nan if v is None else v

    roe = g("roeTTM")
    debt_equity = g("totalDebt/totalEquityAnnual")
    op_margin = g("operatingMarginTTM")
    per = g("peTTM")
    pbr = g("pbAnnual")
    div_yield = g("dividendYieldIndicatedAnnual")
    payout_ratio_pct = g("payoutRatioTTM")
    rev_yoy_pct = g("revenueGrowthTTMYoy")
    interest_coverage = g("netInterestCoverageTTM")   # 배수(예: 12.5) — 변환 불필요, 값이 클수록 부채 상환여력 좋음

    roe_3y_avg = roe                      # 이미 퍼센트
    debt_ratio = np.nan if np.isnan(debt_equity) else debt_equity * 100   # 소수 → 퍼센트 (참고용, 스코어링엔 미사용)
    op_margin_pct = op_margin             # 이미 퍼센트
    rev_yoy = np.nan if np.isnan(rev_yoy_pct) else rev_yoy_pct / 100      # 퍼센트 → 소수
    payout_ratio = np.nan if np.isnan(payout_ratio_pct) else max(payout_ratio_pct / 100, 0.0)  # 퍼센트 → 소수

    op_yoy = np.nan  # Finnhub의 무료 'metric=all'은 영업이익 YoY를 직접 주지 않음 — 매출성장률로 근사
    if not np.isnan(rev_yoy):
        op_yoy = rev_yoy  # 근사치: 매출성장률을 영업이익 모멘텀 프록시로 사용 (게이트 판정용, 소수 스케일)

    for label, val in (("debt_ratio", debt_ratio), ("roe_3y_avg", roe_3y_avg), ("op_margin", op_margin_pct)):
        if not np.isnan(val) and abs(val) > 1000:
            print(
                f"  [WARN] {ticker}: {label} 값이 비정상적으로 큽니다 ({val:.1f}). "
                "Finnhub 필드 스케일이 바뀌었을 가능성이 있습니다 — data_pipeline.fetch_finance_one()의 "
                "스케일 변환 로직을 재검토하세요."
            )

    return {
        "ticker": ticker,
        "share_outstanding": profile.get("shareOutstanding") or np.nan,
        "roe_3y_avg": roe_3y_avg,
        "roe_3y_std": np.nan,
        "debt_ratio": debt_ratio,
        "interest_coverage": interest_coverage,
        "op_margin": op_margin_pct,
        "op_ttm": op_margin,   # 부호만 사용하는 흑자/적자 판별용 프록시 (KOSPI판 이식 시 동일 패턴)
        "op_yoy": op_yoy,
        "rev_yoy": rev_yoy,
        "rev_cagr_3y": np.nan,
        "years_no_rev_decline": 0,
        "net_income_ttm": np.nan,
        "revenue_ttm": np.nan,
        "total_equity": np.nan,
        "cash_dividend_total": np.nan,
        "payout_ratio": payout_ratio,
        "per": per,
        "pbr": pbr,
        "div_yield": div_yield,
        "fcf_yield": np.nan,
        "net_cash_to_mktcap": np.nan,
        # buyback_rate는 여기서 계산할 수 없음(직전 분기 발행주식수가 필요) —
        # build_finance_cache()가 이전 캐시와 비교해 채워넣는다. 최초 1회는 NaN(중립) 처리됨.
        "buyback_rate": np.nan,
    }


def _compute_buyback_rate(shares: float, prev_shares: float) -> float:
    """직전 캐시 대비 발행주식수 감소율. 감소(자사주매입)면 양수, 증가(신주발행)면 음수.
    직전 값이 없거나 0 이하면 비교 불가 → NaN(중립 처리)."""
    if prev_shares is None or np.isnan(prev_shares) or prev_shares <= 0 or np.isnan(shares):
        return np.nan
    return (prev_shares - shares) / prev_shares


def build_finance_cache(force: bool = False, sleep_sec: float = 2.2) -> pd.DataFrame:
    universe = wiki_universe.get_universe().reset_index()
    print(f"[universe] S&P 500+400+600 합산 {len(universe)}개 종목 (Wikipedia)")

    # buyback_rate 계산용: force 여부와 무관하게 "이전 캐시에 있던 발행주식수"는 항상 먼저 읽어둔다.
    # (force=True로 전량 재조회하더라도 직전 분기 대비 자사주매입률은 비교할 수 있어야 하므로,
    # done_tickers 판정과는 별개로 분리한다.)
    prev_shares: dict[str, float] = {}
    if FINANCE_CACHE.exists():
        prior = pd.read_parquet(FINANCE_CACHE)
        if "ticker" in prior.columns and "share_outstanding" in prior.columns:
            prev_shares = prior.set_index("ticker")["share_outstanding"].to_dict()

    existing = pd.DataFrame()
    done_tickers: set[str] = set()
    if FINANCE_CACHE.exists() and not force:
        existing = pd.read_parquet(FINANCE_CACHE)
        if "ticker" in existing.columns and "share_outstanding" in existing.columns:
            done_tickers = set(existing.loc[existing["share_outstanding"].notna(), "ticker"])
        print(f"[cache] 기존 캐시 {len(done_tickers)}개 종목 재사용")

    todo = universe[~universe["ticker"].isin(done_tickers)]
    print(f"[fetch] 신규로 받아올 종목: {len(todo)}개 (분당 60건 제한, 예상 소요 약 {len(todo) * sleep_sec / 60:.1f}분)")

    rows = []
    for i, (_, r) in enumerate(todo.iterrows(), 1):
        try:
            row = fetch_finance_one(r["ticker"])
            row["buyback_rate"] = _compute_buyback_rate(row["share_outstanding"], prev_shares.get(r["ticker"]))
            rows.append(row)
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


def get_full_universe(sleep_sec: float = 1.1) -> pd.DataFrame:
    """유니버스 종목의 실시간 시세(quote)를 결합한 DataFrame. index=ticker.
    columns=[name, sector, price, market_cap, avg_volume].
    시가총액은 분기 재무 캐시의 발행주식수(백만 주) × 당일 현재가로 계산한다.
    종목당 get_quote 1회만 호출하므로 Finnhub 무료 티어(분당 60건) 한도를 지키기 위해
    종목 사이에 sleep_sec만큼 대기한다 (기본값 1.1초 → 약 55콜/분)."""
    idx = wiki_universe.get_universe()
    finance = pd.read_parquet(FINANCE_CACHE).set_index("ticker")
    shares_outstanding = finance["share_outstanding"]

    rows = []
    for ticker in idx.index:
        try:
            quote = finnhub_client.get_quote(ticker)
            price = quote.get("c", np.nan)
            shares = shares_outstanding.get(ticker, np.nan)
            rows.append({
                "ticker": ticker,
                "price": price,
                "market_cap": price * shares * 1_000_000,
                "avg_volume": np.nan,  # Finnhub 무료 profile2/quote는 평균거래량을 직접 주지 않음 —
                                       # 유동성 필터는 시가총액 하한으로 대부분 걸러지므로 당장은 무제한 통과 처리
            })
        except Exception as e:
            print(f"  [WARN] {ticker} 시세 조회 실패: {e}")
        time.sleep(sleep_sec)

    quotes_df = pd.DataFrame(rows).set_index("ticker")

    if len(quotes_df) < len(idx) * 0.5:
        raise RuntimeError(
            f"시세 조회 성공률이 너무 낮습니다: {len(quotes_df)}/{len(idx)}. "
            "Finnhub API 상태나 요청 속도를 확인하세요."
        )

    return idx.join(quotes_df, how="inner")


def status():
    if FINANCE_CACHE.exists():
        fc = pd.read_parquet(FINANCE_CACHE)
        print(f"finance 캐시: {len(fc)}행")
    else:
        print("finance 캐시 없음")
    if wiki_universe.UNIVERSE_CACHE.exists():
        uc = pd.read_parquet(wiki_universe.UNIVERSE_CACHE)
        print(f"universe 캐시: {len(uc)}행")
    else:
        print("universe 캐시 없음")


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
