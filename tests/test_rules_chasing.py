"""추격매수 브레이크 룰 테스트.

시나리오:
    삼성전자: timeline 최신 종가 66,000원
      → 매수가 69,300원 = 전일 종가 대비 +5.0% → 발동
      → 매수가 68,000원 = 전일 종가 대비 +3.0% → 미발동

기대값:
    BUY 69,300원 + 과거 추격매수 score=95 → 발동
        contribution = 40 × 0.95 = 38.0
    BUY 68,000원 → 미발동 (급등 기준 미달)
    SELL → 미발동 (매수 아님)
    BUY 미보유 종목 (timeline 없음) → 미발동 (전일 종가 알 수 없음)
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.rules.base import ProposedOrder
from core.rules.chasing_rule import MAX_CONTRIBUTION, SURGE_THRESHOLD, evaluate

TIMELINE = pd.DataFrame(
    [
        dict(
            date="2026-08-03",
            ticker="005930",
            name="삼성전자",
            quantity=10,
            avg_cost=70_000,
            close=66_000,
            unrealized_pnl=-40_000,
            unrealized_pct=-0.057,
            realized_pnl=0,
            holding_days=3,
            episode_id="005930:2026-08-01",
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
    result = evaluate(order, metric_score=95.0, timeline=TIMELINE)

    assert result.triggered is True
    assert result.score == pytest.approx(MAX_CONTRIBUTION * 0.95, abs=1e-6)
    assert result.evidence != []
    jump_pct = (SURGE_PRICE - PREV_CLOSE) / PREV_CLOSE * 100
    assert f"{jump_pct:.1f}%" in result.evidence[0]["detail"]


def test_buy_below_surge_threshold_does_not_trigger():
    order = ProposedOrder(
        ticker="005930", name="삼성전자", side="BUY", quantity=5, price=BELOW_PRICE
    )
    result = evaluate(order, metric_score=95.0, timeline=TIMELINE)

    assert result.triggered is False
    assert result.score == 0.0


def test_sell_order_does_not_trigger():
    order = ProposedOrder(
        ticker="005930", name="삼성전자", side="SELL", quantity=5, price=SURGE_PRICE
    )
    result = evaluate(order, metric_score=100.0, timeline=TIMELINE)

    assert result.triggered is False
    assert result.score == 0.0


def test_new_ticker_without_timeline_does_not_trigger():
    order = ProposedOrder(ticker="000660", name="SK하이닉스", side="BUY", quantity=5, price=250_000)
    result = evaluate(order, metric_score=100.0, timeline=TIMELINE)

    assert result.triggered is False
    assert result.score == 0.0


def test_exact_threshold_triggers():
    # +5.0% 정확히 = SURGE_THRESHOLD 이상이므로 발동
    exact_price = PREV_CLOSE * (1 + SURGE_THRESHOLD)
    order = ProposedOrder(
        ticker="005930", name="삼성전자", side="BUY", quantity=1, price=exact_price
    )
    result = evaluate(order, metric_score=100.0, timeline=TIMELINE)

    assert result.triggered is True
