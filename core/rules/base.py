"""브레이크 룰 공통 타입.

개입 판정(InterventionReport)과 룰별 기여(RuleContribution)를 정의한다.
docs/sequences.md ② 개입 플로우에서 API 가 받는 응답 형태의 핵심.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 개입 조건 중 점수 쪽 임계 — 주 조건은 "룰 하나라도 triggered" 다(core/rules/engine.py 참조)
INTERVENE_THRESHOLD = 50.0


@dataclass
class ProposedOrder:
    """사용자가 입력한 모의 주문 컨텍스트."""

    ticker: str
    name: str
    side: str  # "BUY" | "SELL"
    quantity: int
    price: float  # 예상 체결가


@dataclass
class RuleContribution:
    """룰 하나의 판정 결과와 기여 점수.

    score 는 총 위험점수(risk_score)의 일부 — 세 룰의 score 합이 risk_score 가 된다.
    """

    key: str  # "disposition_effect" | "averaging_down" | "chasing"
    triggered: bool
    score: float  # 0~해당 룰의 MAX_CONTRIBUTION
    evidence: list[dict] = field(default_factory=list)


@dataclass
class InterventionReport:
    """개입 판정 최종 보고서.

    API 가 UI 에 반환하는 형태. contributions 는 워터폴 그래프 재료.
    """

    risk_score: float  # 0~100
    contributions: list[RuleContribution]  # 순서: chasing → averaging_down → disposition
    should_intervene: bool  # 룰 하나라도 triggered 이거나 risk_score >= INTERVENE_THRESHOLD
