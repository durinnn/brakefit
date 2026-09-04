"""fixtures/upload/*.csv 로 POST /api/upload 경로를 검증한다.

실 증권사 export 를 아직 못 구했으므로, 업로드 경로(표준 CSV / KB 화면 / 이상 데이터 /
깨진 헤더)를 **손으로 검산 가능한 목 데이터**로 대신 검증한다. fixture 값은 전부
지어낸 것이고(AGENTS.md 절대규칙 4), 기대값 근거는 각 테스트 주석에 적어뒀다.

네트워크를 타면 안 되는 지점이 두 군데다 — 둘 다 여기서 막는다.
  · pykrx 종목명→코드 역매핑: KB 화면에는 종목코드가 없어서 api.service._fill_tickers
    가 kb_hts.resolve_tickers() 를 부르고, 그게 pykrx 전종목 목록을 받아온다.
    → stub_ticker_lookup fixture 로 고정 사전을 주입한다.
  · pykrx 일별 종가: fixture 기간(2026-06-02 ~ 2026-08-13)과 종목(005930/035720/
    035420)을 data/cache/prices/*.parquet 캐시 범위(2025-11-03 ~ 2026-09-03) 안으로
    잡아둬서 get_daily_close() 가 캐시에서만 답한다.
Anthropic 호출도 없다 — no_anthropic_key fixture 로 키를 지워 core/guard 폴백 템플릿을
강제한다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from core.engine.engine import build as build_engine
from core.guard.templates import REPORT_FALLBACK
from core.parser import kb_hts

client = TestClient(app)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "upload"

#: KB 화면(0112)에는 종목코드가 없다. 실서비스는 pykrx 로 역매핑하지만 테스트에서는
#: 네트워크를 못 타므로 이 사전으로 대체한다. '가나다반도체' 를 일부러 빼서
#: "역매핑 실패 종목은 경고만 남기고 진단은 계속 돈다" 를 같이 검증한다.
NAME_TO_TICKER = {"삼성전자": "005930", "카카오": "035720", "NAVER": "035420"}


@pytest.fixture(autouse=True)
def no_anthropic_key(monkeypatch):
    """LLM 코칭은 폴백 템플릿으로 고정 — 테스트가 외부 API 에 의존하면 안 된다."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def stub_ticker_lookup(monkeypatch):
    """resolve_tickers() 의 pykrx 조회를 고정 사전으로 대체한다.

    api.service 는 `kb_hts.resolve_tickers` 를 호출 시점에 찾으므로 모듈 속성만
    갈아끼우면 된다. cache 를 넘기고 use_pykrx=False 로 부르면 나머지 로직
    (이미 코드가 붙은 행 보존 · unresolved 목록)은 실물 그대로 돌아간다.
    """
    real = kb_hts.resolve_tickers

    def offline_resolve(trades, *, cache=None, use_pykrx=True):
        return real(trades, cache={**NAME_TO_TICKER, **(cache or {})}, use_pykrx=False)

    monkeypatch.setattr(kb_hts, "resolve_tickers", offline_resolve)


def _upload(name: str):
    content = (FIXTURE_DIR / name).read_bytes()
    return client.post("/api/upload", files={"file": (name, content, "text/csv")})


def _diagnose(session_id: str):
    return client.get("/api/diagnose", params={"session": session_id})


def _assert_diagnosable(session_id: str) -> dict:
    """세션이 진단까지 끝까지 도는지 + 점수 필드가 채워지는지."""
    r = _diagnose(session_id)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["totalTrades"] > 0
    assert 0.0 <= body["overallScore"] <= 100.0
    assert body["overallGrade"] in ("안정", "주의", "위험")
    assert {m["key"] for m in body["metrics"]} == {"disposition", "averaging_down", "chasing"}
    for m in body["metrics"]:
        assert 0.0 <= m["score"] <= 100.0
        assert 0.0 <= m["percentile"] <= 100.0
    # ANTHROPIC_API_KEY 를 지웠으므로 core/guard 는 반드시 폴백 템플릿을 쓴다
    assert body["headline"] == REPORT_FALLBACK["headline"]
    assert body["body"] == REPORT_FALLBACK["body"]
    return body


