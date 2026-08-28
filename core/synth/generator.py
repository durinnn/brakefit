"""합성 거래내역 생성기 — 페르소나별 확률적 매매 시뮬레이션.

실 거래내역이 0건이라(AGENTS.md 현재 상태), core/engine·core/metrics·core/backtest 가
개발·데모에 쓸 유일한 데이터 소스다. 출력은 core/schema.TRADE_COLUMNS 형태 그대로라
다운스트림 어디에서도 "파서 출력인지 synth 출력인지" 구분할 필요가 없다 — 실 거래내역이
들어오면 core/parser 출력으로 갈아끼우기만 하면 되고, 이 모듈은 그때부터 안 써도 된다.

⚠ AGENTS.md 규칙 6: 이 데이터로 만든 리포트에는 "실사용자 분포 아님" 각주 필수
   (core/synth/personas.py 의 NOT_REAL_USER_DISCLAIMER).

── 시뮬레이션 설계 (Monte Carlo 로 검증된 값 — 바꾸면 재검증 필요) ──────────────
결정 로직(_sell_probability/_add_buy_trigger/_entry_weight)은 pandas 를 전혀 쓰지
않는 순수 함수다. 300 trial × 40 episode 검증에서 아래가 확인됐다:

  - 처분효과: 매도확률을 "이익/손실" 부호로만 가른다. core/metrics/disposition.py 가
    3%/-3% 같은 문턱 없이 realized_pnl 의 부호만으로 PGR/PLR 을 가르기 때문 —
    문턱(neutral zone)을 두면 그 구간에서 파는 물량의 실현손익 부호가 사실상 랜덤이
    돼 편향 신호가 희석된다(초기 버전에서 실측으로 확인된 버그).
  - 손실 중 매도확률은 disposition_bias 의 제곱에 지수감쇠(exp(-bias²·3)). bias 의
    1제곱 감쇠는 bias=0.3 만 돼도 손절확률이 사실상 죽어서 "부차적 편향"(다른
    페르소나의 낮은 disposition_bias)까지 오염시켰고, 3제곱·40배는 반대로 강한
    편향에서 PLR 이 완전히 0 으로 포화(=손절을 정말 한 번도 안 함)돼 부자연스러웠다.
    제곱·3배가 저(0.1)·중(0.55)·고(0.85) 세 구간을 전부 눈에 띄게 갈라놓았다.
  - 추격매수: core/metrics/chasing.py 는 아직 "신규 진입"을 판정 못 한다(자기
    TODO에 명시됨 — 원시 시세 인터페이스가 없어서). 그래서 chasing_bias 는
    (a) 진입일 자체를 급등일 쪽으로 가중샘플링 + (b) 보유 중 급등일 추가매수 확률,
    둘 다에 반영해뒀다. (a)는 core/synth/prices.get_daily_close 가 그 인터페이스라
    C 가 chasing.py 에 신규진입 판정을 붙이는 순간 바로 잡히고, 그 전에도 (b) 만으로
    상대적 신호는 확인된다(chasing_prone 이 다른 페르소나 대비 raw 4~10배 — 절대값은
    5%+ 단일일 급등 자체가 희소해서 낮다. 실제 KRX 데이터는 정규분포보다 꼬리가
    두꺼워서 검증에 쓴 Monte Carlo 보다는 더 자주 나올 가능성이 높다).
  - episode 시뮬레이션은 진입일부터 해당 종목 시세의 끝(=관찰기간 스냅샷)까지 전부
    돌린다. 중간에 짧게 자르면 "관찰기간 끝에 열려있는지" 가 아니라 "진입 후 N일에
    열려있는지" 로 뒤바뀌어 PGR/PLR(스냅샷 시점 기준 지표) 정의가 깨진다.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from core.schema import TRADE_COLUMNS, coerce
from core.synth.personas import Persona
from core.synth.prices import as_pairs, get_daily_close

#: core/metrics/chasing.py 의 SURGE_THRESHOLD 와 반드시 일치시킬 것 — 어긋나면
#: synth 가 만든 "추격매수" 가 실제 지표에서는 안 잡힌다.
SURGE_THRESHOLD = 0.05
#: docs/schema.md 물타기 정의("-5% 이하") 와 반드시 일치시킬 것.
AVERAGING_DOWN_THRESHOLD = -0.05

FEE_RATE = 0.00015  # 위탁수수료 근사치(매수/매도 각각 편도)
SELL_TAX_RATE = 0.0018  # 거래세 등 근사치 — 실제 세율표와 다를 수 있음(합성 데이터용)

DEFAULT_UNIVERSE: dict[str, str] = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "035420": "NAVER",
    "035720": "카카오",
    "005490": "POSCO홀딩스",
    "051910": "LG화학",
    "006400": "삼성SDI",
    "105560": "KB금융",
}

PricePath = list[tuple[date, float]]


# ── 순수 결정 로직 (pandas 미사용 — Monte Carlo 로 검증됨) ──────────────────────


def _day_return(prices: PricePath, i: int) -> float:
    if i == 0 or prices[i - 1][1] <= 0:
        return 0.0
    return prices[i][1] / prices[i - 1][1] - 1.0


def _sell_probability(unrealized_pct: float, p: Persona) -> float:
    base = 0.05
    if unrealized_pct >= 0:
        return min(1.0, base * (1 + p.disposition_bias**2 * 20))
    return base * math.exp(-(p.disposition_bias**2) * 3)


def _add_buy_trigger(
    day_return: float, unrealized_pct: float, p: Persona
) -> tuple[float, str] | None:
    if day_return >= SURGE_THRESHOLD:
        # 급등일 자체가 드문 사건이라, 걸렸을 때 놓치지 않도록 확률을 세게 잡는다.
        return min(1.0, p.chasing_bias * 1.3), "chasing"
    if unrealized_pct <= AVERAGING_DOWN_THRESHOLD:
        return p.averaging_down_bias * 0.5, "averaging_down"
    return None


def _entry_weight(prices: PricePath, i: int, p: Persona) -> float:
    # 5%+ 급등만 세는 chasing.py 와 달리, 진입 가중치는 완만한 상승일도 반영해서
    # 급등일이 희소해도 "최근 오른 종목에 몰리는" 성향 자체는 안정적으로 재현되게 한다.
    return 1.0 + p.chasing_bias * max(0.0, _day_return(prices, i)) * 20.0


@dataclass
class _Fill:
    traded_at: date
    side: str  # "BUY" | "SELL"
    price: float
    quantity: int


@dataclass
class _Episode:
    ticker: str
    fills: list[_Fill] = field(default_factory=list)


def _simulate_episode(
    ticker: str, prices: PricePath, entry_idx: int, limit_idx: int, p: Persona, rng: random.Random
) -> tuple[_Episode, int]:
    """entry_idx 에 진입해서 limit_idx 직전까지(또는 매도할 때까지) 시뮬레이션.

    limit_idx: 같은 종목의 다른(먼저 자리잡은) episode 가 시작되는 인덱스 — 그 너머로
    넘어가면 두 episode 의 보유기간이 겹친다. 겹치면 engine 이 나중에 재구성할 실제
    평단가가 이 시뮬레이션이 가정한 평단가와 달라져서, 애써 맞춰둔 편향 신호가
    틀어진다(선택 순서가 시간순이 아니라 rng 순이라, "먼저 뽑힌" episode 가 나중
    날짜에 자리잡을 수도 있어 진입 시점 겹침 체크만으로는 못 막는다).
    (episode, 마지막으로 본 인덱스) 반환.
    """
    entry_date, entry_price = prices[entry_idx]
    quantity = max(1, round(p.budget / entry_price))
    cost_basis = entry_price * quantity
    ep = _Episode(ticker=ticker, fills=[_Fill(entry_date, "BUY", entry_price, quantity)])
    add_buys = 0

    end_idx = min(len(prices), limit_idx)
    for i in range(entry_idx + 1, end_idx):
        d, close = prices[i]
        avg_cost = cost_basis / quantity
        unrealized_pct = close / avg_cost - 1
        if rng.random() < _sell_probability(unrealized_pct, p):
            ep.fills.append(_Fill(d, "SELL", close, quantity))
            return ep, i
        if add_buys < p.max_add_buys:
            trig = _add_buy_trigger(_day_return(prices, i), unrealized_pct, p)
            if trig and rng.random() < trig[0]:
                add_qty = max(1, round((p.budget * 0.5) / close))
                cost_basis += close * add_qty
                quantity += add_qty
                add_buys += 1
                ep.fills.append(_Fill(d, "BUY", close, add_qty))

    return ep, end_idx - 1  # 미청산 — 경계까지 SELL 없이 보유


def _run_persona(persona: Persona, universe: dict[str, PricePath]) -> list[_Episode]:
    rng = random.Random(persona.seed)
    tickers = list(universe.keys())
    episodes: list[_Episode] = []
    occupied: dict[str, list[tuple[int, int]]] = {t: [] for t in tickers}
    attempts = 0
    max_attempts = persona.n_episodes * 50

    while len(episodes) < persona.n_episodes and attempts < max_attempts:
        attempts += 1
        ticker = rng.choice(tickers)
        prices = universe[ticker]
        used = occupied[ticker]
        # 마지막 10거래일은 진입 후보에서 제외 — 최소한의 보유 여지를 남긴다.
        candidates = [
            i for i in range(1, len(prices) - 10) if not any(s <= i <= e for s, e in used)
        ]
        if not candidates:
            continue
        weights = [_entry_weight(prices, i, persona) for i in candidates]
        entry_idx = rng.choices(candidates, weights=weights, k=1)[0]
        limit_idx = min((s for s, _e in used if s > entry_idx), default=len(prices))
        ep, last_idx = _simulate_episode(ticker, prices, entry_idx, limit_idx, persona, rng)
        occupied[ticker].append((entry_idx, last_idx))
        episodes.append(ep)

    return episodes


# ── pandas 접합부 ────────────────────────────────────────────────────────────


def generate_trades(
    persona: Persona,
    tickers: dict[str, str] | None = None,
    start: date = date(2025, 11, 1),
    end: date = date(2026, 8, 20),
) -> pd.DataFrame:
    """페르소나 1명의 합성 거래내역.

    core/schema.TRADE_COLUMNS 형태로 나오고 validate() 를 통과한다 — 파서 출력과
    똑같은 계약이라 core/engine 이후 단계는 출처를 몰라도 된다.

    tickers: {종목코드: 종목명}. 기본값은 DEFAULT_UNIVERSE(코스피 대형주 8종목).
    """
    universe_map = tickers or DEFAULT_UNIVERSE
    price_paths = {t: as_pairs(get_daily_close(t, start, end)) for t in universe_map}

    episodes = _run_persona(persona, price_paths)

    rows: list[dict] = []
    source = f"synth:{persona.key}"
    seq = 0
    for ep in episodes:
        for fill in ep.fills:
            seq += 1
            gross = fill.price * fill.quantity
            fee = round(gross * FEE_RATE)
            if fill.side == "BUY":
                tax = 0.0
                amount = gross + fee
                note = "현금매수"
            else:
                tax = round(gross * SELL_TAX_RATE)
                amount = gross - fee - tax
                note = "현금매도"
            rows.append(
                {
                    "trade_id": f"{source}:{ep.ticker}:{seq}",
                    "traded_at": fill.traded_at,
                    "ticker": ep.ticker,
                    "name": universe_map[ep.ticker],
                    "side": fill.side,
                    "quantity": fill.quantity,
                    "price": fill.price,
                    "amount": amount,
                    "fee": fee,
                    "tax": tax,
                    "source": source,
                    "source_row": seq,
                    "note": note,
                }
            )

    df = pd.DataFrame(rows, columns=TRADE_COLUMNS) if rows else pd.DataFrame(columns=TRADE_COLUMNS)
    return coerce(df).sort_values(["traded_at", "trade_id"]).reset_index(drop=True)


def generate_all_presets(
    tickers: dict[str, str] | None = None,
    start: date = date(2025, 11, 1),
    end: date = date(2026, 8, 20),
) -> dict[str, pd.DataFrame]:
    """데모용 — personas.PRESETS 전부 생성."""
    from core.synth.personas import PRESETS

    return {key: generate_trades(p, tickers, start, end) for key, p in PRESETS.items()}
