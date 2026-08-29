# 미국 주식 스크리닝 웹 — 설계 스펙

날짜: 2026-08-14
기반: 기존 KOSPI 스크리닝 프로젝트(`stock_screen_web`)의 알고리즘·웹 구조를 미국 주식에 이식

## 1. 배경 & 목표

기존 KOSPI-Screening 웹(`stock_screen_web`)은 Stock Note 투자원칙(4대 팩터: 체력/가격/괴리/환원여력)을
규칙 엔진으로 구현해 매일 자동으로 KOSPI+KOSDAQ 전종목을 스크리닝하고, GitHub Actions + Vercel로
운영자 개입 없이 자동 갱신·배포되는 정적 웹사이트다.

이 프로젝트는 동일한 알고리즘과 동일한 웹 UI/기능을 미국 주식(S&P 500+400+600)에 적용한
새 웹사이트를 만든다. 사용자는 비개발자이므로, 계정 생성·API 키 발급 등 사용자만 할 수 있는
단계는 구현 중 명확히 안내하고 확인받는다.

## 2. 전체 구조

기존과 동일한 3단 구조를 그대로 재사용한다.

```
screening/          파이썬 스크리닝 엔진 (data_pipeline.py, ws_alpha.py 상당)
web/                 Next.js 웹사이트 (결과 표시, 업데이트 버튼, 종목 프로필 카드)
.github/workflows/   매일 자동 실행 스케줄 (workflow_dispatch로 수동/웹 실행도 가능)
```

- DB 없음. GitHub Actions가 `web/data/results.json`을 매일 커밋 → Vercel이 그 커밋을 감지해 자동 재배포.
- 웹사이트의 "스크리닝 업데이트 실행" 버튼(관리자 게이트 뒤) → GitHub Actions를 즉시 실행(GH_PAT로 원격 트리거).

## 3. 데이터 소스

**Financial Modeling Prep(FMP)** 단일 API 키로 다음을 모두 조회한다 (한국판의 KRX+DART 조합을 대체):

- 시세/시가총액: 종목별 quote, market cap
- 재무비율: ROE, 영업이익률, 부채비율, 매출/영업이익 YoY, FCF 등
- 밸류에이션: PER, PBR
- 배당: 배당수익률, 배당성향
- 섹터 정보 (FMP profile 엔드포인트가 직접 제공 — 한국판처럼 "미분류" 처리 불필요)

무료 티어는 호출 횟수 제한이 있으므로, 한국판의 `.cache/finance.parquet`과 동일한 방식으로
로컬(Actions 러너) 캐시를 두어 재무데이터는 자주 다시 받지 않는다 (주간 캐시 + 분기 실적시즌에만 강제 갱신).

## 4. 유니버스

**S&P 500 + S&P 400(중형) + S&P 600(소형)** ≈ 1,500개 종목. FMP의 지수 구성종목 엔드포인트로 매번 목록을 가져온다.

## 5. 알고리즘 (기존 로직 이식, 가중치·비율 동일)

### 하드 필터
| 항목 | 기존(KOSPI) | 미국판 |
|---|---|---|
| 시가총액 하한 | 800억원 | **$100M** (사용자 지정) |
| 시가총액 상한 | 40조원 (초대형 제외) | **없음** (사용자 지정 — 메가캡도 스크리닝 대상) |
| 20일 평균 거래대금 하한 | 3억원 | 비율 환산하여 USD로 적용 (예: 약 $230K/일) |
| 부채비율 | 200% 초과 배제 | 동일 |
| ROE(3년평균) | 5% 미만 배제 | 동일 |
| 최근 4분기 누적 영업이익 | 0 초과 요구 | 동일 |
| 3개월 수익률 | +60% 이상 배제(테마급등) | 동일 |

### 4대 팩터 (가중치 동일)
- 체력(Quality) 30% — ROE 3년평균, ROE 변동성, 영업이익률, 부채비율, 매출 CAGR
- 가격(Value) 28% — 이익수익률(1/PER), 순자산수익률(1/PBR), 배당수익률, FCF수익률
- 괴리(Gap) 27% — 12개월 수익률 낮을수록·52주 고점 대비 낙폭 클수록·영업이익 개선일수록 가점, 영업이익 YoY -10% 미만이면 게이트 차단
- 환원여력(Payout) 15% — 배당성향 여유분, 순현금/시총, ROE, 자사주비율

섹터 틸트(한국 특산품 가중치)는 **제거** — 팩터 점수만으로 순위 매김.

### 매매 규칙 엔진(보유종목 액션)
`decide()` 함수(스토리훼손→전량매도, +100%→원금회수, 테마급등 트림, 물타기/불타기 등)는
스크리닝 결과 화면과는 별도 기능이라 이번 1차 구현 범위에서는 **포함하지 않는다**
(기존 KOSPI판 웹에도 노출되어 있지 않고 내부 로직에만 존재 — 필요시 추후 별도 스펙으로 추가).

