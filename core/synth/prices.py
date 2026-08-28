"""실제 KRX 일봉 종가 — 합성 거래의 가격을 현실 시세에 묶는다.

synth 가 만드는 거래가 아무 가격이나 찍으면, 나중에 core/engine 이 실제 pykrx 종가로
평가손익을 계산할 때 페르소나가 의도한 편향 패턴(예: -5% 이하에서 물타기, 전일比 +5%
추격매수)이 어긋난다. 그래서 synth 도 처음부터 실제 종가를 갖고 그 위에서 매매 시점을
고른다 — synth 가 만드는 trades 와 engine 이 나중에 join 할 실제 종가가 항상 같은
숫자를 보게 하기 위함이다.

부수 효과: core/metrics/chasing.py 의 TODO("신규 진입 추격매수를 판정하려면 raw
시세가 있어야 하는데 schema 어디에도 없다 — A/B 에게 인터페이스 노출 요청")를 이
모듈이 충족한다. C 가 chasing.py 에 신규진입 판정을 추가하고 싶으면 get_daily_close()
를 그대로 가져다 쓰면 된다.

.gitignore 방침: data/cache/ 는 커밋한다(데모 당일 KRX 장애 대비). 데모용 유니버스를
한 번 캐시해두면 그 뒤로는 네트워크 없이도 동작한다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "prices"


def get_daily_close(ticker: str, start: date, end: date) -> pd.Series:
    """ticker 의 일별 종가(영업일만). index=Timestamp, name=ticker, 단위=원.

    캐시에 요청 구간이 전부 있으면 네트워크를 타지 않는다.
    """
    cache_path = CACHE_DIR / f"{ticker}.parquet"
    cached = _read_cache(cache_path)

    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    if cached is not None and cached.index.min() <= start_ts and cached.index.max() >= end_ts:
        return cached.loc[start_ts:end_ts]

    from pykrx import stock  # 캐시 hit 이면 이 임포트(+네트워크 계층)를 아예 안 탄다

    df = stock.get_market_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker)
    if df.empty:
        raise ValueError(
            f"{ticker}: pykrx 에서 {start}~{end} 시세를 못 받아왔다 (상장폐지/코드오류?)"
        )
    fetched = df["종가"].rename(ticker)
    fetched.index = pd.to_datetime(fetched.index)

    merged = fetched if cached is None else pd.concat([cached, fetched])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    _write_cache(cache_path, merged)
    return merged.loc[start_ts:end_ts]


def as_pairs(series: pd.Series) -> list[tuple[date, float]]:
    """generator.py 의 pandas-미사용 시뮬레이션 코어가 쓰는 (날짜, 종가) 리스트로 변환."""
    return [(ts.date(), float(v)) for ts, v in series.items()]


def _read_cache(path: Path) -> pd.Series | None:
    if not path.exists():
        return None
    return pd.read_parquet(path).iloc[:, 0]


def _write_cache(path: Path, series: pd.Series) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    series.to_frame().to_parquet(path)
