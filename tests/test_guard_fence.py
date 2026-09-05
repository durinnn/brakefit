"""LLM 응답 코드펜스 제거(_strip_code_fence) 테스트.

haiku 가 "JSON 만 출력하세요" 지시를 어기고 ```json ... ``` 로 감싸 보내는 경우가
실제로 있어서(core/guard/guard.py 참조), 벗기지 못하면 json.loads 가 실패해 멀쩡한
LLM 응답이 폴백 템플릿으로 버려진다. 네 가지 형태를 고정해둔다.
"""

from __future__ import annotations

import json

from core.guard.guard import _strip_code_fence

PAYLOAD = '{"headline": "추격매수 주의", "body": "전일 종가 대비 5.0% 급등"}'


def test_json_tagged_fence_is_stripped():
    assert _strip_code_fence(f"```json\n{PAYLOAD}\n```") == PAYLOAD


def test_untagged_fence_is_stripped():
    assert _strip_code_fence(f"```\n{PAYLOAD}\n```") == PAYLOAD


def test_other_language_tag_is_stripped():
    """언어 태그가 json 이 아니어도(JSON/js 등) 벗긴다."""
    assert _strip_code_fence(f"```JSON\n{PAYLOAD}\n```") == PAYLOAD


def test_plain_json_is_untouched():
    assert _strip_code_fence(PAYLOAD) == PAYLOAD


def test_preamble_before_fence_is_not_stripped():
    """펜스 앞에 잡설이 붙으면 손대지 않는다 → json.loads 실패 → 폴백.

    지시를 크게 벗어난 응답을 부분 추출로 억지로 살리기보다, 검증된 고정 문구로
    빠지는 편이 안전하다는 판단(guard.py _strip_code_fence docstring).
    """
    text = f"다음은 요청하신 JSON입니다.\n```json\n{PAYLOAD}\n```"
    assert _strip_code_fence(text) == text


def test_stripped_output_is_parseable():
    parsed = json.loads(_strip_code_fence(f"```json\n{PAYLOAD}\n```"))
    assert parsed["headline"] == "추격매수 주의"
