# 미국 주식 스크리닝 웹

S&P 500+400+600 종목을 4대 팩터(체력/가격/괴리/환원여력)로 매일 자동 스크리닝하는
웹사이트. GitHub Actions가 매일 자동으로 스크리닝을 돌려 `web/data/results.json`을
갱신하면, Vercel이 그 커밋을 감지해 자동으로 재배포한다. 별도 DB 없음.

## 구조

```
screening/          파이썬 스크리닝 엔진 (fmp_client.py, data_pipeline.py, us_alpha.py)
web/                 Next.js 웹사이트
.github/workflows/   매일 자동 실행 스케줄 (workflow_dispatch로 수동/웹 실행도 가능)
```

## 최초 설정 (한 번만) — 아래 순서대로 진행

### 1. Financial Modeling Prep(FMP) 계정 + API 키
1. https://site.financialmodelingprep.com 접속 → 무료 회원가입
2. 대시보드에서 API 키 복사해둔다
3. 참고: 무료 요금제는 하루 호출 횟수 제한이 있는데, S&P 500+400+600 전체(약 1,500종목)를
   종목당 여러 번씩 조회하는 이 스크리닝의 매일 자동 실행에는 부족할 수 있다. 매일 자동
   갱신이 필요하다면 유료 요금제 전환을 고려한다.

### 2. Anthropic API 키 (AI 종목 프로필 카드용)
1. https://console.anthropic.com 접속 → 계정 생성/로그인
2. API Keys 메뉴에서 새 키 발급, 복사해둔다

### 3. GitHub 저장소 만들기
이 폴더 전체를 새 GitHub 저장소에 push한다.

```bash
git remote add origin <본인의 GitHub 저장소 URL>
git push -u origin master:main
```

### 4. GitHub Secrets 등록
저장소 페이지 → Settings → Secrets and variables → Actions → New repository secret

- `FMP_API_KEY` : 1번에서 발급받은 키
- `ANTHROPIC_API_KEY` : 2번에서 발급받은 키

### 5. GitHub Personal Access Token 발급 (웹사이트가 Actions를 원격 실행시키기 위해 필요)
1. GitHub 우측 상단 프로필 → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token
2. Repository access: 이 저장소만 선택
3. Permissions → Actions: Read and write 로 설정
4. 생성된 토큰(ghp_로 시작)을 복사해둔다 (다시 못 봄, 꼭 메모)

### 6. GitHub Actions 활성화 확인
저장소 페이지 → Actions 탭 → 워크플로우가 보이는지 확인. 처음엔 수동으로 한 번
실행해서 잘 도는지 확인 (Actions → 일일 스크리닝 (미국 주식) → Run workflow).

### 7. Vercel 배포
1. https://vercel.com 가입 (GitHub 계정으로 로그인 추천)
2. "Add New… → Project" → 방금 만든 GitHub 저장소 선택
3. **Root Directory를 `web`으로 지정** (중요 — 안 하면 빌드 실패함)
4. Framework Preset은 Next.js가 자동 인식됨
5. **Environment Variables**에 아래 항목 추가 (Deploy 누르기 전에):
   - `FMP_API_KEY` : 1번 키 (최신 종가 새로고침용)
   - `GH_PAT` : 5번에서 발급받은 GitHub 토큰
   - `GH_OWNER` : GitHub 사용자명
   - `GH_REPO` : 저장소 이름
   - `ADMIN_PASSWORD` : 직접 정한 관리자 비밀번호 (사이트 하단 "관리자" 로그인용)
6. Deploy 클릭

이후로는:
- GitHub Actions가 매일 `results.json`을 커밋할 때마다 Vercel이 자동 재배포
- 웹사이트 하단 "관리자" 로그인 후 "스크리닝 업데이트 실행" 버튼을 누르면
  그 즉시 GitHub Actions가 실행되고, 끝나면 자동으로 사이트가 갱신됨

## 로컬에서 테스트하기

```bash
cd screening
pip install -r requirements.txt
setx FMP_API_KEY "발급받은키"
setx ANTHROPIC_API_KEY "발급받은키"
python data_pipeline.py --build
python us_alpha.py --run --top 50 --export-json "../web/data/results.json" --filtered-json "../web/data/filtered_full.json"
```

```bash
cd web
npm install
npm run dev
```

http://localhost:3000 에서 확인. `/api/prices`, `/api/update-finance`를 로컬에서
테스트하려면 `web/.env.local` 파일을 만들고 아래처럼 채워넣는다 (git에 올라가지 않음):

```
FMP_API_KEY=발급받은키
GH_PAT=발급받은토큰
GH_OWNER=본인깃헙아이디
GH_REPO=저장소이름
ADMIN_PASSWORD=원하는비밀번호
```

## 참고 사항

- 유니버스(S&P 500+400+600) 및 재무비율 필드명은 FMP 요금제/API 버전에 따라 조회
  방식이 달라질 수 있다. `screening/fmp_client.py`와 `screening/data_pipeline.py`의
  주석에 확인 방법이 적혀 있다.
- 하드 필터/팩터 가중치의 상세 근거는 `docs/superpowers/specs/2026-08-14-us-stock-screening-design.md` 참고.
