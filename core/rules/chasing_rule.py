"""추격매수 브레이크 룰.

발동 조건: BUY 주문인데 해당 종목의 최근 timeline 종가 대비 +5% 이상 급등한 가격으로 매수.

기여 점수 = MAX_CONTRIBUTION(40) × (과거 추격매수 score_0_100 / 100)

⚠ 한계: timeline 에 이력이 있는 종목(이미 보유 중이거나 과거 보유)만 전일 종가를 알 수 있다.
   신규 진입 종목은 timeline 이 없어 skip — metrics/chasing.py 의 TODO 와 동일한 제약.
   A/B 가 pykrx 원본 시세 캐시를 노출하면 신규 진입도 판정 가능해진다.
"""

from __future__ import annotations

import pandas as pd

from core.rules.base import ProposedOrder, RuleContribution

MAX_CONTRIBUTION = 40.0
SURGE_THRESHOLD = 0.05  # 전일 종가 대비 +5% 이상이면 급등 추격으로 본다


def evaluate(
    order: ProposedOrder,
    metric_score: float,
    timeline: pd.DataFrame,
) -> RuleContribution:
    """추격매수 룰 평가. metric_score 는 과거 추격매수 score_0_100."""
    if order.side != "BUY":
        return RuleContribution(key="chasing", triggered=False, score=0.0)

    prior = timeline[timeline["ticker"] == order.ticker]
    if prior.empty:
        return RuleContribution(key="chasing", triggered=False, score=0.0)

    latest = prior.sort_values("date").iloc[-1]
    prev_close = latest["close"]
    if prev_close <= 0:
        return RuleContribution(key="chasing", triggered=False, score=0.0)

    jump = (order.price - prev_close) / prev_close
    if jump < SURGE_THRESHOLD:
        return RuleContribution(key="chasing", triggered=False, score=0.0)

    contribution = MAX_CONTRIBUTION * (metric_score / 100.0)
    evidence = [
        {
            "trade_id": f"proposed:{order.ticker}",
            "date": str(latest["date"]),
            "name": order.name,
            "detail": (
                f"전일 종가 {prev_close:,.0f}원 대비 {jump * 100:.1f}% 급등 가격으로 "
                f"{order.quantity}주 매수"
            ),
        }
    ]
    return RuleContribution(
        key="chasing",
        triggered=True,
        score=round(contribution, 2),
        evidence=evidence,
    )
