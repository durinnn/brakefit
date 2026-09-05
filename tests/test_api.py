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
        "dominantKey",
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

    ⚠ 페르소나가 chasing_prone 인 이유: 처분효과 룰은 **DEMO_AS_OF 에 그 종목을 실제로
    보유 중이고 평가이익일 때만** 발동한다. 예전엔 disposition_prone 을 썼는데, 그
    페르소나는 as_of 에 005930 을 안 들고 있는데도 청산된 옛 에피소드의 평가이익으로
    발동하고 있었다(stale — 이 PR 에서 고침).
    """
    r = client.post(
        "/api/simulate-order",
        params={"persona": "chasing_prone"},
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
    # 지배 편향을 서버가 정해서 내려준다 (프론트가 label 로 되짚지 않게)
    assert body["dominantKey"] == "disposition"


def test_미보유_종목_매도는_옛_평가이익으로_발동하지_않는다():
    """stale 회귀 — as_of 에 안 들고 있는 종목의 SELL 은 처분효과 미판정.

    실측(2026-09-05, DEMO_AS_OF=2026-08-18): 005930 을 보유 중인 페르소나는
    rational_baseline·chasing_prone 둘뿐이다. 나머지 셋은 예전엔 청산된 옛
    에피소드의 평가이익 때문에 전부 개입 판정을 받았다.
    """
    sell = {"ticker": "005930", "name": "삼성전자", "side": "SELL", "quantity": 5, "price": 280000}
    non_holders = [p for p in PRESETS if not _holds_at_as_of(p, "005930")]
    assert non_holders  # 데이터가 바뀌어 전원 보유가 되면 이 테스트는 의미가 없어진다

    for persona in non_holders:
        body = client.post("/api/simulate-order", params={"persona": persona}, json=sell).json()
        disposition = {c["label"]: c for c in body["contributions"]}["처분효과"]
        assert disposition["value"] == 0, persona
        assert body["shouldIntervene"] is False, persona
        assert body["dominantKey"] is None, persona


DEMO_PREFILL_ORDER = {
    "ticker": "005930",
    "name": "삼성전자",
    "side": "BUY",
    "quantity": 10,
    "price": 290000,
}

#: DEMO_AS_OF(2026-08-18) **당일** 종가. as_of 는 마지막 거래일이고 모의 주문은 그
#: 이후에 넣으므로, 08-18 종가는 주문 시점에 이미 공시된 값이다(하루 당겨서 08-14
#: 종가 274,500원을 쓰면 /api/universe 의 lastClose 와 어긋난다 — 08-17 은 광복절
#: 대체휴일이라 휴장).
#: 손계산: 290,000 / 268,500 − 1 = +8.01% ≥ SURGE_THRESHOLD(5%) → 추격매수 발동.
PREFILL_REFERENCE_CLOSE = 268_500
PREFILL_CHANGE_RATE = 8.01


def _holds_at_as_of(persona: str, ticker: str) -> bool:
    """DEMO_AS_OF 시점에 그 종목을 실제로 들고 있는가(= 열린 에피소드가 있는가)."""
    from core.engine.engine import build

    trades = service._persona_trades(persona)
    episodes = build(trades, as_of=service.DEMO_AS_OF).episodes
    rows = episodes[episodes["ticker"] == ticker]
    return bool(not rows.empty and rows["is_open"].any())


def test_점수가_낮아도_룰이_발동하면_개입한다():
    """데모 프리필 주문(web/src/lib/api.ts DEMO_ORDER)이 페르소나 **5종 전부**에서 팝업까지 간다.

    기여식이 "MAX_CONTRIBUTION × 과거 지표점수/100" 이라 합성 페르소나(한 축만 강함)는
    50점에 못 닿는다 — 그래도 개입은 떠야 한다(개입 조건 = 룰 하나라도 triggered).

    ⚠ 예전에는 보유 중인 2종(rational_baseline·chasing_prone)만 떴다. 추격매수 룰의
    기준 종가 출처가 timeline(=보유 기간에만 존재)이었기 때문이다. 이제 시세 캐시에서
    읽으므로 미보유 종목의 신규 진입 추격매수도 판정된다.
    """
    for persona in PRESETS:
        r = client.post("/api/simulate-order", params={"persona": persona}, json=DEMO_PREFILL_ORDER)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["shouldIntervene"] is True, persona
        assert body["riskScore"] < 50, persona  # 점수 임계였다면 안 떴을 주문
        # 전원 추격매수가 지배 편향 — 프리필 주문이 +5.65% 급등가라 이 룰이 먼저 잡는다
        assert body["dominantKey"] == "chasing", persona


def test_프리필_주문의_등락률은_as_of_당일_종가_기준이다():
    """표시용 changeRate · 추격매수 룰 · /api/universe 가 **같은 종가**를 본다.

    예전에는 changeRate 를 timeline 마지막 행의 close 로 계산해서, 미보유 종목이면
    0.0% 로 나가고 보유 중이어도 룰이 쓴 종가와 다른 값을 가리켰다. 그 다음엔 룰만
    as_of 당일을 빼서(274,500 · 08-14) 주문 폼의 기준 종가(268,500 · 08-18)와 하루
    어긋났다 — 지금은 core/rules/base.reference_close 하나로 통일돼 있다.
    """
    for persona in PRESETS:
        body = client.post(
            "/api/simulate-order", params={"persona": persona}, json=DEMO_PREFILL_ORDER
        ).json()
        assert body["order"]["changeRate"] == pytest.approx(PREFILL_CHANGE_RATE, abs=0.01), persona
        detail = {c["label"]: c for c in body["contributions"]}["추격매수"]["detail"]
        assert f"{PREFILL_REFERENCE_CLOSE:,}" in detail, persona

    # 주문 폼 기본값(/api/universe)도 같은 종가여야 한다 — 화면 두 곳이 다른 숫자를
    # 보여주면 사용자에겐 그냥 틀린 값이다
    items = client.get("/api/universe", params={"persona": "chasing_prone"}).json()
    samsung = next(i for i in items if i["ticker"] == "005930")
    assert samsung["lastClose"] == pytest.approx(PREFILL_REFERENCE_CLOSE)
    assert samsung["lastDate"] == service.DEMO_AS_OF.isoformat()


def test_미보유_종목_신규진입_추격매수도_판정된다():
    """PR 26 회귀 — 미보유 종목 BUY 가 "판정 불가"로 빠지면 안 된다."""
    non_holders = [p for p in PRESETS if not _holds_at_as_of(p, "005930")]
    assert non_holders  # 데이터가 바뀌어 전원 보유가 되면 이 테스트는 의미가 없어진다

    for persona in non_holders:
        body = client.post(
            "/api/simulate-order", params={"persona": persona}, json=DEMO_PREFILL_ORDER
        ).json()
        chasing = {c["label"]: c for c in body["contributions"]}["추격매수"]
        assert body["shouldIntervene"] is True, persona
        assert "기준 종가" in chasing["detail"], persona
        # 물타기는 보유가 없으면 성립하지 않는다 — 추격매수만 발동한 것이 맞는지
        assert {c["label"]: c for c in body["contributions"]}["물타기"]["value"] == 0, persona


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
