"""core/engine 테스트.

손으로 검산 가능한 작은 시나리오(AGENTS.md 테스트 원칙) — 진입 + 추가매수 1회 +
전량매도, 종목 1개, 6거래일. 기대값은 아래 "손계산" 대로.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from core import schema
from core.engine import engine as engine_module
from core.engine.engine import build

TICKER = "005930"
NAME = "삼성전자"

# 종가: d0=100 d1=90 d2=80 d3=85 d4=95 d5=105
_DATES = [date(2026, 1, i) for i in range(2, 8)]  # d0..d5 = 1/2 ~ 1/7
_CLOSES = [100.0, 90.0, 80.0, 85.0, 95.0, 105.0]


def _fake_get_daily_close(ticker: str, start: date, end: date) -> pd.Series:
    idx = pd.to_datetime(_DATES)
    return pd.Series(_CLOSES, index=idx, name=ticker)


@pytest.fixture(autouse=True)
def _patch_prices(monkeypatch):
    monkeypatch.setattr(engine_module, "get_daily_close", _fake_get_daily_close)


def _trade(traded_at, side, qty, price, amount, fee, tax, row):
    return dict(
        trade_id=f"t:{row}",
        traded_at=traded_at,
        ticker=TICKER,
        name=NAME,
        side=side,
        quantity=qty,
        price=price,
        amount=amount,
        fee=fee,
        tax=tax,
        source="test",
        source_row=row,
        note=side,
    )


def _build_trades() -> pd.DataFrame:
    rows = [
        # 진입: 10주 @ 100, 수수료 5 -> amount = 1000 + 5 = 1005
        _trade(_DATES[0], "BUY", 10, 100.0, 1005.0, 5.0, 0.0, 1),
        # 추가매수(d2, 종가 80일 때): 5주 @ 80, 수수료 2 -> amount = 400 + 2 = 402
        _trade(_DATES[2], "BUY", 5, 80.0, 402.0, 2.0, 0.0, 2),
        # 전량매도(d5): 15주 @ 105, 수수료 3 + 세금 2 -> amount = 1575 - 3 - 2 = 1570
        # (schema.validate() 의 0.5% 허용오차 안에 들어야 해서 수수료를 크게 못 잡음)
        _trade(_DATES[5], "SELL", 15, 105.0, 1570.0, 3.0, 2.0, 3),
    ]
    return schema.coerce(pd.DataFrame(rows))


def test_평단가는_amount_기준_가중평균이다():
    """§6.1 제안: avg_cost = 누적(BUY.amount) / 누적(수량).

    d0: 1005/10 = 100.5
    d2 추가매수 후: (1005+402)/15 = 1407/15 = 93.8 (그 뒤로 안 바뀜 — 매도는 불변)
    """
    result = build(_build_trades(), as_of=date(2026, 1, 20))
    tl = result.timeline.set_index("date")

    assert tl.loc[_DATES[0], "avg_cost"] == pytest.approx(100.5)
    assert tl.loc[_DATES[1], "avg_cost"] == pytest.approx(100.5)  # 거래 없는 날 — 안 바뀜
    assert tl.loc[_DATES[2], "avg_cost"] == pytest.approx(93.8)
    assert tl.loc[_DATES[3], "avg_cost"] == pytest.approx(93.8)
    assert tl.loc[_DATES[4], "avg_cost"] == pytest.approx(93.8)


def test_평가손익과_수량은_손계산과_일치한다():
    result = build(_build_trades(), as_of=date(2026, 1, 20))
    tl = result.timeline.set_index("date")

    # (수량, 평가손익, 평가손익률)
    expected = {
        _DATES[0]: (10, -5.0, 100 / 100.5 - 1),
        _DATES[1]: (10, -105.0, 90 / 100.5 - 1),
        _DATES[2]: (15, -207.0, 80 / 93.8 - 1),
        _DATES[3]: (15, -132.0, 85 / 93.8 - 1),
        _DATES[4]: (15, 18.0, 95 / 93.8 - 1),
    }
    for d, (qty, pnl, pct) in expected.items():
        assert tl.loc[d, "quantity"] == qty
        assert tl.loc[d, "unrealized_pnl"] == pytest.approx(pnl)
        assert tl.loc[d, "unrealized_pct"] == pytest.approx(pct)

    # d5(매도로 청산) 는 수량 0 이라 행이 없어야 한다 (§2 규칙)
    assert _DATES[5] not in tl.index
    assert len(tl) == 5


def test_청산일에는_행이_없지만_episode_realized_pnl에는_잡힌다():
    result = build(_build_trades(), as_of=date(2026, 1, 20))
    ep = result.episodes.iloc[0]

    assert ep["opened_at"] == _DATES[0]
    assert ep["closed_at"] == _DATES[5]
    assert ep["is_open"] == False  # noqa: E712 (numpy/py bool 둘 다 올 수 있어 명시 비교)
    assert ep["add_buy_count"] == 1
    assert ep["holding_days"] == 5

    # 실현손익 = amount - avg_cost(매도 직전) * 수량 = 1570 - 93.8*15 = 1570 - 1407 = 163
    assert ep["realized_pnl"] == pytest.approx(163.0)
    # 최대 평가손실은 d2 에서 -207 (앞의 손계산 테스트와 동일 값)
    assert ep["max_unrealized_loss"] == pytest.approx(-207.0)
    assert ep["max_unrealized_loss_pct"] == pytest.approx(80 / 93.8 - 1)


def test_거래가_없으면_빈_결과를_돌려준다():
    result = build(schema.empty_trades())
    assert result.timeline.empty
    assert result.episodes.empty
    assert list(result.timeline.columns) == schema.TIMELINE_COLUMNS
    assert list(result.episodes.columns) == schema.EPISODE_COLUMNS


def test_한_종목만_거래정지여도_캐리포워드하고_경고를_남긴다(monkeypatch):
    """종목 2개 중 하나만 특정일 종가가 없으면(=거래정지 추정) 직전 종가를 이어붙인다."""
    d0, d1, d2, d3 = (date(2026, 2, i) for i in (2, 3, 4, 5))

    def fake_prices(ticker: str, start: date, end: date) -> pd.Series:
        if ticker == "AAA":
            dates, closes = [d0, d1, d2, d3], [100.0, 110.0, 120.0, 130.0]
        else:  # BBB — d2 에 거래정지로 종가 없음
            dates, closes = [d0, d1, d3], [200.0, 205.0, 210.0]
        return pd.Series(closes, index=pd.to_datetime(dates), name=ticker)

    monkeypatch.setattr(engine_module, "get_daily_close", fake_prices)

    trades = schema.coerce(
        pd.DataFrame(
            [
                dict(
                    trade_id="t:1",
                    traded_at=d0,
                    ticker="AAA",
                    name="AAA종목",
                    side="BUY",
                    quantity=1,
                    price=100.0,
                    amount=100.0,
                    fee=0.0,
                    tax=0.0,
                    source="test",
                    source_row=1,
                    note="BUY",
                ),
                dict(
                    trade_id="t:2",
                    traded_at=d0,
                    ticker="BBB",
                    name="BBB종목",
                    side="BUY",
                    quantity=1,
                    price=200.0,
                    amount=200.0,
                    fee=0.0,
                    tax=0.0,
                    source="test",
                    source_row=2,
                    note="BUY",
                ),
            ]
        )
    )

    result = build(trades, as_of=d3)

    tl = result.timeline
    bbb = tl[tl["ticker"] == "BBB"].set_index("date")
    assert bbb.loc[d2, "close"] == pytest.approx(205.0)  # 직전 종가로 캐리포워드
    assert any("거래정지" in w and "BBB" in w for w in result.warnings)
