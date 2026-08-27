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
uv sync                       # 환경 구성
uv run pytest                 # 전체 테스트
uv run ruff format . && uv run ruff check --fix .   # 커밋 전 필수

python tools/inspect_export.py <증권사파일>          # export 구조 확인
python tools/inspect_export.py <파일> --redact       # 공유용 마스킹 사본
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

React / Next.js · Docker 최적화 · CI-CD · vectorbt·backtrader ·
GitHub Spec Kit 도입 · MCP 5개 이상 · ML 모델 학습

이유는 `claude/toolchain-decisions.md` 참조. 시간이 남아도 되살리지 않는다.

## 현재 상태 (2026-08-27)

- ✅ `core/parser` — KB증권 화면 3종 매핑 완료, 테스트 30개
- ✅ `tools/inspect_export.py` — 증권사 파일 구조 덤프
- ⬜ `docs/schema.md` — **초안만 있음. A 의 확정 필요 (최대 병목)**
- ⬜ `core/synth` — 합성 페르소나 생성기. 실 거래내역이 없어 이게 유일한 데이터 소스
- ⬜ `core/engine` · `core/metrics` · `core/rules` · `core/backtest` · `api/` · `web/`

⚠ **실 거래내역은 아직 0건이다.** 계좌는 개설했으나 국내주식 매매 이력이 없다.
개발·데모는 `core/synth` 의 합성 페르소나로 간다. 파서는 실데이터가 오면 바로 붙도록 준비만 된 상태.
