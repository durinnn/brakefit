"""브레이크 백테스트 — "적용했으면 어땠을까"의 수치 헤드라인.

⚠ test-d-backtest 브랜치의 초안이다. D 가 아직 이 폴더(core/backtest)에 손을
안 대서, 시간 압박 때문에 B 가 먼저 만들어봤다. D 가 다르게 설계하고 싶으면
그냥 갈아엎으면 된다 — dev/main 에는 안 올라가 있다.

── 뭘 계산하나 ──────────────────────────────────────────────────────────────
과거 매수 거래 하나하나에 대해 "그 순간 브레이크가 있었다면 개입했을까"를
재현하고, 실제로는 개입이 없었으니 그 매수가 나중에 어떻게 됐는지(이익/손실)를
붙여서 "개입했더라면 회피했을 손실" vs "개입했더라면 놓쳤을 이익" 을 계산한다.

**룩어헤드 금지(AGENTS.md 절대 규칙 1)를 지키는 방법**: 매수 거래 T 를 평가할 때
"T 이전에 체결된 거래만" 으로 engine 을 다시 돌려서 그 시점의 timeline/episodes/
metrics 를 만든다. T 이후 정보는 절대 안 섞는다. 거래 수만큼 engine.build() 를
반복 호출해서 느리지만(가격은 캐싱돼 있어서 실제로는 빠르다), 이게 제일 안전하다.

**처분효과(SELL) 는 v1 범위 밖이다.** 물타기/추격매수는 "안 샀으면" 이라는
깔끔한 반사실이 있는데, 처분효과는 "안 팔고 계속 들고 있었으면" 이라 그 이후
가격이 오를지 내릴지에 대한 별도 가정이 필요하다 — 다른 종류의 주장이라 v1 에서는
뺐다(범위를 늘리는 대신 줄이는 쪽을 우선한다 — AGENTS.md). 실제로도 세 룰의
MAX_CONTRIBUTION 합 100 중 물타기(35)+추격매수(40)=75 를 차지해서, 대부분의
위험 기여는 이미 커버된다.

**개별 매수 건의 impact 계산**: 그 매수로 산 수량이 나중에(청산됐으면 청산 시점,
아직 보유 중이면 as_of 시점) 어떤 가격이었는지를 봐서
    impact = -(그 매수 수량 × (나중 가격 − 그 매수 가격))
가격이 나중에 떨어졌으면 impact 는 양수(그 매수를 안 했으면 손실을 피함),
올랐으면 음수(안 했으면 이익을 놓침). "나중 가격"은 해당 episode 의 timeline
마지막 행의 종가로 근사한다(정확한 매도 체결가 대신 — 청산/미청산 양쪽에
같은 방식을 쓰기 위한 v1 단순화).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from core.engine.engine import build
from core.metrics import averaging_down, chasing, disposition
from core.rules import engine as rules_engine
from core.rules.base import ProposedOrder

# 이 두 룰만 v1 백테스트 대상 — 클래스 docstring 참조.
BACKTESTABLE_KEYS = ("averaging_down", "chasing")

METRIC_MODULES = (disposition, averaging_down, chasing)


@dataclass
class BlockedCase:
    traded_at: date
    ticker: str
    name: str
    impact: float  # 양수=회피한 손실, 음수=놓친 이익
    bias_key: str  # "averaging_down" | "chasing" (가장 크게 기여한 룰)
    trade_id: str


@dataclass
class BacktestResult:
    period_start: date | None
    period_end: date | None
    intervention_count: int
    avoided_loss: float
    missed_gain: float
    net_benefit: float
    net_benefit_rate: float  # net_benefit / 총매수원금 * 100
    hit_rate: float  # 0~100. avoided_loss 로 끝난 개입 비율
    cases: list[BlockedCase] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def report(self) -> str:
        lines = [
            f"개입 건수   : {self.intervention_count}건",
            f"회피한 손실 : {self.avoided_loss:,.0f}원",
            f"놓친 이익   : {self.missed_gain:,.0f}원",
            f"순효과      : {self.net_benefit:,.0f}원 (방어율 {self.net_benefit_rate:.1f}%)",
            f"적중률      : {self.hit_rate:.1f}%",
        ]
        if self.warnings:
            lines.append(f"경고        : {len(self.warnings)}건")
            lines.extend(f"  ! {w}" for w in self.warnings[:20])
        return "\n".join(lines)


def run(trades: pd.DataFrame, as_of: date | None = None) -> BacktestResult:
    """trades(§1) 전체를 받아 브레이크 백테스트를 돌린다."""
    from core.schema import validate

    problems = validate(trades)
    if problems:
        raise ValueError(f"trades 가 schema.validate() 를 통과 못 함: {problems}")

    if trades.empty:
        return BacktestResult(None, None, 0, 0.0, 0.0, 0.0, 0.0, 0.0)

    as_of = as_of or date.today()
    warnings: list[str] = []

    # "결과"를 알아야 하는 부분(각 매수의 나중 가격)은 딱 한 번, 전체 거래로 계산.
    # 이건 룩어헤드가 아니다 — "그 매수가 실제로 어떻게 됐는지" 는 백테스트 대상
    # 자체(이미 일어난 과거)를 평가하는 것이지, 판정 시점에 미래를 참조하는 게 아니다.
    final_result = build(trades, as_of=as_of)
    exit_price_by_episode = _last_close_by_episode(final_result.timeline)

    buys = trades[trades["side"] == "BUY"].sort_values(["traded_at", "source_row"])

    cases: list[BlockedCase] = []
    for _, t in buys.iterrows():
        prior_trades = trades[trades["traded_at"] < t["traded_at"]]
        # 판정 시점 = 이 매수 하루 전까지의 정보만. engine.as_of 도 그만큼만 채운다.
        cutoff = t["traded_at"] - timedelta(days=1)

        prior_result = build(prior_trades, as_of=cutoff) if not prior_trades.empty else None
        prior_timeline = (
            prior_result.timeline if prior_result else _empty_like(final_result.timeline)
        )
        prior_episodes = (
            prior_result.episodes if prior_result else _empty_like(final_result.episodes)
        )

        metric_results = [
            mod.compute(prior_timeline, prior_trades, prior_episodes) for mod in METRIC_MODULES
        ]

        order = ProposedOrder(
            ticker=t["ticker"],
            name=t["name"],
            side="BUY",
            quantity=int(t["quantity"]),
            price=float(t["price"]),
        )
        # as_of 는 판정 시점(cutoff) 그대로 — 룰이 "그 시점에 보유 중이었나 / 마지막
        # 종가가 그 시점 기준으로 최신인가"를 이걸로 판단한다. 미래는 여전히 안 넘어간다.
        report = rules_engine.evaluate(
            order, metric_results, prior_timeline, prior_episodes, cutoff
        )

        backtestable = [
            c for c in report.contributions if c.key in BACKTESTABLE_KEYS and c.triggered
        ]
        if not backtestable:
            continue

        episode_id = _find_episode_id(final_result.episodes, t["ticker"], t["traded_at"])
        if episode_id is None or episode_id not in exit_price_by_episode:
            warnings.append(f"{t['ticker']}: {t['traded_at']} 매수의 episode 를 못 찾음 — 건너뜀")
            continue

        exit_price = exit_price_by_episode[episode_id]
        impact = -(int(t["quantity"]) * (exit_price - float(t["price"])))
        dominant = max(backtestable, key=lambda c: c.score)

        cases.append(
            BlockedCase(
                traded_at=t["traded_at"],
                ticker=t["ticker"],
                name=t["name"],
                impact=impact,
                bias_key=dominant.key,
                trade_id=t["trade_id"],
            )
        )

    avoided_loss = sum(c.impact for c in cases if c.impact > 0)
    missed_gain = sum(-c.impact for c in cases if c.impact < 0)
    net_benefit = avoided_loss - missed_gain
    total_buy_amount = float(trades.loc[trades["side"] == "BUY", "amount"].sum())
    net_benefit_rate = (net_benefit / total_buy_amount * 100) if total_buy_amount else 0.0
    hit_rate = (sum(1 for c in cases if c.impact > 0) / len(cases) * 100) if cases else 0.0

    return BacktestResult(
        period_start=trades["traded_at"].min(),
        period_end=trades["traded_at"].max(),
        intervention_count=len(cases),
        avoided_loss=avoided_loss,
        missed_gain=missed_gain,
        net_benefit=net_benefit,
        net_benefit_rate=net_benefit_rate,
        hit_rate=hit_rate,
        cases=cases,
        warnings=warnings,
    )


def _last_close_by_episode(timeline: pd.DataFrame) -> dict[str, float]:
    if timeline.empty:
        return {}
    last = timeline.sort_values("date").groupby("episode_id", as_index=False).tail(1)
    return dict(zip(last["episode_id"], last["close"], strict=True))


def _find_episode_id(episodes: pd.DataFrame, ticker: str, traded_at: date) -> str | None:
    """이 매수가 속한 episode 를 opened_at<=traded_at<=(closed_at or 무한대) 로 찾는다."""
    candidates = episodes[episodes["ticker"] == ticker]
    for _, ep in candidates.iterrows():
        opened, closed = ep["opened_at"], ep["closed_at"]
        if opened <= traded_at and (closed is None or pd.isna(closed) or traded_at <= closed):
            return ep["episode_id"]
    return None


def _empty_like(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(columns=df.columns)
