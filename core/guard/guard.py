"""LLM 가드레일 — 공개 API.

evidence JSON을 받아 코칭 문구 {headline, body} 를 생성한다.
LLM 호출 실패·타임아웃·검증 실패 시 모두 고정 템플릿으로 폴백한다.

사용법:
    from core.guard.guard import generate, CoachingText

    text = generate(
        context="order_intervention",
        evidence=intervention_report.contributions[0].evidence,
        triggered_keys=["chasing", "averaging_down"],
    )
    print(text.headline, text.body, text.from_llm)
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import re
from dataclasses import dataclass

from core.guard.templates import get_order_fallback, get_report_fallback
from core.guard.validator import validate

logger = logging.getLogger(__name__)

# architecture.md: "소형 고속 티어" — haiku 가 latency·cost 최적
_LLM_MODEL = "claude-haiku-4-5-20251001"
# sequences.md: "타임아웃(2~3초)" 명시
_TIMEOUT_SEC = 2.5

_SYSTEM_PROMPT = """\
당신은 개인 투자자의 행동 편향 패턴을 객관적으로 설명하는 어시스턴트입니다.

반드시 지켜야 할 규칙:
1. evidence에 제시된 숫자만 사용하세요. 새로운 수치를 만들거나 추정하지 마세요.
2. 투자 추천, 매수/매도 의견, 목표가, 손절가, 전망, 예상수익 언급을 절대 하지 마세요.
3. 객관적 사실만 전달하세요. "~하세요" 형태의 투자 지시는 하지 마세요.
4. 응답은 반드시 아래 JSON 형식만 출력하세요. 다른 텍스트는 출력하지 마세요.
   {"headline": "15자 이내 한 줄 요약", "body": "80자 이내 설명"}
"""


@dataclass
class CoachingText:
    """LLM 가드레일의 최종 출력."""

    headline: str
    body: str
    from_llm: bool  # True: LLM 생성, False: 고정 템플릿 폴백


def _build_user_prompt(context: str, evidence: list[dict], triggered_keys: list[str]) -> str:
    evidence_lines = "\n".join(
        f"  - [{item.get('name', '')}] {item.get('detail', '')}" for item in evidence
    )
    if context == "order_intervention":
        rule_names = {
            "chasing": "추격매수",
            "averaging_down": "물타기",
            "disposition_effect": "처분효과",
        }
        triggered_str = ", ".join(rule_names.get(k, k) for k in triggered_keys)
        return (
            f"다음 편향 패턴이 감지된 주문에 대한 개입 문구를 작성해주세요.\n\n"
            f"발동된 패턴: {triggered_str}\n\n"
            f"근거 (evidence):\n{evidence_lines}"
        )
    # report_summary
    return (
        f"다음 거래 이력 분석 결과에 대한 종합 소견을 작성해주세요.\n\n"
        f"근거 (evidence):\n{evidence_lines}"
    )


# 언어 태그는 json 말고도 뭐가 붙을지 모른다(JSON·js 등) — 알파벳이면 다 벗긴다.
_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """haiku 가 "다른 텍스트는 출력하지 마세요" 지시를 무시하고 ```json ... ``` 로
    감싸서 응답하는 경우가 있다 — 실측 확인됨(라이브 호출 시 매번은 아니지만 재현됨).
    그대로 두면 json.loads 가 백틱 때문에 파싱 실패 → 불필요하게 폴백 템플릿으로 빠진다.

    펜스가 응답 전체를 감쌀 때만(^...$) 벗긴다. 앞뒤에 잡설이 붙은 응답은 손대지 않고
    그대로 돌려줘서 json.loads 에서 실패 → 폴백으로 보낸다 — 지시를 크게 벗어난 응답을
    부분 추출로 억지로 살리는 것보다, 검증된 고정 문구를 쓰는 편이 안전하다.
    """
    match = _CODE_FENCE_RE.match(text)
    return match.group(1).strip() if match else text


def _call_llm(evidence: list[dict], prompt: str) -> CoachingText | None:
    """Anthropic API 호출. 실패 시 None 반환."""
    try:
        import anthropic  # 선택적 의존성 — 미설치 시 폴백으로 넘어감
    except ImportError:
        logger.warning("anthropic 패키지 미설치 — 폴백 템플릿 사용")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY 미설정 — 폴백 템플릿 사용")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_LLM_MODEL,
            max_tokens=200,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = _strip_code_fence(response.content[0].text.strip())
        parsed = json.loads(raw_text)
        headline = str(parsed.get("headline", ""))
        body = str(parsed.get("body", ""))
        full_text = headline + " " + body

        if not validate(full_text, evidence):
            logger.info("LLM 출력 검증 실패 (숫자 화이트리스트 또는 금지어) — 폴백")
            return None

        return CoachingText(headline=headline, body=body, from_llm=True)

    except (json.JSONDecodeError, KeyError, IndexError, Exception) as e:
        logger.info("LLM 호출/파싱 실패: %s — 폴백", e)
        return None


def generate(
    context: str,
    evidence: list[dict],
    triggered_keys: list[str] | None = None,
) -> CoachingText:
    """코칭 문구를 생성한다. LLM 실패·타임아웃 시 고정 템플릿을 반환한다.

    Args:
        context: "report_summary" | "order_intervention"
        evidence: MetricResult.evidence 또는 RuleContribution.evidence 의 합산 목록
        triggered_keys: 발동된 룰 키 목록. order_intervention 에서만 사용.
    """
    triggered_keys = triggered_keys or []
    prompt = _build_user_prompt(context, evidence, triggered_keys)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_call_llm, evidence, prompt)
        try:
            result = future.result(timeout=_TIMEOUT_SEC)
        except concurrent.futures.TimeoutError:
            logger.info("LLM 타임아웃 (%.1fs 초과) — 폴백", _TIMEOUT_SEC)
            result = None

    if result is not None:
        return result

    # 폴백
    if context == "order_intervention":
        tmpl = get_order_fallback(triggered_keys)
    else:
        tmpl = get_report_fallback()

    return CoachingText(headline=tmpl["headline"], body=tmpl["body"], from_llm=False)
