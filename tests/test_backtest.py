"""core/backtest 테스트.

손으로 검산 가능한 시나리오 — 종목 2개, 각각 진입 + 손실중 추가매수(물타기 트리거)
+ 전량매도. 하나는 그 뒤로 가격이 더 떨어져서(회피한 손실), 하나는 회복돼서
(놓친 이익) — 부호 양쪽 다 손으로 검산한다.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from core import schema
from core.backtest.backtest import run
from core.engine import engine as engine_module

DATES = [date(2026, 1, i) for i in range(2, 8)]  # d0..d5


def _prices(closes: list[float]) -> pd.Series:
    return pd.Series(closes, index=pd.to_datetime(DATES))


def _price_fn(mapping: dict[str, list[float]]):
    def fn(ticker: str, start: date, end: date) -> pd.Series:
        s = _prices(mapping[ticker])
        s.name = ticker
        return s

    return fn


def _row(trade_id, traded_at, ticker, name, side, qty, price, amount, row):
    return dict(
        trade_id=trade_id,
        traded_at=traded_at,
        ticker=ticker,
        name=name,
        side=side,
        quantity=qty,
        price=price,
        amount=amount,
        fee=0.0,
        tax=0.0,
        source="test",
        source_row=row,
        note=side,
    )


@pytest.fixture
def two_ticker_trades(monkeypatch):
    # A(005930, 앵커와 동일종목이라 별도 앵커 조회 불필요): 물타기 후 가격 회복 -> 놓친 이익
    # B(000660): 물타기 후 가격 더 하락 -> 회피한 손실
    monkeypatch.setattr(
        engine_module,
        "get_daily_close",
        _price_fn(
            {
                "005930": [100.0, 90.0, 80.0, 90.0, 110.0, 120.0],
                "000660": [100.0, 90.0, 85.0, 70.0, 60.0, 50.0],
            }
        ),
    )

    rows = [
        _row("t:1", DATES[0], "005930", "삼성전자", "BUY", 10, 100.0, 1000.0, 1),
        _row("t:2", DATES[0], "000660", "SK하이닉스", "BUY", 10, 100.0, 1000.0, 2),
        # d2 추가매수 — 둘 다 직전(d1)에 평가손실 상태였어서 물타기 트리거 대상
        _row("t:3", DATES[2], "005930", "삼성전자", "BUY", 5, 80.0, 400.0, 3),
        _row("t:4", DATES[2], "000660", "SK하이닉스", "BUY", 5, 85.0, 425.0, 4),
        # d5 전량매도로 청산
        _row("t:5", DATES[5], "005930", "삼성전자", "SELL", 15, 120.0, 1800.0, 5),
        _row("t:6", DATES[5], "000660", "SK하이닉스", "SELL", 15, 50.0, 750.0, 6),
    ]
    return schema.coerce(pd.DataFrame(rows))


def test_물타기_트리거_두_건이_반대_부호로_잡힌다(two_ticker_trades):
    result = run(two_ticker_trades, as_of=date(2026, 1, 20))

    assert result.intervention_count == 2
    by_ticker = {c.ticker: c for c in result.cases}

    # A: exit 근사가(d4 종가, 매도일엔 timeline 행이 없어서) 110, 매수가 80, 5주
    #    impact = -(5 * (110 - 80)) = -150  (음수 = 놓친 이익)
    assert by_ticker["005930"].impact == pytest.approx(-150.0)
    assert by_ticker["005930"].bias_key == "averaging_down"

    # B: exit 근사가 60, 매수가 85, 5주 -> impact = -(5*(60-85)) = 125 (양수 = 회피한 손실)
    assert by_ticker["000660"].impact == pytest.approx(125.0)


def test_집계_수치는_손계산과_일치한다(two_ticker_trades):
    result = run(two_ticker_trades, as_of=date(2026, 1, 20))

    assert result.avoided_loss == pytest.approx(125.0)
    assert result.missed_gain == pytest.approx(150.0)
    assert result.net_benefit == pytest.approx(-25.0)
    assert result.hit_rate == pytest.approx(50.0)  # 2건 중 1건만 avoided_loss

    # 총매수원금 = (1000+400) + (1000+425) = 2825
    assert result.net_benefit_rate == pytest.approx(-25.0 / 2825 * 100)


def test_진입_매수는_백테스트_대상이_아니다(two_ticker_trades):
    """진입(첫 매수)엔 직전 포지션이 없어서 물타기/추격매수 룰이 트리거될 수 없다."""
    result = run(two_ticker_trades, as_of=date(2026, 1, 20))
    entry_dates = {c.traded_at for c in result.cases}
    assert DATES[0] not in entry_dates


def test_거래가_없으면_빈_결과를_돌려준다():
    result = run(schema.empty_trades())
    assert result.intervention_count == 0
    assert result.cases == []
