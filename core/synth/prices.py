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

import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "prices"

#: 요청 경계(start/end)를 영업일로 굴릴 때 쓰는 오프셋. 휴장일(공휴일)까지는 모르지만
#: 주말은 안다 — 커밋된 캐시가 미스 나는 원인의 대부분이 주말 경계다.
_BDAY = pd.tseries.offsets.BusinessDay()


def get_daily_close(ticker: str, start: date, end: date) -> pd.Series:
    """ticker 의 일별 종가(영업일만). index=Timestamp, name=ticker, 단위=원.

    캐시에 요청 구간이 전부 있으면 네트워크를 타지 않는다.
    """
    cache_path = CACHE_DIR / f"{ticker}.parquet"
    cached = _read_cache(cache_path)

    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    if cached is not None and _covers(cached.index, start_ts, end_ts):
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


def _covers(index: pd.DatetimeIndex, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> bool:
    """캐시가 [start_ts, end_ts] 와 겹치는 '거래일'을 전부 갖고 있는가.

    경계를 날짜 그대로 비교하면 안 된다. start 가 토요일이면 그날 종가는 세상 어디에도
    없으므로 `index.min() <= start_ts` 는 영원히 False 고, 커밋해 둔 캐시가 매 요청마다
    미스 나서 pykrx 를 때린다(데모 당일 네트워크 의존 = P0). 그래서 요청 경계를 먼저
    영업일로 굴린 뒤(start 는 앞으로, end 는 뒤로) 캐시 범위와 비교한다.

    공휴일은 여기서 모른다 — 경계가 공휴일이면 "빠졌다"고 보고 네트워크를 탄다. 틀리는
    방향이 안전한 쪽(과다 fetch)이라 의도적으로 이 정도만 한다.
    """
    need_start = _BDAY.rollforward(start_ts)
    need_end = _BDAY.rollback(end_ts)
    if need_start > need_end:
        return True  # 구간 안에 영업일이 하나도 없다 — 받아올 것도 없다
    return index.min() <= need_start and index.max() >= need_end


def _read_cache(path: Path) -> pd.Series | None:
    if not path.exists():
        return None
    return pd.read_parquet(path).iloc[:, 0]


def _write_cache(path: Path, series: pd.Series) -> None:
    """임시파일에 쓴 뒤 os.replace 로 원자적 교체.

    제자리 덮어쓰기를 하면, 동기 def 로 선언된 FastAPI 엔드포인트가 스레드풀에서 병렬로
    도는 순간 다른 요청이 '쓰다 만' parquet 을 읽는다(실측: OSError "File too short").
    같은 디렉토리에 쓰는 게 중요하다 — os.replace 의 원자성은 동일 파일시스템 안에서만
    보장된다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # pid 만으로는 부족하다 — 같은 프로세스의 스레드 둘이 같은 ticker 를 쓰면 임시파일
    # 이름까지 겹쳐서 원자성이 무의미해진다. uuid 로 쓰는 주체마다 다른 파일을 준다.
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        series.to_frame().to_parquet(tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
