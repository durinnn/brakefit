"""API 응답 스키마 — web/(lovulive 브랜치)의 src/lib/types.ts 와 1:1 대응.

⚠ D 검토용 초안(test-d-backtest 브랜치). D 가 다르게 가고 싶으면 갈아엎어도 됨.

필드명은 프론트가 카멜케이스(TypeScript 관례)라 여기서도 camelCase alias 를 달아
by_alias=True 로 직렬화한다 — 프론트 쪽 변환 코드가 하나도 필요 없게.

⚠ BiasKey 불일치: metrics 쪽 MetricResult.key 는 "disposition_effect" 인데
프론트 types.ts 의 BiasKey 는 "disposition" 이다(끝의 "_effect" 가 없음).
BIAS_KEY_TO_FRONTEND 에서 여기서 한 번만 변환한다 — 이 파일 밖으로는 새지 않게.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: backend MetricResult.key -> frontend BiasKey. 새 지표 추가하면 여기도 추가할 것.
BIAS_KEY_TO_FRONTEND = {
    "disposition_effect": "disposition",
    "averaging_down": "averaging_down",
    "chasing": "chasing",
}

BIAS_KEY_LABEL = {
    "disposition_effect": "처분효과",
    "averaging_down": "물타기",
    "chasing": "추격매수",
}


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class BiasMetric(CamelModel):
    key: str
    name: str
    score: float
    percentile: float
    summary: str
    sample_count: int = Field(serialization_alias="sampleCount")
    delta: float | None = None


class DiagnosisReport(CamelModel):
    period_label: str = Field(serialization_alias="periodLabel")
    total_trades: int = Field(serialization_alias="totalTrades")
    overall_score: float = Field(serialization_alias="overallScore")
    overall_grade: str = Field(serialization_alias="overallGrade")  # "안정"|"주의"|"위험"
    metrics: list[BiasMetric]
    generated_at: str = Field(serialization_alias="generatedAt")
    # core/guard 종합 소견 (context="report_summary"). web/(lovulive) types.ts 에는
    # 아직 이 두 필드가 없음 — D 와 필드명 맞춘 뒤 프론트 표시 붙일 것.
    headline: str
    body: str
    #: 계산 과정에서 사용자가 알아야 할 사실(과매도 클램프·ticker 미해결 등).
    #: 이걸 안 실으면 "내 거래 일부가 빠진 채 계산됐다" 를 사용자가 알 방법이 없다 —
    #: 엔진 경고가 서버 로그에만 남아서 화면상으로는 정상 결과와 구분이 안 된다.
    warnings: list[str] = []


class RiskContribution(CamelModel):
    label: str
    value: float
    detail: str


class PendingOrder(CamelModel):
    ticker: str
    name: str
    side: str
    quantity: int
    price: float
    change_rate: float = Field(serialization_alias="changeRate")


class PatternWarning(CamelModel):
    headline: str
    case_count: int = Field(serialization_alias="caseCount")
    average_return: float = Field(serialization_alias="averageReturn")
    description: str


class InterventionReport(CamelModel):
    order: PendingOrder
    risk_score: float = Field(serialization_alias="riskScore")
    risk_level: str = Field(serialization_alias="riskLevel")  # LOW|MEDIUM|HIGH
    base_score: float = Field(serialization_alias="baseScore")
    contributions: list[RiskContribution]
    warning: PatternWarning
    suggestions: list[str]


class BlockedCase(CamelModel):
    date: str
    name: str
    impact: float
    bias_key: str = Field(serialization_alias="biasKey")


class BacktestResult(CamelModel):
    period_label: str = Field(serialization_alias="periodLabel")
    intervention_count: int = Field(serialization_alias="interventionCount")
    avoided_loss: float = Field(serialization_alias="avoidedLoss")
    missed_gain: float = Field(serialization_alias="missedGain")
    net_benefit: float = Field(serialization_alias="netBenefit")
    net_benefit_rate: float = Field(serialization_alias="netBenefitRate")
    hit_rate: float = Field(serialization_alias="hitRate")
    cases: list[BlockedCase]
    #: DiagnosisReport.warnings 와 같은 목적. 백테스트가 건너뛴 매수가 있으면 여기로 온다.
    warnings: list[str] = []


class PersonaInfo(CamelModel):
    key: str
    name: str
    description: str


class UploadSummary(CamelModel):
    """POST /api/upload 응답 — 업로드한 파일이 어떻게 읽혔는지 요약.

    프론트는 sessionId 를 들고 있다가 진단/개입/백테스트 호출 때 ?session= 로 넘긴다.
    """

    session_id: str = Field(serialization_alias="sessionId")
    trade_count: int = Field(serialization_alias="tradeCount")
    #: 파서가 버린 행 수 (입출금·배당·합계 행 등). 0 이 아니어도 정상이다.
    skipped_count: int = Field(serialization_alias="skippedCount")
    period: str
    warnings: list[str]
    source: str  # "kb_export" | "standard_csv"


class SimulateOrderRequest(BaseModel):
    ticker: str
    name: str
    side: str
    quantity: int
    price: float
