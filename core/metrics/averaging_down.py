"""물타기(averaging down) 지수.

정의: 이미 평가손실 상태인 종목에 추가로 매수하는(=손실을 더 키울 수 있는 자리에
계속 들어가는) 경향. 진입 매수는 "물타기"가 아니다 — 진입 이후의 추가매수만 센다.

    raw = 손실 상태(unrealized_pnl < 0)에서 발생한 추가매수 건수 / 전체 매수 건수

raw 는 이미 [0, 1] 구간이라 그대로 100을 곱해 0~100 에 매핑한다.

⚠ 단순화 지점 (core/engine 이 아직 없어 fixture 로만 검증한 상태):
   - trades 에는 episode_id 가 없어서, (ticker, traded_at) 이 어느 episode 의
     [opened_at, closed_at] 구간에 속하는지로 역매칭한다. 재진입(같은 종목 여러 episode)이
     겹치지 않는다는 전제(= episodes 정의 자체)에 기대는 방식이라, 이 전제가 깨지면 같이 깨진다.
   - "손실 상태였는지"는 매수 당일 종가 기준 timeline 스냅샷(unrealized_pnl)으로 판정한다.
     장중 매수 시점과 종가 시점의 손익이 다를 수 있다는 오차는 감수한다.
"""

from __future__ import annotations

import pandas as pd

from core.metrics.base import MetricResult, clamp


def _find_episode(
    ticker: str, traded_at, episodes: pd.DataFrame
) -> tuple[str, object] | tuple[None, None]:
    """이 매수가 어느 episode 소속인지 찾는다. (episode_id, opened_at) 또는 (None, None)."""
    candidates = episodes[episodes["ticker"] == ticker]
    for _, ep in candidates.iterrows():
        opened = ep["opened_at"]
        closed = ep["closed_at"]
        if opened <= traded_at and (pd.isna(closed) or traded_at <= closed):
            return ep["episode_id"], opened
    return None, None


def compute(timeline: pd.DataFrame, trades: pd.DataFrame, episodes: pd.DataFrame) -> MetricResult:
    """물타기 지수 계산. 입력은 전부 core/engine(A) 의 출력 형태(schema.md §1·§2·§3)."""
    buys = trades[trades["side"] == "BUY"].copy()
    total_buys = len(buys)
    if total_buys == 0 or episodes.empty:
        return MetricResult(key="averaging_down", raw=0.0, score_0_100=0.0, evidence=[])

    buys["traded_at"] = pd.to_datetime(buys["traded_at"])
    episodes = episodes.copy()
    episodes["opened_at"] = pd.to_datetime(episodes["opened_at"])
    episodes["closed_at"] = pd.to_datetime(episodes["closed_at"])
    timeline = timeline.copy()
    timeline["date"] = pd.to_datetime(timeline["date"])

    loss_add_buys = 0
    evidence: list[dict] = []
    for _, t in buys.iterrows():
        episode_id, opened_at = _find_episode(t["ticker"], t["traded_at"], episodes)
        if episode_id is None or t["traded_at"] == opened_at:
            continue  # 매칭 안 되거나, 진입 매수 자체는 추가매수가 아니다

        snapshot = timeline[
            (timeline["episode_id"] == episode_id) & (timeline["date"] == t["traded_at"])
        ]
        if snapshot.empty:
            continue

        unrealized = snapshot.iloc[0]["unrealized_pnl"]
        if unrealized < 0:
            loss_add_buys += 1
            return_pct = round(float(snapshot.iloc[0]["unrealized_pct"]) * 100, 2)
            detail = (
                f"평가손실 {unrealized:,.0f}원({return_pct}%) 상태에서 "
                f"{int(t['quantity'])}주 추가매수"
            )
            evidence.append(
                {
                    "trade_id": t["trade_id"],
                    "date": str(t["traded_at"].date()),
                    "name": t["name"],
                    "detail": detail,
                    # 매수 시점 평가손익률(%). "그 이후 실제 수익률"이 아님
                    "return_pct": return_pct,
                }
            )

    raw = loss_add_buys / total_buys
    score = clamp(raw * 100)

    return MetricResult(key="averaging_down", raw=raw, score_0_100=score, evidence=evidence)
