"""처분효과(disposition effect) 지표 테스트.

core/engine(A) 이 아직 없어서, timeline/episodes 를 손으로 만든 fixture로 대신한다.
episodes 5건 — 손으로 검산 가능한 크기(AGENTS.md 테스트 원칙).

기대값 손계산:
    실현이익 2건(삼성전자, 카카오) vs 미실현이익 0건 → PGR = 2/2 = 1.0
    실현손실 1건(포스코)         vs 미실현손실 2건(네이버, LG엔솔) → PLR = 1/3 ≈ 0.333
    DE(raw) = PGR - PLR ≈ 0.667
    score_0_100 = (raw + 1) / 2 * 100 ≈ 83.33
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.metrics.disposition import compute

EPISODES = pd.DataFrame(
    [
        # 청산 완료 · 이익
        dict(episode_id="005930:2026-08-01", ticker="005930", name="삼성전자",
             opened_at="2026-08-01", closed_at="2026-08-05", realized_pnl=50_000,
             max_unrealized_loss=0, max_unrealized_loss_pct=0.0,
             add_buy_count=0, holding_days=4, is_open=False),
        dict(episode_id="035720:2026-07-01", ticker="035720", name="카카오",
             opened_at="2026-07-01", closed_at="2026-07-07", realized_pnl=30_000,
             max_unrealized_loss=0, max_unrealized_loss_pct=0.0,
             add_buy_count=0, holding_days=6, is_open=False),
        # 청산 완료 · 손실
        dict(episode_id="005490:2026-06-01", ticker="005490", name="포스코",
             opened_at="2026-06-01", closed_at="2026-06-11", realized_pnl=-20_000,
             max_unrealized_loss=-25_000, max_unrealized_loss_pct=-0.08,
             add_buy_count=0, holding_days=10, is_open=False),
        # 미청산 · 현재 평가손실 (버티는 중)
        dict(episode_id="035420:2026-08-01", ticker="035420", name="네이버",
             opened_at="2026-08-01", closed_at=None, realized_pnl=0,
             max_unrealized_loss=-80_000, max_unrealized_loss_pct=-0.06,
             add_buy_count=0, holding_days=20, is_open=True),
        dict(episode_id="373220:2026-07-10", ticker="373220", name="LG에너지솔루션",
             opened_at="2026-07-10", closed_at=None, realized_pnl=0,
             max_unrealized_loss=-40_000, max_unrealized_loss_pct=-0.04,
             add_buy_count=0, holding_days=47, is_open=True),
    ]
)

# 미청산 episode 의 "오늘 기준" 평가손익 — episode 당 최신 스냅샷 한 줄이면 충분
TIMELINE = pd.DataFrame(
    [
        dict(date="2026-08-21", ticker="035420", name="네이버", quantity=10,
             avg_cost=200_000, close=192_000, unrealized_pnl=-80_000,
             unrealized_pct=-0.04, realized_pnl=0, holding_days=20,
             episode_id="035420:2026-08-01"),
        dict(date="2026-08-26", ticker="373220", name="LG에너지솔루션", quantity=5,
             avg_cost=400_000, close=392_000, unrealized_pnl=-40_000,
             unrealized_pct=-0.02, realized_pnl=0, holding_days=47,
             episode_id="373220:2026-07-10"),
    ]
)

TRADES = pd.DataFrame(columns=["trade_id"])  # 이 지표는 아직 trades를 안 쓴다 (TODO 참조)


def test_disposition_effect_matches_hand_calculation():
    result = compute(TIMELINE, TRADES, EPISODES)

    assert result.key == "disposition_effect"
    assert result.raw == pytest.approx(2 / 3, abs=1e-6)
    assert result.score_0_100 == pytest.approx(83.333, abs=0.01)


def test_evidence_picks_fastest_gain_and_longest_loss():
    result = compute(TIMELINE, TRADES, EPISODES)
    trade_ids = [e["trade_id"] for e in result.evidence]

    assert "005930:2026-08-01" in trade_ids  # 가장 빨리 판 이익 (4일)
    assert "373220:2026-07-10" in trade_ids  # 가장 오래 버틴 손실 (47일)


def test_empty_episodes_returns_neutral_score():
    empty = EPISODES.iloc[0:0]
    result = compute(TIMELINE.iloc[0:0], TRADES, empty)

    assert result.raw == 0.0
    assert result.score_0_100 == 50.0
    assert result.evidence == []
