/**
 * FastAPI 연동 완료 (test-d-web-wire, B 작업 — D 검토용).
 *
 * 원래 여기 있던 MOCK_* 더미는 삭제하고 fetch 로 교체했다(컴포넌트는 한 줄도 안 건드림).
 * 내용이 전부 실제 API 호출이라 파일명도 mockData.ts → api.ts 로 맞췄다.
 *
 * ⚠ 엔드포인트 경로는 README 의 제안(`/reports/diagnosis` 등)이 아니라
 * api/main.py(FastAPI, dev 브랜치)에 실제로 구현된 `/api/*` 경로를 그대로 썼다 —
 * README 쪽은 아직 코드가 없던 시점의 제안이라, 실제로 존재하는 쪽에 맞췄다.
 *
 * ⚠ 이 화면들(대시보드/주문/백테스트)은 아직 사용자가 종목·주문을 직접 고르는
 * UI가 없어서, 페르소나와 모의 주문을 DEMO_PERSONA/DEMO_ORDER 로 고정해뒀다.
 * core/synth/personas.py 의 PRESETS 키 중 하나를 고르면 된다 — 실 사용자 데이터
 * 업로드 플로우가 생기면 이 두 상수 대신 실제 입력을 받아야 한다.
 */

import type { BacktestResult, DiagnosisReport, InterventionReport } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/** core/synth/personas.py PRESETS 중 하나. 데모 스토리에 맞는 걸로 고름(추격매수형). */
const DEMO_PERSONA = "chasing_prone";

/* -------------------------------------------------------------------------- */
/* 1. 진단 리포트 (/dashboard)                                                 */
/* -------------------------------------------------------------------------- */

export async function getDiagnosisReport(): Promise<DiagnosisReport> {
  const res = await fetch(`${API_BASE}/api/diagnose?persona=${DEMO_PERSONA}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error("진단 리포트 조회 실패");
  return res.json();
}

/* -------------------------------------------------------------------------- */
/* 2. 모의 주문창 개입 (/trade)                                                */
/* -------------------------------------------------------------------------- */

/** 데모용 고정 주문 — 캐시된 실제 종가(2026-08-18, 268,500원) 대비 +8% 로 잡아서
 *  추격매수 룰이 안정적으로 트리거되게 함. */
const DEMO_ORDER = {
  ticker: "005930",
  name: "삼성전자",
  side: "BUY",
  quantity: 10,
  price: 290_000,
};

export async function getInterventionReport(): Promise<InterventionReport> {
  const res = await fetch(`${API_BASE}/api/simulate-order?persona=${DEMO_PERSONA}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(DEMO_ORDER),
    cache: "no-store",
  });
  if (!res.ok) throw new Error("개입 리포트 조회 실패");
  return res.json();
}

/* -------------------------------------------------------------------------- */
/* 3. 백테스트 증명 (/backtest)                                                */
/* -------------------------------------------------------------------------- */

export async function getBacktestResult(): Promise<BacktestResult> {
  const res = await fetch(`${API_BASE}/api/backtest?persona=${DEMO_PERSONA}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error("백테스트 결과 조회 실패");
  return res.json();
}
