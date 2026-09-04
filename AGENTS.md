# brakefit — AI 코딩 에이전트 지침

> 이 파일은 Claude Code · Gemini CLI · Cursor · Copilot 이 공통으로 읽는다.
> `CLAUDE.md` 는 이 파일을 참조만 한다 (이중 관리 금지).
> 4명이 각자 AI 를 돌리는 프로젝트라, 이 규칙이 없으면 모듈 경계가 하루 만에 무너진다.

## 프로젝트

개인투자자의 거래내역으로 **행동 편향을 수치화**하고, 같은 실수를 반복하기 직전에 **개입**하는 웹서비스.
2026 금융 AI Challenge 출품작. **제출 9/7 10:00** (내부 마감 9/6 밤).

목표는 수상이 아니라 **돌아가는 데모**다. 범위를 늘리는 제안보다 줄이는 제안을 우선한다.

## 명령어

```bash
uv sync --extra web           # 환경 구성 (api/ 가 fastapi 를 쓰므로 web extra 필수 — 그냥 uv sync 만 하면 tests/test_api.py 가 깨짐)
uv run pytest                 # 전체 테스트
uv run ruff format . && uv run ruff check --fix .   # 커밋 전 필수

python tools/inspect_export.py <증권사파일>          # export 구조 확인
python tools/inspect_export.py <파일> --redact       # 공유용 마스킹 사본

python tools/generate_synth_fixtures.py              # fixtures/synth/*.csv 재생성 (실 거래내역 없을 때 이걸로 개발)
python tools/run_engine.py --persona disposition_prone   # engine 결과 확인 (--csv <파일> 도 가능)

uv run uvicorn api.main:app --reload                 # API 서버 실행 (http://localhost:8000/docs)
```

## 폴더 오너십 — 자기 폴더 밖은 PR 리뷰 필수

| 경로 | 담당 |
|---|---|
| `core/schema.py`, `core/engine/` | A (리더) |
| `core/parser/`, `core/synth/` | B |
| `core/metrics/`, `core/rules/` | C |
| `core/backtest/`, `api/`, `web/`, `deploy/` | D |
| `fixtures/` | B 가 공급, 나머지는 읽기 전용 |
| `docs/` | 각자 자기 정의서 소유 |

## 절대 규칙

1. **룩어헤드 금지.** 브레이크 룰과 백테스트는 **주문 시점에 알 수 있는 정보만** 쓴다.
   미래 가격을 참조하는 코드는 그 자체로 버그다. 리뷰에서 제일 먼저 본다.

2. **스키마는 문서가 진실이다.** 모듈 간 데이터 형태는 `docs/schema.md` 에 적힌 것만 유효하다.
   바꾸고 싶으면 코드가 아니라 **문서부터 PR**.

3. **`fee` / `tax` 는 `None` 과 `0` 을 구분한다.**
   `None` = 그 화면이 수수료를 안 알려줌 (실현손익이 gross)
   `0` = 실제로 0원이었음
   섞으면 지표·백테스트 수치가 조용히 틀어진다. `None` 을 `fillna(0)` 하지 말 것.

4. **개인정보를 커밋하지 않는다.** 증권사 export 원본에는 계좌번호·계좌명이 평문으로 들어있다.
   `data/raw/` 는 `.gitignore` 에 있다. `fixtures/` 에 들어가는 값은 전부 지어낸 것이어야 한다.

5. **백테스트 완료 전에는 기획서에 구체 수치를 쓰지 않는다.**

6. **합성 페르소나 결과에는 "실사용자 분포 아님" 각주를 반드시 단다.**

7. **`main` 직접 푸시 금지.** 브랜치 → PR. 논쟁은 10분 토론 후 리더 결정.

## 코드 규칙

- 파이썬 3.11+, `uv` 로 의존성 관리. `pip install` 로 전역 설치 금지
- 새 라이브러리를 넣기 전에 물어본다. D-10 에 의존성이 늘면 배포에서 터진다
- 주석과 문서는 **한국어**. 식별자는 영어 snake_case
- 주석은 "무엇"이 아니라 **"왜"** 를 적는다. 특히 삽질해서 알아낸 것 (예: `engine="calamine"`)
- 새 증권사 화면 지원 = **YAML 매핑 추가**. `core/parser/kb_hts.py` 는 건드리지 않는다
- 예외는 삼키지 않는다. 파서가 행을 버리면 반드시 사유를 `SkippedRow` 로 남긴다

## 테스트

- 새 파서 매핑에는 fixture 와 테스트를 같이 낸다
- fixture 는 **손으로 검산 가능한 크기**로 (10~15건). 큰 데이터로는 버그를 못 찾는다
- 엔진·지표·백테스트는 기대 정답표와 대조하는 테스트가 있어야 한다.
  AI 에게 로직을 맡기려면 채점표가 먼저 있어야 한다

