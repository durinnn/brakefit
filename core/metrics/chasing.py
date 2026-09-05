"""추격매수(chasing) 계수.

정의: 이미 오른 종목에 더 오를 걸 기대하고 뒤늦게 따라 들어가는 경향.

    raw = 전일 종가 대비 +threshold 이상 급등한 뒤 매수한 건수 / 전체 매수 건수

**분모는 전체 매수 건수다.** 판정 불가한 매수(같은 에피소드 안에 비교할 전일 종가가
없는 신규 진입)는 분자에 0 으로 들어갈 뿐 분모에서 빠지지 않는다 — 아래 compute()
docstring 의 "왜" 참조.

raw 는 이미 [0, 1] 구간이라 그대로 100을 곱해 0~100 에 매핑한다.

⚠ 스키마 한계 (core/engine 이 아직 없어 fixture 로만 검증한 상태, 진짜 제약임):
   "당일 급등 후 추격"을 제대로 판정하려면 종목별 일별 시가가 있어야
   장중 등락률(=매수가 대비 당일 시가)을 계산할 수 있다. 그런데 docs/schema.md 의
   trades/timeline/episodes 어디에도 종목별 raw 시세 시계열이 없다 — timeline.close 는
   "포지션을 들고 있는 동안만" 존재하는 값이라 신규 진입 시점엔 비교할 전일 종가가 없다.

   그래서 지금은 스코프를 줄여서 "이미 보유 중인 종목에 대한 추가매수"만 판정한다
   (전일 종가는 같은 episode 의 timeline 에서 구한다). 신규 진입 매수는 추격 여부를
   판정하지 못하므로 분자에 0 으로 들어간다 (분모에는 그대로 남는다 — 아래 참조).

   ⚠ episode 스코핑 필수: "같은 종목"만으로 prior_rows 를 걸러내면 안 된다. 데모
   유니버스처럼 종목 수가 적어 같은 종목에 에피소드가 여러 번 생기는 경우, 이미
   청산된 이전 에피소드의 timeline 행이 "전일 종가"로 잘못 끌려와서 완전히 무관한
   시점끼리 가격을 비교하게 된다 — 신규 진입인데 몇 달 전 청산가와 비교해 가짜
   "+5% 급등"이 뜨는 식. 반드시 같은 episode_id 내에서만 전일 종가를 찾는다
   (합성 페르소나 대조군의 chasing 점수가 튀던 원인이었음).

   TODO: A/B 에게 pykrx 원본 시세 캐시를 별도 인터페이스로 노출해달라고 요청 —
   그래야 신규 진입 추격매수까지 잡을 수 있다. (docs/schema.md 에 항목 추가 후 PR 필요)
"""

from __future__ import annotations

import pandas as pd

from core.metrics.base import MetricResult, clamp

SURGE_THRESHOLD = 0.05  # 전일 종가 대비 +5% 이상이면 "급등 후 추격"으로 본다


def compute(
    timeline: pd.DataFrame,
    trades: pd.DataFrame,
    episodes: pd.DataFrame,  # noqa: ARG001 — 인터페이스 통일을 위해 유지 (지금은 미사용)
) -> MetricResult:
    """추격매수 계수 계산. 입력은 전부 core/engine(A) 의 출력 형태(schema.md §1·§2).

    raw 의 분모는 **전체 매수 건수**다. 판정 불가한 매수(같은 에피소드 안에 전일
    종가가 없는 신규 진입)는 분자 0 으로 처리하고 분모에는 그대로 남긴다.

    왜: 분모를 "판정 가능한 매수 건수"로 바꿔봤더니, 판정 표본이 1~2건인 페르소나에서
    0/100 으로 포화해버렸다(1건 중 1건이 걸리면 곧바로 100점). 데모 경로처럼 종목이
    3개뿐이면 판정 표본이 통째로 한 자릿수라, 대조군 rational_baseline 이 추격매수
    100점을 받고 chasing_prone 과 구분이 안 됐다. 전체 매수를 분모로 두면 "이 사람의
    매수 중 몇 %가 급등 추격이었나"라는 원래 정의로 돌아가고, 판정 못 한 매수는
    "추격 아님" 쪽으로 보수적으로 기운다 — 편향 점수를 과대평가하지 않는 방향이다.
    """
    buys = trades[trades["side"] == "BUY"].copy()
    total_buys = len(buys)
    if total_buys == 0:
        return MetricResult(key="chasing", raw=0.0, score_0_100=0.0, evidence=[])

    buys["traded_at"] = pd.to_datetime(buys["traded_at"])
    timeline = timeline.copy()
    timeline["date"] = pd.to_datetime(timeline["date"])

    judged_buys = 0
    chasing_buys = 0
    evidence: list[dict] = []
    for _, t in buys.iterrows():
        own_rows = timeline[
            (timeline["ticker"] == t["ticker"]) & (timeline["date"] == t["traded_at"])
        ].sort_values("date")
        if own_rows.empty:
            continue  # timeline 에 이 매수일 행이 없음 — 판정 불가
        # 그날 장 마감 시점의 에피소드 = 이 매수가 속한 에피소드. 엔진은 (종목, 날짜)당
        # 행을 하나만 쓰지만(engine.py), 같은 날 전량청산 후 재진입처럼 행이 여러 개로
        # 보일 수 있는 입력에서도 "가장 마지막 상태"를 집도록 정렬 후 마지막을 쓴다.
        episode_id = own_rows.iloc[-1]["episode_id"]

        prior_rows = timeline[
            (timeline["ticker"] == t["ticker"])
            & (timeline["episode_id"] == episode_id)
            & (timeline["date"] < t["traded_at"])
        ]
        if prior_rows.empty:
            continue  # 신규 진입 — 같은 에피소드 내 전일 종가가 없어 판정 불가 (위 TODO 참조)

        prev_close = prior_rows.sort_values("date").iloc[-1]["close"]
        if prev_close <= 0:
            continue

        judged_buys += 1
        jump = (t["price"] - prev_close) / prev_close
        if jump >= SURGE_THRESHOLD:
            chasing_buys += 1
            return_pct = round(jump * 100, 2)
            detail = f"전일 종가 대비 {return_pct:.1f}% 급등 후 {int(t['quantity'])}주 매수"
            evidence.append(
                {
                    "trade_id": t["trade_id"],
                    "date": str(t["traded_at"].date()),
                    "name": t["name"],
                    "detail": detail,
                    "return_pct": return_pct,  # 매수 시점 급등률(%). "그 이후 실제 수익률"이 아님
                }
            )

    if judged_buys == 0:
        # 판정 가능한 매수가 하나도 없음(전부 신규 진입) — 분자가 구조적으로 0 이라
        # 굳이 나눌 것도 없다. 편향 근거가 없으니 0점.
        return MetricResult(key="chasing", raw=0.0, score_0_100=0.0, evidence=[])

    raw = chasing_buys / total_buys
    score = clamp(raw * 100)

    return MetricResult(key="chasing", raw=raw, score_0_100=score, evidence=evidence)
