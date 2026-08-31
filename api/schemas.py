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


class PersonaInfo(CamelModel):
    key: str
    name: str
    description: str


class SimulateOrderRequest(BaseModel):
    ticker: str
    name: str
    side: str
    quantity: int
    price: float
