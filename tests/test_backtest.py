"""core/backtest 테스트.

손으로 검산 가능한 시나리오 — 종목 2개, 각각 진입 + 손실중 추가매수(물타기 트리거)
+ 전량매도. 하나는 그 뒤로 가격이 더 떨어져서(회피한 손실), 하나는 회복돼서
(놓친 이익) — 부호 양쪽 다 손으로 검산한다.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
from fake_prices import FakePriceSource

from core import schema
from core.backtest.backtest import run
from core.engine import engine as engine_module

DATES = [date(2026, 1, i) for i in range(2, 8)]  # d0..d5

CLOSES = {
    # A(005930): 물타기 후 가격 회복 -> 놓친 이익
    "005930": [100.0, 90.0, 80.0, 90.0, 110.0, 120.0],
    # B(000660): 물타기 후 가격 더 하락 -> 회피한 손실
    "000660": [100.0, 90.0, 85.0, 70.0, 60.0, 50.0],
}


def _price_source() -> FakePriceSource:
    """엔진과 룰이 **같은** 가짜 시세를 보게 한다.

    룰이 시세 캐시에서 직접 종가를 읽게 되면서(core/rules/base) 엔진만 monkeypatch
    하면 룰은 실제 캐시(data/cache/prices)를 타게 된다 — 손계산한 시나리오에 진짜
    KRX 종가가 섞여서 결과가 조용히 흔들린다. 그래서 같은 객체를 양쪽에 준다.
    """
    return FakePriceSource(
        {
            ticker: {d.isoformat(): close for d, close in zip(DATES, closes, strict=True)}
            for ticker, closes in CLOSES.items()
        }
    )


class _CutoffGuard:
    """룩어헤드 감시기 — 매수 T 를 판정하면서 T 이후 종가를 요청하면 그 자리에서 실패.

    백테스트는 매수 하나당 추격매수 룰을 정확히 한 번 호출하므로(SELL 은 조기 반환),
    요청 순서와 매수 순서가 1:1 로 대응한다.
    """

    def __init__(self, inner: FakePriceSource, buy_dates: list[date]) -> None:
        self.inner = inner
        self.pending = list(buy_dates)
        self.seen: list[tuple[date, date]] = []  # (매수일, 요청 구간 끝)

    def __call__(self, ticker: str, start: date, end: date) -> pd.Series:
        buy_date = self.pending.pop(0)
        assert end < buy_date, f"룩어헤드: {buy_date} 매수 판정에 {end} 종가를 요청했다"
        self.seen.append((buy_date, end))
        return self.inner(ticker, start, end)


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
def prices(monkeypatch) -> FakePriceSource:
    source = _price_source()
    monkeypatch.setattr(engine_module, "get_daily_close", source)
    return source


@pytest.fixture
def two_ticker_trades(prices):
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


def test_물타기_트리거_두_건이_반대_부호로_잡힌다(two_ticker_trades, prices):
    result = run(two_ticker_trades, as_of=date(2026, 1, 20), price_source=prices)

    assert result.intervention_count == 2
    by_ticker = {c.ticker: c for c in result.cases}

    # A: exit 근사가(d4 종가, 매도일엔 timeline 행이 없어서) 110, 매수가 80, 5주
    #    impact = -(5 * (110 - 80)) = -150  (음수 = 놓친 이익)
    assert by_ticker["005930"].impact == pytest.approx(-150.0)
    assert by_ticker["005930"].bias_key == "averaging_down"

    # B: exit 근사가 60, 매수가 85, 5주 -> impact = -(5*(60-85)) = 125 (양수 = 회피한 손실)
    assert by_ticker["000660"].impact == pytest.approx(125.0)


def test_집계_수치는_손계산과_일치한다(two_ticker_trades, prices):
    result = run(two_ticker_trades, as_of=date(2026, 1, 20), price_source=prices)

    assert result.avoided_loss == pytest.approx(125.0)
    assert result.missed_gain == pytest.approx(150.0)
    assert result.net_benefit == pytest.approx(-25.0)
    assert result.hit_rate == pytest.approx(50.0)  # 2건 중 1건만 avoided_loss

    # 총매수원금 = (1000+400) + (1000+425) = 2825
    assert result.net_benefit_rate == pytest.approx(-25.0 / 2825 * 100)


def test_진입_매수는_백테스트_대상이_아니다(two_ticker_trades, prices):
    """진입(첫 매수)엔 직전 포지션이 없어서 물타기/추격매수 룰이 트리거될 수 없다."""
    result = run(two_ticker_trades, as_of=date(2026, 1, 20), price_source=prices)
    entry_dates = {c.traded_at for c in result.cases}
    assert DATES[0] not in entry_dates


def test_거래가_없으면_빈_결과를_돌려준다():
    result = run(schema.empty_trades())
    assert result.intervention_count == 0
    assert result.cases == []


# ── 룩어헤드 회귀 (AGENTS.md 절대규칙 1) ─────────────────────────────────────


def test_룰이_매수일_이후_종가를_요청하지_않는다(two_ticker_trades, prices):
    """매수 T 의 판정에 T 이후 종가를 쓰면 안 된다.

    감시기가 요청 구간의 끝을 그 자리에서 검사하므로, 룰이 컷을 넘기는 순간
    AssertionError 로 터진다(집계 결과만 보면 안 보이는 종류의 버그).
    """
    buys = two_ticker_trades[two_ticker_trades["side"] == "BUY"].sort_values(
        ["traded_at", "source_row"]
    )
    guard = _CutoffGuard(prices, list(buys["traded_at"]))

    run(two_ticker_trades, as_of=date(2026, 1, 20), price_source=guard)

    # 매수마다 정확히 한 번씩 조회했는지 (조회 자체를 안 하면 감시기가 무력해진다)
    assert len(guard.seen) == len(buys)
    # 판정 컷은 traded_at − 1일이고 기준 종가는 그 **직전** 영업일이라,
    # 요청 구간의 끝은 매수일보다 최소 이틀 앞선다
    assert all((buy_date - end).days >= 2 for buy_date, end in guard.seen)


def test_감시기는_컷을_넘긴_조회를_실제로_잡는다(two_ticker_trades, prices):
    """감시기가 항상 통과하는 빈 껍데기가 아님을 보인다 — 컷을 하루 늦추면 실패한다."""
    buys = two_ticker_trades[two_ticker_trades["side"] == "BUY"].sort_values(
        ["traded_at", "source_row"]
    )
    # 매수일 자체를 상한으로 주는 대신 "매수 하루 전"을 상한으로 줘서, 정상 동작
    # (= 이틀 전까지만 조회)이면 통과하고 미래를 보면 걸리는 경계를 만든다
    too_late = _CutoffGuard(prices, [d - timedelta(days=3) for d in buys["traded_at"]])

    with pytest.raises(AssertionError, match="룩어헤드"):
        run(two_ticker_trades, as_of=date(2026, 1, 20), price_source=too_late)
