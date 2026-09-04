"""브레이크 룰 통합 평가기(engine) 테스트.

시나리오: docs/sequences.md ② 예시에 가까운 시나리오
    삼성전자: timeline 최신 종가 66,000원, 현재 평가손실 -40,000원

    과거 지표 점수:
        추격매수  score=95 → chasing MAX_CONTRIBUTION(40) × 0.95 = 38.0
        물타기    score=63 → averaging_down MAX(35) × 0.63 = 22.05 ≈ 22.05
        처분효과  score=48 (매도가 아니어서 미발동)

    proposed_order: BUY 삼성전자 @69,300원 (+5.0% 급등 가격)
        → 추격매수 발동: 38.0
        → 물타기 발동: 22.05  (손실 중 추가매수)
        → 처분효과 미발동: 0 (SELL 아님)
        → risk_score = 38.0 + 22.05 + 0 = 60.05
        → should_intervene = True (>= 50)

손계산:
    chasing  40 × 0.95   = 38.00
    avg_down 35 × 0.6300 = 22.05
    disp      25 × 0      =  0.00
    합계                  = 60.05
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.metrics.base import MetricResult
from core.rules.base import ProposedOrder
from core.rules.engine import evaluate

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
            add_buy_count=0,
            holding_days=3,
            is_open=True,
        )
    ]
)

METRICS = [
    MetricResult(key="chasing", raw=0.67, score_0_100=95.0),
    MetricResult(key="averaging_down", raw=0.40, score_0_100=63.0),
    MetricResult(key="disposition_effect", raw=0.0, score_0_100=48.0),
]

ORDER_CHASING_AND_AVG = ProposedOrder(
    ticker="005930",
    name="삼성전자",
    side="BUY",
    quantity=5,
    price=69_300,  # 66,000 × 1.05 = 69,300 (+5.0%)
)


def test_risk_score_matches_hand_calculation():
    report = evaluate(ORDER_CHASING_AND_AVG, METRICS, TIMELINE, EPISODES)

    assert report.risk_score == pytest.approx(60.05, abs=0.01)


def test_should_intervene_true_when_above_threshold():
    report = evaluate(ORDER_CHASING_AND_AVG, METRICS, TIMELINE, EPISODES)

    assert report.should_intervene is True


def test_contributions_order_and_keys():
    report = evaluate(ORDER_CHASING_AND_AVG, METRICS, TIMELINE, EPISODES)

    keys = [c.key for c in report.contributions]
    assert keys == ["chasing", "averaging_down", "disposition_effect"]


def test_chasing_and_averaging_down_triggered_disposition_not():
    report = evaluate(ORDER_CHASING_AND_AVG, METRICS, TIMELINE, EPISODES)

    by_key = {c.key: c for c in report.contributions}
    assert by_key["chasing"].triggered is True
    assert by_key["averaging_down"].triggered is True
    assert by_key["disposition_effect"].triggered is False


def test_no_intervention_when_sell_benign():
    """손실 종목 매도 = 세 룰 모두 미발동 → risk_score 0, should_intervene False."""
    order = ProposedOrder(ticker="005930", name="삼성전자", side="SELL", quantity=5, price=66_000)
    report = evaluate(order, METRICS, TIMELINE, EPISODES)

    assert report.risk_score == pytest.approx(0.0, abs=1e-6)
    assert report.should_intervene is False


def test_no_metrics_gives_zero_risk():
    """metric_results 가 빈 리스트이면 이력 없음 → 기여 0."""
    report = evaluate(ORDER_CHASING_AND_AVG, [], TIMELINE, EPISODES)

    assert report.risk_score == pytest.approx(0.0, abs=1e-6)
    assert report.should_intervene is False