## 6. 웹 기능 (기존과 동일 이식)

- 정렬 가능한 결과 표 (`ScreeningTable`)
- 필터 통과 전체 종목 다운로드 버튼
- "스크리닝 업데이트 실행" 버튼 — 관리자 비밀번호 게이트(`AdminGate`) 뒤에 위치, 누르면 GitHub Actions 즉시 실행
- 최신 종가 새로고침 (서버사이드 API 라우트로 FMP 키 비노출)
- 종목별 AI 프로필 카드 — Claude Haiku가 사업내용/대표상품/경쟁사 생성 (미국 기업용으로 프롬프트만 수정)
- "이번주의 명언" → 한국판의 개인 투자노트 인용 대신, 유명 가치투자자(버핏/린치/그레이엄 등) 명언 세트로 대체
- UI 언어: 한국어. 종목명은 티커(예: AAPL)로 표시

## 7. 배포/운영

- GitHub Actions 스케줄: 미국 장마감(ET) 기준 시각으로 변경. 분기 재무 강제갱신 스케줄은
  미국 공시 일정(10-Q/10-K 제출 마감 전후)에 맞춰 조정
- Vercel: Root Directory `web`, 자동배포는 기존과 동일
- 필요 시크릿/환경변수 (기존 DART_API_KEY/KRX_API_KEY 자리를 FMP_API_KEY가 대체):
  - `FMP_API_KEY` — GitHub Secrets + Vercel Env
  - `ANTHROPIC_API_KEY` — GitHub Secrets (AI 프로필 카드용)
  - `GH_PAT`, `GH_OWNER`, `GH_REPO` — Vercel Env (웹에서 Actions 원격 실행용)
  - 관리자 비밀번호 (AdminGate용)

## 8. 사용자가 직접 해야 하는 단계 (비개발자 안내 대상)

구현 진행 중 아래 항목은 사용자 본인이 직접 수행해야 하며, 각 시점에 화면 캡처 수준으로 안내한다:

1. FMP 무료 계정 가입 + API 키 발급
2. Anthropic API 키 발급 (console.anthropic.com)
3. GitHub 새 저장소 생성 (레포명 확인 필요)
4. GitHub Fine-grained Personal Access Token 발급 (Actions Read/Write)
5. GitHub Secrets 등록
6. Vercel 가입 + 프로젝트 연결 + 환경변수 등록
7. 관리자 비밀번호 설정

## 9. 범위 밖 (다음 단계 후보)

- 매매 규칙 엔진(`decide()`)의 웹 노출 (보유종목 입력 → 액션 추천)
- 사용자 지정 유니버스 확장 (러셀지수 등)
- 다국어(영어) UI 전환

## 10. 애드엔덤 (2026-08-14) — 데이터 소스를 FMP → Finnhub + Wikipedia로 변경

1차 구현(Task 1-16, master에 병합됨) 완료 후, FMP 무료 티어의 호출 한도(하루 250건 고정)로는
S&P 500 하나만 스크리닝해도 매일 자동 실행이 불가능하다는 게 확인되어 데이터 소스를 교체한다.

### 문제
- FMP 무료 티어: 하루 250건 고정 상한. 종목당 과거시세 조회 1건씩만 해도 S&P 500(500종목)에서
  이미 500건 필요 — 유니버스 축소나 실행 빈도 축소로는 해결 안 됨(하루 상한 자체가 병목).
- FMP 유료 전환 시 비용은 공식 페이지에서 직접 확인 필요(자동 조회 실패, 봇 차단).

### 결정
- **개별 종목 데이터(시세·재무비율)**: Financial Modeling Prep → **Finnhub 무료 티어**로 교체.
  Finnhub 무료 티어는 하루 총량 상한이 아니라 **분당 60건** 속도 제한이라, 속도 조절만 하면
  S&P 500+400+600 전체(~1,500종목)를 매일 자동 실행해도 무료로 충분하다.
- **지수 구성종목 목록(S&P 500/400/600 티커 명단)**: Finnhub는 S&P 500만 지원하고 그마저도
  유료로 옮겨간 정황이 있어, 대신 **위키피디아**의 "List of S&P 500/400/600 companies" 문서를
  파싱해서 가져온다. API 키 불필요, 완전 무료. 지수 구성종목은 자주 안 바뀌므로 **주 1회**만
  갱신한다(개별 종목 시세·재무데이터는 기존과 동일하게 **매일** 갱신).
