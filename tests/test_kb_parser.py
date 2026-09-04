from __future__ import annotations

from datetime import date

import pytest

from core import schema
from core.parser import kb_hts
from core.parser.reader import UnreadableExport


def test_매매행만_뽑아낸다(ledger_xlsx):
    result = kb_hts.parse(ledger_xlsx)

    # fixture 8행 중 매매는 5건 (입금·배당·합계 제외)
    assert len(result.trades) == 5
    assert result.trades["side"].tolist() == ["BUY", "BUY", "SELL", "BUY", "SELL"]
    assert result.trades["name"].tolist() == [
        "삼성전자", "삼성전자", "삼성전자", "카카오", "카카오",
    ]


def test_스킵한_행은_사유와_함께_남는다(ledger_xlsx):
    result = kb_hts.parse(ledger_xlsx)
    reasons = " ".join(s.reason for s in result.skipped)

    assert len(result.skipped) == 3          # 입금 / 배당금 / 합계
    assert "입금" in reasons
    assert "배당" in reasons
    assert "합계" in reasons


def test_천단위_콤마와_날짜를_파싱한다(ledger_xlsx):
    first = kb_hts.parse(ledger_xlsx).trades.iloc[0]

    assert first["traded_at"] == date(2026, 8, 4)
    assert first["quantity"] == 10
    assert first["price"] == pytest.approx(72_500)
    assert first["amount"] == pytest.approx(725_120)


def test_수수료_세금은_0이_아니라_None이다(ledger_xlsx):
    """이 화면은 수수료를 안 준다. 0 으로 채우면 실현손익이 조용히 틀어진다."""
    result = kb_hts.parse(ledger_xlsx)

    assert result.trades["fee"].isna().all()
    assert result.trades["tax"].isna().all()
    assert any("제공하지 않습니다" in w for w in result.warnings)


def test_안내행이_붙어있어도_헤더를_찾는다(ledger_with_preamble_xlsx):
    """헤더 행 번호 하드코딩 금지 — 화면마다 안내 행 개수가 다르다."""
    result = kb_hts.parse(ledger_with_preamble_xlsx)
    assert len(result.trades) == 5


def test_빈_export는_터지지_않고_경고를_남긴다(empty_ledger_xlsx):
    result = kb_hts.parse(empty_ledger_xlsx)

    assert result.trades.empty
    assert list(result.trades.columns) == schema.TRADE_COLUMNS
    assert any("0건" in w for w in result.warnings)


