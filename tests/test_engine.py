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


def _price_fn_for(mapping: dict[str, tuple[list[date], list[float]]]):
    """{ticker: (날짜들, 종가들)} 을 받아 get_daily_close 자리를 대신할 함수를 만든다."""

    def fn(ticker: str, start: date, end: date) -> pd.Series:
        dates, closes = mapping[ticker]
        return pd.Series(closes, index=pd.to_datetime(dates), name=ticker)

    return fn


def _buy_row(trade_id, traded_at, ticker, name, qty, price, row, amount=None):
    return dict(
        trade_id=trade_id,
        traded_at=traded_at,
        ticker=ticker,
        name=name,
        side="BUY",
        quantity=qty,
        price=price,
        amount=amount if amount is not None else price * qty,
        fee=0.0,
        tax=0.0,
        source="test",
        source_row=row,
        note="BUY",
    )


def _sell_row(trade_id, traded_at, ticker, name, qty, price, row, amount=None):
    return dict(
        trade_id=trade_id,
        traded_at=traded_at,
        ticker=ticker,
        name=name,
        side="SELL",
        quantity=qty,
        price=price,
        amount=amount if amount is not None else price * qty,
        fee=0.0,
        tax=0.0,
        source="test",
        source_row=row,
        note="SELL",
    )


def test_한_종목만_거래정지여도_캐리포워드하고_경고를_남긴다(monkeypatch):
    """종목 2개 중 하나만 특정일 종가가 없으면(=거래정지 추정) 직전 종가를 이어붙인다."""
    d0, d1, d2, d3 = (date(2026, 2, i) for i in (2, 3, 4, 5))

    monkeypatch.setattr(
        engine_module,
        "get_daily_close",
        _price_fn_for(
            {
                "AAA": ([d0, d1, d2, d3], [100.0, 110.0, 120.0, 130.0]),
                "BBB": ([d0, d1, d3], [200.0, 205.0, 210.0]),  # d2 에 거래정지로 종가 없음
                engine_module.CALENDAR_ANCHOR_TICKER: (
                    [d0, d1, d2, d3],
                    [1.0, 1.0, 1.0, 1.0],
                ),
            }
        ),
    )

    trades = schema.coerce(
        pd.DataFrame(
            [
                _buy_row("t:1", d0, "AAA", "AAA종목", 1, 100.0, 1),
                _buy_row("t:2", d0, "BBB", "BBB종목", 1, 200.0, 2),
            ]
        )
    )

    result = build(trades, as_of=d3)

    tl = result.timeline
    bbb = tl[tl["ticker"] == "BBB"].set_index("date")
    assert bbb.loc[d2, "close"] == pytest.approx(205.0)  # 직전 종가로 캐리포워드
    assert any("거래정지" in w and "BBB" in w for w in result.warnings)


def test_거래내역에_종목이_1개뿐이어도_앵커_덕분에_거래정지를_잡는다(monkeypatch):
    """CALENDAR_ANCHOR_TICKER 를 추가하기 전에는 종목이 1개뿐이면 비교 대상이 없어서
    거래정지를 아예 못 잡았다 — 이제는 항상 앵커를 같이 조회해서 잡는다.
    """
    d0, d1, d2, d3 = (date(2026, 3, i) for i in (2, 3, 4, 5))

    monkeypatch.setattr(
        engine_module,
        "get_daily_close",
        _price_fn_for(
            {
                "CCC": ([d0, d1, d3], [50.0, 55.0, 60.0]),  # d2 에 거래정지
                engine_module.CALENDAR_ANCHOR_TICKER: (
                    [d0, d1, d2, d3],
                    [1.0, 1.0, 1.0, 1.0],
                ),
            }
        ),
    )

    trades = schema.coerce(pd.DataFrame([_buy_row("t:1", d0, "CCC", "CCC종목", 1, 50.0, 1)]))

    result = build(trades, as_of=d3)

    ccc = result.timeline.set_index("date")
    assert ccc.loc[d2, "close"] == pytest.approx(55.0)  # 직전 종가로 캐리포워드
    assert any("거래정지" in w and "CCC" in w for w in result.warnings)


