"""포지션 재구성 엔진 — trades(§1) 를 timeline(§2) · episodes(§3) 로 바꾼다.

docs/schema.md §6 의 결정을 그대로 구현한다(2026-08-31 확정 — A 가 B 에게 위임,
근거는 문서 쪽에 남아있다): §6.1 amount 기준 평단가 / §6.2 T+2 보정 없음 /
§6.3 동일일 다중체결 그대로 둠. 아래 각 지점에 "§6.N" 으로 표시해뒀다 — 나중에
실 거래내역으로 반증되면 문서부터 고치고 여기를 따라 고칠 것.

── 알고리즘 ──────────────────────────────────────────────────────────────
종목별로 독립적으로 하루씩 걸어간다(포지션은 종목마다 완전히 별개라서). 하루치
처리 순서:
  1. 그날 체결된 거래(§6.3: 동일일 여러 건이면 source_row 순서대로 전부 적용)
     - BUY: 진입(직전 수량 0) 이면 새 episode 시작, 아니면 추가매수(add_buy_count+=1).
       평단가는 §6.1 대로 amount(정산금액) 기준: avg_cost = 누적(BUY.amount) / 누적(수량)
       — fee/tax 를 따로 더할 필요가 없다. amount 자체가 이미 수수료 포함 금액이라서다.
     - SELL: 실현손익 = amount - avg_cost(그 매도 직전) × 수량. 평단가는 안 바뀐다(불변).
       전량 매도면 episode 청산.
  2. 그날 끝난 뒤 수량 > 0 이면 timeline 행 하나 기록(종가는 pykrx, 없으면 캐리포워드).
     수량 0 이면 행을 안 만든다(§2 규칙) — 그래서 "청산되는 날의 실현손익"은
     timeline 에는 안 뜨고 episodes.realized_pnl(누적) 에만 잡힌다. disposition
     지표는 episodes 기준이라 문제없지만, "일별 실현손익" 을 보는 곳이 생기면
     이 지점을 다시 봐야 한다.

거래정지 캐리포워드: "그 종목만 종가가 없는 날"을 알려면 시장 전체가 연 날인지가
필요하다. 이번 실행에 등장한 종목들 날짜의 합집합 + CALENDAR_ANCHOR_TICKER(초대형주,
사실상 매 거래일 거래됨) 를 항상 같이 섞어서 기준 달력으로 쓴다 — 종목이 1개뿐인
거래내역이어도 앵커 덕분에 거래정지를 구분할 수 있다. (초판에는 앵커가 없어서 종목
1개면 못 잡는 한계가 있었다 — 이후 추가.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from core.schema import EPISODE_COLUMNS, TIMELINE_COLUMNS, empty_episodes, empty_timeline, validate
from core.synth.prices import get_daily_close

#: 기준 달력 앵커 — 삼성전자. 사실상 매 개장일 거래되므로, 거래내역에 종목이 1개뿐이어도
#: "그날 시장이 열렸는지"를 이걸로 판단할 수 있다.
CALENDAR_ANCHOR_TICKER = "005930"


@dataclass
class EngineResult:
    timeline: pd.DataFrame
    episodes: pd.DataFrame
    warnings: list[str] = field(default_factory=list)

    def report(self) -> str:
        """사람이 읽는 요약 — core/parser 의 ParseResult.report() 와 같은 패턴."""
        lines = [
            f"타임라인    : {len(self.timeline)}행",
            f"episode     : {len(self.episodes)}건"
            + (
                f" (미청산 {int(self.episodes['is_open'].sum())}건)"
                if not self.episodes.empty
                else ""
            ),
        ]
        if not self.episodes.empty:
            lines.append(f"종목 수     : {self.episodes['ticker'].nunique()}개")
            total_realized = self.episodes["realized_pnl"].sum()
            lines.append(f"총 실현손익 : {total_realized:,.0f}원")
        if self.warnings:
            lines.append(f"경고        : {len(self.warnings)}건")
            for w in self.warnings[:20]:
                lines.append(f"  ! {w}")
            if len(self.warnings) > 20:
                lines.append(f"  ... 외 {len(self.warnings) - 20}개")
        return "\n".join(lines)


@dataclass
class _EpisodeState:
    episode_id: str
    ticker: str
    name: str
    opened_at: date
    opened_idx: int  # 이 종목 유효달력(캐리포워드 포함) 안에서의 진입일 위치
    quantity: int = 0
    cost_basis: float = 0.0  # 누적 BUY.amount (§6.1 제안 — 평단가의 분자)
    realized_pnl: float = 0.0
    max_unrealized_loss: float = 0.0
    max_unrealized_pct: float = 0.0
    add_buy_count: int = 0


def build(trades: pd.DataFrame, as_of: date | None = None) -> EngineResult:
    """trades(§1, 파서·synth 공통 출력) -> EngineResult(timeline, episodes, warnings).

    as_of: 타임라인을 어디까지 채울지. 기본값은 오늘 — 아직 안 판(is_open) 포지션도
    "지금" 기준 평가손익까지 보여준다.
    """
    problems = validate(trades)
    if problems:
        raise ValueError(f"trades 가 schema.validate() 를 통과 못 함: {problems}")

    if trades.empty:
        return EngineResult(timeline=empty_timeline(), episodes=empty_episodes(), warnings=[])

    as_of = as_of or date.today()
    warnings: list[str] = []

    # ticker 가 비어있는 행은 종목을 특정할 수 없어서 계산에서 빠진다(스키마상 정상 입력 —
    # 파서가 화면에서 종목코드를 못 읽으면 None 으로 두고 resolve_tickers() 가 채우는 구조).
    # 다만 조용히 사라지면 "왜 이 종목이 결과에 없지" 를 아무도 못 찾는다 — AGENTS.md
    # "예외는 삼키지 않는다" 에 따라 버린 건수와 추정 원인을 남긴다.
    unresolved = int(trades["ticker"].isna().sum())
    if unresolved:
        warnings.append(f"ticker 미해결 {unresolved}건 제외 (resolve_tickers() 미적용?)")

    tickers = sorted(trades["ticker"].dropna().unique())
    global_start = trades["traded_at"].min()

    # 거래정지 감지용 기준 달력 — 등장한 종목 + 앵커 종목의 pykrx 거래일 합집합.
    # 앵커를 안 섞으면 거래내역에 종목이 1개뿐일 때 "이 날이 거래정지인지 상장전인지
    # 시장이 원래 휴장인지" 구분할 기준이 없어서 캐리포워드가 아예 동작 안 했다.
    calendar_tickers = sorted({*tickers, CALENDAR_ANCHOR_TICKER})
    raw_prices: dict[str, dict[date, float]] = {}
    for ticker in calendar_tickers:
        series = get_daily_close(ticker, global_start, as_of)
        raw_prices[ticker] = {ts.date(): float(v) for ts, v in series.items()}
    # as_of 이후 날짜는 여기서 한 번 더 걸러낸다 — get_daily_close 가 실수로(또는
    # 캐시 오염으로) as_of 너머 데이터를 돌려줘도, 룩어헤드 금지(AGENTS.md 절대
    # 규칙 1)가 이 필터 하나로 보장된다. core/backtest 가 "그 거래 시점까지만"
    # 알 수 있는 상태를 재현하려고 as_of 를 과거로 좁혀 호출하는데, 그게 새는 순간
    # 백테스트 수치 전체가 미래를 훔쳐본 게 된다 — 만든 김에 방어선을 하나 더 둔다.
    full_calendar = sorted({d for prices in raw_prices.values() for d in prices if d <= as_of})

    timeline_rows: list[dict] = []
    episode_rows: list[dict] = []
    used_episode_ids: set[str] = set()

    for ticker in tickers:
        ticker_trades = trades[trades["ticker"] == ticker].sort_values(["traded_at", "source_row"])
        name = ticker_trades["name"].iloc[0]
        by_day: dict[date, pd.DataFrame] = dict(tuple(ticker_trades.groupby("traded_at")))

        calendar = _effective_calendar(raw_prices[ticker], full_calendar, warnings, ticker)
        if not calendar:
            warnings.append(f"{ticker}: pykrx 종가를 하나도 못 구해서 이 종목은 건너뜀")
            continue
        calendar_days = [d for d, _ in calendar]
        start_idx = _first_index_on_or_after(calendar_days, ticker_trades["traded_at"].min())

        ep: _EpisodeState | None = None
        for idx in range(start_idx, len(calendar)):
            day, close = calendar[idx]
            day_realized = 0.0

            if day in by_day:
                for _, t in by_day[day].iterrows():
                    if t["side"] == "BUY":
                        if ep is None:
                            ep = _EpisodeState(
                                episode_id=_unique_episode_id(f"{ticker}:{day}", used_episode_ids),
                                ticker=ticker,
                                name=name,
                                opened_at=day,
                                opened_idx=idx,
                            )
                        else:
                            ep.add_buy_count += 1
                        ep.quantity += int(t["quantity"])
                        ep.cost_basis += float(t["amount"])  # §6.1 제안
                    else:  # SELL
                        # 살아있는 ep 는 항상 quantity > 0 이다(아래 오버셀 클램프 때문에
                        # 수량이 음수로 내려갈 수 없고, 0 이 되는 순간 청산하고 ep=None).
                        # 그래서 여기 걸리는 건 "정말로 보유가 없는데 매도가 찍힌" 경우뿐.
                        if ep is None:
                            warnings.append(
                                f"{ticker}: {day} 보유 없이 매도 기록 — 데이터 이상, 건너뜀"
                            )
                            continue
                        avg_cost = ep.cost_basis / ep.quantity  # 이 매도 "직전" 평단가
                        raw_qty = int(t["quantity"])
                        sell_qty = min(raw_qty, ep.quantity)
                        # 오버셀 방어 — 보유수량보다 많이 판 기록(거래내역 일부 누락, 기간을
                        # 잘라 받은 export 등)을 그대로 믿으면 없는 수량까지 실현손익이
                        # 잡히고 cost_basis 가 음수가 된 채 폐기돼서 조용히 숫자가 틀어진다.
                        # 보유분까지만 계상하고 초과분은 버리되, 버린 사실을 반드시 남긴다.
                        if raw_qty > sell_qty:
                            warnings.append(
                                f"{ticker}: {day} 보유수량 {ep.quantity}주인데 매도 {raw_qty}주 — "
                                f"보유분 {sell_qty}주까지만 실현손익에 반영하고 "
                                f"초과 {raw_qty - sell_qty}주는 무시 (거래내역 누락 추정)"
                            )
                        # 정산금액도 반영한 수량 비율만큼만 인정한다 — 안 그러면 보유한 적
                        # 없는 주식의 매도대금까지 실현손익에 섞인다.
                        proceeds = float(t["amount"]) * sell_qty / raw_qty
                        piece = proceeds - avg_cost * sell_qty
                        ep.realized_pnl += piece
                        day_realized += piece
                        ep.cost_basis -= avg_cost * sell_qty
                        ep.quantity -= sell_qty
                        if ep.quantity == 0:
                            episode_rows.append(
                                _episode_row(ep, closed_at=day, idx=idx, is_open=False)
                            )
                            ep = None

            if ep is not None and ep.quantity > 0:
                avg_cost = ep.cost_basis / ep.quantity
                unrealized_pnl = (close - avg_cost) * ep.quantity
                unrealized_pct = close / avg_cost - 1
                ep.max_unrealized_loss = min(ep.max_unrealized_loss, unrealized_pnl)
                ep.max_unrealized_pct = min(ep.max_unrealized_pct, unrealized_pct)
                timeline_rows.append(
                    {
                        "date": day,
                        "ticker": ticker,
                        "name": name,
                        "quantity": ep.quantity,
                        "avg_cost": avg_cost,
                        "close": close,
                        "unrealized_pnl": unrealized_pnl,
                        "unrealized_pct": unrealized_pct,
                        "realized_pnl": day_realized,
                        "holding_days": idx - ep.opened_idx,
                        "episode_id": ep.episode_id,
                    }
                )

        if ep is not None and ep.quantity > 0:
            episode_rows.append(
                _episode_row(ep, closed_at=None, idx=len(calendar) - 1, is_open=True)
            )

    timeline = (
        pd.DataFrame(timeline_rows, columns=TIMELINE_COLUMNS) if timeline_rows else empty_timeline()
    )
    episodes = (
        pd.DataFrame(episode_rows, columns=EPISODE_COLUMNS) if episode_rows else empty_episodes()
    )
    return EngineResult(timeline=timeline, episodes=episodes, warnings=warnings)


def _episode_row(ep: _EpisodeState, closed_at: date | None, idx: int, is_open: bool) -> dict:
    return {
        "episode_id": ep.episode_id,
        "ticker": ep.ticker,
        "name": ep.name,
        "opened_at": ep.opened_at,
        "closed_at": closed_at,
        "realized_pnl": ep.realized_pnl,
        "max_unrealized_loss": ep.max_unrealized_loss,
        "max_unrealized_loss_pct": ep.max_unrealized_pct,
        "add_buy_count": ep.add_buy_count,
        "holding_days": idx - ep.opened_idx,
        "is_open": is_open,
    }


def _unique_episode_id(base: str, used: set[str]) -> str:
    """episode_id 를 유일하게 만든다 — 같은 (종목, 진입일) 이 두 번 나오면 "#2" 부터 붙인다.

    같은 날 전량청산하고 다시 들어가면 "{ticker}:{진입일}" 이 그대로 충돌한다(§6.3 이
    동일일 다중체결을 합치지 않기로 확정했으니 실제로 일어날 수 있는 시나리오다).
    충돌한 채 두면 timeline·episodes 의 episode_id 가 서로 다른 에피소드를 가리키면서
    같은 값이 돼서, 이걸 키로 groupby/isin 하는 core/metrics·core/backtest 가 두
    에피소드를 하나로 뭉갠다.

    첫 에피소드는 접미사 없이 docs/schema.md §2·§3 의 "{ticker}:{진입일}" 형식을 그대로
    유지한다. 하류(core/metrics, core/rules, core/backtest)는 episode_id 를 키로만 쓰고
    형식을 파싱하지 않는 걸 확인했으므로 접미사가 붙어도 안전하다.
    """
    if base not in used:
        used.add(base)
        return base
    n = 2
    while f"{base}#{n}" in used:
        n += 1
    used.add(f"{base}#{n}")
    return f"{base}#{n}"


def _effective_calendar(
    ticker_prices: dict[date, float],
    full_calendar: list[date],
    warnings: list[str],
    ticker: str,
) -> list[tuple[date, float]]:
    """ticker_prices 에 없는 날(=거래정지 추정)은 직전 종가로 캐리포워드."""
    result: list[tuple[date, float]] = []
    last_close: float | None = None
    for d in full_calendar:
        if d in ticker_prices:
            last_close = ticker_prices[d]
            result.append((d, last_close))
        elif last_close is not None:
            warnings.append(
                f"{ticker}: {d} 종가 없음(거래정지 추정) — "
                f"직전 종가 {last_close:,.0f}원으로 캐리포워드"
            )
            result.append((d, last_close))
        # else: 아직 이 종목 데이터가 시작 안 됨(상장 전 등) — 스킵
    return result


def _first_index_on_or_after(calendar_days: list[date], target: date) -> int:
    for i, d in enumerate(calendar_days):
        if d >= target:
            return i
    return len(calendar_days)