def test_엉뚱한_화면이면_안내와_함께_실패한다(tmp_path):
    """잔고 화면을 넣으면 '이 파일 아니다' 라고 말해줘야 한다."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["구분", "계좌번호", "종목명", "평가손익", "잔고수량", "매입단가"])
    ws.append(["예수금", "000-000-000-00", "", 0, 0, 0])
    path = tmp_path / "balance.xlsx"
    wb.save(path)

    with pytest.raises(UnreadableExport, match="inspect_export"):
        kb_hts.parse(path)


def test_스키마_검증을_통과한다(ledger_xlsx):
    result = kb_hts.parse(ledger_xlsx)
    problems = schema.validate(result.trades)

    # 정산금액에 수수료가 반영된 걸 잡아내는 경고 1건은 정상 (fixture 가 그렇게 생겼다)
    assert all("수수료" in p for p in problems), problems


def test_trade_id는_유일하다(ledger_xlsx):
    trades = kb_hts.parse(ledger_xlsx).trades
    assert trades["trade_id"].is_unique


def test_리포트가_사람이_읽을_수_있게_나온다(ledger_xlsx):
    report = kb_hts.parse(ledger_xlsx).report()

    assert "거래 건수   : 5건" in report
    assert "2026-08-04 ~ 2026-08-20" in report
    assert "종목코드 미해결" in report


# ── 0330 실현손익 화면 ───────────────────────────────────────────────────────

PNL_MAPPING = "core/parser/mappings/kb_0330_realized_pnl.yaml"


def test_실현손익_화면은_수수료와_세금을_준다(realized_pnl_xlsx):
    result = kb_hts.parse(realized_pnl_xlsx, PNL_MAPPING)

    assert len(result.trades) == 2
    assert result.trades["fee"].tolist() == [385.0, 504.0]
    assert result.trades["tax"].tolist() == [1308.0, 1712.0]
    assert result.trades["fee"].notna().all()


def test_매매구분_컬럼으로_side를_판정한다(realized_pnl_xlsx):
    result = kb_hts.parse(realized_pnl_xlsx, PNL_MAPPING)
    assert result.trades["side"].tolist() == ["SELL", "SELL"]


def test_괄호는_음수로_읽는다(realized_pnl_xlsx):
    """실현손익 -49,216 이 '(49,216)' 으로 표기되는 경우."""
    from core.parser.kb_hts import parse_number

    fmt = {"strip_chars": [",", "%"], "parenthesis_is_negative": True}
    assert parse_number("(49,216)", fmt) == -49216.0
    assert parse_number("12,707", fmt) == 12707.0


def test_매도금액을_정산금액으로_쓴다(realized_pnl_xlsx):
    result = kb_hts.parse(realized_pnl_xlsx, PNL_MAPPING)
    assert result.trades.iloc[0]["amount"] == pytest.approx(594_400)


def test_안내문구_행은_버린다(realized_pnl_xlsx):
    result = kb_hts.parse(realized_pnl_xlsx, PNL_MAPPING)
    assert any("정상적으로 조회" in s.reason or "필수값" in s.reason
               for s in result.skipped)


# ── 0112 거래내역조회 · 2행 레코드 ───────────────────────────────────────────

TXN_MAPPING = "core/parser/mappings/kb_0112_transactions.yaml"


def test_두_행에_걸친_거래를_하나로_읽는다(transactions_xlsx):
    """1행=1레코드로 읽으면 단가·수수료가 통째로 날아간다."""
    result = kb_hts.parse(transactions_xlsx, TXN_MAPPING)

    assert len(result.trades) == 2                      # 입금 행 제외
    assert result.trades["price"].tolist() == [72_500.0, 74_300.0]
    assert result.trades["fee"].tolist() == [120.0, 98.0]


def test_흩어진_세금_컬럼을_합산한다(transactions_xlsx):
    """거래세 등 + 농특세/부가세 + 소득세 + 지방소득세 + 양도세 → tax 하나로."""
    sell = kb_hts.parse(transactions_xlsx, TXN_MAPPING).trades.iloc[1]

    assert sell["side"] == "SELL"
    assert sell["tax"] == pytest.approx(1_070 + 217)    # 매도만 세금이 붙는다


def test_정산금액을_쓴다_거래금액이_아니라(transactions_xlsx):
    """거래금액은 수수료·세금 반영 전, 정산금액이 실제 현금 흐름이다."""
    trades = kb_hts.parse(transactions_xlsx, TXN_MAPPING).trades

    assert trades.iloc[0]["amount"] == pytest.approx(725_120)   # 매수: 수수료 더해짐
    assert trades.iloc[1]["amount"] == pytest.approx(593_015)   # 매도: 수수료·세금 빠짐


def test_전자금융입금_행은_스킵된다(transactions_xlsx):
    result = kb_hts.parse(transactions_xlsx, TXN_MAPPING)
    assert any("입금" in s.reason for s in result.skipped)


def test_슬래시_날짜를_읽는다(transactions_xlsx):
    """실측 표기가 2026/08/27 (슬래시) 였다."""
    first = kb_hts.parse(transactions_xlsx, TXN_MAPPING).trades.iloc[0]
    assert first["traded_at"] == date(2026, 8, 4)


# ── 0377 종목코드 사전 ───────────────────────────────────────────────────────

def test_0377에서_종목코드_사전을_뽑는다(executions_xlsx):
    codes = kb_hts.build_ticker_map(executions_xlsx)
    assert codes == {"삼성전자": "005930", "카카오": "035720"}


def test_엑셀이_날린_앞자리_0을_복원한다(executions_xlsx):
    """35720 (숫자로 저장됨) → '035720'."""
    codes = kb_hts.build_ticker_map(executions_xlsx)
    assert codes["카카오"] == "035720"


def test_사전으로_종목코드를_채운다(transactions_xlsx, executions_xlsx):
    result = kb_hts.parse(transactions_xlsx, TXN_MAPPING)
    codes = kb_hts.build_ticker_map(executions_xlsx)

    trades, unresolved = kb_hts.resolve_tickers(result.trades, cache=codes,
                                                use_pykrx=False)
    assert trades["ticker"].tolist() == ["005930", "005930"]
    assert unresolved == []


@pytest.mark.parametrize("raw, expected", [
    ("005930", "005930"),
    (5930.0, "005930"),        # 엑셀이 숫자로 저장
    (35720, "035720"),
    ("035720.0", "035720"),    # 문자열 소수 표기
    ("", None),
    (None, None),
    ("1234567", None),         # 6자리 초과 → 종목코드 아님
])
def test_종목코드_정규화(raw, expected):
    assert kb_hts.normalize_ticker(raw) == expected