def test_부분매도_두번은_실현손익이_episode에_합산된다(monkeypatch):
    """진입 10주 -> 부분매도 4주 -> 보유 -> 전량매도 6주. 평단가는 부분매도로 안 바뀐다."""
    d0, d1, d2, d3 = (date(2026, 4, i) for i in (1, 2, 3, 4))
    monkeypatch.setattr(
        engine_module,
        "get_daily_close",
        _price_fn_for({TICKER: ([d0, d1, d2, d3], [100.0, 110.0, 90.0, 120.0])}),
    )

    trades = schema.coerce(
        pd.DataFrame(
            [
                _buy_row("t:1", d0, TICKER, NAME, 10, 100.0, 1),
                dict(
                    trade_id="t:2",
                    traded_at=d1,
                    ticker=TICKER,
                    name=NAME,
                    side="SELL",
                    quantity=4,
                    price=110.0,
                    amount=440.0,
                    fee=0.0,
                    tax=0.0,
                    source="test",
                    source_row=2,
                    note="SELL",
                ),
                dict(
                    trade_id="t:3",
                    traded_at=d3,
                    ticker=TICKER,
                    name=NAME,
                    side="SELL",
                    quantity=6,
                    price=120.0,
                    amount=720.0,
                    fee=0.0,
                    tax=0.0,
                    source="test",
                    source_row=3,
                    note="SELL",
                ),
            ]
        )
    )

    result = build(trades, as_of=d3)
    tl = result.timeline.set_index("date")

    # 부분매도 후에도 평단가는 그대로 100 — "매도 시 불변" 규칙
    assert tl.loc[d0, ["quantity", "avg_cost"]].tolist() == [10, 100.0]
    assert tl.loc[d1, ["quantity", "avg_cost"]].tolist() == [6, 100.0]
    assert tl.loc[d1, "realized_pnl"] == pytest.approx(40.0)  # 440 - 100*4
    assert tl.loc[d2, "quantity"] == 6
    assert d3 not in tl.index  # 전량매도로 청산 -> 그날은 행 없음

    ep = result.episodes.iloc[0]
    assert ep["closed_at"] == d3
    # 누적 실현손익 = (440-100*4) + (720-100*6) = 40 + 120 = 160
    assert ep["realized_pnl"] == pytest.approx(160.0)
    assert ep["add_buy_count"] == 0  # 추가매수 없음 — 매도만 두 번


def test_전량청산_후_재진입하면_별개의_episode_두개다(monkeypatch):
    d0, d1, d2, d3, d4 = (date(2026, 5, i) for i in (1, 2, 3, 4, 5))
    monkeypatch.setattr(
        engine_module,
        "get_daily_close",
        _price_fn_for({TICKER: ([d0, d1, d2, d3, d4], [100.0, 110.0, 95.0, 90.0, 92.0])}),
    )

    trades = schema.coerce(
        pd.DataFrame(
            [
                _buy_row("t:1", d0, TICKER, NAME, 5, 100.0, 1),
                dict(
                    trade_id="t:2",
                    traded_at=d1,
                    ticker=TICKER,
                    name=NAME,
                    side="SELL",
                    quantity=5,
                    price=110.0,
                    amount=550.0,
                    fee=0.0,
                    tax=0.0,
                    source="test",
                    source_row=2,
                    note="SELL",
                ),
                # d2 는 쉬고 d3 에 재진입
                _buy_row("t:3", d3, TICKER, NAME, 3, 90.0, 3),
            ]
        )
    )

    result = build(trades, as_of=d4)

    assert len(result.episodes) == 2
    ep1, ep2 = result.episodes.iloc[0], result.episodes.iloc[1]
    assert (ep1["opened_at"], ep1["closed_at"], ep1["is_open"]) == (d0, d1, False)
    assert (ep2["opened_at"], ep2["closed_at"], ep2["is_open"]) == (d3, None, True)
    assert ep1["episode_id"] != ep2["episode_id"]

    tl = result.timeline.set_index("date")
    assert d2 not in tl.index  # 청산~재진입 사이엔 포지션이 없다 — 행 없음
    assert tl.loc[d3, "episode_id"] == ep2["episode_id"]


