# 매매 브레이크 — 프론트엔드 MVP

2030 신규 주식 투자자의 행동 편향을 수치화하고, 무리한 매매 직전에 개입하는 서비스의 프론트엔드 스켈레톤.

- **스택:** Next.js 15 (App Router) · TypeScript · Tailwind CSS 3
- **데이터:** FastAPI(`api/`) 호출. `src/lib/api.ts` 한 곳에서만 관리
- **레이아웃:** 모바일 MTS 채널 기준으로 최대 430px 폭 고정

## 실행

```bash
npm install
npm run dev     # http://localhost:3000
npm run typecheck
```

> 이 저장소는 네트워크가 차단된 환경에서 작성되어 `node_modules`가 포함되어 있지 않습니다.
> 첫 실행 전 반드시 `npm install`을 돌려야 합니다.

## 화면

| 경로 | 화면 | 핵심 요소 |
|---|---|---|
| `/dashboard` | 진단 리포트 | 종합 편향 반원 게이지 + 3대 지표(처분효과·물타기·추격매수) 점수/상위 백분위 프로그레스 바 |
| `/trade` | 모의 주문창 개입 | 상단 위험 게이지(0~100) · 중단 기여도 워터폴 차트 · 하단 붉은 경고 박스 + 멈추기/강행 액션 |
| `/backtest` | 백테스트 증명 | 회피한 손실 ↔ 놓친 이익 대칭 비교, 최종 순수익(Net)을 최대 강조 |
| `/upload` | 거래내역 업로드 | 증권사 파일(.csv/.xlsx/.xls) 업로드 → 세션 발급 → 위 3화면이 내 데이터로 전환 |

`/`는 `/dashboard`로 리다이렉트됩니다. 업로드 없이도 데모 페르소나로 전 화면이 동작합니다.

## 데이터 소스 — 데모 페르소나 vs 업로드 세션

`/upload`에서 파일을 올리면 백엔드가 `sessionId`를 주고, 이걸 **쿠키 `bf_session`**(path=/)에
심습니다. 이후 `/api/*` 호출에 `?session=<sessionId>`가 붙고, 쿠키가 없으면 기존
`?persona=chasing_prone`로 폴백합니다.

localStorage가 아니라 쿠키인 이유: `/dashboard` · `/trade` · `/backtest`가 전부 async
**서버 컴포넌트**라 렌더 시점에 세션을 알아야 하는데, 서버에서는 localStorage를 못 읽습니다.
쿠키면 `next/headers`의 `cookies()`로 서버가 그대로 읽습니다.

- 서버 읽기: `src/lib/session.server.ts` (`getServerSession`)
- 클라이언트 읽기/쓰기/삭제: `src/lib/session.ts`
- 세션이 만료돼 백엔드가 **404**를 주면 `api.ts`가 조용히 페르소나로 폴백하고
  (`sessionExpired: true`), `DataSourceBadge`가 쿠키를 정리합니다 — 데모 중 Render가
  재시작해도 화면이 죽지 않게.

대시보드 상단 배지에서 현재 소스("데모 페르소나" / "내 거래내역 · N건")를 확인하고
데모로 되돌릴 수 있습니다.

## 구조

```
src/
├─ app/
│  ├─ layout.tsx           # 모바일 셸 + 하단 탭
│  ├─ globals.css          # Tailwind 엔트리, .card/.label 유틸
│  ├─ page.tsx             # → /dashboard 리다이렉트
│  ├─ dashboard/page.tsx
│  ├─ trade/page.tsx
│  ├─ backtest/page.tsx
│  └─ upload/page.tsx      # 클라이언트 컴포넌트 (파일 입력)
├─ components/
│  ├─ ArcGauge.tsx         # 반원 게이지 (SVG, 라이브러리 無)
│  ├─ ProgressBar.tsx      # 0~100 가로 바
│  ├─ WaterfallChart.tsx   # 기여도 워터폴 (CSS 절대위치 막대)
│  ├─ ComparisonBar.tsx    # 손실/이익 대칭 비교
│  ├─ NetResultCard.tsx    # 순수익 강조 카드
│  ├─ WarningBox.tsx       # 붉은 경고 박스
│  ├─ BiasMetricCard.tsx
│  ├─ InterventionActions.tsx  # 클라이언트 컴포넌트
│  ├─ DataSourceBadge.tsx  # 클라이언트 컴포넌트 (쿠키 정리·리셋)
│  ├─ PageHeader.tsx
│  └─ BottomNav.tsx
└─ lib/
   ├─ types.ts             # 도메인 타입 (백엔드 스키마와 1:1 대응 목표)
   ├─ api.ts               # FastAPI 호출 (구 mockData.ts — 더미는 이미 걷어냄)
   ├─ session.ts           # bf_session 쿠키 (클라이언트)
   ├─ session.server.ts    # bf_session 쿠키 (서버, next/headers)
   └─ format.ts            # 표기 유틸
```

## FastAPI 연동 방법

컴포넌트는 데이터 출처를 전혀 모릅니다. 세 개의 async 함수 본문만 바꾸면 됩니다.

```ts
// src/lib/api.ts (구 src/lib/mockData.ts)
export async function getDiagnosisReport(): Promise<DiagnosisReport> {
  const res = await fetch(`${API_BASE}/reports/diagnosis`, { cache: "no-store" });
  if (!res.ok) throw new Error("진단 리포트 조회 실패");
  return res.json();
}
```

1. `MOCK_*` 상수 삭제
2. 각 함수 본문을 `fetch`로 교체 (**시그니처·반환 타입은 유지**)
3. `.env.local`에 `NEXT_PUBLIC_API_BASE=http://localhost:8000`
4. 컴포넌트는 수정하지 않음

필요한 엔드포인트:

| 함수 | 제안 엔드포인트 | 반환 타입 |
|---|---|---|
| `getDiagnosisReport` | `GET /reports/diagnosis` | `DiagnosisReport` |
| `getInterventionReport` | `POST /orders/evaluate` | `InterventionReport` |
| `getBacktestResult` | `GET /backtest/result` | `BacktestResult` |

## 디자인 원칙

무채색(`ink` 10단계) 베이스에 포인트 컬러 2개만 사용합니다.

- `risk` `#E0484A` — 위험, 경고, 편향 심각
- `safe` `#2FB6A0` — 방어 성공, 순수익
- `warn` `#E0A030` — 주의 구간

숫자는 `.tabular`(tabular-nums)로 자릿수를 고정해 스캔 가독성을 확보했습니다.
