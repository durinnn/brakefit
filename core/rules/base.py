"""브레이크 룰 공통 타입 + "직전 종가" 조회.

개입 판정(InterventionReport)과 룰별 기여(RuleContribution)를 정의한다.
docs/sequences.md ② 개입 플로우에서 API 가 받는 응답 형태의 핵심.

여기에 종가 조회가 같이 있는 이유: 룰이 쓰는 "직전 종가"의 출처를 한 곳으로 못박기
위해서다. 예전에는 timeline(=포지션을 들고 있는 동안에만 존재하는 시계열)에서 종가를
꺼냈는데, 그러면 (1) 미보유 종목은 아예 판정이 안 되고 (2) 청산된 옛 에피소드의
마지막 종가가 "전일 종가"로 둔갑했다. 이제 docs/schema.md §5 의 공용 시세 인터페이스
(core/synth/prices.get_daily_close)에서 읽는다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from core.synth.prices import get_daily_close

# 개입 조건 중 점수 쪽 임계 — 주 조건은 "룰 하나라도 triggered" 다(core/rules/engine.py 참조)
INTERVENE_THRESHOLD = 50.0

#: 룰이 쓰는 시세 조회기. (ticker, start, end) -> 종가 Series(index=Timestamp).
#: 기본값은 core/synth/prices.get_daily_close 지만, 테스트에서 fake 를 주입해
#: "룰이 어떤 날짜 구간을 요청했는지"까지 검증할 수 있게 콜러블로 뚫어둔다.
PriceSource = Callable[[str, date, date], "pd.Series"]

#: 기준 종가를 찾을 때 거꾸로 훑는 달력일수. 좁을수록 커밋된 캐시
#: (data/cache/prices) 안에서 끝나 네트워크를 안 탄다. 14일이면 설·추석 연휴
#: (최장 5영업일 휴장)를 넘겨도 종가가 최소 하나는 들어온다.
PREV_CLOSE_LOOKBACK_DAYS = 14


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
    #: 판정을 못 했거나 근거가 약해진 사유(시세 조회 실패·기준일 없음 등).
    #: triggered=False 에는 "발동 안 함"과 "판정 못 함"이 섞여 있는데, 그 둘을
    #: 구분할 유일한 단서다 — AGENTS.md "예외는 삼키지 않는다".
    warnings: list[str] = field(default_factory=list)


@dataclass
class InterventionReport:
    """개입 판정 최종 보고서.

    API 가 UI 에 반환하는 형태. contributions 는 워터폴 그래프 재료.
    """

    risk_score: float  # 0~100
    contributions: list[RuleContribution]  # 순서: chasing → averaging_down → disposition
    should_intervene: bool  # 룰 하나라도 triggered 이거나 risk_score >= INTERVENE_THRESHOLD
    #: 세 룰의 warnings 를 순서대로 합친 것. 호출자(api/service)가 로그로 남긴다.
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReferenceClose:
    """판정 기준이 된 종가와 그 종가의 날짜."""

    close: float
    date: date


def last_close_on_or_before(
    ticker: str,
    on_or_before: date,
    price_source: PriceSource | None = None,
    *,
    lookback_days: int = PREV_CLOSE_LOOKBACK_DAYS,
) -> ReferenceClose | None:
    """[on_or_before - lookback_days, on_or_before] 구간의 **마지막** 종가. 없으면 None.

    ⚠ 룩어헤드 금지(AGENTS.md 절대규칙 1): 조회 구간의 끝을 on_or_before 로 못박는다.
    get_daily_close() 가 [start, end] 로 잘라서 주므로 그 다음 날 종가는 애초에 이
    함수 안으로 들어오지 못한다 — "마지막 행"을 집어도 미래를 볼 수 없다.
    (실제로 data/cache/prices 는 as_of 보다 뒤 날짜까지 갖고 있어서, 이 경계가 없으면
    조용히 미래 종가를 쓰게 된다.)

    조회 실패(네트워크·미캐시)는 여기서 삼키지 않는다 — 예외를 그대로 올려서
    호출자가 "미판정 + 사유"로 처리할지 502 로 올릴지 정하게 한다.
    """
    source = price_source or get_daily_close
    series = source(ticker, on_or_before - timedelta(days=lookback_days), on_or_before)
    if series is None or len(series) == 0:
        return None
    stamp = series.index[-1]
    close = float(series.iloc[-1])
    if close <= 0:
        return None
    return ReferenceClose(close=close, date=stamp.date() if hasattr(stamp, "date") else stamp)


def previous_close(
    ticker: str,
    as_of: date | None,
    price_source: PriceSource | None = None,
) -> tuple[ReferenceClose | None, str | None]:
    """as_of **직전**(당일 제외) 마지막 영업일 종가 → (기준 종가, 미판정 사유).

    as_of 당일을 빼는 이유: 주문을 넣는 시점에 그날 종가는 아직 없다. 캐시에는
    들어있으므로(장 마감 후 채운 파일) 경계를 안 걸면 "오늘 종가와 비교해서 급등"
    이라는, 주문 시점에는 알 수 없는 판정을 하게 된다.

    둘 중 하나만 채워진 튜플을 돌려준다 — 종가를 못 구하면 사유가 반드시 있다.
    """
    if as_of is None:
        return None, f"{ticker}: 기준일(as_of)을 몰라 직전 종가를 정할 수 없음 — 미판정"
    try:
        ref = last_close_on_or_before(ticker, as_of - timedelta(days=1), price_source)
    except AssertionError:
        # 불변식 위반(주로 테스트 감시기의 룩어헤드 검사)은 시세 장애가 아니다.
        # 여기서 "미판정 + 경고"로 바꿔버리면 룩어헤드 회귀가 조용히 통과한다.
        raise
    except Exception as exc:  # 네트워크·미캐시·상장폐지 등 — 사유를 남기고 미판정
        detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        return None, (
            f"{ticker}: {as_of} 직전 종가 조회 실패 ({type(exc).__name__}: {detail}) — 미판정"
        )
    if ref is None:
        return None, (
            f"{ticker}: {as_of} 이전 {PREV_CLOSE_LOOKBACK_DAYS}일 안에 종가가 없음 — 미판정"
        )
    return ref, None


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
