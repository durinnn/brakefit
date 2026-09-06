"""기획서 §7.3 논증용 — 복합형 페르소나의 "놓친 이익"을 시장분 / 종목 초과분으로 분해.

── 왜 ──────────────────────────────────────────────────────────────────────
백테스트 순효과가 음수(−545,700원)인 이유를 "브레이크가 틀렸다"가 아니라 "이 기간
KRX 가 전반적 상승장이라 무엇을 샀든 올랐다(= 개입의 기회비용)"로 설명하려면,
놓친 이익 중 지수가 끌어올린 몫이 얼마인지를 숫자로 보여야 한다.

    놓친 이익 = 시장 기여분 + 종목 초과분
    시장 기여분 = 매수금액 × (매수일 → 평가 기준일) KOSPI 지수 수익률

── 무엇을 그대로 재사용하나 ─────────────────────────────────────────────────
거래 생성은 api.service._persona_trades(= generate_trades(PRESETS[...],
tickers=DEMO_UNIVERSE, end=DEMO_AS_OF)), 집계는 core.backtest.backtest.run 을
그대로 호출한다. 이 스크립트는 백테스트 숫자를 다시 계산하지 않는다 — 재현이
어긋나면(합계 avoidedLoss 7,000 / missedGain 552,700) 즉시 죽는다.

── 평가 기준일 정의 (임의로 정하지 않았다) ─────────────────────────────────
core/backtest/backtest.py 의 개별 매수 impact 는

    exit_price_by_episode = _last_close_by_episode(final_result.timeline)   # L114
    impact = -(int(t["quantity"]) * (exit_price - float(t["price"])))       # L168

이고, _last_close_by_episode 는 timeline 을 date 로 정렬해 episode 별 **마지막 행**의
종가를 쓴다(L203-207). 즉 평가 시점은 "N일 후"가 아니라 **그 매수가 속한 episode 의
timeline 마지막 날** — 청산된 episode 면 청산 직전 보유 마지막 영업일, 미청산이면
as_of(DEMO_AS_OF = 2026-08-18) 다. 지수 수익률도 매수일 → 그 날짜로 잡는다.
매수금액도 impact 와 같은 정의인 수량 × 단가를 쓴다(amount 아님 — impact 가 그렇다).

── KOSPI 지수 ──────────────────────────────────────────────────────────────
data/cache/index/1001.parquet 캐시가 구간을 덮으면 네트워크를 안 탄다
(core/synth/prices.py 의 캐시 유틸을 그대로 재사용 — 같은 parquet 형식).
캐시가 없으면 pykrx 로 받아서 같은 자리에 캐시한다. 둘 다 안 되면 사유를 찍고 종료.

실행:
    uv run python scripts/decompose_missed_gain.py
"""

from __future__ import annotations

import sys
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.service import DEMO_AS_OF, _persona_trades  # noqa: E402
from core.backtest import backtest as bt  # noqa: E402
from core.engine.engine import build as build_engine  # noqa: E402

# core/synth/prices.py 와 같은 캐시 형식(단일 컬럼 parquet)을 쓰므로 유틸을 그대로 쓴다.
# 비공개 이름이지만 여기서 복붙하면 "캐시 경계를 영업일로 굴린다" 같은 삽질 결과가
# 두 벌이 되어 갈라진다 — 재사용이 맞다.
from core.synth.prices import _covers, _read_cache, _write_cache  # noqa: E402

PERSONA_KEY = "mixed_realistic"
KOSPI_TICKER = "1001"
INDEX_CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache" / "index"

#: 재현 확인용 기대값(기획서 §7.3 에 실린 숫자). 어긋나면 호출 경로가 틀린 것이다.
EXPECTED = {"avoided_loss": 7_000.0, "missed_gain": 552_700.0, "net_benefit": -545_700.0}


# ── KOSPI 지수 종가 ──────────────────────────────────────────────────────────


def _fetch_kospi_pykrx(start: date, end: date) -> pd.Series:
    """1순위: pykrx 의 KRX 지수 API."""
    from pykrx import stock

    df = stock.get_index_ohlcv_by_date(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), KOSPI_TICKER, name_display=False
    )
    if df.empty:
        return pd.Series(dtype="float64")
    s = df["종가"].astype(float)
    s.index = pd.to_datetime(s.index)
    return s


