from __future__ import annotations

import sys
import types
from datetime import date

import pandas as pd
import pytest

from core.synth import prices as prices_module
from core.synth.prices import as_pairs, get_daily_close


def _ban_pykrx(monkeypatch) -> None:
    """pykrx 를 임포트하는 순간 터지게 만든다 — '네트워크를 안 탄다'를 실제로 검증."""

    def _boom(*_args, **_kwargs):
        raise AssertionError("캐시 히트여야 하는데 pykrx 를 임포트했다")

    fake = types.ModuleType("pykrx")
    fake.__getattr__ = _boom
    monkeypatch.setitem(sys.modules, "pykrx", fake)


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


def test_주말_경계로_요청해도_캐시_히트다(tmp_path, monkeypatch):
    """P0 회귀: start 가 토요일이면 그날 종가는 존재할 수 없다.

    경계를 날짜 그대로 비교하던 시절엔 커밋된 캐시(첫 거래일 시작)가 매 요청마다
    미스 나서 요청당 pykrx 를 18번 때렸다.
    """
    monkeypatch.setattr(prices_module, "CACHE_DIR", tmp_path)
    _ban_pykrx(monkeypatch)

    idx = pd.date_range("2025-11-03", periods=5, freq="B")  # 월~금
    seeded = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx, name="005930")
    seeded.to_frame().to_parquet(tmp_path / "005930.parquet")

    # 2025-11-01 은 토요일, 2025-11-09 는 일요일 — 둘 다 캐시에 있을 수 없는 날짜
    result = get_daily_close("005930", date(2025, 11, 1), date(2025, 11, 9))

    assert result.tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_구간_바깥은_여전히_캐시_미스다(tmp_path, monkeypatch):
    """경계 굴리기가 '없는 데이터를 있다고 우기는' 데까지 번지면 안 된다."""
    monkeypatch.setattr(prices_module, "CACHE_DIR", tmp_path)

    idx = pd.date_range("2025-11-03", periods=5, freq="B")
    seeded = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx, name="005930")
    seeded.to_frame().to_parquet(tmp_path / "005930.parquet")

    calls: list[tuple] = []

    class _FakeStock:
        @staticmethod
        def get_market_ohlcv(start, end, ticker):
            calls.append((start, end, ticker))
            return pd.DataFrame({"종가": []}, index=pd.to_datetime([]))

    fake_pykrx = types.ModuleType("pykrx")
    fake_pykrx.stock = _FakeStock
    monkeypatch.setitem(sys.modules, "pykrx", fake_pykrx)

    with pytest.raises(ValueError):  # 캐시 뒤쪽으로 넘어간 구간 → fetch 시도
        get_daily_close("005930", date(2025, 11, 3), date(2025, 12, 1))
    assert calls, "캐시 범위 밖인데 네트워크를 안 탔다"


def test_캐시_쓰기는_원자적이다(tmp_path, monkeypatch):
    """to_parquet 이 중간에 죽어도 기존 캐시는 온전해야 한다 — 찢어진 parquet 금지."""
    monkeypatch.setattr(prices_module, "CACHE_DIR", tmp_path)

    path = tmp_path / "005930.parquet"
    idx = pd.date_range("2025-11-03", periods=3, freq="B")
    good = pd.Series([1.0, 2.0, 3.0], index=idx, name="005930")
    prices_module._write_cache(path, good)

    original = path.read_bytes()

    def _explode(self, *_a, **_kw):
        raise OSError("디스크가 죽었다")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _explode)
    with pytest.raises(OSError):
        prices_module._write_cache(path, good)

    assert path.read_bytes() == original  # 기존 파일 그대로
    assert not list(tmp_path.glob(".*tmp")), "임시파일이 남았다"


def test_as_pairs는_date와_float_튜플리스트로_바꾼다():
    idx = pd.to_datetime(["2026-03-02", "2026-03-03"])
    s = pd.Series([50_000.0, 51_000.0], index=idx, name="005930")

    pairs = as_pairs(s)

    assert pairs == [(date(2026, 3, 2), 50_000.0), (date(2026, 3, 3), 51_000.0)]
