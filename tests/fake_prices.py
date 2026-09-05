"""테스트용 가짜 시세 조회기(PriceSource).

룰이 시세를 **콜러블 주입**으로 읽게 만든 이유가 여기 있다 — 실제 캐시/네트워크를
타지 않고도 "룰이 어떤 종목의 어떤 날짜 구간을 요청했는지"까지 검증할 수 있다.
룩어헤드 회귀 테스트(요청 구간의 끝이 판정 시점보다 뒤면 실패)의 핵심 도구.
"""

from __future__ import annotations

from datetime import date

import pandas as pd


class FakePriceSource:
    """{ticker: {날짜: 종가}} 로 만든 가짜 시세.

    calls 에 (ticker, start, end) 요청 이력을 남긴다.
    forbid_after 를 주면 그 날짜를 **초과**해 요청하는 순간 AssertionError 로 터진다 —
    "as_of 다음 날부터의 종가는 애초에 요청조차 하면 안 된다" 를 강제하는 장치다.
    (as_of 당일은 허용이다: 판정 시점이 as_of 보다 뒤라 그날 종가는 이미 공시됐다 —
    core/rules/base.reference_close docstring 참조.)
    """

    def __init__(
        self,
        closes: dict[str, dict[str, float]],
        *,
        forbid_after: date | None = None,
    ) -> None:
        self.series = {
            ticker: pd.Series(
                list(by_date.values()),
                index=pd.to_datetime(list(by_date.keys())),
                name=ticker,
            ).sort_index()
            for ticker, by_date in closes.items()
        }
        self.forbid_after = forbid_after
        self.calls: list[tuple[str, date, date]] = []

    def __call__(self, ticker: str, start: date, end: date) -> pd.Series:
        self.calls.append((ticker, start, end))
        if self.forbid_after is not None:
            assert end <= self.forbid_after, (
                f"룩어헤드: {ticker} 시세를 {end} 까지 요청했다 (허용 상한 {self.forbid_after})"
            )
        series = self.series.get(ticker)
        if series is None:
            # 캐시에도 없고 상장도 안 된 종목 — 실제 get_daily_close 와 같은 실패 모양
            raise ValueError(f"{ticker}: 시세를 못 받아왔다 (테스트 fake)")
        return series.loc[pd.Timestamp(start) : pd.Timestamp(end)]


class ExplodingPriceSource:
    """항상 실패하는 시세 조회기 — 네트워크 장애/미캐시 상황 재현용."""

    def __init__(self, message: str = "pykrx 연결 실패 (테스트 fake)") -> None:
        self.message = message
        self.calls: list[tuple[str, date, date]] = []

    def __call__(self, ticker: str, start: date, end: date) -> pd.Series:
        self.calls.append((ticker, start, end))
        raise ConnectionError(self.message)