def test_동일일_다중체결은_합치지_않고_전부_적용한다(monkeypatch):
    """§6.3 제안 — 같은 날 두 번 사면 두 건 다 반영하고, 두 번째부터 추가매수로 센다."""
    d0 = date(2026, 6, 1)
    monkeypatch.setattr(engine_module, "get_daily_close", _price_fn_for({TICKER: ([d0], [100.0])}))

    trades = schema.coerce(
        pd.DataFrame(
            [
                _buy_row("t:1", d0, TICKER, NAME, 5, 100.0, 1, amount=500.0),
                _buy_row("t:2", d0, TICKER, NAME, 3, 102.0, 2, amount=306.0),
            ]
        )
    )

    result = build(trades, as_of=d0)
    tl = result.timeline.set_index("date")

    # 두 건이 합쳐진 하루치 상태 하나만 기록 — 수량 8, 평단가 (500+306)/8 = 100.75
    assert len(tl) == 1
    assert tl.loc[d0, "quantity"] == 8
    assert tl.loc[d0, "avg_cost"] == pytest.approx(100.75)
    assert result.episodes.iloc[0]["add_buy_count"] == 1  # 두 번째 매수만 추가매수로 카운트


# ── 방어선 회귀 테스트 ──────────────────────────────────────────────────────
# 아래 5개는 "지우면 반드시 깨지는" 방어 코드들을 붙잡아두는 테스트다.
# 특히 as_of 클리핑은 AGENTS.md 절대 규칙 1(룩어헤드 금지)의 마지막 방어선이라,
# engine.py 의 `if d <= as_of` 를 지우면 이 테스트가 실패해야 한다(뮤테이션 확인함).


def test_as_of_이후_가격과_체결은_결과에_새지_않는다(monkeypatch):
    """룩어헤드 금지(AGENTS.md 절대 규칙 1) 회귀 테스트.

    get_daily_close 가 (캐시 오염 등으로) as_of 너머 종가를 돌려주고 거래내역에도
    as_of 이후 체결이 섞여 있는 상황을 만든다. engine.build() 는 as_of 까지만
    보여야 하므로, 타임라인에 as_of 초과 날짜가 없고 as_of 이후의 매도는
    반영되지 않아야 한다(=포지션은 미청산 상태로 남는다).

    core/backtest 가 "그 거래 시점까지만 알 수 있던 상태"를 재현하려고 as_of 를
    과거로 좁혀 부르는데, 여기가 새면 백테스트 수치 전체가 미래를 훔쳐본 게 된다.
    """
    d0, d1, d2, d3, d4 = (date(2026, 7, i) for i in (1, 2, 3, 4, 5))
    as_of = d2

    # 페이크는 end 를 무시하고 as_of 이후(d3, d4) 종가까지 전부 돌려준다 — 일부러.
    monkeypatch.setattr(
        engine_module,
        "get_daily_close",
        _price_fn_for({TICKER: ([d0, d1, d2, d3, d4], [100.0, 110.0, 120.0, 130.0, 140.0])}),
    )

    trades = schema.coerce(
        pd.DataFrame(
            [
                _buy_row("t:1", d0, TICKER, NAME, 10, 100.0, 1, amount=1000.0),
                # as_of 이후 체결 — "지금" 기준으로는 아직 일어나지 않은 일이다
                _sell_row("t:2", d4, TICKER, NAME, 10, 140.0, 2, amount=1400.0),
            ]
        )
    )

    result = build(trades, as_of=as_of)

    # 1) 타임라인에 as_of 초과 날짜가 하나도 없다 (d0, d1, d2 세 줄만)
    assert not (result.timeline["date"] > as_of).any()
    assert result.timeline["date"].tolist() == [d0, d1, d2]

    # 2) as_of 이후 매도가 적용되지 않았다 — 미청산 상태 그대로, 실현손익 0
    assert len(result.episodes) == 1
    ep = result.episodes.iloc[0]
    assert ep["is_open"] == True  # noqa: E712
    assert ep["closed_at"] is None
    assert ep["realized_pnl"] == pytest.approx(0.0)