def _session_trades(session_id: str):
    """세션에 실제로 저장된 표준 거래내역.

    fee=None 과 fee=0 의 구분(AGENTS.md 절대규칙 3)은 HTTP 응답에 안 실려서
    프로세스 메모리를 직접 본다. api/service.py 의 _SESSIONS 는 이 구분을
    지켜야 할 유일한 저장소다.
    """
    return service._SESSIONS[session_id]


# ── ① standard_basic.csv — 표준 스키마 정상 경로 ─────────────────────────────


def test_표준_CSV_는_전_행이_거래로_들어간다():
    r = _upload("standard_basic.csv")
    assert r.status_code == 200, r.text
    body = r.json()

    # fixture 는 데이터 12행뿐이고 버릴 행을 안 넣었다 (매수 7 / 매도 5)
    assert body["source"] == "standard_csv"
    assert body["tradeCount"] == 12
    assert body["skippedCount"] == 0
    assert body["warnings"] == []
    # 첫 체결 2026-06-02 ~ 마지막 체결 2026-08-13
    assert body["period"] == "2026.06.02 ~ 2026.08.13"


def test_표준_CSV_의_빈_수수료는_0이_아니라_None으로_남는다():
    """수수료를 안 주는 화면에서 온 행(5·12행)은 fee/tax 가 빈칸이다.

    여기서 0 으로 채워지면 매도 실현손익이 세금만큼 조용히 부풀려진다.
    """
    session_id = _upload("standard_basic.csv").json()["sessionId"]
    trades = _session_trades(session_id)

    # 12행 중 fee/tax 가 빈칸인 건 2행 (2026-07-02 NAVER 매수 · 2026-08-13 삼성전자 매도)
    assert int(trades["fee"].isna().sum()) == 2
    assert int(trades["tax"].isna().sum()) == 2
    # 나머지 10행은 실제 값이 있고, 매수 7건의 tax 는 '진짜 0원'이라 NaN 이 아니다
    assert (trades.loc[trades["fee"].notna(), "fee"] > 0).all()
    assert int((trades["tax"] == 0).sum()) == 6  # 매수 7건 중 fee/tax 빈칸인 1건 제외


def test_표준_CSV_세션은_진단까지_돈다():
    session_id = _upload("standard_basic.csv").json()["sessionId"]
    body = _assert_diagnosable(session_id)
    assert body["totalTrades"] == 12
    assert body["periodLabel"] == "2026.06.02 ~ 2026.08.13"


# ── ② kb_0112_sample.csv — KB 0112 화면 형식 ─────────────────────────────────


def test_KB_0112_형식은_KB_매핑으로_인식된다(stub_ticker_lookup):
    """2행 헤더 + 2행 레코드 구조를 그대로 재현했으므로 standard_csv 로 새면 안 된다."""
    r = _upload("kb_0112_sample.csv")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["source"] == "kb_export"
    # 레코드 14개 중 매매는 10건 (매수 6 / 매도 4),
    # 버려지는 4건 = 전자금융입금 · 배당금 · 전자금융출금 · "정상적으로 조회되었습니다."
    assert body["tradeCount"] == 10
    assert body["skippedCount"] == 4
    assert body["period"] == "2026.06.02 ~ 2026.08.13"


def test_KB_0112_은_종목코드가_없어_경고를_남긴다(stub_ticker_lookup):
    body = _upload("kb_0112_sample.csv").json()
    joined = " ".join(body["warnings"])

    # ① 화면 자체가 ticker 를 안 준다는 파서 경고
    assert "ticker" in joined and "제공하지 않습니다" in joined
    # ② 역매핑 사전에 없는 '가나다반도체' 만 미해결로 남는다 (나머지 3종목은 해결됨)
    assert "종목코드를 못 찾음" in joined
    assert "가나다반도체" in joined
    for resolved in NAME_TO_TICKER:
        assert f"{resolved} —" not in joined and f"{resolved}," not in joined


