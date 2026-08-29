"""폴백 고정 템플릿.

LLM 호출이 타임아웃되거나 검증을 통과하지 못했을 때 반환하는 사전 작성 문구.
sequences.md: "룰별 고정 템플릿 소견 (폴백)" — 서비스 핵심(점수·게이지)은
LLM 장애와 무관하게 항상 작동해야 한다. 폴백이 발동해도 점수·워터폴은 그대로.

두 context 별로 분리:
  "report_summary"     — CSV 업로드 후 전체 진단 소견
  "order_intervention" — 주문 직전 룰별 개입 문구
"""

from __future__ import annotations

# ── 진단 리포트 종합 소견 ──────────────────────────────────
REPORT_FALLBACK = {
    "headline": "행동 편향이 감지되었습니다",
    "body": (
        "과거 거래 패턴에서 처분효과, 물타기, 추격매수 경향이 분석되었습니다. "
        "아래 지표를 참고해 매매 습관을 점검해보세요."
    ),
}

# ── 주문 개입 문구 — 룰 키 기준 ──────────────────────────
_ORDER_FALLBACKS: dict[str, dict[str, str]] = {
    "chasing": {
        "headline": "추격매수 패턴이 감지됩니다",
        "body": (
            "급등 직후 매수는 과거에도 반복된 패턴입니다. "
            "잠시 멈추고 매수 이유를 다시 점검해보세요."
        ),
    },
    "averaging_down": {
        "headline": "물타기 패턴이 감지됩니다",
        "body": (
            "손실 중인 종목에 추가 매수하려 합니다. "
            "과거에 같은 선택을 했을 때의 결과를 먼저 확인해보세요."
        ),
    },
    "disposition_effect": {
        "headline": "처분효과 패턴이 감지됩니다",
        "body": (
            "평가이익 중인 종목을 서둘러 매도하려 합니다. "
            "손실 종목과 비교해 균형 있는 판단을 해보세요."
        ),
    },
    "default": {
        "headline": "과거 패턴과 유사한 주문입니다",
        "body": "이 주문은 과거에 반복된 편향 패턴과 유사합니다. 잠시 멈추고 다시 생각해보세요.",
    },
}


def get_report_fallback() -> dict[str, str]:
    return REPORT_FALLBACK


def get_order_fallback(triggered_keys: list[str]) -> dict[str, str]:
    """발동된 룰 중 가장 기여가 큰 룰(리스트 첫 번째)의 템플릿을 반환한다.

    engine.py 는 워터폴 순서(chasing → averaging_down → disposition)로
    contributions 를 정렬해서 넘기므로, triggered_keys[0] 이 최우선 룰이다.
    """
    for key in triggered_keys:
        if key in _ORDER_FALLBACKS:
            return _ORDER_FALLBACKS[key]
    return _ORDER_FALLBACKS["default"]
