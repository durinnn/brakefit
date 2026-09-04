"""물타기 브레이크 룰 테스트.

시나리오:
    삼성전자: 현재 평가손실 -40,000원 보유 중
    카카오: 현재 평가이익 +30,000원 보유 중

기대값:
    BUY 삼성전자 (손실 중) + 과거 물타기 score=60 → 발동
        contribution = 35 × 0.6 = 21.0
    BUY 카카오 (이익 중) → 미발동
    SELL 삼성전자 → 미발동 (매수 아님)
    BUY 미보유 종목 → 미발동 (신규 진입은 물타기 아님)
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.rules.averaging_down_rule import MAX_CONTRIBUTION, evaluate
from core.rules.base import ProposedOrder

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
        dict(
            date="2026-07-03",
            ticker="035720",
            name="카카오",
            quantity=20,
            avg_cost=40_000,
            close=41_500,
            unrealized_pnl=30_000,
            unrealized_pct=0.0375,
            realized_pnl=0,
            holding_days=3,
            episode_id="035720:2026-07-01",
        ),
    ]
)


def test_buy_into_loss_triggers_with_correct_contribution():
    order = ProposedOrder(ticker="005930", name="삼성전자", side="BUY", quantity=5, price=64_000)
    result = evaluate(order, metric_score=60.0, timeline=TIMELINE)

    assert result.triggered is True
    assert result.score == pytest.approx(MAX_CONTRIBUTION * 0.6, abs=1e-6)
    assert result.evidence != []
    assert "삼성전자" in result.evidence[0]["detail"]


def test_buy_into_profit_does_not_trigger():
    order = ProposedOrder(ticker="035720", name="카카오", side="BUY", quantity=5, price=41_500)
    result = evaluate(order, metric_score=80.0, timeline=TIMELINE)

    assert result.triggered is False
    assert result.score == 0.0


def test_sell_order_does_not_trigger():
    order = ProposedOrder(ticker="005930", name="삼성전자", side="SELL", quantity=5, price=66_000)
    result = evaluate(order, metric_score=100.0, timeline=TIMELINE)

    assert result.triggered is False
    assert result.score == 0.0


def test_new_position_does_not_trigger():
    order = ProposedOrder(ticker="000660", name="SK하이닉스", side="BUY", quantity=5, price=200_000)
    result = evaluate(order, metric_score=100.0, timeline=TIMELINE)

    assert result.triggered is False
    assert result.score == 0.0
