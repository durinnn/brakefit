"""LLM 출력 검증기(validator) 테스트.

LLM 없이 순수 함수만 테스트한다.

숫자 화이트리스트 시나리오:
    evidence에 "80,000원"이 있으면 LLM이 "80,000" 또는 "80000"을 써도 통과.
    evidence에 없는 숫자(예: "100,000")를 LLM이 쓰면 실패.

금지어 시나리오:
    "추천", "목표가" 등이 포함된 출력은 즉시 실패.
"""

from __future__ import annotations

import pytest

from core.guard.validator import (
    BANNED_WORDS,
    _extract_number_tokens,
    build_whitelist,
    has_banned_words,
    is_numbers_whitelisted,
    validate,
)

SAMPLE_EVIDENCE = [
    {
        "trade_id": "proposed:005930",
        "date": "2026-08-03",
        "name": "삼성전자",
        "detail": "현재 평가손실 -40,000원 상태에서 삼성전자 5주 추가매수",
    },
    {
        "trade_id": "t2",
        "date": "2026-08-03",
        "name": "삼성전자",
        "detail": "전일 종가 66,000원 대비 5.0% 급등 가격으로 5주 매수",
    },
]


# ── 숫자 추출 ───────────────────────────────────────────────


def test_extract_includes_comma_and_plain_form():
    tokens = _extract_number_tokens("80,000원")
    assert "80,000" in tokens
    assert "80000" in tokens  # 콤마 제거 버전


def test_extract_decimal():
    tokens = _extract_number_tokens("5.0%")
    assert "5.0" in tokens


def test_extract_plain_integer():
    tokens = _extract_number_tokens("3일")
    assert "3" in tokens


# ── 화이트리스트 ─────────────────────────────────────────────


def test_whitelist_contains_evidence_numbers():
    wl = build_whitelist(SAMPLE_EVIDENCE)
    assert "40,000" in wl or "40000" in wl
    assert "66,000" in wl or "66000" in wl
    assert "5.0" in wl


def test_numbers_in_evidence_pass():
    # evidence에 있는 숫자만 쓴 LLM 출력 → 통과
    text = "평가손실 40,000원 상태에서 추가매수했습니다."
    assert is_numbers_whitelisted(text, SAMPLE_EVIDENCE) is True


def test_hallucinated_number_fails():
    # evidence에 없는 100,000 → 실패
    text = "평가손실 100,000원 상태입니다."
    assert is_numbers_whitelisted(text, SAMPLE_EVIDENCE) is False


def test_no_numbers_in_output_passes():
    text = "과거 패턴과 유사한 주문입니다."
    assert is_numbers_whitelisted(text, SAMPLE_EVIDENCE) is True


def test_empty_evidence_fails_if_output_has_numbers():
    # evidence가 비어있는데 LLM이 수치를 씀 → 화이트리스트 없음 → 실패
    assert is_numbers_whitelisted("손실 50,000원", []) is False


# ── 금지어 필터 ──────────────────────────────────────────────


@pytest.mark.parametrize("word", BANNED_WORDS)
def test_each_banned_word_detected(word):
    assert has_banned_words(f"이 종목을 {word} 드립니다") is True


def test_clean_text_has_no_banned_words():
    text = "과거 거래 이력에서 추격매수 패턴이 감지되었습니다."
    assert has_banned_words(text) is False


# ── 통합 validate ────────────────────────────────────────────


def test_validate_passes_clean_output():
    text = "평가손실 40,000원 상태에서의 추가매수입니다."
    assert validate(text, SAMPLE_EVIDENCE) is True


def test_validate_fails_on_banned_word():
    text = "이 종목 매수를 추천합니다."
    assert validate(text, SAMPLE_EVIDENCE) is False


def test_validate_fails_on_hallucinated_number():
    text = "손실 999,000원이 예상됩니다."
    assert validate(text, SAMPLE_EVIDENCE) is False


def test_validate_fails_if_both_bad():
    text = "목표가 300,000원을 추천합니다."
    assert validate(text, SAMPLE_EVIDENCE) is False
