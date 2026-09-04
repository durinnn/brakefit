"""api/ 스모크 테스트 — 실제 HTTP 요청으로 엔드포인트가 진짜 응답하는지 확인.

DEMO_AS_OF 가 캐시 범위 안이라 네트워크 없이 재현된다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import service
from api.main import app
from core.synth.personas import PRESETS

client = TestClient(app)

FIXTURE_CSV = Path(__file__).resolve().parents[1] / "fixtures" / "synth" / "chasing_prone.csv"


def test_헬스체크():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_페르소나_목록():
    r = client.get("/api/personas")
    assert r.status_code == 200
    keys = {p["key"] for p in r.json()}
    assert keys == {
        "rational_baseline",
        "disposition_prone",
        "averaging_down_prone",
        "chasing_prone",
        "mixed_realistic",
    }


def test_진단_엔드포인트는_camelCase_필드로_응답한다():
    r = client.get("/api/diagnose", params={"persona": "disposition_prone"})
    assert r.status_code == 200
    body = r.json()

    assert set(body.keys()) == {
        "periodLabel",
        "totalTrades",
        "overallScore",
        "overallGrade",
        "metrics",
        "generatedAt",
        "headline",
        "body",
    }
    assert body["overallGrade"] in ("안정", "주의", "위험")
    assert {m["key"] for m in body["metrics"]} == {"disposition", "averaging_down", "chasing"}
    for m in body["metrics"]:
        assert 0.0 <= m["score"] <= 100.0
        assert 0.0 <= m["percentile"] <= 100.0
    # ANTHROPIC_API_KEY 없는 테스트 환경이므로 core/guard 폴백 템플릿 그대로 나와야 함
    assert body["headline"]
    assert body["body"]


def test_모르는_페르소나는_404():
    r = client.get("/api/diagnose", params={"persona": "does_not_exist"})
    assert r.status_code == 404


def test_개입_엔드포인트():
    r = client.post(
        "/api/simulate-order",
        params={"persona": "averaging_down_prone"},
        json={"ticker": "005930", "name": "삼성전자", "side": "BUY", "quantity": 5, "price": 70000},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "order",
        "riskScore",
        "riskLevel",
        "baseScore",
        "contributions",
        "warning",
        "suggestions",
    }
    assert body["riskLevel"] in ("LOW", "MEDIUM", "HIGH")
    assert len(body["contributions"]) == 3
    assert len(body["suggestions"]) >= 1
    assert set(body["warning"].keys()) == {"headline", "caseCount", "averageReturn", "description"}
    assert isinstance(body["warning"]["averageReturn"], float)
    # 사례가 없으면(caseCount=0) 평균도 0 — 그 외엔 core/metrics 의 return_pct 평균이라
    # 어느 룰이 dominant 인지에 따라 부호가 갈리므로 여기서는 존재 여부만 확인한다
    if body["warning"]["caseCount"] == 0:
        assert body["warning"]["averageReturn"] == 0.0


def test_백테스트_엔드포인트():
    r = client.get("/api/backtest", params={"persona": "chasing_prone"})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "periodLabel",
        "interventionCount",
        "avoidedLoss",
        "missedGain",
        "netBenefit",
        "netBenefitRate",
        "hitRate",
        "cases",
    }
    for case in body["cases"]:
        assert case["biasKey"] in ("averaging_down", "chasing")


# ── 업로드 세션 ──────────────────────────────────────────────────────────────


def _upload(name: str, content: bytes, content_type: str = "text/csv"):
    return client.post("/api/upload", files={"file": (name, content, content_type)})


@pytest.fixture
def csv_session() -> str:
    """표준 거래내역 CSV(fixtures/synth)를 업로드해서 얻은 sessionId."""
    r = _upload("chasing_prone.csv", FIXTURE_CSV.read_bytes())
    assert r.status_code == 200, r.text
    return r.json()["sessionId"]


def test_표준_CSV_업로드는_세션을_발급한다():
    r = _upload("chasing_prone.csv", FIXTURE_CSV.read_bytes())
    assert r.status_code == 200, r.text
    body = r.json()

    assert set(body.keys()) == {
        "sessionId",
        "tradeCount",
        "skippedCount",
        "period",
        "warnings",
        "source",
    }
    assert body["source"] == "standard_csv"
    assert body["tradeCount"] > 0
    assert body["skippedCount"] == 0
    assert body["sessionId"]
    assert " ~ " in body["period"]


def test_세션으로_세_엔드포인트_전부_돈다(csv_session):
    d = client.get("/api/diagnose", params={"session": csv_session})
    assert d.status_code == 200, d.text
    assert d.json()["totalTrades"] > 0

    b = client.get("/api/backtest", params={"session": csv_session})
    assert b.status_code == 200, b.text

    s = client.post(
        "/api/simulate-order",
        params={"session": csv_session},
        json={"ticker": "035720", "name": "카카오", "side": "BUY", "quantity": 3, "price": 60000},
    )
    assert s.status_code == 200, s.text
    assert s.json()["riskLevel"] in ("LOW", "MEDIUM", "HIGH")


def test_세션은_페르소나와_다른_결과를_준다(csv_session):
    """session 이 주어지면 persona 는 무시된다 — 기간 라벨이 페르소나와 달라야 한다."""
    session_body = client.get("/api/diagnose", params={"session": csv_session}).json()
    persona_body = client.get("/api/diagnose", params={"persona": "mixed_realistic"}).json()
    assert session_body["periodLabel"] != persona_body["periodLabel"]


def test_KB_export_업로드(ledger_xlsx: Path):
    """conftest 의 KB 거래내역(예수금 원장) fixture 를 그대로 올려본다.

    이 화면에는 종목코드가 없어서 resolve_tickers() 가 붙는다 — 오프라인/장 마감
    등으로 역매핑이 실패해도 업로드 자체는 성공하고 경고로만 남아야 한다.
    """
    r = _upload(
        "kb_ledger_sample.xlsx",
        ledger_xlsx.read_bytes(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "kb_export"
    assert body["tradeCount"] == 5  # LEDGER_ROWS 의 매수 3건 + 매도 2건
    assert body["skippedCount"] > 0  # 입금·배당·합계 행은 버려진다


def test_모르는_세션은_404():
    assert client.get("/api/diagnose", params={"session": "없는세션"}).status_code == 404
    assert client.get("/api/backtest", params={"session": "없는세션"}).status_code == 404
    r = client.post(
        "/api/simulate-order",
        params={"session": "없는세션"},
        json={"ticker": "005930", "name": "삼성전자", "side": "BUY", "quantity": 1, "price": 70000},
    )
    assert r.status_code == 404


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("empty.csv", b""),
        ("whitespace.csv", b"   \n\n"),
        ("garbage.bin", b"\x00\x01\x02 not a spreadsheet \xff\xfe"),
        ("wrong_columns.csv", b"a,b,c\n1,2,3\n"),
    ],
)
def test_읽을_수_없는_파일은_400(name, content):
    r = _upload(name, content)
    assert r.status_code == 400, r.text
    assert r.json()["detail"]  # 사유가 한국어로 들어있어야 한다


def test_5MB_초과_업로드는_413():
    """무료 인스턴스(512MB) 보호 — 상한을 1바이트만 넘겨도 거절되어야 한다."""
    r = _upload("huge.csv", b"x" * (service.MAX_UPLOAD_BYTES + 1))
    assert r.status_code == 413, r.text
    assert "5MB" in r.json()["detail"]

    # 경계값: 정확히 상한이면 크기 검사는 통과하고, 내용이 거래내역이 아니라서 400 이 된다
    r = _upload("boundary.csv", b"x" * service.MAX_UPLOAD_BYTES)
    assert r.status_code == 400, r.text


def test_세션은_상한을_넘으면_오래된_것부터_밀린다():
    """세션 LRU — 상한+1 개를 올리면 가장 오래된 하나만 사라져야 한다."""
    tiny_csv = (
        "traded_at,ticker,name,side,quantity,price\n2026-08-10,005930,삼성전자,BUY,1,70000\n"
    ).encode()
    session_ids = []
    for _ in range(service.MAX_SESSIONS + 1):
        r = _upload("tiny.csv", tiny_csv)
        assert r.status_code == 200, r.text
        session_ids.append(r.json()["sessionId"])

    # 제일 먼저 올린 세션만 밀려나고(404), 최근 MAX_SESSIONS 개는 살아있어야 한다
    assert client.get("/api/diagnose", params={"session": session_ids[0]}).status_code == 404
    assert not service.has_session(session_ids[0])
    for sid in session_ids[1:]:
        assert service.has_session(sid), sid
    assert len(service._SESSIONS) == service.MAX_SESSIONS


def test_lifespan_이_기준선_캐시를_미리_채운다():
    """콜드스타트 후 첫 진단이 페르소나 5종 계산을 뒤집어쓰지 않도록 기동 시 워밍."""
    service._reference_cache = None
    try:
        with TestClient(app):  # with 로 열어야 lifespan 이 실행된다
            cache = service._reference_cache
            assert cache is not None
            assert set(cache) == {"disposition_effect", "averaging_down", "chasing"}
            assert all(len(v) == len(PRESETS) for v in cache.values())
    finally:
        # 다른 테스트가 쓰는 전역이라 원상복구까지가 이 테스트의 책임
        service._reference_cache = None


@pytest.mark.parametrize("persona", ["rational_baseline", "mixed_realistic"])
def test_세_엔드포인트_전부_같은_페르소나로_에러없이_돈다(persona):
    assert client.get("/api/diagnose", params={"persona": persona}).status_code == 200
    assert client.get("/api/backtest", params={"persona": persona}).status_code == 200
    r = client.post(
        "/api/simulate-order",
        params={"persona": persona},
        json={
            "ticker": "000660",
            "name": "SK하이닉스",
            "side": "BUY",
            "quantity": 1,
            "price": 200000,
        },
    )
    assert r.status_code == 200
