"""브레이크 룰 통합 평가기.

세 룰(처분효과·물타기·추격매수)을 전부 실행하고 InterventionReport 를 반환한다.
API 의 POST /simulate-order 가 이 함수 하나를 호출하면 된다.

세 룰의 MAX_CONTRIBUTION 합이 100 이므로 risk_score 는 자연스럽게 0~100 에 들어온다.
단, 부동소수점 오차 방지를 위해 clamp 를 유지한다.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from core.metrics.base import MetricResult, clamp
from core.rules import averaging_down_rule, chasing_rule, disposition_rule
from core.rules.base import INTERVENE_THRESHOLD, InterventionReport, ProposedOrder


def evaluate(
    proposed_order: ProposedOrder,
    metric_results: list[MetricResult],
    timeline: pd.DataFrame,
    episodes: pd.DataFrame,
    as_of: date | None = None,
) -> InterventionReport:
    """주문 하나에 세 룰을 모두 평가해 InterventionReport 를 반환한다.

    timeline/episodes 는 engine.build(as_of=...) 의 출력을, as_of 는 그때 쓴 값을
    그대로 넘긴다. episodes 는 "지금 이 종목을 들고 있는가"(is_open)의 유일한 근거라
    없으면 청산된 옛 포지션을 현재 상태로 착각한다 — 각 룰 docstring 참조.
    """
    scores_by_key = {m.key: m.score_0_100 for m in metric_results}

    # metric_results 가 없는 경우: 과거 편향 이력 없음 → 기여 0
    disp_score = scores_by_key.get("disposition_effect", 0.0)
    avg_score = scores_by_key.get("averaging_down", 0.0)
    chase_score = scores_by_key.get("chasing", 0.0)

    chase_result = chasing_rule.evaluate(proposed_order, chase_score, timeline, episodes, as_of)
    avg_result = averaging_down_rule.evaluate(proposed_order, avg_score, timeline, episodes)
    disp_result = disposition_rule.evaluate(proposed_order, disp_score, timeline)

    # 워터폴 순서: 기여가 큰 룰 먼저 (시퀀스 다이어그램 예시와 맞춤)
    contributions = [chase_result, avg_result, disp_result]
    risk_score = clamp(sum(c.score for c in contributions))

    # 개입 조건 = "룰 하나라도 발동". 점수 임계는 OR 로 남겨둔다.
    #
    # 왜: (1) core/backtest 는 룰별 c.triggered 로 개입 주문을 세는데(backtest.py),
    #     팝업만 risk_score >= 50 을 쓰면 "백테스트가 센 주문"과 "팝업이 뜨는 주문"이
    #     서로 다른 집합이 된다 — 증명 화면과 개입 화면이 다른 얘기를 하게 됨.
    #     (2) 기여식이 MAX_CONTRIBUTION(40/35/25) × 과거지표점수/100 이라 50 을 넘으려면
    #     룰 두 개가 동시에 강해야 하는데, 합성 페르소나는 한 축만 강하게 생성돼서
    #     데모에서 팝업이 한 번도 안 떴다. 처분효과는 상한이 25 라 단독으로는 구조적으로
    #     50 도달 불가(SELL 주문은 영원히 개입 없음).
    # risk_level(LOW/MEDIUM/HIGH)은 여전히 점수 기반이라 강도 표현은 그대로 유지된다.
    should_intervene = any(c.triggered for c in contributions) or risk_score >= INTERVENE_THRESHOLD

    return InterventionReport(
        risk_score=round(risk_score, 2),
        contributions=contributions,
        should_intervene=should_intervene,
    )
