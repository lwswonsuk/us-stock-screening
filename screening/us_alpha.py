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
import time
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


# ═══════════════════════════════════════════════════════════════
# 4. 필터 & 합성
# ═══════════════════════════════════════════════════════════════

def apply_hard_filters(df: pd.DataFrame, cfg: Config = CFG) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    reasons = pd.Series("", index=df.index)

    def cut(cond: pd.Series, label: str):
        nonlocal m, reasons
        bad = cond & m
        reasons[bad] = label
        m = m & ~cond

    cut(df["mktcap_usd"] < cfg.min_mktcap_usd, "시총하한")
    cut(df["avg_volume_usd"] < cfg.min_avg_volume_usd, "유동성")
    cut(df["debt_ratio"] > cfg.max_debt_ratio, "부채과다")
    cut(df["roe_3y_avg"] < cfg.min_roe, "ROE미달")
    if cfg.require_positive_op:
        cut(df["op_ttm"] <= 0, "적자")
    cut(df["ret_3m"] > cfg.max_3m_return, "테마급등")

    out = df.copy()
    out["passed"] = m
    out["filter_reason"] = reasons
    return out


def composite(df: pd.DataFrame, cfg: Config = CFG) -> pd.DataFrame:
    d = df.copy()
    d["s_quality"] = score_quality(d)
    d["s_value"] = score_value(d)
    d["s_gap"] = score_gap(d)
    d["s_payout"] = score_payout(d)

    d["score"] = (
        cfg.w_quality * d["s_quality"]
        + cfg.w_value * d["s_value"]
        + cfg.w_gap * d["s_gap"]
        + cfg.w_payout * d["s_payout"]
    )
    return d.sort_values("score", ascending=False)


# ═══════════════════════════════════════════════════════════════
# 5. 데모 — 합성 데이터로 로직 검증
# ═══════════════════════════════════════════════════════════════

