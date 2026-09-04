"""폴백 템플릿 + guard.generate() 폴백 동작 테스트.

LLM 호출 없이 폴백 경로만 검증한다.
ANTHROPIC_API_KEY 가 없는 환경(CI 포함)에서도 전부 통과해야 한다.
"""

from __future__ import annotations

import pytest

from core.guard.guard import CoachingText, generate
from core.guard.templates import get_order_fallback, get_report_fallback

EVIDENCE = [
    {
        "trade_id": "proposed:005930",
        "date": "2026-08-03",
        "name": "삼성전자",
        "detail": "전일 종가 66,000원 대비 5.0% 급등 가격으로 5주 매수",
    }
]


# ── 폴백 템플릿 자체 검증 ─────────────────────────────────────


def test_report_fallback_has_headline_and_body():
    tmpl = get_report_fallback()
    assert tmpl["headline"]
    assert tmpl["body"]


@pytest.mark.parametrize("key", ["chasing", "averaging_down", "disposition_effect"])
def test_order_fallback_exists_for_each_rule(key):
    tmpl = get_order_fallback([key])
    assert tmpl["headline"]
    assert tmpl["body"]


def test_order_fallback_unknown_key_returns_default():
    tmpl = get_order_fallback(["unknown_rule"])
    assert tmpl["headline"]  # default 템플릿 반환


def test_order_fallback_first_key_wins():
    # 기여가 큰 룰(첫 번째)의 템플릿이 나와야 함
    tmpl_chase = get_order_fallback(["chasing", "averaging_down"])
    tmpl_chase_only = get_order_fallback(["chasing"])
    assert tmpl_chase["headline"] == tmpl_chase_only["headline"]


# ── generate() 폴백 경로 ─────────────────────────────────────


def test_generate_returns_fallback_without_api_key(monkeypatch):
    """API 키 없으면 from_llm=False 인 CoachingText 반환."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = generate(
        context="order_intervention",
        evidence=EVIDENCE,
        triggered_keys=["chasing"],
    )

    assert isinstance(result, CoachingText)
    assert result.from_llm is False
    assert result.headline
    assert result.body


def test_generate_report_fallback_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = generate(context="report_summary", evidence=EVIDENCE)

    assert result.from_llm is False
    assert result.headline
    assert result.body


def test_generate_fallback_picks_correct_rule_template(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = generate(
        context="order_intervention",
        evidence=EVIDENCE,
        triggered_keys=["averaging_down"],
    )

    expected = get_order_fallback(["averaging_down"])
    assert result.headline == expected["headline"]


def test_generate_empty_triggered_keys_uses_default(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = generate(context="order_intervention", evidence=EVIDENCE, triggered_keys=[])

    assert result.headline  # default 템플릿
    assert result.from_llm is False
