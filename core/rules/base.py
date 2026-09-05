"""브레이크 룰 공통 타입.

개입 판정(InterventionReport)과 룰별 기여(RuleContribution)를 정의한다.
docs/sequences.md ② 개입 플로우에서 API 가 받는 응답 형태의 핵심.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# 개입 조건 중 점수 쪽 임계 — 주 조건은 "룰 하나라도 triggered" 다(core/rules/engine.py 참조)
INTERVENE_THRESHOLD = 50.0


@dataclass
class ProposedOrder:
    """사용자가 입력한 모의 주문 컨텍스트."""

    ticker: str
    name: str
    side: str  # "BUY" | "SELL"
    quantity: int
    price: float  # 예상 체결가


@dataclass
class RuleContribution:
    """룰 하나의 판정 결과와 기여 점수.

    score 는 총 위험점수(risk_score)의 일부 — 세 룰의 score 합이 risk_score 가 된다.
    """

    key: str  # "disposition_effect" | "averaging_down" | "chasing"
    triggered: bool
    score: float  # 0~해당 룰의 MAX_CONTRIBUTION
    evidence: list[dict] = field(default_factory=list)


@dataclass
class InterventionReport:
    """개입 판정 최종 보고서.

    API 가 UI 에 반환하는 형태. contributions 는 워터폴 그래프 재료.
    """

    risk_score: float  # 0~100
    contributions: list[RuleContribution]  # 순서: chasing → averaging_down → disposition
    should_intervene: bool  # 룰 하나라도 triggered 이거나 risk_score >= INTERVENE_THRESHOLD


def open_episode_ids(episodes: pd.DataFrame, ticker: str) -> set[str]:
    """as_of 시점에 **아직 들고 있는** 에피소드의 episode_id 집합 (docs/schema.md §3).

    브레이크 룰이 "지금 이 종목의 상태"를 볼 때 반드시 거쳐야 하는 관문이다. timeline
    에서 종목만 걸러 마지막 행을 집으면, 몇 달 전에 청산된 에피소드의 마지막 날 행이
    "현재 평가손익"·"전일 종가"로 둔갑한다(실측: rational_baseline 의 000660 은 as_of
    2026-08-18 인데 timeline 마지막 행이 2026-08-11 — 그 사이는 보유 자체가 없었다).

    episodes 는 engine.build(as_of=...) 가 만든 그대로여야 한다 — is_open 은 그
    as_of 기준 값이라, 다른 시점의 episodes 를 섞으면 판정도 그만큼 어긋난다.
    """
    if episodes is None or episodes.empty:
        return set()
    rows = episodes[episodes["ticker"] == ticker]
    if rows.empty:
        return set()
    if "is_open" in rows.columns:
        open_rows = rows[rows["is_open"].fillna(False).astype(bool)]
    else:  # is_open 이 없는 입력(수기 fixture 등)은 closed_at 으로 판단한다
        open_rows = rows[rows["closed_at"].isna()]
    return set(open_rows["episode_id"])
