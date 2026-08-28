"""core/synth/generator.py 테스트.

결정 로직(_sell_probability/_add_buy_trigger/_entry_weight)은 순수 함수라 손으로
정확한 기대값을 계산해서 대조한다. _run_persona/generate_trades 는 확률적 시뮬레이션
이라 정확한 결과값 대신, 시드를 고정하고 "항상 성립해야 하는 규칙"(구조적 불변식)을
검증한다 — 매수부터 시작한다 / 매도는 있어도 한 건뿐이고 마지막에만 온다 / 날짜는
비내림차순이다 등.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, timedelta
from itertools import pairwise

import pytest

from core import schema
from core.synth import generator
from core.synth.generator import (
    _add_buy_trigger,
    _entry_weight,
    _run_persona,
    _sell_probability,
    generate_trades,
)
from core.synth.personas import CHASING_PRONE, DISPOSITION_PRONE, RATIONAL_BASELINE, Persona

_NEUTRAL = Persona("t", "t", "t", disposition_bias=0.0, averaging_down_bias=0.0, chasing_bias=0.0)


# ── 순수 결정 로직 — 손으로 검산 ──────────────────────────────────────────────


def test_이익_중_매도확률은_처분편향의_제곱에_비례해_커진다():
    p = replace(_NEUTRAL, disposition_bias=0.5)
    # base=0.05, (1 + 0.5**2 * 20) = 1 + 5 = 6  ->  0.3
    assert _sell_probability(0.02, p) == pytest.approx(0.30)


def test_손실_중_매도확률은_처분편향의_제곱에_지수감쇠한다():
    p = replace(_NEUTRAL, disposition_bias=0.5)
    expected = 0.05 * math.exp(-(0.5**2) * 3)
    assert _sell_probability(-0.02, p) == pytest.approx(expected)


def test_손실중_매도확률이_이익중보다_항상_낮거나_같다_편향이_있으면():
    for bias in (0.1, 0.5, 0.85):
        p = replace(_NEUTRAL, disposition_bias=bias)
        assert _sell_probability(-0.01, p) < _sell_probability(0.01, p)


def test_급등일_추가매수트리거는_chasing편향에서_나온다():
    p = replace(_NEUTRAL, chasing_bias=0.5)
    prob, reason = _add_buy_trigger(day_return=0.06, unrealized_pct=0.0, p=p)
    assert prob == pytest.approx(0.65)  # min(1, 0.5*1.3)
    assert reason == "chasing"


def test_손실5퍼센트_추가매수트리거는_averaging_down편향에서_나온다():
    p = replace(_NEUTRAL, averaging_down_bias=0.4)
    prob, reason = _add_buy_trigger(day_return=0.0, unrealized_pct=-0.06, p=p)
    assert prob == pytest.approx(0.20)  # 0.4*0.5
    assert reason == "averaging_down"


def test_중립구간에서는_추가매수트리거가_없다():
    p = replace(_NEUTRAL, chasing_bias=0.9, averaging_down_bias=0.9)
    assert _add_buy_trigger(day_return=0.01, unrealized_pct=-0.02, p=p) is None


def test_진입가중치는_편향0이면_날짜와_무관하게_1이다():
    prices = [(date(2026, 1, 1), 100.0), (date(2026, 1, 2), 120.0)]  # +20% day
    assert _entry_weight(prices, 1, _NEUTRAL) == 1.0


def test_진입가중치는_상승폭과_chasing편향에_비례해_커진다():
    prices = [(date(2026, 1, 1), 100.0), (date(2026, 1, 2), 105.0)]  # +5%
    p = replace(_NEUTRAL, chasing_bias=0.5)
    # 1 + 0.5 * 0.05 * 20 = 1 + 0.5 = 1.5
    assert _entry_weight(prices, 1, p) == pytest.approx(1.5)


# ── episode 시뮬레이션 — 구조적 불변식 ────────────────────────────────────────


def _fake_price_path(n: int = 60, seed: int = 7) -> list[tuple[date, float]]:
    import random

    rng = random.Random(seed)
    start = date(2026, 1, 1)
    price = 50_000.0
    path = []
    for i in range(n):
        price = max(1_000.0, price * (1 + rng.gauss(0.0003, 0.02)))
        path.append((start + timedelta(days=i), price))
    return path


def test_episode는_항상_매수로_시작하고_매도는_있어도_마지막_한_건뿐이다():
    universe = {"TEST": _fake_price_path()}
    persona = replace(RATIONAL_BASELINE, n_episodes=8, seed=42)

    episodes = _run_persona(persona, universe)

    assert len(episodes) > 0
    for ep in episodes:
        assert ep.fills[0].side == "BUY"
        sell_positions = [i for i, f in enumerate(ep.fills) if f.side == "SELL"]
        assert sell_positions in ([], [len(ep.fills) - 1])
        assert all(f.quantity > 0 for f in ep.fills)
        dates = [f.traded_at for f in ep.fills]
        assert dates == sorted(dates)


def test_같은_종목의_episode끼리는_보유기간이_겹치지_않는다():
    universe = {"TEST": _fake_price_path(n=90, seed=3)}
    persona = replace(RATIONAL_BASELINE, n_episodes=6, seed=1)

    episodes = _run_persona(persona, universe)
    price_index = {d: i for i, (d, _) in enumerate(universe["TEST"])}

    spans = sorted(
        (price_index[ep.fills[0].traded_at], price_index[ep.fills[-1].traded_at]) for ep in episodes
    )
    for (_s1, e1), (s2, _e2) in pairwise(spans):
        assert e1 < s2


def test_한_종목에_많이_밀어넣어도_유령_보유가_안_남는다():
    """실제 pykrx 데이터로 fixture 를 구워보고서야 드러난 회귀 버그.

    간격 없이 다음 episode 바로 앞에 진입 후보가 잡히면, 그 episode 는 시뮬레이션할
    기회(하루)도 없이 강제 미청산 처리됐다. 문제는 그 뒤로 같은 종목에 새로 잡히는
    episode 들이 전부 이 "유령 보유" 위에 쌓여서, 실제로는 청산된 그 episode들의
    매도가 전량이 아니라 유령 보유를 뺀 나머지만 판 것처럼 수량이 어긋났다 —
    누적수량이 다시 0으로 돌아오지 않는 채로 계속 쌓였다.
    MIN_HOLDING_ROOM 로 "다음 episode 시작 전 최소 N거래일" 을 강제해서 막았다.
    """
    universe = {"TEST": _fake_price_path(n=200, seed=11)}
    persona = replace(RATIONAL_BASELINE, n_episodes=40, seed=5)  # 한 종목에 몰아서 밀도 스트레스

    episodes = _run_persona(persona, universe)
    all_fills = sorted((f.traded_at, f.side, f.quantity) for ep in episodes for f in ep.fills)

    qty = 0
    zero_crossings = 0  # 0 -> 양수로 넘어가는 "진짜 새 진입" 횟수
    for _traded_at, side, quantity in all_fills:
        was_zero = qty == 0
        qty += quantity if side == "BUY" else -quantity
        assert qty >= 0  # 안 가진 걸 팔 수는 없다
        if was_zero and side == "BUY":
            zero_crossings += 1

    # episode 개수만큼 "누적수량 0에서 새로 시작" 하는 진입이 있어야 한다 — 두
    # episode 가 하나의 미청산 포지션 위에 몰래 얹히면 이 값이 실제 episode 수보다
    # 작아진다(유령 보유 버그의 직접적인 증상).
    assert zero_crossings == len(episodes)


# ── pandas 접합부 (get_daily_close 를 몽키패치해서 네트워크 없이 검증) ──────────


@pytest.fixture
def small_universe(monkeypatch):
    """15거래일짜리 손검산 가능한 유니버스 — 급등일(+6%)과 손실 구간을 포함."""
    import pandas as pd

    closes = [100, 101, 103, 109, 107, 104, 98, 93, 90, 95, 99, 102, 106, 110, 115]
    idx = pd.date_range("2026-01-02", periods=len(closes), freq="B")

    def _fake_get_daily_close(ticker, start, end):
        return pd.Series([float(c) for c in closes], index=idx, name=ticker)

    monkeypatch.setattr(generator, "get_daily_close", _fake_get_daily_close)
    return {"TEST01": "테스트종목"}


def test_generate_trades는_스키마를_통과한다(small_universe):
    persona = replace(RATIONAL_BASELINE, n_episodes=3, seed=99)

    df = generate_trades(persona, tickers=small_universe)

    assert list(df.columns) == schema.TRADE_COLUMNS
    assert schema.validate(df) == []
    assert len(df) > 0
    assert set(df["side"].unique()) <= {"BUY", "SELL"}
    assert (df["source"] == f"synth:{persona.key}").all()


def test_페르소나가_다르면_출처_문자열도_다르다(small_universe):
    df_disposition = generate_trades(
        replace(DISPOSITION_PRONE, n_episodes=2), tickers=small_universe
    )
    df_chasing = generate_trades(replace(CHASING_PRONE, n_episodes=2), tickers=small_universe)

    assert df_disposition["source"].iloc[0] == "synth:disposition_prone"
    assert df_chasing["source"].iloc[0] == "synth:chasing_prone"