- 섹터 정보는 더 이상 데이터 소스가 직접 제공하지 않으므로(위키피디아 표에 업종 컬럼이 있으면
  활용, 없으면 Finnhub `company_profile2`의 `finnhubIndustry` 필드로 보완).

### 영향받는 범위
`screening/fmp_client.py` → `screening/finnhub_client.py`로 교체, `screening/wiki_universe.py`
신규 추가(위키피디아 파싱 + 주간 캐시), `screening/data_pipeline.py`·`screening/us_alpha.py`의
데이터 조립 부분 재작성, `web/app/api/prices/route.ts`(최신가 새로고침)를 Finnhub 호출로 교체,
`.github/workflows/daily-screen.yml`의 시크릿을 `FMP_API_KEY` → `FINNHUB_API_KEY`로 교체,
`README.md`의 1번 단계(FMP 가입)를 Finnhub 가입으로 교체. 알고리즘(4대 팩터, 하드필터, 가중치)과
웹 UI/기능은 변경 없음 — 순수 데이터 소스 교체.

## 11. 애드엔덤 (2026-08-28) — 부채 건전성·자사주매입 지표 교체, 52주 신저가 리스트 추가

사용자 요청: "부채비율보다 이자보상배율이 부채 건전성 지표로 더 낫다", "부채비율 하드필터는
없애라", "자사주매입을 새 지표로 추가하라(주주환원에서 중요)", "52주 신저가 종목을 별도로
뽑아달라", "자사주매입과 52주 낙폭이 더 중요한 지표로 작동하게 하라".

### 결정
- **부채비율 하드필터 폐지**: `Config.max_debt_ratio`와 `apply_hard_filters()`의 "부채과다"
  컷을 제거. 부채가 많다고 무조건 배제하지 않고, 대신 랭킹에서 감점 요인으로만 반영한다.
- **체력(quality) 팩터에서 부채비율 → 이자보상배율(interest_coverage) 교체**: Finnhub
  `netInterestCoverageTTM`(영업이익/이자비용 배수, 변환 불필요) 사용. 값이 높을수록 고득점.
- **환원여력(payout) 팩터에서 죽은 필드였던 treasury_ratio → 자사주매입률(buyback_rate)
  교체 + 비중 확대(0.10→0.35)**: Finnhub가 자사주매입 데이터를 직접 제공하지 않아, 이전
  분기 캐시 대비 발행주식수 감소율로 근사한다. 최초 도입 분기는 비교 기준이 없어 중립(NaN)
  처리됨. `data_pipeline.build_finance_cache()`가 `--force` 여부와 무관하게 이전 캐시의
  발행주식수를 먼저 읽어둔 뒤 새 값과 비교해 계산한다.
- **괴리(gap) 팩터에서 52주 낙폭(drawdown_52w) 비중 확대(0.25→0.40)**, 나머지 하위 가중치는
  비례 축소.
- **52주 신저가 근접 종목 별도 리스트 추가**: `data_pipeline.compute_return_and_drawdown()`가
  `pct_above_52w_low`(저점 대비 상승률, 0에 가까울수록 신저가 근접)를 추가로 계산·반환하고,
  `us_alpha.run_real()`이 하드필터 통과 종목 중 이 값이 가장 낮은 상위 30개를 종합점수와
  무관하게 별도 정렬해 `results.json`의 `near_52w_low` 키로 export한다. 웹에서는 기존
  `ScreeningTable`을 재사용해 별도 섹션으로 노출.
- 4대 팩터 간 최상위 가중치(체력30/가격28/괴리27/환원여력15)는 변경 없음 — 조정은 각 팩터
  내부의 하위 가중치에서만 이루어짐.

### 영향받는 범위
`screening/us_alpha.py`(Config·4개 score_* 함수·apply_hard_filters·load_real·run_real·
make_demo·KOR_NAMES), `screening/data_pipeline.py`(fetch_finance_one·build_finance_cache·
compute_return_and_drawdown), `screening/stock_profile.py`(AI 프로필 프롬프트용 지표 라벨),
`web/app/AlgorithmInfo.tsx`·`web/app/ScreeningTable.tsx`·`web/app/page.tsx`(52주 신저가
섹션), `.github/workflows/daily-screen.yml`(재무캐시 키 v2→v3, 신규 필드가 채워진 캐시로
강제 갱신). 재무 캐시 스키마가 바뀌므로(신규 컬럼 필수) `load_real()`은 `share_outstanding`과
함께 `interest_coverage`/`buyback_rate` 컬럼 존재 여부도 검사해 구버전 캐시를 명확한 오류로
거부한다(기존 `share_outstanding` 가드와 동일 패턴).

