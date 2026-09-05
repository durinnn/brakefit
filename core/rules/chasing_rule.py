"""추격매수 브레이크 룰.

발동 조건: BUY 주문인데 해당 종목의 **직전 종가** 대비 +5% 이상 급등한 가격으로 매수.

기여 점수 = MAX_CONTRIBUTION(40) × (과거 추격매수 score_0_100 / 100)

⚠ 한계: timeline 에 이력이 있는 종목(이미 보유 중이거나 과거 보유)만 직전 종가를 알 수 있다.
   신규 진입 종목은 timeline 이 없어 skip — metrics/chasing.py 의 TODO 와 동일한 제약.
   A/B 가 pykrx 원본 시세 캐시를 노출하면 신규 진입도 판정 가능해진다.

⚠ "직전 종가"는 as_of 기준으로 최신이어야 한다. 종목만으로 timeline 을 걸러 마지막
   행을 집으면 몇 달 전에 청산된 에피소드의 마지막 날 종가가 "전일 종가"로 들어와서,
   그 사이 주가가 얼마가 됐든 무관하게 가짜 급등률이 계산된다(실측: rational_baseline
   의 000660 은 as_of 2026-08-18 인데 timeline 마지막 행이 2026-08-11). 그래서
   (1) as_of 에 열린 에피소드가 있으면 그 에피소드 안에서만 직전 종가를 찾고,
   (2) 열린 에피소드가 없으면 마지막 종가가 as_of 로부터 MAX_STALE_BUSINESS_DAYS
       영업일 이내일 때만 쓴다(청산 직후 재진입). 그보다 오래됐으면 "직전 종가 없음"
       으로 미판정(triggered=False) 한다 — 룩어헤드 금지의 반대편, 과거를 현재로
       착각하지 않기 위한 조건이다.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from core.rules.base import ProposedOrder, RuleContribution, open_episode_ids

MAX_CONTRIBUTION = 40.0
SURGE_THRESHOLD = 0.05  # 전일 종가 대비 +5% 이상이면 급등 추격으로 본다

#: 열린 에피소드가 없을 때 "직전 종가"로 인정할 최대 경과 영업일.
#: 1 = as_of 당일 또는 직전 영업일 종가까지만. 청산 다음 날 재진입은 살리되 그보다
#: 오래된 종가는 안 쓴다. 공휴일은 반영하지 않으므로(pd.bdate_range = 월~금) 연휴가
#: 끼면 실제보다 오래된 것으로 세는데, 그 방향의 오차는 "미판정"이라 안전하다.
MAX_STALE_BUSINESS_DAYS = 1


def _business_days_between(start: date, end: date) -> int:
    """start ~ end 사이 경과 영업일(월~금, 공휴일 미반영). end <= start 면 0."""
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    if end_ts <= start_ts:
        return 0
    return len(pd.bdate_range(start_ts, end_ts)) - 1  # 양끝 포함이라 1 을 뺀다


def _reference_row(
    timeline: pd.DataFrame,
    episodes: pd.DataFrame,
    ticker: str,
    as_of: date | None,
) -> pd.Series | None:
    """급등률의 기준이 될 timeline 행(=직전 종가)을 고른다. 없으면 None (모듈 docstring)."""
    rows = timeline[timeline["ticker"] == ticker]
    if rows.empty:
        return None
    rows = rows.sort_values("date")

    open_ids = open_episode_ids(episodes, ticker)
    if open_ids:
        held = rows[rows["episode_id"].isin(open_ids)]
        if not held.empty:
            return held.iloc[-1]  # 보유 중 — 마지막 행이 곧 as_of 시점의 종가다

    # 열린 에피소드가 없다 = 지금은 이 종목을 안 들고 있다. 마지막 종가가 as_of 에서
    # 얼마나 떨어져 있는지 모르면(as_of 미상) 쓰지 않는다 — 오래된 값일 수 있다.
    if as_of is None:
        return None
    last = rows.iloc[-1]
    if _business_days_between(last["date"], as_of) > MAX_STALE_BUSINESS_DAYS:
        return None
    return last


def evaluate(
    order: ProposedOrder,
    metric_score: float,
    timeline: pd.DataFrame,
    episodes: pd.DataFrame,
    as_of: date | None = None,
) -> RuleContribution:
    """추격매수 룰 평가. metric_score 는 과거 추격매수 score_0_100.

    episodes/as_of 는 engine.build(as_of=...) 의 출력과 그 as_of 를 그대로 넘긴다.
    as_of 를 생략하면 "열린 에피소드가 있을 때만" 판정한다(가장 보수적).
    """
    if order.side != "BUY":
        return RuleContribution(key="chasing", triggered=False, score=0.0)

    latest = _reference_row(timeline, episodes, order.ticker, as_of)
    if latest is None:
        return RuleContribution(key="chasing", triggered=False, score=0.0)

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
