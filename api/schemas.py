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
    #: 개입 팝업을 띄울지 말지의 **판정 결과 그 자체**(core/rules 의 should_intervene).
    #: 프론트가 riskLevel == "HIGH" 로 재유도하지 않게 그대로 실어보낸다 — 지금은
    #: RISK_LEVEL_THRESHOLDS[1] == INTERVENE_THRESHOLD 라 둘이 우연히 같지만, 룰 쪽
    #: 임계값이 바뀌는 순간 프론트만 조용히 틀리게 된다.
    should_intervene: bool = Field(serialization_alias="shouldIntervene")
    base_score: float = Field(serialization_alias="baseScore")
    contributions: list[RiskContribution]
    warning: PatternWarning
    #: 이번 판정을 주도한 편향(BiasKey). 개입이 아니면 None.
    #: 프론트가 contributions 의 value 최댓값이나 label 문자열로 되짚지 않게 하려고
    #: 서버가 정해서 내려준다 — 지배 편향 규칙("발동한 룰 중 기여 최대")은 core/rules
    #: 의 개입 조건과 붙어 있어서, 라벨만 보는 클라이언트는 규칙이 바뀔 때 조용히 틀린다.
    dominant_key: str | None = Field(default=None, serialization_alias="dominantKey")
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


class UniverseItem(CamelModel):
    """GET /api/universe 의 한 종목 — 모의 주문 폼의 종목 select 재료.

    lastClose/lastDate 는 폼 기본값(예상 체결가) 용도다. **as_of 이하의 종가만** 담는다 —
    이후 시세를 프리필하면 사용자가 미래를 보고 주문가를 정하게 되어 룩어헤드가 된다
    (AGENTS.md 절대규칙 1). 시세를 못 구하면 거짓값을 만들지 않고 null 로 둔다.
    """

    ticker: str
    name: str
    last_close: float | None = Field(default=None, serialization_alias="lastClose")
    last_date: str | None = Field(default=None, serialization_alias="lastDate")


class SimulateOrderRequest(BaseModel):
    ticker: str
    name: str
    #: "BUY" | "SELL". SELL 도 정상 입력이다 — core/rules/disposition_rule 이 매도를
    #: 판정한다(다만 처분효과 룰 단독 최대 기여가 25점이라 개입 임계 50 에는 못 미친다).
    side: str
    quantity: int
    price: float
