"""브레이크 룰 공통 타입 + "기준 종가" 조회.

개입 판정(InterventionReport)과 룰별 기여(RuleContribution)를 정의한다.
docs/sequences.md ② 개입 플로우에서 API 가 받는 응답 형태의 핵심.

여기에 종가 조회가 같이 있는 이유: 룰이 쓰는 "기준 종가"의 출처를 한 곳으로 못박기
위해서다. 예전에는 timeline(=포지션을 들고 있는 동안에만 존재하는 시계열)에서 종가를
꺼냈는데, 그러면 (1) 미보유 종목은 아예 판정이 안 되고 (2) 청산된 옛 에피소드의
마지막 종가가 "전일 종가"로 둔갑했다. 이제 docs/schema.md §5 의 공용 시세 인터페이스
(core/synth/prices.get_daily_close)에서 읽는다.

조회기는 reference_close() **하나**다 — 룰·표시용 등락률·주문 폼의 최근 종가가
같은 함수를 거치게 해서, 화면에 뜬 기준 종가와 판정에 쓴 기준 종가가 갈라지지
않도록 한다(예전에는 /api/universe 만 as_of 를 포함해서 하루 어긋났다).
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
REFERENCE_CLOSE_LOOKBACK_DAYS = 14


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


def reference_close(
    ticker: str,
    as_of: date | None,
    price_source: PriceSource | None = None,
    *,
    lookback_days: int = REFERENCE_CLOSE_LOOKBACK_DAYS,
) -> tuple[ReferenceClose | None, str | None]:
    """as_of **이하**(당일 포함) 마지막 영업일 종가 → (기준 종가, 미판정 사유).

    as_of 당일을 **포함**하는 이유: 실제 호출 경로에서 as_of 는 이미 주문 시점보다
    앞선 날이라, as_of 종가는 주문을 넣는 사람이 이미 아는 값이다.
      · 개입 판정(api/service.simulate_order): as_of = 보유 거래내역의 **마지막
        거래일**(데모는 DEMO_AS_OF=2026-08-18)이고, 모의 주문은 그 이후인 "지금"
        넣는다 — 08-18 종가는 이미 장이 끝나 공시된 값이다.
      · 백테스트(core/backtest): 판정 컷이 cutoff = traded_at − 1일이라, cutoff
        당일 종가도 매수 시점에는 이미 나와 있다.
    당일을 빼면 오히려 하루 뒤처진 종가를 쓰게 돼서, core/metrics/chasing 의 T−1
    기준(전일 종가 대비 급등)과 하루 어긋나고 /api/universe 의 lastClose(as_of 이하)
    와 팝업 changeRate 가 서로 다른 종가를 가리켰다.

    ⚠ 룩어헤드 금지(AGENTS.md 절대규칙 1)의 경계는 여전히 여기 한 곳이다: 조회
    구간의 끝을 as_of 로 못박으므로 as_of **초과** 종가는 애초에 이 함수 안으로
    들어오지 못한다 — "마지막 행"을 집어도 미래를 볼 수 없다. (data/cache/prices 는
    as_of 보다 뒤 날짜까지 갖고 있어서, 이 경계가 없으면 조용히 미래를 쓰게 된다.)

    둘 중 하나만 채워진 튜플을 돌려준다 — 종가를 못 구하면 사유가 반드시 있다.
    """
    if as_of is None:
        return None, f"{ticker}: 기준일(as_of)을 몰라 기준 종가를 정할 수 없음 — 미판정"
    source = price_source or get_daily_close
    try:
        series = source(ticker, as_of - timedelta(days=lookback_days), as_of)
    except AssertionError:
        # 불변식 위반(주로 테스트 감시기의 룩어헤드 검사)은 시세 장애가 아니다.
        # 여기서 "미판정 + 경고"로 바꿔버리면 룩어헤드 회귀가 조용히 통과한다.
        raise
    except Exception as exc:  # 네트워크·미캐시·상장폐지 등 — 사유를 남기고 미판정
        detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        return None, (
            f"{ticker}: {as_of} 이하 종가 조회 실패 ({type(exc).__name__}: {detail}) — 미판정"
        )

    if series is None or len(series) == 0 or float(series.iloc[-1]) <= 0:
        return None, (f"{ticker}: {as_of} 까지 거슬러 {lookback_days}일 안에 종가가 없음 — 미판정")
    stamp = series.index[-1]
    ref = ReferenceClose(
        close=float(series.iloc[-1]),
        date=stamp.date() if hasattr(stamp, "date") else stamp,
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
