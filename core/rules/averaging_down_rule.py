"""물타기 브레이크 룰.

발동 조건: BUY 주문인데 해당 종목이 현재 평가손실 상태.
→ 손실을 더 키울 수 있는 자리에 추가 진입하는 물타기 패턴.

기여 점수 = MAX_CONTRIBUTION(35) × (과거 물타기 score_0_100 / 100)
"""

from __future__ import annotations

import pandas as pd

from core.rules.base import ProposedOrder, RuleContribution

MAX_CONTRIBUTION = 35.0


def evaluate(
    order: ProposedOrder,
    metric_score: float,
    timeline: pd.DataFrame,
) -> RuleContribution:
    """물타기 룰 평가. metric_score 는 과거 물타기 score_0_100."""
    if order.side != "BUY":
        return RuleContribution(key="averaging_down", triggered=False, score=0.0)

    holding = timeline[timeline["ticker"] == order.ticker]
    if holding.empty:
        # 신규 진입 — 아직 손실 상태일 수 없음
        return RuleContribution(key="averaging_down", triggered=False, score=0.0)

    latest = holding.sort_values("date").iloc[-1]
    unrealized = latest["unrealized_pnl"]

    if unrealized >= 0:
        return RuleContribution(key="averaging_down", triggered=False, score=0.0)

    contribution = MAX_CONTRIBUTION * (metric_score / 100.0)
    evidence = [
        {
            "trade_id": f"proposed:{order.ticker}",
            "date": str(latest["date"]),
            "name": order.name,
            "detail": (
                f"현재 평가손실 {unrealized:,.0f}원 상태에서 "
                f"{order.name} {order.quantity}주 추가매수"
            ),
        }
    ]
    return RuleContribution(
        key="averaging_down",
        triggered=True,
        score=round(contribution, 2),
        evidence=evidence,
    )