def _fetch_kospi_naver(start: date, end: date) -> pd.Series:
    """2순위: pykrx 안의 네이버 차트 소스.

    ⚠ 왜 필요한가: 이 환경에서 KRX 지수 bld(MDCSTAT00301·전체지수기본정보)는 본문이
    'LOGOUT' 인 400 을 돌려줘서 pykrx 가 빈 DataFrame 을 준다(pykrx 의
    dataframe_empty_handler 가 예외를 삼킨다 — 그래서 "조용히 0행"으로 보인다).
    같은 pykrx 의 네이버 소스(fchart)는 같은 기간 지수를 정상으로 준다. 새 의존성을
    추가하지 않고 지수를 얻는 유일한 경로라 fallback 으로 둔다.

    pykrx.website.naver.wrap 을 그대로 못 쓰는 이유: 그쪽은 종가를 int64 로 캐스팅해서
    (개별종목 전용) 소수점 둘째 자리까지 있는 지수 값에서 깨진다. fetch 만 빌려 쓰고
    파싱은 여기서 한다.
    """
    from pykrx.website.naver.core import Sise

    # count 는 "오늘로부터 며칠치" — 달력일수는 영업일수보다 항상 크므로 여유분이다.
    count = (date.today() - start).days + 10
    xml = Sise().fetch("KOSPI", count)
    rows: list[tuple[pd.Timestamp, float]] = []
    for node in ET.fromstring(xml).iter(tag="item"):
        parts = str(node.get("data")).split("|")
        rows.append((pd.Timestamp(parts[0]), float(parts[4])))  # [날짜, 시, 고, 저, 종, 거래량]
    if not rows:
        return pd.Series(dtype="float64")
    s = pd.Series(dict(rows), name=KOSPI_TICKER).sort_index()
    return s.loc[pd.Timestamp(start) : pd.Timestamp(end)]


def load_kospi_close(start: date, end: date) -> pd.Series:
    """KOSPI 일별 종가. 캐시가 구간을 덮으면 네트워크를 타지 않는다."""
    cache_path = INDEX_CACHE_DIR / f"{KOSPI_TICKER}.parquet"
    cached = _read_cache(cache_path)
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    if cached is not None and _covers(cached.index, start_ts, end_ts):
        print(f"[지수] 캐시 사용: {cache_path}")
        return cached.loc[start_ts:end_ts]

    reasons: list[str] = []
    fetched = pd.Series(dtype="float64")
    for label, fetcher in (("pykrx KRX", _fetch_kospi_pykrx), ("pykrx 네이버", _fetch_kospi_naver)):
        try:
            fetched = fetcher(start, end)
        except Exception as exc:  # 사유를 삼키지 않는다(AGENTS.md)
            reasons.append(f"{label}: {type(exc).__name__}: {exc}")
            continue
        if not fetched.empty:
            print(f"[지수] {label} 조회 성공 ({len(fetched)}행) → 캐시에 기록")
            break
        reasons.append(f"{label}: 0행(빈 응답)")

    if fetched.empty:
        raise SystemExit(
            "KOSPI 지수를 가져오지 못했습니다. 캐시도 없고 네트워크 조회도 실패했습니다.\n"
            f"  캐시 경로: {cache_path} (존재: {cache_path.exists()})\n"
            + "".join(f"  - {r}\n" for r in reasons)
            + "  → 네트워크가 되는 환경에서 한 번 실행해 캐시를 만든 뒤 다시 돌리세요."
        )

    fetched = fetched.rename(KOSPI_TICKER)
    merged = fetched if cached is None else pd.concat([cached, fetched])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    _write_cache(cache_path, merged)
    return merged.loc[start_ts:end_ts]


# ── 백테스트 재현 + 평가 기준일 복원 ────────────────────────────────────────


def _last_row_by_episode(timeline: pd.DataFrame) -> dict[str, tuple[date, float]]:
    """episode 별 timeline 마지막 행 → (평가 기준일, 종가).

    backtest._last_close_by_episode(L203-207) 와 **같은 정렬·그룹 기준**이다. 거기서는
    종가만 돌려주는데 여기서는 그 행의 날짜가 필요해서 같은 방식으로 한 번 더 뽑는다.
    """
    last = timeline.sort_values("date").groupby("episode_id", as_index=False).tail(1)
    return {row["episode_id"]: (row["date"], float(row["close"])) for _, row in last.iterrows()}


