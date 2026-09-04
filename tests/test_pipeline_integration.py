"""synth -> engine -> C 의 실제 metrics/rules 까지 진짜로 연결되는지 확인.

tests/test_metrics_*.py 는 core/engine 이 없던 시절 손으로 만든 fixture 를 쓴다 —
정밀 검증용으로 여전히 유효해서 안 건드린다(예: disposition 지표의 정확한 PGR/PLR
공식 검증은 거기가 담당). 여기는 반대 방향 — "진짜 engine 출력을 진짜 metrics/rules
에 먹였을 때 파이프라인 전체가 안 깨지고, 페르소나별 편향 방향성이 유지되는지" 를 본다.

AS_OF 는 data/cache/prices/ 에 이미 캐싱된 범위 안으로 고정 — 네트워크 없이 재현된다.
"""

from __future__ import annotations

from datetime import date

import pytest

from core import schema
from core.engine.engine import build
from core.metrics import averaging_down, chasing, disposition
from core.rules import engine as rules_engine
from core.rules.base import ProposedOrder
from core.synth.generator import generate_trades
from core.synth.personas import (
    AVERAGING_DOWN_PRONE,
    CHASING_PRONE,
    DISPOSITION_PRONE,
    RATIONAL_BASELINE,
)

AS_OF = date(2026, 8, 18)
UNIVERSE = {"005930": "삼성전자", "000660": "SK하이닉스", "035420": "NAVER"}

METRIC_MODULES = (disposition, averaging_down, chasing)


def _run_pipeline(persona):
    trades = generate_trades(persona, tickers=UNIVERSE, end=AS_OF)
    assert schema.validate(trades) == [], (
        "synth 출력 자체가 schema 를 못 통과하면 그 뒤는 의미 없음"
    )

    result = build(trades, as_of=AS_OF)
    metric_results = [
        mod.compute(result.timeline, trades, result.episodes) for mod in METRIC_MODULES
    ]
    return trades, result, metric_results


def _score(metric_results, key: str) -> float:
    return next(m for m in metric_results if m.key == key).score_0_100


@pytest.mark.parametrize(
    "persona",
    [RATIONAL_BASELINE, DISPOSITION_PRONE, AVERAGING_DOWN_PRONE, CHASING_PRONE],
    ids=lambda p: p.key,
)
def test_synth_페르소나가_engine을_거쳐_metrics까지_에러없이_연결된다(persona):
    trades, result, metric_results = _run_pipeline(persona)

    assert list(result.timeline.columns) == schema.TIMELINE_COLUMNS
    assert list(result.episodes.columns) == schema.EPISODE_COLUMNS
    assert len(metric_results) == 3

    for m in metric_results:
        assert 0.0 <= m.score_0_100 <= 100.0
        for ev in m.evidence:
            # docs/schema.md §4: evidence 는 최소 이 네 필드를 갖는다.
            assert {"trade_id", "date", "name", "detail"} <= ev.keys()


def test_처분효과형은_대조군보다_disposition_점수가_뚜렷이_높다():
    _, _, rational = _run_pipeline(RATIONAL_BASELINE)
    _, _, disp_prone = _run_pipeline(DISPOSITION_PRONE)

    assert _score(disp_prone, "disposition_effect") > _score(rational, "disposition_effect")


def test_물타기형은_대조군보다_averaging_down_점수가_뚜렷이_높다():
    _, _, rational = _run_pipeline(RATIONAL_BASELINE)
    _, _, avgdown_prone = _run_pipeline(AVERAGING_DOWN_PRONE)

    assert _score(avgdown_prone, "averaging_down") > _score(rational, "averaging_down")


def test_추격매수형은_대조군보다_chasing_점수가_높거나_같다():
    """chasing 은 5%+ 단일일 급등 자체가 희소해서 절대 신호가 약하다(core/synth/generator.py
    모듈 docstring 참조) — '뚜렷이' 대신 '최소한 역전은 안 됨' 정도로 느슨하게 검증."""
    _, _, rational = _run_pipeline(RATIONAL_BASELINE)
    _, _, chasing_prone = _run_pipeline(CHASING_PRONE)

    assert _score(chasing_prone, "chasing") >= _score(rational, "chasing")


def test_브레이크_룰_엔진까지_연결된다():
    trades, result, metric_results = _run_pipeline(DISPOSITION_PRONE)

    order = ProposedOrder(ticker="005930", name="삼성전자", side="BUY", quantity=1, price=70_000)
    report = rules_engine.evaluate(order, metric_results, result.timeline, result.episodes)

    assert 0.0 <= report.risk_score <= 100.0
    assert isinstance(report.should_intervene, bool)
    assert {c.key for c in report.contributions} == {
        "disposition_effect",
        "averaging_down",
        "chasing",
    }
