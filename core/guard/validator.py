"""LLM 출력 검증기.

두 가지 검증을 담당한다:
  1. 숫자 화이트리스트 — LLM 출력의 모든 숫자가 evidence 안에 있어야 한다.
     evidence에 없는 숫자를 LLM이 지어냈다면 검증 실패 → 폴백.
  2. 금지어 필터 — 투자 추천·매수/매도 의견 등 규제 리스크 표현 차단.

두 검증 모두 통과해야 validate() 가 True를 반환한다.
이 모듈은 순수 함수만 포함 — LLM 호출 없이 단독 테스트 가능.
"""

from __future__ import annotations

import re

# 규제 리스크 + 서비스 성격에 맞지 않는 표현 목록
BANNED_WORDS: list[str] = [
    "추천",
    "매수하세요",
    "매도하세요",
    "목표가",
    "손절가",
    "적정가",
    "전망",
    "예상수익",
    "오를",
    "내릴",
]


def _extract_number_tokens(text: str) -> set[str]:
    """텍스트에서 숫자 토큰을 추출한다.

    "80,000" 같은 콤마 포함 형식과 "80000" 일반 형식을 모두 whitelist에 추가해
    LLM이 둘 중 어느 형식으로 써도 매칭되게 한다.
    """
    raw_tokens = re.findall(r"\d[\d,.]*", text)
    result: set[str] = set()
    for token in raw_tokens:
        result.add(token)
        result.add(token.replace(",", ""))  # 콤마 제거 버전도 추가
    return result


def build_whitelist(evidence: list[dict]) -> set[str]:
    """evidence 전체에서 허용된 숫자 집합을 만든다."""
    whitelist: set[str] = set()
    for item in evidence:
        for value in item.values():
            whitelist |= _extract_number_tokens(str(value))
    return whitelist


def is_numbers_whitelisted(text: str, evidence: list[dict]) -> bool:
    """LLM 출력의 모든 숫자가 evidence에 존재하는가."""
    output_numbers = _extract_number_tokens(text)
    if not output_numbers:
        return True  # 숫자 없는 출력은 통과
    return output_numbers.issubset(build_whitelist(evidence))


def has_banned_words(text: str) -> bool:
    """금지어가 하나라도 포함되어 있는가."""
    return any(word in text for word in BANNED_WORDS)


def validate(text: str, evidence: list[dict]) -> bool:
    """숫자 화이트리스트 + 금지어 필터 모두 통과하면 True."""
    return not has_banned_words(text) and is_numbers_whitelisted(text, evidence)
