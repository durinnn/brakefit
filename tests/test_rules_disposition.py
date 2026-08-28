"""처분효과 브레이크 룰 테스트.

시나리오 (손계산 가능한 크기):
    삼성전자: 현재 평가이익 +80,000원 보유 중
    카카오: 현재 평가손실 -45,000원 보유 중

기대값:
    SELL 삼성전자 (이익 종목) + 과거 처분효과 score=80 → 발동
        contribution = 25 × 0.8 = 20.0
    SELL 카카오 (손실 종목) → 미발동 (처분효과 반대방향)
    BUY 삼성전자 → 미발동 (매도 아님)
    SELL 미보유 종목 → 미발동 (timeline 없음)
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.rules.base import ProposedOrder
from core.rules.disposition_rule import MAX_CONTRIBUTION, evaluate

TIMELINE = pd.DataFrame(
    [
        dict(
            date="2026-08-04",
            ticker="005930",
            name="삼성전자",
            quantity=20,
            avg_cost=67_000,
            close=71_000,
            unrealized_pnl=80_000,
            unrealized_pct=0.06,
            realized_pnl=0,
            holding_days=4,
            episode_id="005930:2026-08-01",
        ),
        dict(
            date="2026-07-03",
            ticker="035720",
            name="카카오",
            quantity=30,
            avg_cost=39_000,
            close=37_500,
            unrealized_pnl=-45_000,
            unrealized_pct=-0.038,
            realized_pnl=0,
            holding_days=3,
            episode_id="035720:2026-07-01",
        ),
    ]
)


def test_sell_profit_triggers_with_correct_contribution():
    order = ProposedOrder(ticker="005930", name="삼성전자", side="SELL", quantity=10, price=71_000)
    result = evaluate(order, metric_score=80.0, timeline=TIMELINE)

    assert result.triggered is True
    assert result.score == pytest.approx(MAX_CONTRIBUTION * 0.8, abs=1e-6)
    assert result.evidence != []
    assert "삼성전자" in result.evidence[0]["detail"]


def test_sell_loss_does_not_trigger():
    order = ProposedOrder(ticker="035720", name="카카오", side="SELL", quantity=10, price=37_500)
    result = evaluate(order, metric_score=80.0, timeline=TIMELINE)

    assert result.triggered is False
    assert result.score == 0.0


def test_buy_order_does_not_trigger():
    order = ProposedOrder(ticker="005930", name="삼성전자", side="BUY", quantity=5, price=71_000)
    result = evaluate(order, metric_score=100.0, timeline=TIMELINE)

    assert result.triggered is False
    assert result.score == 0.0


def test_unknown_ticker_does_not_trigger():
    order = ProposedOrder(
        ticker="000660", name="SK하이닉스", side="SELL", quantity=5, price=200_000
    )
    result = evaluate(order, metric_score=100.0, timeline=TIMELINE)

    assert result.triggered is False
    assert result.score == 0.0


def test_zero_metric_score_gives_zero_contribution_even_if_triggered():
    order = ProposedOrder(ticker="005930", name="삼성전자", side="SELL", quantity=10, price=71_000)
    result = evaluate(order, metric_score=0.0, timeline=TIMELINE)

    assert result.triggered is True
    assert result.score == pytest.approx(0.0, abs=1e-6)
