"""처분효과(disposition effect) 지표.

정의: 오른 종목은 서둘러 팔고(익절), 내린 종목은 계속 버티는(손절 회피) 경향.
학술적으로는 Odean(1998) 의 PGR/PLR 측정법을 그대로 쓴다.

    PGR (Proportion of Gains Realized)
        = 실현한 이익 건수 / (실현한 이익 건수 + 미실현 평가이익 건수)
    PLR (Proportion of Losses Realized)
        = 실현한 손실 건수 / (실현한 손실 건수 + 미실현 평가손실 건수)
    DE  = PGR - PLR

DE 가 클수록 "이익은 서둘러 확정하고 손실은 안 판다" 는 뜻이다.
raw 는 이론상 [-1, 1] 구간이므로 (raw + 1) / 2 * 100 으로 0~100 에 선형 매핑한다.

⚠ 단순화 지점 (core/engine 이 아직 없어 fixture 로만 검증한 상태):
   evidence 는 지금 episode 단위 정보만 담는다. 실제로는 episode 의
   opened_at/closed_at 구간에 속하는 trades 행을 찾아 trade_id 를 채워야
   docs/schema.md §4 의 "evidence 는 최소 trade_id 를 갖는다" 요건을 완전히 만족한다.
   trades 인자를 지금 안 쓰는 이유도 이것 — TODO: trade_id 역추적.
"""

from __future__ import annotations

import pandas as pd

from core.metrics.base import MetricResult, clamp


def _latest_snapshot(timeline: pd.DataFrame, episode_ids: pd.Series) -> pd.DataFrame:
    """미청산 episode 들의 timeline 최신 행(=오늘 기준 평가손익)만 뽑는다."""
    open_rows = timeline[timeline["episode_id"].isin(episode_ids)]
    if open_rows.empty:
        return open_rows
    return open_rows.sort_values("date").groupby("episode_id", as_index=False).tail(1)


def _closed_episode_return_pct(
    ticker: str, opened_at, closed_at, realized_pnl: float, trades: pd.DataFrame
) -> float | None:
    """청산된 episode 의 수익률(%) = realized_pnl / 그 episode 기간 중 BUY 금액 합.

    engine.py 의 회계 모델(§6.1, amount 기준 평단가)에서 완전 청산 시
    cost_basis 가 정확히 0 으로 소진되므로, [opened_at, closed_at] 구간의
    BUY.amount 합이 그 episode 의 총 원가와 정확히 같다(근사가 아님).
    ⚠ 같은 날 이 episode 청산 + 다음 episode 재진입이 동시에 있으면 그 재진입
    매수까지 같이 잡힐 수 있음 — averaging_down.py 의 date-range 매칭과 동일한
    한계(episode_id 가 trades 에 없어서 생기는 구조적 제약).
    """
    traded_at = pd.to_datetime(trades["traded_at"])
    buys = trades[
        (trades["ticker"] == ticker)
        & (trades["side"] == "BUY")
        & (traded_at >= pd.Timestamp(opened_at))
        & (traded_at <= pd.Timestamp(closed_at))
    ]
    cost_basis = buys["amount"].sum()
    if cost_basis <= 0:
        return None
    return round(realized_pnl / cost_basis * 100, 2)


def compute(timeline: pd.DataFrame, trades: pd.DataFrame, episodes: pd.DataFrame) -> MetricResult:
    """처분효과 점수 계산. 입력은 전부 core/engine(A) 의 출력 형태(schema.md §2·§3)."""
    if episodes.empty:
        return MetricResult(key="disposition_effect", raw=0.0, score_0_100=50.0, evidence=[])

    closed = episodes[~episodes["is_open"]]
    open_eps = episodes[episodes["is_open"]]

    realized_gains = closed[closed["realized_pnl"] > 0]
    realized_losses = closed[closed["realized_pnl"] < 0]

    latest_open = _latest_snapshot(timeline, open_eps["episode_id"])
    unrealized_gains = (
        latest_open[latest_open["unrealized_pnl"] > 0] if not latest_open.empty else latest_open
    )
    unrealized_losses = (
        latest_open[latest_open["unrealized_pnl"] < 0] if not latest_open.empty else latest_open
    )

    pgr_denom = len(realized_gains) + len(unrealized_gains)
    plr_denom = len(realized_losses) + len(unrealized_losses)
    pgr = len(realized_gains) / pgr_denom if pgr_denom else 0.0
    plr = len(realized_losses) / plr_denom if plr_denom else 0.0

    raw = pgr - plr
    score = clamp((raw + 1) / 2 * 100)

    # evidence: 가장 빨리 판 이익 실현 건 + 가장 오래 버틴 손실(미실현 포함) 건을 근거로 제시
    evidence: list[dict] = []
    if not realized_gains.empty:
        fastest = realized_gains.nsmallest(1, "holding_days").iloc[0]
        return_pct = _closed_episode_return_pct(
            ticker=fastest["ticker"],
            opened_at=fastest["opened_at"],
            closed_at=fastest["closed_at"],
            realized_pnl=fastest["realized_pnl"],
            trades=trades,
        )
        pct_str = f"({return_pct}%)" if return_pct is not None else ""
        detail = (
            f"{fastest['holding_days']}일 만에 매도, "
            f"실현손익 {fastest['realized_pnl']:,.0f}원{pct_str}"
        )
        evidence.append(
            {
                "trade_id": fastest["episode_id"],  # TODO: trades 에서 실제 trade_id 역추적
                "date": str(fastest["opened_at"]),
                "name": fastest["name"],
                "detail": detail,
                **({"return_pct": return_pct} if return_pct is not None else {}),
            }
        )
    longest_loss_pool = pd.concat(
        [
            realized_losses,
            latest_open[latest_open["episode_id"].isin(unrealized_losses["episode_id"])],
        ]
        if not latest_open.empty
        else [realized_losses]
    )
    if not longest_loss_pool.empty:
        longest = longest_loss_pool.nlargest(1, "holding_days").iloc[0]
        # episodes 쪽 행엔 unrealized_pnl 컬럼 자체가 없어 concat 후 NaN이 된다 →
        # NaN이면 아직 미청산이 아니라 "청산된 행"이라는 뜻이므로 realized_pnl로 폴백.
        pnl_value = (
            longest["unrealized_pnl"]
            if pd.notna(longest.get("unrealized_pnl"))
            else longest["realized_pnl"]
        )
        date_value = (
            longest["opened_at"] if pd.notna(longest.get("opened_at")) else longest.get("date")
        )
        if pd.notna(longest.get("unrealized_pnl")):
            return_pct = round(float(longest["unrealized_pct"]) * 100, 2)
        else:
            return_pct = _closed_episode_return_pct(
                ticker=longest["ticker"],
                opened_at=longest["opened_at"],
                closed_at=longest["closed_at"],
                realized_pnl=longest["realized_pnl"],
                trades=trades,
            )
        pct_str = f"({return_pct}%)" if return_pct is not None else ""
        detail = f"{longest['holding_days']}일째 보유 중, 손익 {pnl_value:,.0f}원{pct_str}"
        evidence.append(
            {
                "trade_id": longest["episode_id"],  # TODO: trades 에서 실제 trade_id 역추적
                "date": str(date_value),
                "name": longest["name"],
                "detail": detail,
                **({"return_pct": return_pct} if return_pct is not None else {}),
            }
        )

    return MetricResult(key="disposition_effect", raw=raw, score_0_100=score, evidence=evidence)
