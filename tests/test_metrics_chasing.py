"""추격매수(chasing) 계수 테스트.

core/engine(A) 이 아직 없어서, trades/timeline 을 손으로 만든 fixture로 대신한다.
(episodes 는 이 지표에서 안 쓰지만 인터페이스 통일을 위해 빈 DataFrame으로 넘긴다.)

시나리오 (손계산 가능한 크기):
    한미반도체: 08-01 진입매수 (전일 종가 없음 → 판정 불가) →
                08-02 추가매수 @109,000 (전일종가 100,000 대비 +9% → 추격 O) →
                08-03 추가매수 @110,000 (전일종가 109,000 대비 +0.9% → 추격 X)
    카카오:     07-01 진입매수 (전일 종가 없음 → 판정 불가) →
                07-02 추가매수 @43,000 (전일종가 40,000 대비 +7.5% → 추격 O)

기대값 손계산:
    전체 매수 건수 = 5건 (진입 2건 + 추가매수 3건)
    추격매수로 판정된 건 = 2건 (한미반도체 08-02, 카카오 07-02)
    raw = 2 / 5 = 0.4
    score_0_100 = 40.0
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.metrics.chasing import compute

EPISODES = pd.DataFrame(columns=["episode_id", "ticker"])  # 이 지표는 episodes 를 안 쓴다

TIMELINE = pd.DataFrame(
    [
        # 한미반도체
        dict(
            date="2026-08-01",
            ticker="042700",
            name="한미반도체",
            quantity=10,
            avg_cost=100_000,
            close=100_000,
            unrealized_pnl=0,
            unrealized_pct=0.0,
            realized_pnl=0,
            holding_days=1,
            episode_id="042700:2026-08-01",
        ),
        dict(
            date="2026-08-02",
            ticker="042700",
            name="한미반도체",
            quantity=20,
            avg_cost=104_500,
            close=109_000,
            unrealized_pnl=90_000,
            unrealized_pct=0.043,
            realized_pnl=0,
            holding_days=2,
            episode_id="042700:2026-08-01",
        ),
        dict(
            date="2026-08-03",
            ticker="042700",
            name="한미반도체",
            quantity=30,
            avg_cost=106_333,
            close=110_000,
            unrealized_pnl=110_000,
            unrealized_pct=0.034,
            realized_pnl=0,
            holding_days=3,
            episode_id="042700:2026-08-01",
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
            quantity=30,
            avg_cost=41_000,
            close=43_000,
            unrealized_pnl=60_000,
            unrealized_pct=0.049,
            realized_pnl=0,
            holding_days=2,
            episode_id="035720:2026-07-01",
        ),
    ]
)

TRADES = pd.DataFrame(
    [
        dict(
            trade_id="t1",
            traded_at="2026-08-01",
            ticker="042700",
            name="한미반도체",
            side="BUY",
            quantity=10,
            price=100_000,
        ),
        dict(
            trade_id="t2",
            traded_at="2026-08-02",
            ticker="042700",
            name="한미반도체",
            side="BUY",
            quantity=10,
            price=109_000,
        ),
        dict(
            trade_id="t3",
            traded_at="2026-08-03",
            ticker="042700",
            name="한미반도체",
            side="BUY",
            quantity=10,
            price=110_000,
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
            traded_at="2026-07-02",
            ticker="035720",
            name="카카오",
            side="BUY",
            quantity=10,
            price=43_000,
        ),
    ]
)


def test_chasing_matches_hand_calculation():
    result = compute(TIMELINE, TRADES, EPISODES)

    assert result.key == "chasing"
    assert result.raw == pytest.approx(0.4, abs=1e-6)
    assert result.score_0_100 == pytest.approx(40.0, abs=1e-6)


def test_evidence_excludes_entry_and_small_moves():
    result = compute(TIMELINE, TRADES, EPISODES)
    trade_ids = {e["trade_id"] for e in result.evidence}

    assert trade_ids == {"t2", "t5"}
    assert "t1" not in trade_ids  # 신규 진입 — 전일 종가 없어 판정 불가
    assert "t3" not in trade_ids  # +0.9% 는 급등 기준(5%) 미달


def test_no_buys_returns_zero():
    empty_trades = TRADES.iloc[0:0]
    result = compute(TIMELINE, empty_trades, EPISODES)

    assert result.raw == 0.0
    assert result.score_0_100 == 0.0
    assert result.evidence == []
