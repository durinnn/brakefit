"""추격매수 브레이크 룰 테스트.

시나리오 (as_of = 2026-08-04 화):
    삼성전자(005930): 08-04 까지 **보유 중**(에피소드 열려 있음), 마지막 종가 66,000원
      → 매수가 69,300원 = +5.0% → 발동
      → 매수가 67,980원 = +3.0% → 미발동
    SK하이닉스(000660): 05-04 진입 → 07-31 청산. timeline 마지막 행은 07-31(금)이라
      as_of 로부터 2영업일 전 = MAX_STALE_BUSINESS_DAYS(1) 초과 → "직전 종가 없음"
      으로 미판정. 옛 종가와 비교하면 +25% 짜리 가짜 급등이 잡히는 자리다.
    NAVER(035420): 08-03(월) 청산 = as_of 직전 영업일이라 그 종가는 아직 유효 →
      청산 다음 날 재진입은 정상 판정한다.

기대값:
    BUY 69,300원 + 과거 추격매수 score=95 → 발동, contribution = 40 × 0.95 = 38.0
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from core.rules.base import ProposedOrder
from core.rules.chasing_rule import MAX_CONTRIBUTION, SURGE_THRESHOLD, evaluate

AS_OF = date(2026, 8, 4)


def _timeline_row(date_: str, ticker: str, name: str, close: float, episode_id: str) -> dict:
    return dict(
        date=date_,
        ticker=ticker,
        name=name,
        quantity=10,
        avg_cost=70_000,
        close=close,
        unrealized_pnl=-40_000,
        unrealized_pct=-0.057,
        realized_pnl=0,
        holding_days=3,
        episode_id=episode_id,
    )


TIMELINE = pd.DataFrame(
    [
        _timeline_row("2026-08-03", "005930", "삼성전자", 65_000, "005930:2026-08-01"),
        _timeline_row("2026-08-04", "005930", "삼성전자", 66_000, "005930:2026-08-01"),
        # 청산된 지 오래된 에피소드 — 마지막 종가가 as_of 기준 stale
        _timeline_row("2026-07-31", "000660", "SK하이닉스", 200_000, "000660:2026-05-04"),
        # as_of 직전 영업일에 청산 — 종가는 아직 "직전 종가" 로 유효
        _timeline_row("2026-08-03", "035420", "NAVER", 150_000, "035420:2026-07-20"),
    ]
)

EPISODES = pd.DataFrame(
    [
        dict(
            episode_id="005930:2026-08-01",
            ticker="005930",
            name="삼성전자",
            opened_at=date(2026, 8, 1),
            closed_at=None,
            is_open=True,
        ),
        dict(
            episode_id="000660:2026-05-04",
            ticker="000660",
            name="SK하이닉스",
            opened_at=date(2026, 5, 4),
            closed_at=date(2026, 7, 31),
            is_open=False,
        ),
        dict(
            episode_id="035420:2026-07-20",
            ticker="035420",
            name="NAVER",
            opened_at=date(2026, 7, 20),
            closed_at=date(2026, 8, 3),
            is_open=False,
        ),
    ]
)

PREV_CLOSE = 66_000
SURGE_PRICE = int(PREV_CLOSE * (1 + SURGE_THRESHOLD))  # 69,300원 (+5.0%)
BELOW_PRICE = int(PREV_CLOSE * 1.03)  # 67,980원 (+3.0%)


def test_buy_after_surge_triggers_with_correct_contribution():
    order = ProposedOrder(
        ticker="005930", name="삼성전자", side="BUY", quantity=5, price=SURGE_PRICE
    )
    result = evaluate(order, 95.0, TIMELINE, EPISODES, AS_OF)

    assert result.triggered is True
    assert result.score == pytest.approx(MAX_CONTRIBUTION * 0.95, abs=1e-6)
    assert result.evidence != []
    jump_pct = (SURGE_PRICE - PREV_CLOSE) / PREV_CLOSE * 100
    assert f"{jump_pct:.1f}%" in result.evidence[0]["detail"]
    # 열린 에피소드의 **마지막** 행(08-04)을 썼는지 — 08-03(65,000원)을 쓰면 급등률이 달라진다
    assert result.evidence[0]["date"] == "2026-08-04"


def test_buy_below_surge_threshold_does_not_trigger():
    order = ProposedOrder(
        ticker="005930", name="삼성전자", side="BUY", quantity=5, price=BELOW_PRICE
    )
    result = evaluate(order, 95.0, TIMELINE, EPISODES, AS_OF)

    assert result.triggered is False
    assert result.score == 0.0


def test_sell_order_does_not_trigger():
    order = ProposedOrder(
        ticker="005930", name="삼성전자", side="SELL", quantity=5, price=SURGE_PRICE
    )
    result = evaluate(order, 100.0, TIMELINE, EPISODES, AS_OF)

    assert result.triggered is False
    assert result.score == 0.0


def test_new_ticker_without_timeline_does_not_trigger():
    order = ProposedOrder(ticker="042700", name="한미반도체", side="BUY", quantity=5, price=250_000)
    result = evaluate(order, 100.0, TIMELINE, EPISODES, AS_OF)

    assert result.triggered is False
    assert result.score == 0.0


def test_exact_threshold_triggers():
    # +5.0% 정확히 = SURGE_THRESHOLD 이상이므로 발동
    exact_price = PREV_CLOSE * (1 + SURGE_THRESHOLD)
    order = ProposedOrder(
        ticker="005930", name="삼성전자", side="BUY", quantity=1, price=exact_price
    )
    result = evaluate(order, 100.0, TIMELINE, EPISODES, AS_OF)

    assert result.triggered is True


# ── stale timeline 회귀 ──────────────────────────────────────────────────────


def test_closed_old_episode_does_not_trigger():
    """몇 달 전 청산된 에피소드의 마지막 종가를 "전일 종가"로 쓰지 않는다."""
    order = ProposedOrder(ticker="000660", name="SK하이닉스", side="BUY", quantity=5, price=250_000)
    result = evaluate(order, 100.0, TIMELINE, EPISODES, AS_OF)

    assert result.triggered is False  # 200,000 → 250,000 은 +25% 지만 비교 자체가 무효
    assert result.score == 0.0


def test_re_entry_next_business_day_still_judged():
    """직전 영업일에 청산한 종목의 종가는 아직 유효하다 — 재진입 추격은 잡는다."""
    order = ProposedOrder(ticker="035420", name="NAVER", side="BUY", quantity=5, price=165_000)
    result = evaluate(order, 100.0, TIMELINE, EPISODES, AS_OF)

    assert result.triggered is True  # 150,000 → 165,000 = +10%
    assert result.score == pytest.approx(MAX_CONTRIBUTION, abs=1e-6)


def test_without_as_of_only_open_episodes_are_judged():
    """as_of 를 모르면 종가가 얼마나 묵었는지 알 수 없다 — 보유 중일 때만 판정."""
    closed = ProposedOrder(ticker="035420", name="NAVER", side="BUY", quantity=5, price=165_000)
    assert evaluate(closed, 100.0, TIMELINE, EPISODES).triggered is False

    held = ProposedOrder(
        ticker="005930", name="삼성전자", side="BUY", quantity=5, price=SURGE_PRICE
    )
    assert evaluate(held, 100.0, TIMELINE, EPISODES).triggered is True


def test_empty_episodes_falls_back_to_no_judgement():
    """episodes 가 비면 '보유 중'인지 알 수 없다 — as_of 기준 신선도만으로 판단한다."""
    empty = pd.DataFrame(columns=["episode_id", "ticker", "closed_at", "is_open"])
    order = ProposedOrder(ticker="000660", name="SK하이닉스", side="BUY", quantity=5, price=250_000)

    assert evaluate(order, 100.0, TIMELINE, empty, AS_OF).triggered is False