def make_demo(n: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    sectors = ["Technology", "Health Care", "Financials", "Industrials", "Consumer Discretionary",
               "Consumer Staples", "Energy", "Materials", "Utilities", "Real Estate"]
    df = pd.DataFrame(index=[f"TCK{i:04d}" for i in range(n)])
    df["name"] = df.index
    df["sector"] = rng.choice(sectors, n)
    df["mktcap_usd"] = rng.lognormal(21.0, 1.5, n)
    df["avg_volume_usd"] = rng.lognormal(13.0, 1.5, n)
    df["roe_3y_avg"] = rng.normal(10, 8, n)
    df["roe_3y_std"] = np.abs(rng.normal(4, 2.5, n))
    df["op_margin"] = rng.normal(12, 8, n)
    df["debt_ratio"] = np.abs(rng.normal(90, 60, n))
    df["rev_cagr_3y"] = rng.normal(0.06, 0.10, n)
    df["years_no_rev_decline"] = rng.integers(0, 6, n)
    df["per"] = np.abs(rng.lognormal(2.6, 0.6, n))
    df["pbr"] = np.abs(rng.lognormal(0.5, 0.7, n))
    df["div_yield"] = np.abs(rng.normal(1.2, 1.2, n))
    df["fcf_yield"] = rng.normal(0.04, 0.05, n)
    df["ret_12m"] = rng.normal(0.08, 0.35, n)
    df["ret_3m"] = rng.normal(0.02, 0.20, n)
    df["drawdown_52w"] = np.abs(rng.normal(0.25, 0.15, n))
    df["op_yoy"] = rng.normal(0.06, 0.30, n)
    df["rev_yoy"] = rng.normal(0.05, 0.15, n)
    df["op_ttm"] = rng.normal(200_000_000, 400_000_000, n)
    df["payout_ratio"] = np.abs(rng.normal(0.20, 0.15, n))
    df["net_cash_to_mktcap"] = rng.normal(0.05, 0.20, n)
    df["treasury_ratio"] = np.abs(rng.normal(0.02, 0.03, n))
    return df


def run_demo():
    pd.set_option("display.width", 200, "display.max_columns", 50)
    df = make_demo()
    filt = apply_hard_filters(df)
    ranked = composite(filt)

    print("=" * 78)
    print("STEP 1 — 하드 필터")
    print("=" * 78)
    print(f"유니버스 {len(df)} → 통과 {int(filt['passed'].sum())}")
    print(filt.loc[~filt["passed"], "filter_reason"].value_counts().to_string())

    print("\n" + "=" * 78)
    print("STEP 2 — 종합 랭킹 상위 15")
    print("=" * 78)
    cols = ["name", "sector", "per", "pbr", "roe_3y_avg", "debt_ratio",
            "ret_12m", "op_yoy", "s_quality", "s_value", "s_gap", "s_payout", "score"]
    top = ranked[ranked["passed"]].head(15)[cols]
    print(top.round(3).to_string())



# ═══════════════════════════════════════════════════════════════
# 6. 실데이터 어댑터
# ═══════════════════════════════════════════════════════════════

def get_historical_prices_batch(tickers: list[str], sleep_sec: float = 0.2) -> dict[str, dict]:
    """티커 리스트에 대해 (3개월수익률, 12개월수익률, 52주낙폭)을 계산해 dict로 반환한다.
    개별 종목 조회 실패는 건너뛰고 계속 진행한다. data_pipeline.build_finance_cache와
    동일하게 호출 사이에 sleep을 둬 FMP 요청 빈도를 제한한다."""
    import fmp_client
    from data_pipeline import compute_return_and_drawdown

    out: dict[str, dict] = {}
    for ticker in tickers:
        try:
            prices = fmp_client.get_historical_prices(ticker, days=380)
            ret_3m, ret_12m, drawdown_52w = compute_return_and_drawdown(prices)
            out[ticker] = {"ret_3m": ret_3m, "ret_12m": ret_12m, "drawdown_52w": drawdown_52w}
        except Exception as e:
            print(f"  [WARN] {ticker} 가격 히스토리 조회 실패: {e}")
        time.sleep(sleep_sec)
    return out


def load_real() -> pd.DataFrame:
    """FMP 유니버스 + 재무 캐시 + 가격히스토리를 조립해 스코어링용 DataFrame을 만든다.
    사전 준비: python data_pipeline.py --build 로 .cache/finance.parquet 만들어둘 것."""
    import data_pipeline

    if not data_pipeline.FINANCE_CACHE.exists():
        raise RuntimeError(
            "재무 캐시가 없습니다. 먼저 실행하세요: python data_pipeline.py --build"
        )

    universe = data_pipeline.get_full_universe()
    universe = universe.rename(columns={"market_cap": "mktcap_usd"})
    # FMP의 avgVolume은 주식수(거래량) 단위다. 유동성 필터(min_avg_volume_usd)는
    # "일평균 거래대금"(달러) 기준이므로 여기서 가격을 곱해 달러 단위로 환산한다.
    universe["avg_volume_usd"] = universe["avg_volume"] * universe["price"]

    fin = pd.read_parquet(data_pipeline.FINANCE_CACHE).set_index("ticker")
    df = universe.join(fin, how="inner")

    price_hist = get_historical_prices_batch(list(df.index))
    df["ret_3m"] = df.index.map(lambda t: price_hist.get(t, {}).get("ret_3m", np.nan))
    df["ret_12m"] = df.index.map(lambda t: price_hist.get(t, {}).get("ret_12m", np.nan))
    df["drawdown_52w"] = df.index.map(lambda t: price_hist.get(t, {}).get("drawdown_52w", np.nan))

    # op_ttm은 하드필터(적자 배제)에만 쓰이므로, 영업이익률 × 매출총계 근사가 없으면
    # 시가총액 × 영업이익률 부호만으로 흑자/적자를 판별한다 (부호만 필요).
    df["op_ttm"] = df["op_margin"]

    return df


# ═══════════════════════════════════════════════════════════════
# 7. 실행 — 스크리닝 + JSON export
# ═══════════════════════════════════════════════════════════════

KOR_NAMES = {
    "name": "종목명", "sector": "섹터", "mktcap_usd": "시가총액(백만$)",
    "price": "현재가", "per": "PER", "pbr": "PBR", "roe_3y_avg": "ROE(%)",
    "debt_ratio": "부채비율(%)", "div_yield": "배당수익률(%)", "payout_ratio_pct": "배당성향(%)",
    "score": "종합점수",
}


def _record_value(col: str, v) -> str | float | None:
    """DataFrame 값을 JSON 레코드 값으로 변환한다. mktcap_usd는 헤더 단위("백만$")에
    맞춰 이 시점에만 백만 단위로 나눈다 — 필터링/스코어링에 쓰이는 원본 DataFrame의
    달러 단위 값은 건드리지 않는다."""
    if col == "mktcap_usd" and not pd.isna(v):
        v = v / 1_000_000
    if pd.isna(v):
        return None
    if isinstance(v, (int, float, np.floating, np.integer)):
        return round(float(v), 4)
    return str(v)


def run_real(top_n: int = 50, export_json: str | None = None, filtered_json: str | None = None) -> pd.DataFrame:
    d = load_real()
    filt = apply_hard_filters(d)
    ranked = composite(filt)
    # payout_ratio는 score_payout 계산에 필요한 0~1 소수 그대로 두고, 화면/JSON
    # 표시용으로만 별도 ×100 컬럼을 둔다 (라벨이 "배당성향(%)"이므로).
    ranked["payout_ratio_pct"] = ranked["payout_ratio"] * 100

    print(f"유니버스 {len(d)} → 통과 {int(filt['passed'].sum())}")

    cols = ["name", "sector", "mktcap_usd", "price", "per", "pbr", "roe_3y_avg",
            "debt_ratio", "div_yield", "payout_ratio_pct", "score"]
    cols = [c for c in cols if c in ranked.columns]

    top = ranked[ranked["passed"]].head(top_n)[cols]

    if export_json:
        import json
        from pathlib import Path as _Path

        records = []
        for ticker, row in top.iterrows():
            rec = {"stock_code": str(ticker)}
            for c in cols:
                rec[c] = _record_value(c, row[c])
            rec["name"] = rec["stock_code"]   # 화면에는 회사 전체명 대신 티커를 표시 (설계 결정)
            records.append(rec)

        quote = pick_quote_for_week()

        def _build_payload(recs):
            return {
                "as_of_date": pd.Timestamp.now("UTC").strftime("%Y%m%d"),
                "financial_year": None,
                "generated_at": pd.Timestamp.now("UTC").isoformat(),
                "quote_text": quote["text"],
                "quote_author": quote["author"],
                "universe_total": int(len(d)),
                "universe_passed": int(filt["passed"].sum()),
                "columns": cols,
                "column_labels_ko": {c: KOR_NAMES.get(c, c) for c in cols},
                "results": recs,
            }

        out_path = _Path(export_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        for rec in records:
            rec["profile"] = None
        out_path.write_text(json.dumps(_build_payload(records), ensure_ascii=False, indent=2), encoding="utf-8")

        profile_map = generate_all_profiles(records)
        for rec in records:
            rec["profile"] = profile_map.get(rec["stock_code"])

        out_path.write_text(json.dumps(_build_payload(records), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[export] JSON 저장 완료 → {export_json} ({len(records)}종목)")

    if filtered_json:
        import json
        from pathlib import Path as _Path

        passed_all = ranked[ranked["passed"]][cols]
        records = []
        for ticker, row in passed_all.iterrows():
            rec = {"stock_code": str(ticker)}
            for c in cols:
                rec[c] = _record_value(c, row[c])
            rec["name"] = rec["stock_code"]   # 화면에는 회사 전체명 대신 티커를 표시 (설계 결정)
            records.append(rec)

        payload = {
            "as_of_date": pd.Timestamp.now("UTC").strftime("%Y%m%d"),
            "financial_year": None,
            "generated_at": pd.Timestamp.now("UTC").isoformat(),
            "columns": cols,
            "column_labels_ko": {c: KOR_NAMES.get(c, c) for c in cols},
            "results": records,
        }
        out_path = _Path(filtered_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[export] 필터통과 전체 JSON 저장 완료 → {filtered_json} ({len(records)}종목)")

    return ranked


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--export-json", default="", help="예: ../web/data/results.json")
    ap.add_argument("--filtered-json", default="", help="예: ../web/data/filtered_full.json")
    a = ap.parse_args()
    if a.run:
        run_real(a.top, a.export_json if a.export_json else None, a.filtered_json if a.filtered_json else None)
    else:
        run_demo()
