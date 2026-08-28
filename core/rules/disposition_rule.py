"""처분효과 브레이크 룰.

발동 조건: SELL 주문인데 해당 종목이 현재 평가이익 상태.
→ 이익은 서둘러 확정하는 처분효과를 강화하는 주문.

기여 점수 = MAX_CONTRIBUTION(25) × (과거 처분효과 score_0_100 / 100)
처분효과 이력이 강한 사용자일수록 이번 매도의 위험 기여가 커진다.
"""

from __future__ import annotations

import pandas as pd

from core.rules.base import ProposedOrder, RuleContribution

MAX_CONTRIBUTION = 25.0


def evaluate(
    order: ProposedOrder,
    metric_score: float,
    timeline: pd.DataFrame,
) -> RuleContribution:
    """처분효과 룰 평가. metric_score 는 과거 처분효과 score_0_100."""
    if order.side != "SELL":
        return RuleContribution(key="disposition_effect", triggered=False, score=0.0)

    holding = timeline[timeline["ticker"] == order.ticker]
    if holding.empty:
        return RuleContribution(key="disposition_effect", triggered=False, score=0.0)

    latest = holding.sort_values("date").iloc[-1]
    unrealized = latest["unrealized_pnl"]

    if unrealized <= 0:
        # 손실 종목 매도는 처분효과 반대방향 — 개입 불필요
        return RuleContribution(key="disposition_effect", triggered=False, score=0.0)

    contribution = MAX_CONTRIBUTION * (metric_score / 100.0)
    evidence = [
        {
            "trade_id": f"proposed:{order.ticker}",
            "date": str(latest["date"]),
            "name": order.name,
            "detail": (f"현재 평가이익 {unrealized:,.0f}원인 {order.name}을 매도 — 처분효과 패턴"),
        }
    ]
    return RuleContribution(
        key="disposition_effect",
        triggered=True,
        score=round(contribution, 2),
        evidence=evidence,
    )
