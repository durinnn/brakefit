"""추격매수 브레이크 룰 테스트.

시나리오 (as_of = 2026-08-04 화):
    가짜 시세 (삼성전자 005930)
        08-03(월) 66,000원   ← as_of 직전 영업일 = 기준 종가
        08-04(화) 80,000원   ← as_of 당일. 주문 시점에는 모르는 값이므로 절대 쓰면 안 된다
        08-05(수) 90,000원   ← 미래

기대값 (손계산):
    BUY 69,300원 = 66,000 × 1.05 = +5.0% → 발동
        contribution = MAX_CONTRIBUTION(40) × (95/100) = 38.0
    BUY 67,980원 = 66,000 × 1.03 = +3.0% → 미발동
    BUY 69,300원인데 08-04 종가(80,000)를 기준으로 삼았다면 -13.4% 라 미발동 —
        기준 종가를 잘못 잡으면 이 테스트가 반대로 뒤집힌다.

보유 여부는 판정 조건이 아니다: timeline/episodes 를 아예 안 받는다.
"""

from __future__ import annotations

from datetime import date

import pytest
from fake_prices import ExplodingPriceSource, FakePriceSource

from core.rules.base import ProposedOrder
from core.rules.chasing_rule import MAX_CONTRIBUTION, SURGE_THRESHOLD, evaluate

AS_OF = date(2026, 8, 4)
PREV_CLOSE = 66_000
SURGE_PRICE = PREV_CLOSE * (1 + SURGE_THRESHOLD)  # 69,300원 (+5.0%)
BELOW_PRICE = PREV_CLOSE * 1.03  # 67,980원 (+3.0%)


def _prices(**kwargs) -> FakePriceSource:
    return FakePriceSource(
        {
            "005930": {
                "2026-07-31": 64_000,
                "2026-08-03": PREV_CLOSE,
                "2026-08-04": 80_000,  # as_of 당일 — 쓰면 안 됨
                "2026-08-05": 90_000,  # 미래
            }
        },
        **kwargs,
    )


def _order(price: float, side: str = "BUY", ticker: str = "005930") -> ProposedOrder:
    return ProposedOrder(ticker=ticker, name="삼성전자", side=side, quantity=5, price=price)


def test_신규진입_급등매수는_보유중이_아니어도_발동한다():
    """미보유 종목 매수 — timeline 이 없어도 시세 캐시로 판정한다(PR 26 의 미판정 회귀)."""
    result = evaluate(_order(SURGE_PRICE), 95.0, AS_OF, _prices())

    assert result.triggered is True
    assert result.score == pytest.approx(MAX_CONTRIBUTION * 0.95, abs=1e-6)
    assert result.warnings == []
    # 기준 종가는 as_of 직전 영업일(08-03) — 당일(08-04) 이었다면 미발동이었을 주문이다
    assert result.evidence[0]["date"] == "2026-08-03"
    assert "5.0%" in result.evidence[0]["detail"]


def test_급등이_아니면_미발동():
    result = evaluate(_order(BELOW_PRICE), 95.0, AS_OF, _prices())

    assert result.triggered is False
    assert result.score == 0.0
    assert result.warnings == []  # 판정은 했다 — 사유가 붙으면 안 된다


def test_정확히_임계값이면_발동():
    assert evaluate(_order(SURGE_PRICE), 100.0, AS_OF, _prices()).triggered is True


def test_매도주문은_미발동():
    result = evaluate(_order(SURGE_PRICE, side="SELL"), 100.0, AS_OF, _prices())

    assert result.triggered is False
    assert result.score == 0.0


# ── 룩어헤드 회귀 ────────────────────────────────────────────────────────────


def test_as_of_당일_이후_종가는_요청조차_하지_않는다():
    """기준 종가 조회 구간의 끝이 as_of 미만이어야 한다.

    fake 가 as_of 이상 날짜를 요청받으면 그 자리에서 AssertionError 로 터진다.
    """
    prices = _prices(forbid_from=AS_OF)
    evaluate(_order(SURGE_PRICE), 95.0, AS_OF, prices)

    ticker, start, end = prices.calls[0]
    assert ticker == "005930"
    assert end < AS_OF
    assert start < end  # lookback 구간이 실제로 뒤로 열려 있어야 한다


def test_as_of_당일_종가로_판정하면_뒤집히는_주문():
    """08-04 종가(80,000)를 기준으로 삼으면 -13% 라 미발동 — 그 구현은 이 테스트가 잡는다."""
    result = evaluate(_order(SURGE_PRICE), 95.0, AS_OF, _prices())
    assert result.triggered is True


# ── 미판정 + 사유 ────────────────────────────────────────────────────────────


def test_시세조회_실패는_미판정이고_사유를_남긴다():
    result = evaluate(_order(SURGE_PRICE), 100.0, AS_OF, ExplodingPriceSource())

    assert result.triggered is False
    assert result.score == 0.0
    assert len(result.warnings) == 1
    assert "005930" in result.warnings[0]
    assert "ConnectionError" in result.warnings[0]


def test_시세가_없는_종목도_미판정이고_사유를_남긴다():
    result = evaluate(_order(250_000, ticker="042700"), 100.0, AS_OF, _prices())

    assert result.triggered is False
    assert result.warnings and "042700" in result.warnings[0]


def test_lookback_안에_종가가_없으면_미판정():
    """상장폐지·장기 거래정지 등으로 최근 종가가 통째로 빈 경우."""
    stale = FakePriceSource({"005930": {"2026-01-05": 50_000}})  # 7개월 전 종가뿐
    result = evaluate(_order(SURGE_PRICE), 100.0, AS_OF, stale)

    assert result.triggered is False
    assert result.warnings and "종가가 없음" in result.warnings[0]


def test_as_of_없이는_판정하지_않는다():
    """기준일을 모르면 어떤 날 종가를 써야 하는지도 모른다 — 미판정 + 사유."""
    result = evaluate(_order(SURGE_PRICE), 100.0, None, _prices())

    assert result.triggered is False
    assert result.warnings and "as_of" in result.warnings[0]
