"""처분효과 브레이크 룰 테스트.

시나리오 (as_of = 2026-08-04 화, 손계산 가능한 크기):
    삼성전자(005930): **보유 중**(에피소드 열림). 20주 · 평단 67,000원
        as_of 당일(08-04) 종가 71,000원 = 기준 종가
        → 평가이익 = (71,000 − 67,000) × 20 = +80,000원 → 발동
    카카오(035720): **보유 중**. 30주 · 평단 39,000원, 08-04 종가 37,500원
        → 평가손실 −45,000원 → 미발동 (처분효과 반대방향)
    SK하이닉스(000660): 07-31 **청산**. timeline 에는 이익으로 끝난 마지막 행이
        남아 있지만 as_of 에는 안 들고 있다 → 미판정 (stale 회귀)

기대값:
    SELL 삼성전자 + 과거 처분효과 score=80 → contribution = 25 × 0.8 = 20.0
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from fake_prices import ExplodingPriceSource, FakePriceSource

from core.rules.base import ProposedOrder
from core.rules.disposition_rule import MAX_CONTRIBUTION, evaluate

AS_OF = date(2026, 8, 4)


def _timeline_row(date_: str, ticker: str, name: str, **kw) -> dict:
    row = dict(
        date=date_,
        ticker=ticker,
        name=name,
        quantity=20,
        avg_cost=67_000,
        close=71_000,
        unrealized_pnl=80_000,
        unrealized_pct=0.06,
        realized_pnl=0,
        holding_days=4,
        episode_id=f"{ticker}:open",
    )
    row.update(kw)
    return row


TIMELINE = pd.DataFrame(
    [
        _timeline_row("2026-08-04", "005930", "삼성전자"),
        _timeline_row(
            "2026-08-04",
            "035720",
            "카카오",
            quantity=30,
            avg_cost=39_000,
            close=37_500,
            unrealized_pnl=-45_000,
            unrealized_pct=-0.038,
        ),
        # 07-31 에 이익으로 청산된 옛 포지션 — as_of 에는 보유 없음
        _timeline_row(
            "2026-07-31",
            "000660",
            "SK하이닉스",
            quantity=10,
            avg_cost=150_000,
            close=200_000,
            unrealized_pnl=500_000,
            unrealized_pct=0.33,
            episode_id="000660:closed",
        ),
    ]
)

EPISODES = pd.DataFrame(
    [
        dict(episode_id="005930:open", ticker="005930", closed_at=None, is_open=True),
        dict(episode_id="035720:open", ticker="035720", closed_at=None, is_open=True),
        dict(
            episode_id="000660:closed",
            ticker="000660",
            closed_at=date(2026, 7, 31),
            is_open=False,
        ),
    ]
)

PRICES = FakePriceSource(
    {
        # 08-03(전날) 값을 쓰면 손익 부호가 뒤집히도록 일부러 반대로 깔았다
        "005930": {"2026-08-03": 40_000, "2026-08-04": 71_000},
        "035720": {"2026-08-03": 99_000, "2026-08-04": 37_500},
        "000660": {"2026-08-03": 300_000, "2026-08-04": 300_000},
    },
    forbid_after=AS_OF,  # as_of 다음 날 종가는 요청조차 하면 안 된다
)


def _sell(ticker: str, name: str, price: float) -> ProposedOrder:
    return ProposedOrder(ticker=ticker, name=name, side="SELL", quantity=10, price=price)


def test_평가이익_종목_매도는_발동한다():
    result = evaluate(_sell("005930", "삼성전자", 71_000), 80.0, TIMELINE, EPISODES, AS_OF, PRICES)

    assert result.triggered is True
    assert result.score == pytest.approx(MAX_CONTRIBUTION * 0.8, abs=1e-6)
    # 평가이익 = (71,000 − 67,000) × 20 = 80,000원
    assert "80,000" in result.evidence[0]["detail"]
    assert result.evidence[0]["date"] == "2026-08-04"  # as_of 당일 종가가 기준


def test_평가손실_종목_매도는_미발동():
    result = evaluate(_sell("035720", "카카오", 37_500), 80.0, TIMELINE, EPISODES, AS_OF, PRICES)

    assert result.triggered is False
    assert result.score == 0.0


def test_매수주문은_미발동():
    order = ProposedOrder(ticker="005930", name="삼성전자", side="BUY", quantity=5, price=71_000)
    result = evaluate(order, 100.0, TIMELINE, EPISODES, AS_OF, PRICES)

    assert result.triggered is False


def test_거래이력이_없는_종목은_미발동():
    result = evaluate(_sell("042700", "한미반도체", 200_000), 100.0, TIMELINE, EPISODES, AS_OF)

    assert result.triggered is False
    assert result.score == 0.0


def test_지표점수가_0이면_발동해도_기여는_0():
    result = evaluate(_sell("005930", "삼성전자", 71_000), 0.0, TIMELINE, EPISODES, AS_OF, PRICES)

    assert result.triggered is True
    assert result.score == pytest.approx(0.0, abs=1e-6)


# ── stale 회귀 (PR 26 이 물타기·추격매수만 고치고 남겨둔 경로) ────────────────


def test_청산된_옛_포지션의_평가이익으로_발동하지_않는다():
    """as_of 에 안 들고 있는 종목은 팔 수도 없다 — timeline 마지막 행이 +50만원이어도 미판정."""
    result = evaluate(
        _sell("000660", "SK하이닉스", 300_000), 100.0, TIMELINE, EPISODES, AS_OF, PRICES
    )

    assert result.triggered is False
    assert result.score == 0.0


def test_episodes_가_없으면_보유_판단_불가라_미발동():
    empty = pd.DataFrame(columns=["episode_id", "ticker", "closed_at", "is_open"])
    result = evaluate(_sell("005930", "삼성전자", 71_000), 100.0, TIMELINE, empty, AS_OF, PRICES)

    assert result.triggered is False


def test_평가손익은_timeline_이_아니라_기준_종가로_계산한다():
    """timeline.close 가 오래된 값이어도 판정은 as_of 이하 마지막 종가를 따른다.

    timeline 행은 이익(+80,000)인데 기준 종가가 평단 아래면 손실로 뒤집혀야 한다.
    """
    dropped = FakePriceSource({"005930": {"2026-08-04": 60_000}})  # 평단 67,000 아래
    result = evaluate(
        _sell("005930", "삼성전자", 60_000), 100.0, TIMELINE, EPISODES, AS_OF, dropped
    )

    assert result.triggered is False


def test_시세조회_실패시_timeline_으로_물러서되_사유를_남긴다():
    result = evaluate(
        _sell("005930", "삼성전자", 71_000),
        100.0,
        TIMELINE,
        EPISODES,
        AS_OF,
        ExplodingPriceSource(),
    )

    assert result.triggered is True  # timeline 의 unrealized_pnl(+80,000)로 대체 판정
    assert len(result.warnings) == 1
    assert "ConnectionError" in result.warnings[0]
    assert "대체 판정" in result.warnings[0]