def test_KB_0112_은_수수료_세금을_준다(stub_ticker_lookup):
    """0112 는 수수료·세금 컬럼이 다 있는 화면이라 fee/tax 가 None 이면 안 된다."""
    session_id = _upload("kb_0112_sample.csv").json()["sessionId"]
    trades = _session_trades(session_id)

    assert trades["fee"].notna().all()
    assert trades["tax"].notna().all()
    # 매수 6건은 세금이 실제로 0원 / 매도 4건은 거래세 등 + 농특세 합산
    assert int((trades["tax"] == 0).sum()) == 6
    # 2026-07-28 삼성전자 12주 매도: 거래세 등 3,960 + 농특세 792 = 4,752
    sell = trades[(trades["side"] == "SELL") & (trades["traded_at"] == date(2026, 7, 28))].iloc[0]
    assert sell["tax"] == pytest.approx(4752.0)
    assert sell["fee"] == pytest.approx(396.0)


def test_KB_0112_세션은_진단까지_돈다(stub_ticker_lookup):
    session_id = _upload("kb_0112_sample.csv").json()["sessionId"]
    body = _assert_diagnosable(session_id)
    # 코드를 못 찾은 가나다반도체 1건도 세션에는 남아있다 (엔진이 계산에서만 뺀다)
    assert body["totalTrades"] == 10


def test_KB_0112_의_미해결_종목은_엔진에서만_빠진다(stub_ticker_lookup):
    session_id = _upload("kb_0112_sample.csv").json()["sessionId"]
    trades = _session_trades(session_id)

    assert int(trades["ticker"].isna().sum()) == 1  # 가나다반도체 매수 1건
    result = build_engine(trades, as_of=date(2026, 8, 13))
    assert any("ticker 미해결 1건" in w for w in result.warnings)
    assert set(result.episodes["ticker"]) == {"005930", "035720", "035420"}


# ── ③ standard_oversell.csv — 보유보다 많이 판 행 ────────────────────────────


def test_오버셀_행이_있어도_업로드는_성공한다():
    r = _upload("standard_oversell.csv")
    assert r.status_code == 200, r.text
    body = r.json()

    # 오버셀은 스키마 위반이 아니다 — 파서/스키마 단계에서는 정상 10건으로 통과한다
    assert body["tradeCount"] == 10
    assert body["skippedCount"] == 0
    assert body["warnings"] == []


def test_오버셀은_엔진이_경고하고_보유분까지만_계상한다():
    """2026-07-28 삼성전자: 보유 15주(10주 + 5주)인데 매도 20주로 찍혀 있다.

    손계산 — 매수 정산금액 3,605,541 + 1,550,233 = 5,155,774 (15주, 평단 343,718.27)
    매도대금은 수량 비율로 깎아서 4,391,420 x 15/20 = 3,293,565
    → 실현손익 3,293,565 - 5,155,774 = -1,862,209
    초과 5주를 그대로 믿었다면 없는 주식의 매도대금까지 손익에 섞였을 것이다.
    """
    session_id = _upload("standard_oversell.csv").json()["sessionId"]
    result = build_engine(_session_trades(session_id), as_of=date(2026, 8, 13))

    assert any("보유수량 15주인데 매도 20주" in w for w in result.warnings)
    first = result.episodes.set_index("episode_id").loc["005930:2026-06-02"]
    assert first["realized_pnl"] == pytest.approx(-1_862_209.0)
    assert not first["is_open"]
    # 오버셀 다음 매수(2026-08-04)는 새 episode 로 정상 이어진다 — 파이프라인이 멈추지 않는다
    assert "005930:2026-08-04" in set(result.episodes["episode_id"])


def test_오버셀_세션도_진단까지_돈다():
    session_id = _upload("standard_oversell.csv").json()["sessionId"]
    _assert_diagnosable(session_id)


# ── ④ broken_columns.csv — 헤더가 엉뚱한 파일 ────────────────────────────────


def test_헤더가_엉뚱하면_400과_한국어_사유():
    r = _upload("broken_columns.csv")
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]

    assert "거래내역을 읽지 못했습니다" in detail
    # KB 매핑 3종 + 표준 CSV, 총 4가지 시도 사유가 전부 들어있어야 진단이 가능하다
    for mapping in ("kb_transaction_ledger", "kb_0112_transactions", "kb_0330_realized_pnl"):
        assert mapping in detail
    assert "필수 컬럼 없음" in detail
    assert "docs/schema.md" in detail


def test_헤더가_엉뚱하면_세션이_안_생긴다():
    before = set(service._SESSIONS)
    _upload("broken_columns.csv")
    assert set(service._SESSIONS) == before
