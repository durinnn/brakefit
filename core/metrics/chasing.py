"""추격매수(chasing) 계수.

정의: 이미 오른 종목에 더 오를 걸 기대하고 뒤늦게 따라 들어가는 경향.

    raw = 전일 종가 대비 +threshold 이상 급등한 뒤 매수한 건수 / 전체 매수 건수

raw 는 이미 [0, 1] 구간이라 그대로 100을 곱해 0~100 에 매핑한다.

⚠ 스키마 한계 (core/engine 이 아직 없어 fixture 로만 검증한 상태, 진짜 제약임):
   "당일 급등 후 추격"을 제대로 판정하려면 종목별 일별 시가가 있어야
   장중 등락률(=매수가 대비 당일 시가)을 계산할 수 있다. 그런데 docs/schema.md 의
   trades/timeline/episodes 어디에도 종목별 raw 시세 시계열이 없다 — timeline.close 는
   "포지션을 들고 있는 동안만" 존재하는 값이라 신규 진입 시점엔 비교할 전일 종가가 없다.

   그래서 지금은 스코프를 줄여서 "이미 보유 중인 종목에 대한 추가매수"만 판정한다
   (전일 종가는 같은 episode 의 timeline 에서 구한다). 신규 진입 매수는 판정 대상에서
   제외한다 (분모에도 넣지 않는다 — 아래 참조).

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

    raw 의 분모는 "전체 매수 건수"가 아니라 "판정 가능한 매수 건수"(=같은 에피소드
    내에서 전일 종가를 아는 추가매수)다. 신규 진입은 애초에 판정 불가라 분모에
    넣지 않는다 — 넣으면 거래 횟수가 적은 케이스에서 우연히 걸린 한두 건이 비율을
    크게 흔든다.
    """
    buys = trades[trades["side"] == "BUY"].copy()
    if len(buys) == 0:
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
        ]
        if own_rows.empty:
            continue  # timeline 에 이 매수일 행이 없음 — 판정 불가
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
        return MetricResult(key="chasing", raw=0.0, score_0_100=0.0, evidence=[])

    raw = chasing_buys / judged_buys
    score = clamp(raw * 100)

    return MetricResult(key="chasing", raw=raw, score_0_100=score, evidence=evidence)
