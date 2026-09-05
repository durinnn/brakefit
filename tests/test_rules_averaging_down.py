"""물타기 브레이크 룰 테스트.

시나리오:
    삼성전자(005930): **보유 중**, 현재 평가손실 -40,000원
    카카오(035720): **보유 중**, 현재 평가이익 +30,000원
    SK하이닉스(000660): 손실로 끝난 옛 에피소드가 07-31 에 청산됨 (지금은 미보유)

기대값:
    BUY 삼성전자 (보유 + 손실 중) + 과거 물타기 score=60 → 발동
        contribution = 35 × 0.6 = 21.0
    BUY 카카오 (보유 + 이익 중) → 미발동
    SELL 삼성전자 → 미발동 (매수 아님)
    BUY 미보유 종목 → 미발동 (신규 진입은 물타기 아님)
    BUY SK하이닉스 (청산된 옛 손실 포지션만 있음) → 미발동
        — 종목만으로 timeline 마지막 행을 집으면 몇 달 전 평가손실이 "현재 평가손실"로
          둔갑해서 신규 진입에 물타기 경고가 붙는다(stale 회귀).
"""

from __future__ import annotations

from datetime import date

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
            date="2026-08-03",
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
        # 청산된 에피소드의 마지막 행 — 평가손실로 끝났지만 지금은 보유 자체가 없다
        dict(
            date="2026-07-31",
            ticker="000660",
            name="SK하이닉스",
            quantity=5,
            avg_cost=220_000,
            close=200_000,
            unrealized_pnl=-100_000,
            unrealized_pct=-0.09,
            realized_pnl=0,
            holding_days=20,
            episode_id="000660:2026-05-04",
        ),
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
            episode_id="035720:2026-07-01",
            ticker="035720",
            name="카카오",
            opened_at=date(2026, 7, 1),
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
    ]
)


def test_buy_into_loss_triggers_with_correct_contribution():
    order = ProposedOrder(ticker="005930", name="삼성전자", side="BUY", quantity=5, price=64_000)
    result = evaluate(order, 60.0, TIMELINE, EPISODES)

    assert result.triggered is True
    assert result.score == pytest.approx(MAX_CONTRIBUTION * 0.6, abs=1e-6)
    assert result.evidence != []
    assert "삼성전자" in result.evidence[0]["detail"]


def test_buy_into_profit_does_not_trigger():
    order = ProposedOrder(ticker="035720", name="카카오", side="BUY", quantity=5, price=41_500)
    result = evaluate(order, 80.0, TIMELINE, EPISODES)

    assert result.triggered is False
    assert result.score == 0.0


def test_sell_order_does_not_trigger():
    order = ProposedOrder(ticker="005930", name="삼성전자", side="SELL", quantity=5, price=66_000)
    result = evaluate(order, 100.0, TIMELINE, EPISODES)

    assert result.triggered is False
    assert result.score == 0.0


def test_new_position_does_not_trigger():
    order = ProposedOrder(ticker="042700", name="한미반도체", side="BUY", quantity=5, price=200_000)
    result = evaluate(order, 100.0, TIMELINE, EPISODES)

    assert result.triggered is False
    assert result.score == 0.0


# ── stale timeline 회귀 ──────────────────────────────────────────────────────


def test_closed_losing_episode_does_not_trigger():
    """청산된 옛 포지션의 평가손실을 '현재 평가손실'로 쓰지 않는다."""
    order = ProposedOrder(ticker="000660", name="SK하이닉스", side="BUY", quantity=5, price=190_000)
    result = evaluate(order, 100.0, TIMELINE, EPISODES)

    assert result.triggered is False
    assert result.score == 0.0


def test_open_episode_uses_only_its_own_rows():
    """같은 종목의 옛 에피소드 행이 섞여 있어도 열린 에피소드의 행만 본다."""
    timeline = pd.concat(
        [
            TIMELINE,
            # 카카오의 이전(청산된) 에피소드 — 큰 평가손실로 끝났다
            pd.DataFrame(
                [
                    dict(
                        date="2026-06-30",
                        ticker="035720",
                        name="카카오",
                        quantity=20,
                        avg_cost=50_000,
                        close=45_000,
                        unrealized_pnl=-100_000,
                        unrealized_pct=-0.1,
                        realized_pnl=0,
                        holding_days=10,
                        episode_id="035720:2026-06-01",
                    )
                ]
            ),
        ],
        ignore_index=True,
    )
    order = ProposedOrder(ticker="035720", name="카카오", side="BUY", quantity=5, price=41_500)

    # 열린 에피소드(035720:2026-07-01)는 평가이익 상태 → 미발동
    assert evaluate(order, 100.0, timeline, EPISODES).triggered is False


def test_empty_episodes_does_not_trigger():
    """episodes 가 비면 보유 중인지 알 수 없다 — 근거 없이 발동하지 않는다."""
    empty = pd.DataFrame(columns=["episode_id", "ticker", "closed_at", "is_open"])
    order = ProposedOrder(ticker="005930", name="삼성전자", side="BUY", quantity=5, price=64_000)

    assert evaluate(order, 100.0, TIMELINE, empty).triggered is False
