from __future__ import annotations

from datetime import date

import pandas as pd

from core.synth import prices as prices_module
from core.synth.prices import as_pairs, get_daily_close


def test_캐시가_구간을_전부_덮으면_그대로_반환한다(tmp_path, monkeypatch):
    monkeypatch.setattr(prices_module, "CACHE_DIR", tmp_path)

    idx = pd.date_range("2026-01-02", periods=5, freq="B")
    seeded = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0], index=idx, name="005930")
    seeded.to_frame().to_parquet(tmp_path / "005930.parquet")

    result = get_daily_close("005930", date(2026, 1, 2), date(2026, 1, 8))

    assert result.tolist() == [100.0, 101.0, 102.0, 103.0, 104.0]


def test_캐시_미스는_pykrx로_받아서_캐시에_쓴다(tmp_path, monkeypatch):
    monkeypatch.setattr(prices_module, "CACHE_DIR", tmp_path)

    fake_df = pd.DataFrame(
        {"종가": [200.0, 205.0, 198.0]},
        index=pd.to_datetime(["2026-02-02", "2026-02-03", "2026-02-04"]),
    )

    class _FakeStock:
        @staticmethod
        def get_market_ohlcv(start, end, ticker):
            assert ticker == "000660"
            return fake_df

    import sys
    import types

    fake_pykrx = types.ModuleType("pykrx")
    fake_pykrx.stock = _FakeStock
    monkeypatch.setitem(sys.modules, "pykrx", fake_pykrx)
    monkeypatch.setitem(sys.modules, "pykrx.stock", _FakeStock)

    result = get_daily_close("000660", date(2026, 2, 2), date(2026, 2, 4))
    assert result.tolist() == [200.0, 205.0, 198.0]

    cache_path = tmp_path / "000660.parquet"
    assert cache_path.exists()
    cached = pd.read_parquet(cache_path)
    assert cached.iloc[:, 0].tolist() == [200.0, 205.0, 198.0]


def test_as_pairs는_date와_float_튜플리스트로_바꾼다():
    idx = pd.to_datetime(["2026-03-02", "2026-03-03"])
    s = pd.Series([50_000.0, 51_000.0], index=idx, name="005930")

    pairs = as_pairs(s)

    assert pairs == [(date(2026, 3, 2), 50_000.0), (date(2026, 3, 3), 51_000.0)]
