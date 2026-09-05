/**
 * 도메인 타입 정의.
 * FastAPI 백엔드의 응답 스키마(Pydantic)와 1:1로 대응시키는 것을 목표로 한다.
 * api.ts(구 mockData.ts)를 걷어내도 이 파일은 그대로 남는다.
 */

/** 3대 편향 지표 식별자 */
export type BiasKey = "disposition" | "averaging_down" | "chasing";

/** 진단 리포트 - 개별 편향 지표 */
export interface BiasMetric {
  key: BiasKey;
  /** 화면 표기명 (예: 처분효과) */
  name: string;
  /** 0~100 점수. 높을수록 편향이 강함 */
  score: number;
  /** 상위 백분위 (예: 12 → 상위 12%) */
  percentile: number;
  /** 한 줄 해석 문구 */
  summary: string;
  /** 근거가 된 거래 건수 */
  sampleCount: number;
  /** 직전 진단 대비 점수 변화량 (없으면 null) */
  delta: number | null;
}

/** 진단 리포트 화면 전체 응답 */
export interface DiagnosisReport {
  /** 분석에 사용된 거래 기간 */
  periodLabel: string;
  totalTrades: number;
  /** 종합 편향 점수 0~100 */
  overallScore: number;
  overallGrade: "안정" | "주의" | "위험";
  metrics: BiasMetric[];
  generatedAt: string;
  /**
   * 계산 중 사용자가 알아야 할 사실(보유수량보다 많은 매도 기록, 종목코드 미해결 등).
   * 없으면 빈 배열. 구버전 백엔드 응답에는 아예 없을 수 있어 optional 이다.
   */
  warnings?: string[];
}

/** 위험 점수 기여도 워터폴의 단일 항목 */
export interface RiskContribution {
  label: string;
  /** 가산(+) / 감산(-) 포인트 */
  value: number;
  /** 사용자에게 보여줄 근거 설명 */
  detail: string;
}

/** 개입 화면에서 다루는 주문 정보 */
export interface PendingOrder {
  ticker: string;
  name: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
  /** 직전 종가 대비 등락률 (%) */
  changeRate: number;
}

/** 과거 유사 패턴 경고 */
export interface PatternWarning {
  headline: string;
  /** 유사 사례 건수 */
  caseCount: number;
  /**
   * 해당 사례들의 evidence.return_pct 평균 (%). **주문 이후의 실제 수익률이 아니다.**
   * 지배 편향에 따라 의미가 다르다 — 추격매수: 매수 시점 급등률 / 물타기: 매수
   * 시점 평가손익률 / 처분효과: 근거 episode 의 손익률(실현 또는 현재 미실현).
   * 화면 레이블은 WarningBox 가 지배 편향별로 바꿔 단다.
   */
  averageReturn: number;
  description: string;
}

/** 모의 주문창 개입 화면 전체 응답 */
export interface InterventionReport {
  order: PendingOrder;
  /** 0~100 위험 게이지 */
  riskScore: number;
  riskLevel: "LOW" | "MEDIUM" | "HIGH";
  /**
   * 개입 팝업을 띄울지의 판정 결과(백엔드 core/rules 가 정한다).
   * riskLevel 로 재계산하지 말 것 — 임계값은 룰 쪽에만 있어야 한다.
   */
  shouldIntervene: boolean;
  /** 워터폴 시작점 (기준 위험도) */
  baseScore: number;
  contributions: RiskContribution[];
  warning: PatternWarning;
  /** 시스템이 제안하는 대안 행동 */
  suggestions: string[];
}

/** 모의 주문 폼에서 고를 수 있는 종목 (GET /api/universe 응답 항목) */
export interface UniverseItem {
  ticker: string;
  name: string;
  /**
   * 기준일(as_of) 이하의 마지막 종가. 주문 폼의 예상 체결가 기본값으로 쓴다.
   * 시세를 못 구했으면 null — 임의의 값으로 채우지 않는다.
   */
  lastClose: number | null;
  /** lastClose 가 찍힌 날짜 (YYYY-MM-DD). lastClose 가 null 이면 같이 null */
  lastDate: string | null;
}

/** 클라이언트가 POST /api/simulate-order 로 보내는 모의 주문 */
export interface OrderInput {
  ticker: string;
  name: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
}

/** 거래내역 업로드 결과 (POST /api/upload 응답) */
export interface UploadResult {
  /** 이후 /api/* 호출에 `?session=` 으로 붙이는 식별자 */
  sessionId: string;
  /** 파싱에 성공한 거래 건수 */
  tradeCount: number;
  /** 파서가 버린 행 수 (사유는 warnings 로 옴) */
  skippedCount: number;
  /** 분석 대상 기간 표기 (예: 2026-01-02 ~ 2026-08-29) */
  period: string;
  /** 사용자에게 보여줄 경고 문구. 없으면 빈 배열 */
  warnings: string[];
  /** 어떤 형식으로 인식했는지 */
  source: "kb_export" | "standard_csv";
}

/** 백테스트 - 개별 차단 사례 */
export interface BlockedCase {
  date: string;
  name: string;
  /** 브레이크가 막았을 때의 손익 영향 (원). 양수=회피한 손실, 음수=놓친 이익 */
  impact: number;
  biasKey: BiasKey;
}

/** 백테스트 증명 화면 전체 응답 */
export interface BacktestResult {
  periodLabel: string;
  /** 브레이크가 개입했을 거래 건수 */
  interventionCount: number;
  /** 회피한 손실 총액 (원, 양수) */
  avoidedLoss: number;
  /** 놓친 이익 총액 (원, 양수) */
  missedGain: number;
  /** 순수익 = 회피한 손실 - 놓친 이익 */
  netBenefit: number;
  /** 원금 대비 방어율 (%) */
  netBenefitRate: number;
  /** 개입이 유효했던 비율 (%) */
  hitRate: number;
  cases: BlockedCase[];
  /** DiagnosisReport.warnings 와 같은 목적 (백테스트가 건너뛴 매수 등) */
  warnings?: string[];
}
