"""추격매수(chasing) 계수 테스트.

trades/timeline 을 손으로 만든 fixture 로 검산한다(엔진을 안 태우고 지표만 본다).

시나리오 (손계산 가능한 크기):
    한미반도체: 08-01 진입매수 (같은 에피소드 내 전일 종가 없음 → 판정 불가) →
                08-02 추가매수 @109,000 (전일종가 100,000 대비 +9% → 추격 O) →
                08-03 추가매수 @110,000 (전일종가 109,000 대비 +0.9% → 추격 X)
    카카오:     07-01 진입매수 (같은 에피소드 내 전일 종가 없음 → 판정 불가) →
                07-02 추가매수 @43,000 (전일종가 40,000 대비 +7.5% → 추격 O)

기대값 손계산:
    분모 = **전체 매수 건수** 5건 (t1~t5). 판정 불가한 신규 진입(t1·t4)도 분모에
    남고 분자에만 0 으로 들어간다 — 분모를 "판정 가능한 매수"로 두면 표본이 1~2건인
    페르소나가 0/100 으로 포화한다(core/metrics/chasing.py compute() docstring).
    분자 = 추격 판정 2건 (한미반도체 08-02, 카카오 07-02)
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
    # 분모는 전체 매수 5건(판정 불가한 신규 진입 t1·t4 포함) — 모듈 docstring 손계산
    assert result.raw == pytest.approx(2 / 5, abs=1e-6)
    assert result.score_0_100 == pytest.approx(40.0, abs=1e-3)


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


def test_all_buys_unjudgeable_returns_zero():
    """판정 가능한 매수가 0건(전부 신규 진입)이면 0점 — 0 나눗셈으로 죽지 않는다."""
    entries_only = TRADES[TRADES["trade_id"].isin(["t1", "t4"])]
    result = compute(TIMELINE, entries_only, EPISODES)

    assert result.raw == 0.0
    assert result.score_0_100 == 0.0
    assert result.evidence == []


# ── 에피소드 스코핑 회귀 (89dccd6 에서 고친 버그) ────────────────────────────
# 같은 종목에 에피소드가 두 개(7월 진입·청산 → 8월 재진입)일 때, 8월 진입 매수의
# "전일 종가"로 7월 청산 직전 종가가 끌려오면 안 된다. 종목만으로 timeline 을 거르면
# 40,000원(7월) 대비 60,000원(8월) = +50% 짜리 가짜 급등이 잡힌다.
RE_ENTRY_TIMELINE = pd.DataFrame(
    [
        dict(
            date="2026-07-01",
            ticker="035720",
            name="카카오",
            quantity=10,
            avg_cost=40_000,
            close=40_000,
            unrealized_pnl=0,
            unrealized_pct=0.0,
            realized_pnl=0,
            holding_days=1,
            episode_id="035720:2026-07-01",
        ),
        # 07-02 에 전량 청산 → 엔진은 그날 행을 안 만든다(schema.md §2). 8월까지 공백.
        dict(
            date="2026-08-03",
            ticker="035720",
            name="카카오",
            quantity=10,
            avg_cost=60_000,
            close=60_000,
            unrealized_pnl=0,
            unrealized_pct=0.0,
            realized_pnl=0,
            holding_days=1,
            episode_id="035720:2026-08-03",  # 재진입 = 새 에피소드
        ),
    ]
)

RE_ENTRY_TRADES = pd.DataFrame(
    [
        dict(
            trade_id="r1",
            traded_at="2026-07-01",
            ticker="035720",
            name="카카오",
            side="BUY",
            quantity=10,
            price=40_000,
        ),
        dict(
            trade_id="r2",
            traded_at="2026-08-03",
            ticker="035720",
            name="카카오",
            side="BUY",
            quantity=10,
            price=60_000,
        ),
    ]
)


def test_re_entry_is_not_compared_with_previous_episode_close():
    result = compute(RE_ENTRY_TIMELINE, RE_ENTRY_TRADES, EPISODES)

    # 두 매수 모두 각자 에피소드의 첫 행이라 판정 불가 → 추격 0건
    assert result.evidence == []
    assert result.raw == 0.0
    assert result.score_0_100 == 0.0
