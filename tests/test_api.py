"""api/ 스모크 테스트 — 실제 HTTP 요청으로 엔드포인트가 진짜 응답하는지 확인.

DEMO_AS_OF 가 캐시 범위 안이라 네트워크 없이 재현된다.
"""

from __future__ import annotations

from datetime import date
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
        "warnings",
    }
    assert body["overallGrade"] in ("안정", "주의", "위험")
    assert {m["key"] for m in body["metrics"]} == {"disposition", "averaging_down", "chasing"}
    for m in body["metrics"]:
        assert 0.0 <= m["score"] <= 100.0
        assert 0.0 <= m["percentile"] <= 100.0
    # ANTHROPIC_API_KEY 없는 테스트 환경이므로 core/guard 폴백 템플릿 그대로 나와야 함
    assert body["headline"]
    assert body["body"]


def test_페르소나_진단은_경고가_비어있다():
    """합성 거래는 엔진이 트집 잡을 데가 없다 — 여기에 뭔가 뜨면 생성기 쪽 버그다."""
    for persona in ("disposition_prone", "chasing_prone", "mixed_realistic"):
        body = client.get("/api/diagnose", params={"persona": persona}).json()
        assert body["warnings"] == [], f"{persona}: {body['warnings']}"
    assert client.get("/api/backtest", params={"persona": "chasing_prone"}).json()["warnings"] == []


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
        "shouldIntervene",
        "baseScore",
        "contributions",
        "warning",
        "suggestions",
    }
    assert body["riskLevel"] in ("LOW", "MEDIUM", "HIGH")
    # 프론트가 riskLevel 로 개입 여부를 재유도하지 않도록 판정 결과를 그대로 싣는다.
    # 개입 조건이 "룰 하나라도 발동" 이라(core/rules/engine.py) 둘은 더 이상 동치가
    # 아니다 — 점수 임계는 OR 로 남아 있으므로 HIGH 면 반드시 개입이라는 방향만 성립한다.
    assert body["riskLevel"] != "HIGH" or body["shouldIntervene"] is True
    assert len(body["contributions"]) == 3
    assert len(body["suggestions"]) >= 1
    assert set(body["warning"].keys()) == {"headline", "caseCount", "averageReturn", "description"}
    assert isinstance(body["warning"]["averageReturn"], float)
    # 사례가 없으면(caseCount=0) 평균도 0 — 그 외엔 core/metrics 의 return_pct 평균이라
    # 어느 룰이 dominant 인지에 따라 부호가 갈리므로 여기서는 존재 여부만 확인한다
    if body["warning"]["caseCount"] == 0:
        assert body["warning"]["averageReturn"] == 0.0


