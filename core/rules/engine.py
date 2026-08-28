"""브레이크 룰 통합 평가기.

세 룰(처분효과·물타기·추격매수)을 전부 실행하고 InterventionReport 를 반환한다.
API 의 POST /simulate-order 가 이 함수 하나를 호출하면 된다.

세 룰의 MAX_CONTRIBUTION 합이 100 이므로 risk_score 는 자연스럽게 0~100 에 들어온다.
단, 부동소수점 오차 방지를 위해 clamp 를 유지한다.
"""

from __future__ import annotations

import pandas as pd

from core.metrics.base import MetricResult, clamp
from core.rules import averaging_down_rule, chasing_rule, disposition_rule
from core.rules.base import INTERVENE_THRESHOLD, InterventionReport, ProposedOrder


def evaluate(
    proposed_order: ProposedOrder,
    metric_results: list[MetricResult],
    timeline: pd.DataFrame,
    episodes: pd.DataFrame,  # noqa: ARG001 — 인터페이스 통일, 향후 룰 추가 시 사용
) -> InterventionReport:
    """주문 하나에 세 룰을 모두 평가해 InterventionReport 를 반환한다."""
    scores_by_key = {m.key: m.score_0_100 for m in metric_results}

    # metric_results 가 없는 경우: 과거 편향 이력 없음 → 기여 0
    disp_score = scores_by_key.get("disposition_effect", 0.0)
    avg_score = scores_by_key.get("averaging_down", 0.0)
    chase_score = scores_by_key.get("chasing", 0.0)

    chase_result = chasing_rule.evaluate(proposed_order, chase_score, timeline)
    avg_result = averaging_down_rule.evaluate(proposed_order, avg_score, timeline)
    disp_result = disposition_rule.evaluate(proposed_order, disp_score, timeline)

    # 워터폴 순서: 기여가 큰 룰 먼저 (시퀀스 다이어그램 예시와 맞춤)
    contributions = [chase_result, avg_result, disp_result]
    risk_score = clamp(sum(c.score for c in contributions))

    return InterventionReport(
        risk_score=round(risk_score, 2),
        contributions=contributions,
        should_intervene=risk_score >= INTERVENE_THRESHOLD,
    )