### 미검증 사항 (구현 중 확인 필요)
Finnhub의 `company_basic_financials`(metric=all) 응답 필드명(ROE, 부채비율, PER/PBR, 배당수익률,
배당성향, 매출성장률에 해당하는 정확한 키 이름)은 실시간 문서 접근이 막혀 있어 완전히 확정하지
못했다. 구현 시 실제 API 키로 한 번 호출해 응답을 직접 확인하고 필드 매핑을 맞출 것.

## 12. 애드엔덤 (2026-08-29) — 52주 신저가 리스트를 메인 목록의 하드필터로 전환

§11에서 추가한 "52주 신저가 근접 종목" 별도 리스트(`near_52w_low`)를 폐지하고, 그 취지를
메인 스크리닝 목록 자체의 하드필터로 흡수한다. 사용자 요청: "52주 신저가 근접 종목 섹션을
삭제해달라", "대신 목록을 (1) 52주 저점 10% 이내, (2) 5년 전보다 이익 증가, (3) REIT·ETF
제외라는 3가지 조건으로 한 번 더 필터링해달라". 적용 범위는 AskUserQuestion으로 확인받음
(메인 목록에 하드필터로 추가 — 별도 섹션 유지 아님).

### 결정
- **`apply_hard_filters()`에 3개 컷 추가**: `Config.max_pct_above_52w_low`(기본 0.10, 즉
  52주 저점 대비 +10% 초과 시 배제), `Config.min_eps_growth_5y`(기본 0.0, 5년 EPS CAGR이
  0% 이하면 배제), REIT 배제(GICS Sub-Industry에 "REIT" 포함 시 배제). 세 조건 모두
  결측(NaN)이면 "충족 여부를 알 수 없다"는 원칙으로 보수적으로 배제 처리한다(통과 조건이 아니라
  배제 조건으로 코딩 — `~(cond)` 형태).
- **ETF 제외는 별도 로직 없이 자연히 충족됨**: 유니버스가 위키피디아 S&P 500/400/600
  "구성종목(constituents)" 표 기반이라 애초에 지수 편입 종목(주식)만 존재하고 ETF는
  포함되지 않는다. 죽은 코드를 추가하지 않기 위해 이 사실만 UI 설명에 문서화하고 별도
  필터 로직은 두지 않았다.
- **5년 EPS 성장률 데이터**: Finnhub `epsGrowth5Y`(5년 EPS CAGR, %) 필드를 라이브 API
  호출로 실측 확인 후 사용(예: AAPL epsGrowth5Y=17.91). "5년 전보다 이익 증가"를 CAGR
  부호(> 0)로 근사 판정한다 — 정확한 5년전 단일시점 EPS 대비 비교가 아니라 5년 추세의
  방향성 근사치임을 알아둘 것.
- **REIT 판별을 위해 `wiki_universe.py`에 GICS Sub-Industry 컬럼 신규 파싱**: 기존
  `sector`(GICS Sector, 예: "Real Estate")만으로는 REIT과 일반 부동산관리회사를 구분할 수
  없어, 더 세분화된 GICS Sub-Industry(예: "Retail REITs", "Office REITs")를 별도
  `sub_industry` 컬럼으로 추가 파싱했다. 라이브 확인 결과 S&P 500/400/600 위키 표 3개 모두
  "GICS Sub-Industry" 헤더로 일관되게 존재.
- **"52주 신저가 근접 종목" 별도 섹션은 완전히 삭제**: `run_real()`의 `near_52w_low` export,
  `web/app/page.tsx`의 두 번째 `ScreeningTable` 섹션, `ScreeningTable`의
  `defaultSortKey`/`defaultSortDir` prop을 모두 되돌렸다. 이제 메인 목록 자체가 "저점 근처 +
  이익 성장 + REIT 제외" 조건을 만족하는 종목만 담는다.

### 영향받는 범위
`screening/us_alpha.py`(Config에 필드 2개 추가, `apply_hard_filters`에 컷 3개 추가,
`load_real`의 캐시 스키마 가드에 `eps_growth_5y`/`sub_industry` 추가, `run_real`에서
`near_52w_low` export 제거, `make_demo`에 대응 합성 컬럼 추가), `screening/data_pipeline.py`
(`fetch_finance_one`에 `eps_growth_5y` 필드 추가), `screening/wiki_universe.py`
(`sub_industry` 컬럼 신규 파싱), `screening/stock_profile.py`(AI 프로필 프롬프트 라벨),
`web/app/AlgorithmInfo.tsx`·`web/app/page.tsx`·`web/app/ScreeningTable.tsx`,
`.github/workflows/daily-screen.yml`(재무+유니버스 캐시 키 v3→v4, 신규 스키마로 강제
재구축). 재무 캐시뿐 아니라 유니버스 캐시도 스키마가 바뀌므로(`sub_industry` 신규 컬럼)
`load_real()`은 두 캐시 모두에 대해 구버전 거부 가드를 둔다.