def test_매도_주문도_판정된다():
    """SELL 은 처분효과 룰(core/rules/disposition_rule)이 받는다 — 400 이 되면 안 된다.

    처분효과 룰의 MAX_CONTRIBUTION 은 25 라 점수로는 개입 임계(50)를 못 넘지만,
    개입 조건이 "룰 하나라도 발동" 이라 평가이익 종목 매도는 개입 대상이 된다
    (예전에는 매도 주문에 개입이 구조적으로 불가능했다).
    """
    r = client.post(
        "/api/simulate-order",
        params={"persona": "disposition_prone"},
        json={
            "ticker": "005930",
            "name": "삼성전자",
            "side": "SELL",
            "quantity": 5,
            "price": 280000,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["order"]["side"] == "SELL"
    assert body["shouldIntervene"] is True
    assert body["riskScore"] < 50  # 점수 임계가 아니라 룰 발동으로 개입한 것이 맞는지
    detail = {c["label"]: c for c in body["contributions"]}["처분효과"]
    assert detail["value"] > 0


DEMO_PREFILL_ORDER = {
    "ticker": "005930",
    "name": "삼성전자",
    "side": "BUY",
    "quantity": 10,
    "price": 290000,  # 캐시된 실제 종가(268,500원) 대비 +8% → 추격매수 발동
}


def _holds_at_as_of(persona: str, ticker: str) -> bool:
    """DEMO_AS_OF 시점에 그 종목을 실제로 들고 있는가(= 열린 에피소드가 있는가)."""
    from core.engine.engine import build

    trades = service._persona_trades(persona)
    episodes = build(trades, as_of=service.DEMO_AS_OF).episodes
    rows = episodes[episodes["ticker"] == ticker]
    return bool(not rows.empty and rows["is_open"].any())


def test_점수가_낮아도_룰이_발동하면_개입한다():
    """데모 프리필 주문(web/src/lib/api.ts DEMO_ORDER)이 보유 중인 페르소나에서 팝업까지 간다.

    기여식이 "MAX_CONTRIBUTION × 과거 지표점수/100" 이라 합성 페르소나(한 축만 강함)는
    50점에 못 닿는다 — 그래도 개입은 떠야 한다(개입 조건 = 룰 하나라도 triggered).

    ⚠ 5종 전부가 아니라 "DEMO_AS_OF 에 005930 을 보유 중인 페르소나"만 뜬다. 추격매수
    룰은 직전 종가가 있어야 급등률을 계산하는데, 그 종가의 유일한 출처인 timeline 은
    보유 기간에만 존재하기 때문이다(core/rules/chasing_rule.py). 미보유 페르소나는
    몇 영업일 전에 청산한 옛 종가와 비교하는 대신 미판정으로 빠진다 — 예전에는 그
    stale 종가로 전원 발동해서 5종 전부 팝업이 떴다.
    """
    holders = [p for p in PRESETS if _holds_at_as_of(p, "005930")]
    # 데모 기본 페르소나(web DEMO_PERSONA)는 반드시 보유 중이어야 시연이 성립한다
    assert "chasing_prone" in holders

    for persona in holders:
        r = client.post("/api/simulate-order", params={"persona": persona}, json=DEMO_PREFILL_ORDER)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["shouldIntervene"] is True, persona
        assert body["riskScore"] < 50, persona  # 점수 임계였다면 안 떴을 주문


def test_미보유_종목_프리필_주문은_옛_종가로_발동하지_않는다():
    """청산한 지 여러 영업일 지난 종목은 "직전 종가"가 없어 추격매수 미판정.

    stale timeline 회귀 방어 — 룰 단위 검증은 tests/test_rules_chasing.py.
    """
    non_holders = [p for p in PRESETS if not _holds_at_as_of(p, "005930")]
    assert non_holders  # 데이터가 바뀌어 전원 보유가 되면 이 테스트는 의미가 없어진다

    for persona in non_holders:
        r = client.post("/api/simulate-order", params={"persona": persona}, json=DEMO_PREFILL_ORDER)
        assert r.status_code == 200, r.text
        body = r.json()
        # 미보유 + 마지막 종가가 MAX_STALE_BUSINESS_DAYS 를 넘긴 상태(현재 합성 데이터
        # 기준) → BUY 는 세 룰 모두 근거가 없어 개입 없음
        assert body["shouldIntervene"] is False, persona
        chasing = {c["label"]: c for c in body["contributions"]}["추격매수"]
        assert chasing["value"] == 0, persona


# ── 주문 유니버스 ────────────────────────────────────────────────────────────


def test_유니버스_페르소나():
    """페르소나 유니버스는 DEMO_UNIVERSE 그대로 + 종가는 DEMO_AS_OF 이하여야 한다."""
    r = client.get("/api/universe", params={"persona": "chasing_prone"})
    assert r.status_code == 200, r.text
    items = r.json()

    assert {i["ticker"] for i in items} == set(service.DEMO_UNIVERSE)
    for item in items:
        assert set(item.keys()) == {"ticker", "name", "lastClose", "lastDate"}
        assert item["name"] == service.DEMO_UNIVERSE[item["ticker"]]
        # 커밋된 시세 캐시가 DEMO_AS_OF 를 덮으므로 여기서는 종가가 반드시 나온다
        assert item["lastClose"] is not None and item["lastClose"] > 0
        # 룩어헤드 금지 — 기준일 다음 날 종가를 폼 기본값으로 흘리면 안 된다
        assert date.fromisoformat(item["lastDate"]) <= service.DEMO_AS_OF


def test_유니버스_세션(csv_session):
    """세션 유니버스는 그 사람이 실제 거래한 종목 + 종가는 마지막 체결일 이하."""
    r = client.get("/api/universe", params={"session": csv_session})
    assert r.status_code == 200, r.text
    items = r.json()
    assert items

    trades = service._SESSIONS[csv_session]
    assert {i["ticker"] for i in items} == {str(t) for t in trades["ticker"].dropna()}

    as_of = max(trades["traded_at"].dropna())
    for item in items:
        if item["lastDate"] is None:
            continue  # 캐시에 없는 종목은 시세 없이 null 로 나가는 게 정상이다
        assert date.fromisoformat(item["lastDate"]) <= as_of


def test_유니버스도_모르는_세션은_404():
    assert client.get("/api/universe", params={"session": "없는세션"}).status_code == 404
    assert client.get("/api/universe", params={"persona": "does_not_exist"}).status_code == 404


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
        "warnings",
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