## 하지 말 것 (이번 대회 한정)

Docker 최적화 · CI-CD · vectorbt·backtrader ·
GitHub Spec Kit 도입 · MCP 5개 이상 · ML 모델 학습

이유는 `claude/toolchain-decisions.md` 참조. 시간이 남아도 되살리지 않는다.

> React/Next.js 는 2026-08-28 부로 제외됨 — D 가 `lovulive` 브랜치에 프론트 스켈레톤을
> 이미 Next.js 로 짜서 올렸다. `web/` 은 이 스택으로 확정.

## 현재 상태 (2026-08-31)

- ✅ `core/parser` — KB증권 화면 3종 매핑 완료, 테스트 30개. **실제 export 파일로 첫 검증
  완료** (0112 화면, 해외주식 1건 정상 파싱 — 아래 참조)
- ✅ `tools/inspect_export.py` — 증권사 파일 구조 덤프
- ✅ `core/synth` — 합성 페르소나 5종. Monte Carlo + 실제 pykrx 데이터로 편향 신호 검증
  완료. `core/synth/prices.py` 가 pykrx 원시 시세 인터페이스도 겸함(§5).
  `fixtures/synth/*.csv` 로 데모 데이터 공급 완료 — `tools/generate_synth_fixtures.py`
  로 재생성 가능
- ✅ `core/metrics` (처분효과·물타기·추격매수) · `core/rules`(브레이크 룰 3종) ·
  `core/guard`(LLM 가드레일) — C 담당, `dev` 에 있음
- ✅ `docs/schema.md` §6 미결 3개 — **A 가 B 에게 위임, 확정됨** (§6.1 amount 기준
  평단가 / §6.2 T+2 보정 없음 / §6.3 동일일 다중체결 그대로 둠)
- ✅ `core/engine` — B 가 §6 확정값으로 구현, `test-jw` → `dev` 병합. synth 거래 ->
  engine -> C 의 실제 metrics/rules 까지 로컬에서 끝까지 연결 확인함(처음으로 전체
  파이프라인이 돌아감). `tools/run_engine.py` 로 CLI 실행 가능
- ⚠ `pyproject.toml` 에 `setuptools<81` 추가함(사전 논의 없이 — pykrx 가 요구하는
  `pkg_resources` 를 최신 setuptools 가 빼버려서 import 자체가 안 됐음, D-10 코드규칙
  "새 라이브러리 전 물어보기" 예외적으로 건너뜀). `uv.lock` 도 커밋함
- ✅ `core/backtest` · `api/` — **D 오너십인데 D 무응답이라 B 가 대신 초안 작성,
  `dev` 에 병합함** (`test-d-backtest` 브랜치 거쳐서). D 가 검토해서 갈아엎어도 됨.
  물타기·추격매수(BUY) 만 v1 범위 — 처분효과(SELL)는 반사실 정의가 달라서 제외
  (근거는 `core/backtest/backtest.py` 모듈 docstring). `api/` 는 FastAPI로
  engine→metrics→rules→backtest 를 HTTP 로 노출, `web/`(lovulive)의 `types.ts`
  형태에 맞춰 camelCase 로 응답 — `uv sync --extra web` 필요(위 명령어 참조)
  ⚠ 백테스트를 synth 데이터로 실행해보니 물타기형/추격매수형 페르소나에서
  net_benefit 이 음수로 나옴(이 기간 KRX 가 전반적 상승장이라, 편향과 무관하게
  "더 사면 나중에 올라있을 확률"이 높아서) — 데모 기간 선택에 따라 헤드라인
  숫자가 크게 흔들릴 수 있음, **기획서에 수치 넣기 전에 팀 논의 필요**
- ⬜ `deploy/` — 미착수
- ⚠ `web/` — 스켈레톤은 `lovulive` 브랜치에 있으나 **레포 히스토리와 무관한 별개
  브랜치(unrelated history)라 일반 병합이 안 됨** + 파일이 `web/` 이 아니라 레포
  루트에 있어서(`AGENTS.md` 오너십과 불일치) 재구성 필요. D 확인 필요 (보류 중 —
  급하면 B 가 대신 재구성 가능)

**실 거래내역 진행 상황**: 계좌 개설 후 첫 거래 발생 (2026-08-31) — 해외주식(미국,
VolitionRx) 1건은 0112 화면에서 정상 파싱 확인(단, 해외주식이라 KRX ticker 없음 +
통화가 USD 라 engine/metrics 파이프라인에는 못 태움 — 국내주식 전용 설계라 범위 밖).
국내주식(디아이씨) 매수 1건도 체결됐으나 0112 화면 반영 대기 중(정산 지연 추정).
개발·데모는 여전히 `core/synth` 가 메인 — 실데이터는 검증용 보너스.
