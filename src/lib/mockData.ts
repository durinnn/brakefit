/**
 * ⚠️ 임시 더미 데이터 계층.
 *
 * 모든 화면은 이 파일이 export 하는 async 함수(getDiagnosisReport / getInterventionReport /
 * getBacktestResult)만 호출한다. 컴포넌트는 데이터가 어디서 오는지 알지 못한다.
 *
 * FastAPI 연동 시:
 *   1) 아래 상수(MOCK_*)를 삭제한다.
 *   2) 각 함수 본문을 fetch 로 교체한다. 시그니처와 반환 타입은 그대로 둔다.
 *
 *      export async function getDiagnosisReport(): Promise<DiagnosisReport> {
 *        const res = await fetch(`${API_BASE}/reports/diagnosis`, { cache: "no-store" });
 *        if (!res.ok) throw new Error("진단 리포트 조회 실패");
 *        return res.json();
 *      }
 *
 *   3) 컴포넌트는 단 한 줄도 고치지 않는다.
 */

import type {
  BacktestResult,
  DiagnosisReport,
  InterventionReport,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/* -------------------------------------------------------------------------- */
/* 1. 진단 리포트 (/dashboard)                                                 */
/* -------------------------------------------------------------------------- */

const MOCK_DIAGNOSIS: DiagnosisReport = {
  periodLabel: "2025.09 ~ 2026.08 (12개월)",
  totalTrades: 284,
  overallScore: 74,
  overallGrade: "위험",
  generatedAt: "2026-08-27T09:12:00+09:00",
  metrics: [
    {
      key: "disposition",
      name: "처분효과",
      score: 81,
      percentile: 8,
      sampleCount: 132,
      delta: 6,
      summary:
        "오른 종목은 평균 4일 만에 팔고, 내린 종목은 평균 47일을 버텼습니다.",
    },
    {
      key: "averaging_down",
      name: "물타기 지수",
      score: 68,
      percentile: 17,
      sampleCount: 41,
      delta: -3,
      summary:
        "손실 구간에서의 추가 매수가 전체 매수의 34%를 차지합니다.",
    },
    {
      key: "chasing",
      name: "추격매수 계수",
      score: 73,
      percentile: 12,
      sampleCount: 56,
      delta: 11,
      summary:
        "당일 5% 이상 급등한 종목을 장중에 따라 산 사례가 56건입니다.",
    },
  ],
};

export async function getDiagnosisReport(): Promise<DiagnosisReport> {
  return MOCK_DIAGNOSIS;
}

/* -------------------------------------------------------------------------- */
/* 2. 모의 주문창 개입 (/trade)                                                */
/* -------------------------------------------------------------------------- */

const MOCK_INTERVENTION: InterventionReport = {
  order: {
    ticker: "042700",
    name: "한미반도체",
    side: "BUY",
    quantity: 30,
    price: 118_400,
    changeRate: 9.8,
  },
  riskScore: 87,
  riskLevel: "HIGH",
  baseScore: 20,
  contributions: [
    {
      label: "당일 급등 추격",
      value: 26,
      detail: "장중 +9.8% 상태에서의 신규 진입",
    },
    {
      label: "직전 손실 직후 매수",
      value: 21,
      detail: "34분 전 -212만원 손절 확정",
    },
    {
      label: "평소 대비 주문 규모",
      value: 14,
      detail: "평균 주문금액의 3.1배",
    },
    {
      label: "동일 종목 재진입",
      value: 9,
      detail: "최근 30일 내 4번째 진입 시도",
    },
    {
      label: "분산 보유 상태",
      value: -3,
      detail: "포트폴리오 종목 수 11개로 양호",
    },
  ],
  warning: {
    headline: "당신의 과거 추격매수 12건 평균 수익률은 -18%입니다",
    caseCount: 12,
    averageReturn: -18,
    description:
      "이번 주문은 과거 손실을 냈던 12건과 진입 조건이 87% 일치합니다. 그중 10건은 매수 후 3일 내 하락 전환했습니다.",
  },
  suggestions: [
    "주문 금액을 평소 수준(약 120만원)으로 낮추기",
    "장 마감 후 종가로 재검토하기",
    "24시간 쿨다운 후 알림 받기",
  ],
};

export async function getInterventionReport(): Promise<InterventionReport> {
  return MOCK_INTERVENTION;
}

/* -------------------------------------------------------------------------- */
/* 3. 백테스트 증명 (/backtest)                                                */
/* -------------------------------------------------------------------------- */

const MOCK_BACKTEST: BacktestResult = {
  periodLabel: "2025.09 ~ 2026.08 (12개월)",
  interventionCount: 37,
  avoidedLoss: 8_420_000,
  missedGain: 2_180_000,
  netBenefit: 6_240_000,
  netBenefitRate: 12.4,
  hitRate: 73,
  cases: [
    { date: "2026.07.14", name: "에코프로비엠", impact: 1_940_000, biasKey: "chasing" },
    { date: "2026.05.02", name: "포스코홀딩스", impact: 1_310_000, biasKey: "averaging_down" },
    { date: "2026.03.19", name: "카카오", impact: 880_000, biasKey: "disposition" },
    { date: "2026.02.06", name: "삼성SDI", impact: -640_000, biasKey: "chasing" },
    { date: "2025.12.11", name: "LG에너지솔루션", impact: 1_120_000, biasKey: "averaging_down" },
    { date: "2025.10.28", name: "네이버", impact: -430_000, biasKey: "disposition" },
  ],
};

export async function getBacktestResult(): Promise<BacktestResult> {
  return MOCK_BACKTEST;
}
