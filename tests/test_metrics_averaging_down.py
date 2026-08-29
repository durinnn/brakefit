"""물타기(averaging down) 지수 테스트.

core/engine(A) 이 아직 없어서, trades/timeline/episodes 를 손으로 만든 fixture로 대신한다.

시나리오 (손계산 가능한 크기 — AGENTS.md 테스트 원칙):
    삼성전자: 08-01 진입매수 10주 → 08-02 (매수 없음, 종가 하락) →
              08-03 추가매수 5주 (그날 종가 기준 평가손실 상태 → 물타기 O) →
              08-04 추가매수 5주 (그날 종가 기준 평가이익 상태 → 물타기 X)
    카카오:   07-01 진입매수 20주 → 07-02 (매수 없음, 종가 하락) →
              07-03 추가매수 10주 (평가손실 상태 → 물타기 O)

기대값 손계산:
    전체 매수 건수 = 5건 (진입 2건 + 추가매수 3건)
    손실 상태 추가매수 = 2건 (삼성전자 08-03, 카카오 07-03)
    raw = 2 / 5 = 0.4
    score_0_100 = 40.0
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.metrics.averaging_down import compute

EPISODES = pd.DataFrame(
    [
        dict(
            episode_id="005930:2026-08-01",
            ticker="005930",
            name="삼성전자",
            opened_at="2026-08-01",
            closed_at=None,
            realized_pnl=0,
            max_unrealized_loss=-40_000,
            max_unrealized_loss_pct=-0.057,
            add_buy_count=2,
            holding_days=4,
            is_open=True,
        ),
        dict(
            episode_id="035720:2026-07-01",
            ticker="035720",
            name="카카오",
            opened_at="2026-07-01",
            closed_at=None,
            realized_pnl=0,
            max_unrealized_loss=-45_000,
            max_unrealized_loss_pct=-0.038,
            add_buy_count=1,
            holding_days=3,
            is_open=True,
        ),
    ]
)

TIMELINE = pd.DataFrame(
    [
        # 삼성전자
        dict(
            date="2026-08-01",
            ticker="005930",
            name="삼성전자",
            quantity=10,
            avg_cost=70_000,
            close=70_000,
            unrealized_pnl=0,
            unrealized_pct=0.0,
            realized_pnl=0,
            holding_days=1,
            episode_id="005930:2026-08-01",
        ),
        dict(
            date="2026-08-02",
            ticker="005930",
            name="삼성전자",
            quantity=10,
            avg_cost=70_000,
            close=66_000,
            unrealized_pnl=-40_000,
            unrealized_pct=-0.057,
            realized_pnl=0,
            holding_days=2,
            episode_id="005930:2026-08-01",
        ),
        dict(
            date="2026-08-03",
            ticker="005930",
            name="삼성전자",
            quantity=15,
            avg_cost=68_000,
            close=66_000,
            unrealized_pnl=-30_000,
            unrealized_pct=-0.029,
            realized_pnl=0,
            holding_days=3,
            episode_id="005930:2026-08-01",
        ),
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
        # 카카오
        dict(
            date="2026-07-01",
            ticker="035720",
            name="카카오",
            quantity=20,
            avg_cost=40_000,
            close=40_000,
            unrealized_pnl=0,
            unrealized_pct=0.0,
            realized_pnl=0,
            holding_days=1,
            episode_id="035720:2026-07-01",
        ),
        dict(
            date="2026-07-02",
            ticker="035720",
            name="카카오",
            quantity=20,
            avg_cost=40_000,
            close=38_000,
            unrealized_pnl=-40_000,
            unrealized_pct=-0.05,
            realized_pnl=0,
            holding_days=2,
            episode_id="035720:2026-07-01",
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

TRADES = pd.DataFrame(
    [
        dict(
            trade_id="t1",
            traded_at="2026-08-01",
            ticker="005930",
            name="삼성전자",
            side="BUY",
            quantity=10,
            price=70_000,
        ),
        dict(
            trade_id="t2",
            traded_at="2026-08-03",
            ticker="005930",
            name="삼성전자",
            side="BUY",
            quantity=5,
            price=64_000,
        ),
        dict(
            trade_id="t3",
            traded_at="2026-08-04",
            ticker="005930",
            name="삼성전자",
            side="BUY",
            quantity=5,
            price=65_000,
        ),
        dict(
            trade_id="t4",
            traded_at="2026-07-01",
            ticker="035720",
            name="카카오",
            side="BUY",
            quantity=20,
            price=40_000,
        ),
        dict(
            trade_id="t5",
            traded_at="2026-07-03",
            ticker="035720",
            name="카카오",
            side="BUY",
            quantity=10,
            price=37_500,
        ),
    ]
)


def test_averaging_down_matches_hand_calculation():
    result = compute(TIMELINE, TRADES, EPISODES)

    assert result.key == "averaging_down"
    assert result.raw == pytest.approx(0.4, abs=1e-6)
    assert result.score_0_100 == pytest.approx(40.0, abs=1e-6)


def test_evidence_only_includes_loss_state_add_buys():
    result = compute(TIMELINE, TRADES, EPISODES)
    trade_ids = {e["trade_id"] for e in result.evidence}

    assert trade_ids == {"t2", "t5"}  # 손실 상태 추가매수만
    assert "t1" not in trade_ids  # 진입매수는 제외
    assert "t3" not in trade_ids  # 평가이익 상태 추가매수는 제외


def test_no_buys_returns_zero():
    empty_trades = TRADES.iloc[0:0]
    result = compute(TIMELINE, empty_trades, EPISODES)

    assert result.raw == 0.0
    assert result.score_0_100 == 0.0
    assert result.evidence == []