def test_보유수량_초과_매도는_보유분만_실현하고_경고를_남긴다(monkeypatch):
    """10주 보유 중 15주 매도 기록(거래내역 일부 누락 등).

    손계산: 평단가 = 1000/10 = 100. 인정 수량 = 10주(보유분).
    정산금액도 비례 인정 → 1800 × 10/15 = 1200.
    실현손익 = 1200 − 100×10 = 200. 초과 5주는 버리고 경고.
    """
    d0, d1 = date(2026, 8, 3), date(2026, 8, 4)
    monkeypatch.setattr(
        engine_module,
        "get_daily_close",
        _price_fn_for({TICKER: ([d0, d1], [100.0, 120.0])}),
    )

    trades = schema.coerce(
        pd.DataFrame(
            [
                _buy_row("t:1", d0, TICKER, NAME, 10, 100.0, 1, amount=1000.0),
                _sell_row("t:2", d1, TICKER, NAME, 15, 120.0, 2, amount=1800.0),
            ]
        )
    )

    result = build(trades, as_of=d1)

    assert len(result.episodes) == 1
    ep = result.episodes.iloc[0]
    assert ep["realized_pnl"] == pytest.approx(200.0)  # 없는 5주 몫은 안 잡힌다
    assert ep["closed_at"] == d1
    assert ep["is_open"] == False  # noqa: E712

    # 종목·날짜·보유량·매도량이 경고에 다 들어있어야 사람이 원본을 되짚을 수 있다
    over = [w for w in result.warnings if "초과" in w]
    assert len(over) == 1
    assert TICKER in over[0]
    assert str(d1) in over[0]
    assert "보유수량 10주" in over[0]
    assert "매도 15주" in over[0]
    assert "초과 5주" in over[0]

    # 청산일(d1)은 수량 0 이라 행이 없고, d0 한 줄만 남는다
    assert result.timeline["date"].tolist() == [d0]


def test_ticker가_비어있는_행은_제외하되_경고를_남긴다(monkeypatch):
    """resolve_tickers() 를 안 돌린 trades 가 들어오면 그 행은 조용히 사라지면 안 된다."""
    d0, d1 = date(2026, 8, 10), date(2026, 8, 11)
    monkeypatch.setattr(
        engine_module,
        "get_daily_close",
        _price_fn_for({TICKER: ([d0, d1], [100.0, 105.0])}),
    )

    trades = schema.coerce(
        pd.DataFrame(
            [
                _buy_row("t:1", d0, None, "미해결종목", 5, 100.0, 1, amount=500.0),
                _buy_row("t:2", d0, TICKER, NAME, 5, 100.0, 2, amount=500.0),
            ]
        )
    )

    result = build(trades, as_of=d1)

    assert any("ticker 미해결 1건" in w and "resolve_tickers()" in w for w in result.warnings)
    # 드롭 자체는 유지 — 계산에는 ticker 가 있는 종목만 들어간다
    assert result.timeline["ticker"].unique().tolist() == [TICKER]
    assert len(result.episodes) == 1


