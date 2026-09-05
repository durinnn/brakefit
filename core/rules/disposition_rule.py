"""처분효과 브레이크 룰.

발동 조건: SELL 주문인데 해당 종목을 **지금 들고 있고** 그 포지션이 평가이익 상태.
→ 이익은 서둘러 확정하는 처분효과를 강화하는 주문.

기여 점수 = MAX_CONTRIBUTION(25) × (과거 처분효과 score_0_100 / 100)
처분효과 이력이 강한 사용자일수록 이번 매도의 위험 기여가 커진다.

⚠ "지금 들고 있고" 가 조건에 들어간 이유(물타기 룰과 같은 stale 패턴): 종목만으로
   timeline 을 걸러 마지막 행의 unrealized_pnl 을 쓰면, 몇 달 전에 **이익으로 청산한**
   옛 에피소드 때문에 지금은 갖고 있지도 않은 종목의 매도 주문에 처분효과 경고가
   붙는다. 실제로 데모 페르소나 5종 전부가 삼성전자 SELL 에서 개입 판정을 받았는데,
   그중 셋은 DEMO_AS_OF 에 삼성전자를 보유하고 있지도 않았다. 안 들고 있는 종목은
   팔 수도 없으므로 처분효과의 대상이 아니다 — 미판정으로 뺀다.

⚠ 평가손익은 **as_of 이하 마지막 종가 − 평단** 으로 다시 계산한다(시세 캐시 =
   core/rules/base.reference_close). timeline.unrealized_pnl 은 그 행 날짜의 종가
   기준이라, 열린 에피소드로 스코핑해도 "마지막 행 날짜 == as_of" 가 보장되지 않으면
   기준일이 어긋난다(거래정지·캘린더 결측). 종가 출처를 추격매수 룰과 한 곳으로
   맞춰두면 두 룰이 같은 날 같은 가격을 본다.
   시세를 못 구하면 timeline 의 값으로 물러서되, 사유를 warnings 에 남긴다.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from core.rules.base import (
    PriceSource,
    ProposedOrder,
    RuleContribution,
    open_episode_ids,
    reference_close,
)

MAX_CONTRIBUTION = 25.0


def _skip(warnings: list[str] | None = None) -> RuleContribution:
    return RuleContribution(
        key="disposition_effect",
        triggered=False,
        score=0.0,
        warnings=warnings or [],
    )


def evaluate(
    order: ProposedOrder,
    metric_score: float,
    timeline: pd.DataFrame,
    episodes: pd.DataFrame | None = None,
    as_of: date | None = None,
    price_source: PriceSource | None = None,
) -> RuleContribution:
    """처분효과 룰 평가. metric_score 는 과거 처분효과 score_0_100.

    episodes 는 engine.build(as_of=...) 의 출력을 그대로 넘긴다 — is_open 이 그
    as_of 기준이라 "지금 보유 중인가"의 유일한 근거다.
    """
    if order.side != "SELL":
        return _skip()

    open_ids = open_episode_ids(episodes, order.ticker)
    if not open_ids:
        # 미보유(신규이거나 이미 전량 청산) — 팔 물량이 없으니 처분효과가 성립하지 않는다
        return _skip()

    holding = timeline[
        (timeline["ticker"] == order.ticker) & (timeline["episode_id"].isin(open_ids))
    ]
    if holding.empty:
        # 에피소드는 열려 있는데 timeline 행이 없다 = 엔진 출력이 서로 안 맞는 상태
        return _skip()

    latest = holding.sort_values("date").iloc[-1]
    quantity = float(latest["quantity"])
    avg_cost = float(latest["avg_cost"])

    ref, price_warning = reference_close(order.ticker, as_of, price_source)
    warnings: list[str] = []
    if ref is not None:
        unrealized = (ref.close - avg_cost) * quantity
        basis_date = ref.date.isoformat()
    else:
        # 시세를 못 구했다 — 열린 에피소드로 스코핑돼 있어 stale 은 아니지만 기준일이
        # as_of 와 다를 수 있다. 판정은 하되 사유를 잃지 않는다.
        unrealized = float(latest["unrealized_pnl"])
        basis_date = str(latest["date"])
        if price_warning:
            warnings.append(f"{price_warning} (timeline 마지막 종가 {basis_date} 로 대체 판정)")

    if unrealized <= 0:
        # 손실 종목 매도는 처분효과 반대방향 — 개입 불필요
        return _skip(warnings)

    contribution = MAX_CONTRIBUTION * (metric_score / 100.0)
    evidence = [
        {
            "trade_id": f"proposed:{order.ticker}",
            "date": basis_date,
            "name": order.name,
            "detail": (f"현재 평가이익 {unrealized:,.0f}원인 {order.name}을 매도 — 처분효과 패턴"),
        }
    ]
    return RuleContribution(
        key="disposition_effect",
        triggered=True,
        score=round(contribution, 2),
        evidence=evidence,
        warnings=warnings,
    )
