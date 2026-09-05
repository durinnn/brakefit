"""브레이크 룰 통합 평가기(engine) 테스트.

시나리오 (as_of = 2026-08-04 화): docs/sequences.md ② 예시에 가까운 시나리오
    삼성전자: 10주 보유 중 · 평단 70,000원
    가짜 시세: 08-04(as_of 당일 = 기준 종가) 66,000원 / 08-03 종가 90,000원(쓰면 뒤집힘)
    → 평가손익 = (66,000 − 70,000) × 10 = −40,000원 (평가손실)

    과거 지표 점수:
        추격매수  score=95 → chasing MAX_CONTRIBUTION(40) × 0.95 = 38.0
        물타기    score=63 → averaging_down MAX(35) × 0.63 = 22.05
        처분효과  score=48 (매도가 아니어서 미발동)

    proposed_order: BUY 삼성전자 @69,300원 (= 66,000 × 1.05, +5.0% 급등 가격)
        → 추격매수 발동: 38.0
        → 물타기 발동: 22.05  (손실 중 추가매수)
        → 처분효과 미발동: 0 (SELL 아님)
        → risk_score = 38.0 + 22.05 + 0 = 60.05
        → should_intervene = True (룰 발동 + 점수 임계 둘 다 만족)

손계산:
    chasing  40 × 0.95   = 38.00
    avg_down 35 × 0.6300 = 22.05
    disp      25 × 0      =  0.00
    합계                  = 60.05
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from fake_prices import ExplodingPriceSource, FakePriceSource

from core.metrics.base import MetricResult
from core.rules.base import INTERVENE_THRESHOLD, ProposedOrder
from core.rules.engine import evaluate

AS_OF = date(2026, 8, 4)

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


def _prices(close_0804: float = 66_000, **kwargs) -> FakePriceSource:
    # 08-03 은 일부러 기준 종가와 멀리 떨어뜨렸다 — 하루 어긋나게 잡으면 판정이 뒤집힌다
    return FakePriceSource(
        {"005930": {"2026-07-31": 64_000, "2026-08-03": 90_000, "2026-08-04": close_0804}},
        **kwargs,
    )


def _evaluate(order, metrics=None, timeline=None, prices=None):
    return evaluate(
        order,
        METRICS if metrics is None else metrics,
        TIMELINE if timeline is None else timeline,
        EPISODES,
        AS_OF,
        prices or _prices(),
    )


def test_risk_score_matches_hand_calculation():
    report = _evaluate(ORDER_CHASING_AND_AVG)

    assert report.risk_score == pytest.approx(60.05, abs=0.01)


def test_should_intervene_true_when_above_threshold():
    assert _evaluate(ORDER_CHASING_AND_AVG).should_intervene is True


def test_contributions_order_and_keys():
    report = _evaluate(ORDER_CHASING_AND_AVG)

    keys = [c.key for c in report.contributions]
    assert keys == ["chasing", "averaging_down", "disposition_effect"]


def test_chasing_and_averaging_down_triggered_disposition_not():
    report = _evaluate(ORDER_CHASING_AND_AVG)

    by_key = {c.key: c for c in report.contributions}
    assert by_key["chasing"].triggered is True
    assert by_key["averaging_down"].triggered is True
    assert by_key["disposition_effect"].triggered is False


def test_no_intervention_when_sell_benign():
    """손실 종목 매도 = 세 룰 모두 미발동 → risk_score 0, should_intervene False."""
    order = ProposedOrder(ticker="005930", name="삼성전자", side="SELL", quantity=5, price=66_000)
    report = _evaluate(order)

    assert report.risk_score == pytest.approx(0.0, abs=1e-6)
    assert report.should_intervene is False


def test_no_metrics_gives_zero_risk():
    """metric_results 가 빈 리스트이면 이력 없음 → 기여 0.

    단 점수만 0 이고 룰 자체는 발동한다(급등가 + 손실 종목 추가매수). 개입 조건이
    triggered 기준이라 should_intervene 은 True — 과거 이력이 없어도 지금 이 주문이
    편향 패턴이면 알려주는 게 맞다는 판단(백테스트도 같은 기준으로 이 주문을 센다).
    """
    report = _evaluate(ORDER_CHASING_AND_AVG, metrics=[])

    assert report.risk_score == pytest.approx(0.0, abs=1e-6)
    assert report.should_intervene is True


# ── 개입 조건 = 룰 하나라도 triggered (2026-09-04 리더 결정) ──────────────────


def test_single_rule_triggered_intervenes_below_threshold():
    """룰 하나만 발동 + 합산 점수 < 50 이어도 개입한다.

    SELL + 평가이익 → 처분효과만 발동. 상한이 25 라 점수로는 절대 50 을 못 넘는데,
    예전 판정(점수 임계)에서는 이 때문에 매도 주문에 개입이 구조적으로 불가능했다.

    기준 종가 75,000원 · 평단 70,000원 · 10주 → 평가이익 +50,000원.
    """
    order = ProposedOrder(ticker="005930", name="삼성전자", side="SELL", quantity=5, price=75_000)

    report = _evaluate(order, prices=_prices(close_0804=75_000))

    triggered = [c for c in report.contributions if c.triggered]
    assert [c.key for c in triggered] == ["disposition_effect"]
    assert report.risk_score < INTERVENE_THRESHOLD
    assert report.should_intervene is True
    # 지배 편향(API 가 팝업 문구에 쓰는 값)은 발동한 룰 중 기여 최대 = 처분효과
    assert max(triggered, key=lambda c: c.score).key == "disposition_effect"


def test_no_rule_triggered_does_not_intervene():
    """아무 룰도 발동 안 하면 과거 지표가 아무리 높아도 개입 없음.

    시세에도 timeline 에도 없는 종목 신규 매수 → 세 룰 전부 판단 근거가 없어 미발동.
    """
    order = ProposedOrder(ticker="000660", name="SK하이닉스", side="BUY", quantity=1, price=200_000)

    report = _evaluate(order)

    assert all(c.triggered is False for c in report.contributions)
    assert report.risk_score == pytest.approx(0.0, abs=1e-6)
    assert report.should_intervene is False


# ── 기준 종가 출처 = 시세 캐시 (as_of 컷) ────────────────────────────────────


def test_기준_종가는_as_of_당일까지만_본다():
    """08-03 종가(90,000)를 썼다면 69,300 매수는 −23% 라 추격매수가 미발동한다.

    반대쪽 경계도 같이 본다 — as_of 다음 날 종가를 요청하면 fake 가 그 자리에서 터진다.
    """
    prices = _prices(forbid_after=AS_OF)
    report = _evaluate(ORDER_CHASING_AND_AVG, prices=prices)

    assert {c.key: c.triggered for c in report.contributions}["chasing"] is True
    assert all(end == AS_OF for _, _, end in prices.calls)


def test_룰의_미판정_사유가_보고서로_올라온다():
    """시세를 못 구하면 개입은 없고 사유만 남는다 — 조용히 '발동 안 함'이 되면 안 된다."""
    report = _evaluate(ORDER_CHASING_AND_AVG, prices=ExplodingPriceSource())

    assert report.should_intervene is True  # 물타기는 timeline 만으로 판정되므로 여전히 발동
    assert report.warnings
    assert any("ConnectionError" in w for w in report.warnings)
