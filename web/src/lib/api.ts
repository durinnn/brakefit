/**
 * FastAPI 연동 (test-d-web-wire, B 작업 — D 검토용).
 *
 * 원래 여기 있던 MOCK_* 더미는 삭제하고 fetch 로 교체했다(컴포넌트는 한 줄도 안 건드림).
 * 내용이 전부 실제 API 호출이라 파일명도 mockData.ts → api.ts 로 맞췄다.
 *
 * ⚠ 엔드포인트 경로는 README 의 제안(`/reports/diagnosis` 등)이 아니라
 * api/main.py(FastAPI, dev 브랜치)에 실제로 구현된 `/api/*` 경로를 그대로 썼다 —
 * README 쪽은 아직 코드가 없던 시점의 제안이라, 실제로 존재하는 쪽에 맞췄다.
 *
 * 데이터 소스는 두 갈래다:
 *   - 업로드 세션 있음 → `?session=<sessionId>` (사용자가 올린 실제 거래내역)
 *   - 없음             → `?persona=<DEMO_PERSONA>` (합성 페르소나 데모)
 * 세션이 만료(404)되면 조용히 페르소나로 폴백한다 — 데모 도중 Render 가 재시작해도
 * 화면이 죽으면 안 되기 때문. 폴백했다는 사실은 sessionExpired 로 화면에 전달해서
 * 배지가 쿠키를 정리하게 한다.
 */

import type {
  BacktestResult,
  DiagnosisReport,
  InterventionReport,
  UploadResult,
} from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/** core/synth/personas.py PRESETS 중 하나. 데모 스토리에 맞는 걸로 고름(추격매수형). */
const DEMO_PERSONA = "chasing_prone";

/** 화면이 지금 무엇을 보고 있는지 */
export type DataSource = "session" | "persona";

export interface ApiResult<T> {
  data: T;
  source: DataSource;
  /** session 을 줬는데 404 라 persona 로 되돌린 경우 true */
  sessionExpired: boolean;
}

/** `?session=` 또는 `?persona=` 중 하나를 붙인다. */
function query(session: string | null | undefined): string {
  return session
    ? `?session=${encodeURIComponent(session)}`
    : `?persona=${DEMO_PERSONA}`;
}

/**
 * 세션 우선 호출 + 404 시 페르소나 폴백 공통 처리.
 * init 을 함수로 받는 이유: POST 본문을 재시도 때 그대로 다시 써야 해서.
 */
async function fetchWithFallback<T>(
  path: string,
  session: string | null | undefined,
  errorMessage: string,
  init: RequestInit = {},
): Promise<ApiResult<T>> {
  if (session) {
    const res = await fetch(`${API_BASE}${path}${query(session)}`, {
      ...init,
      cache: "no-store",
    });
    if (res.ok) {
      return { data: (await res.json()) as T, source: "session", sessionExpired: false };
    }
    // 404 = 서버가 모르는 세션(재시작·만료). 그 외 에러는 감추지 않는다.
    if (res.status !== 404) throw new Error(errorMessage);
  }

  const res = await fetch(`${API_BASE}${path}${query(null)}`, {
    ...init,
    cache: "no-store",
  });
  if (!res.ok) throw new Error(errorMessage);
  return {
    data: (await res.json()) as T,
    source: "persona",
    sessionExpired: Boolean(session),
  };
}

/* -------------------------------------------------------------------------- */
/* 0. 거래내역 업로드 (/upload) — 클라이언트에서만 호출                        */
/* -------------------------------------------------------------------------- */

export async function uploadTrades(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);

  // Content-Type 은 직접 지정하지 않는다 — boundary 를 브라우저가 붙여야 한다
  const res = await fetch(`${API_BASE}/api/upload`, {
    method: "POST",
    body: form,
    cache: "no-store",
  });

  if (!res.ok) {
    // 백엔드는 실패 시 400 { detail: "한국어 사유" } 로 준다. 파싱 실패는 상태코드로 대체.
    let detail = `업로드에 실패했습니다 (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body?.detail === "string" && body.detail) detail = body.detail;
    } catch {
      /* JSON 이 아니면 기본 문구 유지 */
    }
    throw new Error(detail);
  }

  return (await res.json()) as UploadResult;
}

/* -------------------------------------------------------------------------- */
/* 1. 진단 리포트 (/dashboard)                                                 */
/* -------------------------------------------------------------------------- */

export function getDiagnosisReport(
  session?: string | null,
): Promise<ApiResult<DiagnosisReport>> {
  return fetchWithFallback<DiagnosisReport>(
    "/api/diagnose",
    session,
    "진단 리포트 조회 실패",
  );
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

export function getInterventionReport(
  session?: string | null,
): Promise<ApiResult<InterventionReport>> {
  return fetchWithFallback<InterventionReport>(
    "/api/simulate-order",
    session,
    "개입 리포트 조회 실패",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(DEMO_ORDER),
    },
  );
}

/* -------------------------------------------------------------------------- */
/* 3. 백테스트 증명 (/backtest)                                                */
/* -------------------------------------------------------------------------- */

export function getBacktestResult(
  session?: string | null,
): Promise<ApiResult<BacktestResult>> {
  return fetchWithFallback<BacktestResult>(
    "/api/backtest",
    session,
    "백테스트 결과 조회 실패",
  );
}