def main() -> None:
    trades = _persona_trades(PERSONA_KEY)
    result = bt.run(trades, as_of=DEMO_AS_OF)

    print(f"[백테스트] 페르소나={PERSONA_KEY} as_of={DEMO_AS_OF}")
    print(result.report())
    actual = {
        "avoided_loss": result.avoided_loss,
        "missed_gain": result.missed_gain,
        "net_benefit": result.net_benefit,
    }
    if actual != EXPECTED:
        raise SystemExit(
            f"백테스트 재현 실패 — 기대 {EXPECTED} / 실제 {actual}. "
            "api.service 의 백테스트 호출 경로가 바뀌었는지 확인할 것."
        )
    print(f"[백테스트] 기대값 재현 확인 {EXPECTED}\n")

    # 평가 기준일은 "전체 거래로 한 번 빌드한 timeline"에서 나온다 — backtest.run 이
    # 내부에서 하는 것과 같은 호출(L113)이라 같은 결과가 나온다.
    final = build_engine(trades, as_of=DEMO_AS_OF)
    last_by_episode = _last_row_by_episode(final.timeline)
    trade_by_id = trades.set_index("trade_id")

    # 놓친 이익으로 집계된 건 = impact < 0 (backtest L183 과 같은 조건. -0.0 은
    # 파이썬에서 < 0 이 False 라 양쪽 어디에도 안 들어간다 — 그 정의를 그대로 따른다).
    missed_cases = [c for c in result.cases if c.impact < 0]

    span_start = min(c.traded_at for c in missed_cases)
    eval_dates = []
    rows = []
    for c in missed_cases:
        ep_id = bt._find_episode_id(final.episodes, c.ticker, c.traded_at)
        eval_date, _ = last_by_episode[ep_id]
        eval_dates.append(eval_date)
        t = trade_by_id.loc[c.trade_id]
        rows.append(
            {
                "traded_at": c.traded_at,
                "name": c.name,
                # impact 와 같은 정의(수량 × 단가). amount 를 쓰면 분모가 달라진다.
                "buy_amount": int(t["quantity"]) * float(t["price"]),
                "eval_date": eval_date,
                "missed_gain": -c.impact,
            }
        )

    kospi = load_kospi_close(span_start, max(eval_dates))

    def close_on(d: date) -> float:
        """그 날짜의 지수 종가. 휴장일이면 직전 영업일 종가(asof)."""
        v = kospi.asof(pd.Timestamp(d))
        if pd.isna(v):
            raise SystemExit(f"KOSPI 종가를 못 찾음: {d} (캐시 구간 밖)")
        return float(v)

    for r in rows:
        idx_ret = close_on(r["eval_date"]) / close_on(r["traded_at"]) - 1
        r["index_return"] = idx_ret
        r["market_part"] = r["buy_amount"] * idx_ret
        r["excess"] = r["missed_gain"] - r["market_part"]

    _print_table(rows)

    total_missed = sum(r["missed_gain"] for r in rows)
    total_market = sum(r["market_part"] for r in rows)
    total_excess = total_missed - total_market
    share = total_market / total_missed * 100 if total_missed else 0.0
    print(
        f"\n놓친 이익 {total_missed:,.0f}원 중 시장 상승분 약 {total_market:,.0f}원"
        f"({share:.1f}%), 종목 초과분 약 {total_excess:,.0f}원"
    )
    print("\n※ 합성 페르소나 결과이며 실사용자 분포가 아님 (AGENTS.md 절대 규칙 6)")


#: 표 컬럼 (제목, 폭, 정렬). 한글은 터미널에서 두 칸을 먹으므로 str.ljust 로는
#: 열이 안 맞는다 — _pad() 가 표시 폭 기준으로 채운다.
_COLUMNS = (
    ("매수일", 10, "<"),
    ("종목", 10, "<"),
    ("매수금액", 11, ">"),
    ("평가 기준일", 11, "<"),
    ("지수 수익률", 11, ">"),
    ("놓친 이익", 11, ">"),
    ("시장 기여분", 12, ">"),
    ("초과분", 11, ">"),
)
#: 열 사이 여백. 오른쪽 정렬 열이 폭을 꽉 채우면 다음 열과 붙어 읽히므로 필요하다.
_GUTTER = "  "
_TABLE_WIDTH = sum(w for _, w, _ in _COLUMNS) + len(_GUTTER) * (len(_COLUMNS) - 1)


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int, align: str) -> str:
    fill = " " * max(0, width - _display_width(text))
    return fill + text if align == ">" else text + fill


def _row(cells: list[str]) -> str:
    return _GUTTER.join(_pad(c, w, a) for c, (_, w, a) in zip(cells, _COLUMNS, strict=True))


def _print_table(rows: list[dict]) -> None:
    print(_row([title for title, _, _ in _COLUMNS]))
    print("-" * _TABLE_WIDTH)
    for r in rows:
        print(
            _row(
                [
                    r["traded_at"].isoformat(),
                    r["name"],
                    f"{r['buy_amount']:,.0f}",
                    r["eval_date"].isoformat(),
                    f"{r['index_return'] * 100:.2f}%",
                    f"{r['missed_gain']:,.0f}",
                    f"{r['market_part']:,.0f}",
                    f"{r['excess']:,.0f}",
                ]
            )
        )
    print("-" * _TABLE_WIDTH)
    print(
        _row(
            [
                "합계",
                "",
                f"{sum(r['buy_amount'] for r in rows):,.0f}",
                "",
                "",
                f"{sum(r['missed_gain'] for r in rows):,.0f}",
                f"{sum(r['market_part'] for r in rows):,.0f}",
                f"{sum(r['excess'] for r in rows):,.0f}",
            ]
        )
    )


if __name__ == "__main__":
    main()