def test_같은날_청산후_재진입해도_episode_id가_충돌하지_않는다(monkeypatch):
    """§6.3(동일일 다중체결 그대로 둠) 때문에 "{ticker}:{진입일}" 이 하루에 두 번 나온다.

    d0 에 5주 사고 → 같은 날 5주 전량매도(청산) → 같은 날 3주 재진입.
    첫 에피소드는 기존 형식 그대로, 두 번째는 "#2" 접미사로 구분된다.
    """
    d0, d1 = date(2026, 9, 1), date(2026, 9, 2)
    monkeypatch.setattr(
        engine_module,
        "get_daily_close",
        _price_fn_for({TICKER: ([d0, d1], [100.0, 105.0])}),
    )

    trades = schema.coerce(
        pd.DataFrame(
            [
                _buy_row("t:1", d0, TICKER, NAME, 5, 100.0, 1, amount=500.0),
                _sell_row("t:2", d0, TICKER, NAME, 5, 110.0, 2, amount=550.0),
                _buy_row("t:3", d0, TICKER, NAME, 3, 100.0, 3, amount=300.0),
            ]
        )
    )

    result = build(trades, as_of=d1)

    assert len(result.episodes) == 2
    ids = result.episodes["episode_id"].tolist()
    assert len(set(ids)) == 2  # 핵심 — 하류가 이걸 키로 groupby/isin 한다
    assert ids[0] == f"{TICKER}:{d0}"  # 첫 에피소드는 기존 형식 유지
    assert ids[1] == f"{TICKER}:{d0}#2"

    ep1, ep2 = result.episodes.iloc[0], result.episodes.iloc[1]
    assert (ep1["opened_at"], ep1["closed_at"], ep1["is_open"]) == (d0, d0, False)
    assert ep1["realized_pnl"] == pytest.approx(50.0)  # 550 - 100*5
    assert (ep2["opened_at"], ep2["closed_at"], ep2["is_open"]) == (d0, None, True)

    # 그날 종가 시점의 포지션은 두 번째 에피소드 것이다
    tl = result.timeline.set_index("date")
    assert tl.loc[d0, "episode_id"] == ids[1]
    assert tl.loc[d0, "quantity"] == 3
    assert tl.loc[d0, "realized_pnl"] == pytest.approx(50.0)  # 그날 실현손익은 그날에 잡힌다


def test_traded_at이_Timestamp로_들어와도_date로_정규화되어_동작한다(monkeypatch):
    """CSV(parse_dates)·엑셀 파서를 거치면 체결일이 Timestamp 로 온다.

    정규화가 없으면 engine 의 by_day 키(Timestamp)와 달력 날짜(date)가 안 맞아서
    거래가 통째로 매칭에 실패한다 — 에러 없이 조용히 "거래 없던 날"이 된다.
    """
    d0, d1 = date(2026, 10, 5), date(2026, 10, 6)
    monkeypatch.setattr(
        engine_module,
        "get_daily_close",
        _price_fn_for({TICKER: ([d0, d1], [100.0, 110.0])}),
    )

    trades = schema.coerce(
        pd.DataFrame([_buy_row("t:1", pd.Timestamp(d0), TICKER, NAME, 10, 100.0, 1, amount=1000.0)])
    )

    # coerce 단계에서 이미 date 로 내려와 있어야 한다 (Timestamp 는 date 의 하위형이라
    # isinstance 로는 못 잡는다 — 타입을 정확히 본다)
    assert type(trades["traded_at"].iloc[0]) is date

    result = build(trades, as_of=d1)

    tl = result.timeline.set_index("date")
    assert result.timeline["date"].tolist() == [d0, d1]
    assert tl.loc[d0, ["quantity", "avg_cost"]].tolist() == [10, 100.0]
    assert tl.loc[d0, "unrealized_pnl"] == pytest.approx(0.0)
    assert tl.loc[d1, "unrealized_pnl"] == pytest.approx(100.0)  # (110-100)*10
