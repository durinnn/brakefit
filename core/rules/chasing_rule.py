"""추격매수 브레이크 룰.

발동 조건: BUY 주문인데 해당 종목의 **직전 종가** 대비 +5% 이상 급등한 가격으로 매수.

기여 점수 = MAX_CONTRIBUTION(40) × (과거 추격매수 score_0_100 / 100)

── "직전 종가"를 어디서 읽나 ────────────────────────────────────────────────
timeline 이 아니라 **시세 캐시**(core/rules/base.previous_close → docs/schema.md §5
core/synth/prices.get_daily_close)에서 읽는다.

timeline 을 쓰던 시절의 두 가지 문제를 한꺼번에 없앤다.
  1. timeline 은 **포지션을 들고 있는 동안에만** 존재한다. 그래서 미보유 종목(=신규
     진입) 매수는 비교할 종가가 아예 없어 영원히 미판정이었다 — 정작 추격매수의
     교과서적인 형태가 "안 갖고 있던 종목이 급등하니까 따라 들어가는 것"인데도.
  2. 종목만으로 timeline 을 걸러 마지막 행을 집으면 몇 달 전 청산된 에피소드의
     마지막 날 종가가 "전일 종가"로 둔갑했다(stale). 그걸 막으려고 "열린 에피소드
     안에서만" 이라는 조건을 걸었더니 1번이 더 나빠졌다.

시세 캐시에는 as_of 와 무관하게 그 종목의 모든 영업일 종가가 있으므로, 보유 여부와
무관하게 판정할 수 있고 stale 도 구조적으로 불가능하다(항상 as_of 직전 영업일).

⚠ 룩어헤드 금지(AGENTS.md 절대규칙 1): 기준 종가는 **as_of 당일을 제외한** 마지막
   영업일 종가다. 캐시 파일에는 as_of 이후 종가도 들어있어서(장 마감 후 채운 파일)
   경계를 안 걸면 조용히 미래를 본다. 경계는 previous_close() 한 곳에만 있다.

⚠ 시세를 못 구하면(네트워크·미캐시·lookback 안에 영업일 없음) 발동하지 않고
   RuleContribution.warnings 에 사유를 남긴다. triggered=False 만 보면 "급등이 아님"
   과 "판정 못 함"이 구분되지 않으므로, 사유를 남기는 게 이 룰의 계약이다.
"""

from __future__ import annotations

from datetime import date

from core.rules.base import PriceSource, ProposedOrder, RuleContribution, previous_close

MAX_CONTRIBUTION = 40.0
SURGE_THRESHOLD = 0.05  # 전일 종가 대비 +5% 이상이면 급등 추격으로 본다


def _skip(warning: str | None = None) -> RuleContribution:
    return RuleContribution(
        key="chasing",
        triggered=False,
        score=0.0,
        warnings=[warning] if warning else [],
    )


def evaluate(
    order: ProposedOrder,
    metric_score: float,
    as_of: date | None = None,
    price_source: PriceSource | None = None,
) -> RuleContribution:
    """추격매수 룰 평가. metric_score 는 과거 추격매수 score_0_100.

    as_of 는 engine.build(as_of=...) 에 쓴 기준일을 그대로 넘긴다 — 기준 종가의
    경계다. 생략하면 "언제 기준인지 모름"이라 판정하지 않는다(가장 보수적).

    timeline/episodes 를 더 받지 않는다: 보유 여부는 이 룰의 판정 조건이 아니다.
    """
    if order.side != "BUY":
        return _skip()

    ref, warning = previous_close(order.ticker, as_of, price_source)
    if ref is None:
        return _skip(warning)

    jump = (order.price - ref.close) / ref.close
    if jump < SURGE_THRESHOLD:
        return _skip()

    contribution = MAX_CONTRIBUTION * (metric_score / 100.0)
    evidence = [
        {
            "trade_id": f"proposed:{order.ticker}",
            "date": ref.date.isoformat(),
            "name": order.name,
            "detail": (
                f"직전 종가({ref.date}) {ref.close:,.0f}원 대비 {jump * 100:.1f}% 급등 "
                f"가격으로 {order.quantity}주 매수"
            ),
        }
    ]
    return RuleContribution(
        key="chasing",
        triggered=True,
        score=round(contribution, 2),
        evidence=evidence,
    )
