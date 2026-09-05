"""물타기 브레이크 룰.

발동 조건: BUY 주문인데 해당 종목을 **지금 들고 있고** 그 포지션이 평가손실 상태.
→ 손실을 더 키울 수 있는 자리에 추가 진입하는 물타기 패턴.

기여 점수 = MAX_CONTRIBUTION(35) × (과거 물타기 score_0_100 / 100)

⚠ "지금 들고 있고" 가 조건에 들어간 이유: 종목만으로 timeline 을 걸러 마지막 행의
   unrealized_pnl 을 쓰면, 이미 청산된 옛 에피소드가 손실로 끝났다는 이유만으로 몇 달
   뒤의 신규 진입 주문에 물타기 경고가 붙는다(실측: rational_baseline 의 000660 은
   as_of 2026-08-18 인데 timeline 마지막 행이 2026-08-11 — 그 사이 보유가 없었다).
   물타기는 정의상 "손실 중인 보유분에 더 태우는 것"이라, 보유가 없으면 그냥 신규
   진입이고 이 룰의 대상이 아니다.
"""

from __future__ import annotations

import pandas as pd

from core.rules.base import ProposedOrder, RuleContribution, open_episode_ids

MAX_CONTRIBUTION = 35.0


def evaluate(
    order: ProposedOrder,
    metric_score: float,
    timeline: pd.DataFrame,
    episodes: pd.DataFrame,
) -> RuleContribution:
    """물타기 룰 평가. metric_score 는 과거 물타기 score_0_100.

    episodes 는 engine.build(as_of=...) 의 출력을 그대로 넘긴다 — is_open 이 그
    as_of 기준이라 "지금 보유 중인가"의 유일한 근거다.
    """
    if order.side != "BUY":
        return RuleContribution(key="averaging_down", triggered=False, score=0.0)

    open_ids = open_episode_ids(episodes, order.ticker)
    if not open_ids:
        # 미보유(신규 진입이거나 이미 전량 청산) — 물타기가 성립하지 않는다
        return RuleContribution(key="averaging_down", triggered=False, score=0.0)

    holding = timeline[
        (timeline["ticker"] == order.ticker) & (timeline["episode_id"].isin(open_ids))
    ]
    if holding.empty:
        # 에피소드는 열려 있는데 timeline 행이 없다 = 엔진 출력이 서로 안 맞는 상태.
        # 판정 근거가 없으니 발동하지 않는다.
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
