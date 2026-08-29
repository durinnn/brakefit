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
    ticker: str, prices: PricePath, entry_idx: int, p: Persona, rng: random.Random
) -> tuple[_Episode, int, bool]:
    """entry_idx 에 진입해서 매도할 때까지(또는 시세 끝까지) 시뮬레이션.

    (episode, 마지막으로 본 인덱스, 청산 여부) 반환. 청산 안 됐으면 그 종목은 관찰기간
    끝까지 계속 들고 있는 것 — docs/schema.md §3 의 episode 정의("청산 후 재진입하면
    새 episode")상, 청산이 안 된 채로는 같은 종목에 새 episode 가 생길 수 없다. 그래서
    끝까지 돌린다(중간에서 끊으면 그 뒤로 생기는 "새 episode" 가 사실은 이미 들고 있는
    포지션 위에 얹히는 추가매수인데 별개 진입인 것처럼 취급돼서, engine 이 나중에
    재구성할 평단가가 이 시뮬레이션이 가정한 것과 달라진다 — 실제 pykrx 데이터로
    fixture 를 구워보고서야 드러난 버그. 처음엔 "다음 episode 시작 전 최소 여유일"만
    두면 될 줄 알았는데, 그 여유일 안에 못 팔면 결국 같은 문제로 돌아갔다).
    """
    entry_date, entry_price = prices[entry_idx]
    quantity = max(1, round(p.budget / entry_price))
    cost_basis = entry_price * quantity
    ep = _Episode(ticker=ticker, fills=[_Fill(entry_date, "BUY", entry_price, quantity)])
    add_buys = 0

    for i in range(entry_idx + 1, len(prices)):
        d, close = prices[i]
        avg_cost = cost_basis / quantity
        unrealized_pct = close / avg_cost - 1
        if rng.random() < _sell_probability(unrealized_pct, p):
            ep.fills.append(_Fill(d, "SELL", close, quantity))
            return ep, i, True
        if add_buys < p.max_add_buys:
            trig = _add_buy_trigger(_day_return(prices, i), unrealized_pct, p)
            if trig and rng.random() < trig[0]:
                add_qty = max(1, round((p.budget * 0.5) / close))
                cost_basis += close * add_qty
                quantity += add_qty
                add_buys += 1
                ep.fills.append(_Fill(d, "BUY", close, add_qty))

    return ep, len(prices) - 1, False  # 미청산 — 관찰기간 끝까지 보유


#: 새 episode 를 시작하려면 시세 끝까지 최소 이만큼 거래일이 남아있어야 한다 — 순전히
#: 품질 문제다(며칠 못 굴려보고 바로 미청산 처리되는 episode 가 너무 잦으면 신호가
#: 희석된다). 겹침 방지는 frontier 설계 자체가 보장하므로 이 값은 작아도 안전하다.
MIN_HOLDING_ROOM = 3


def _run_persona(persona: Persona, universe: dict[str, PricePath]) -> list[_Episode]:
    rng = random.Random(persona.seed)
    tickers = list(universe.keys())
    episodes: list[_Episode] = []
    # ticker 별 "다음 episode 가 시작될 수 있는 가장 이른 인덱스" — 청산되면 그 다음
    # 날로, 미청산이면 시세 끝(=그 종목은 이제 더 못 받음)으로 전진한다. 과거 빈 구간을
    # 채워넣지 않는다 — 뒤에 이미 잡아둔 episode 와 겹칠 방법이 원천적으로 없어야
    # (선택 순서가 시간순이 아니라 rng 순이라) 겹침을 사후에 못 걸러내는 일이 없다.
    frontier: dict[str, int] = {t: 1 for t in tickers}
    attempts = 0
    max_attempts = persona.n_episodes * 50

    while len(episodes) < persona.n_episodes and attempts < max_attempts:
        attempts += 1
        ticker = rng.choice(tickers)
        prices = universe[ticker]
        start_from = frontier[ticker]
        last_candidate = len(prices) - 1 - MIN_HOLDING_ROOM
        if start_from > last_candidate:
            continue  # 이 종목은 이번 페르소나 시뮬레이션에서 더 못 받는다
        candidates = list(range(start_from, last_candidate + 1))
        weights = [_entry_weight(prices, i, persona) for i in candidates]
        entry_idx = rng.choices(candidates, weights=weights, k=1)[0]
        ep, last_idx, closed = _simulate_episode(ticker, prices, entry_idx, persona, rng)
        frontier[ticker] = last_idx + 1 if closed else len(prices)
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
