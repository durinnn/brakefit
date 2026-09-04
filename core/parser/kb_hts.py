"""KB증권 export → 표준 거래내역.

컬럼 매핑·판정 규칙은 전부 mappings/*.yaml 에 있다. 이 파일에는 로직만 있다.
KB가 화면을 바꾸거나 다른 화면을 쓰게 되면 **YAML만 고치면 된다.**

    from core.parser.kb_hts import parse

    result = parse("da03450000.xls")
    print(result.report())          # 검증 리포트를 눈으로 확인
    result.trades                   # 표준 거래내역 DataFrame
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yaml

from core import schema
from core.parser import reader
from core.parser.reader import UnreadableExport, is_blank, text, trim_right

MAPPING_DIR = Path(__file__).parent / "mappings"
DEFAULT_MAPPING = MAPPING_DIR / "kb_transaction_ledger.yaml"

#: 숫자로 파싱하면 안 되는 필드 (나머지는 전부 숫자 취급)
TEXT_FIELDS = frozenset({"name", "note", "side_text", "category", "ticker"})

#: 정산금액을 어디서 가져올지 — (매도용 필드, 매수용 필드) 후보를 순서대로 시도
AMOUNT_SOURCES = (("credit", "debit"), ("sell_amount", "buy_amount"))


def resolve_amount(row: dict, side: str) -> float | None:
    """화면마다 금액 컬럼 이름이 달라서 후보를 순서대로 뒤진다."""
    for sell_field, buy_field in AMOUNT_SOURCES:
        value = row.get(sell_field if side == "SELL" else buy_field)
        if value:
            return value
    if (value := row.get("amount")):
        return value
    # 마지막 수단: 단가 × 수량 (수수료·세금 미반영이므로 검증에서 걸릴 수 있음)
    if row.get("price") and row.get("quantity"):
        return row["price"] * row["quantity"]
    return None


# ── 값 파싱 ──────────────────────────────────────────────────────────────────

def parse_number(cell, fmt: dict) -> float | None:
    """'1,234' · '(1,234)' · '1234원' · 1234.0 → float"""
    if cell is None or (isinstance(cell, str) and not cell.strip()):
        return None
    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        return float(cell)

    s = str(cell).strip()
    negative = False
    if fmt.get("parenthesis_is_negative") and s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    for ch in fmt.get("strip_chars", []):
        s = s.replace(ch, "")
    if s.startswith("-"):
        negative, s = True, s[1:]
    if not s or not re.fullmatch(r"\d*\.?\d*", s):
        return None
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


def parse_date(cell, fmt: dict) -> date | None:
    """엑셀 날짜 셀 / 문자열 날짜 모두 처리."""
    if cell is None:
        return None
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell

    s = str(cell).strip()
    if not s:
        return None
    # '2026-08-27 14:03:11' 처럼 시각이 붙어 오면 날짜만
    s = s.split()[0]
    for pattern in fmt.get("date_formats", []):
        try:
            return datetime.strptime(s, pattern).date()
        except ValueError:
            continue
    # 마지막 시도: 구분자 제거 후 8자리
    digits = re.sub(r"\D", "", s)
    if len(digits) == 8:
        try:
            return datetime.strptime(digits, "%Y%m%d").date()
        except ValueError:
            pass
    return None


# ── 판정 ────────────────────────────────────────────────────────────────────

def decide_side(row: dict, rules: list[dict]) -> str | None:
    """YAML 의 side_rules 를 위에서부터 적용. 먼저 맞는 규칙이 이긴다.

    지원하는 조건:
      note_contains      — '내용' 텍스트에 이 단어가 있으면 (거래내역 원장 화면)
      side_text_contains — 매매구분 컬럼 값에 이 단어가 있으면 (실현손익/체결 화면)
      has_value          — 해당 필드에 0 아닌 값이 있으면 (폴백)
    """
    for rule in rules:
        cond = rule.get("when", {})
        if needles := cond.get("note_contains"):
            if any(n in (row.get("note") or "") for n in needles):
                return rule["side"]
        if needles := cond.get("side_text_contains"):
            if any(n in (row.get("side_text") or "") for n in needles):
                return rule["side"]
        if field := cond.get("has_value"):
            value = row.get(field)
            if value is not None and value != 0:
                return rule["side"]
    return None


def should_drop(row: dict, raw_text: str, filters: dict) -> str | None:
    """버려야 할 행이면 사유를, 아니면 None 을 돌려준다."""
    for needle in filters.get("drop_if_text_matches", []):
        if needle in raw_text:
            return f"데이터 행이 아님 ('{needle}')"

    note = row.get("note") or ""
    for needle in filters.get("drop_if_note_contains", []):
        if needle in note:
            # '주식매수' 처럼 매매 키워드가 함께 있으면 매매 행이다
            if any(k in note for k in ("매수", "매도", "매입", "매각")):
                continue
            return f"매매 행이 아님 (내용='{note}')"

    missing = [f for f in filters.get("drop_if_missing", []) if row.get(f) in (None, "", 0)]
    if missing:
        return f"필수값 없음: {', '.join(missing)}"
    return None


# ── 메인 ────────────────────────────────────────────────────────────────────

def parse(path: str | Path, mapping_path: str | Path = DEFAULT_MAPPING) -> schema.ParseResult:
    """KB export 파일 하나를 표준 거래내역으로 변환한다."""
    path = Path(path)
    mapping = yaml.safe_load(Path(mapping_path).read_text(encoding="utf-8"))

    fmt = mapping.get("formats", {})
    colmap: dict[str, str] = mapping["columns"]
    filters = mapping.get("row_filters", {})
    absent = mapping.get("absent_fields", [])

    sheets = reader.read_sheets(path)
    records: list[dict] = []
    skipped: list[schema.SkippedRow] = []
    warnings: list[str] = []

    if absent:
        warnings.append(
            f"이 화면({mapping['screen']})은 {', '.join(absent)} 을(를) 제공하지 않습니다 "
            "— 해당 필드는 None 입니다 (0 아님)"
        )

    header_rows: int = mapping.get("header_rows", 1)
    record_rows: int = mapping.get("record_rows", 1)
    tax_fields: list[str] = mapping.get("tax_fields", ["tax"])

    parsed_any_sheet = False
    for sheet_name, rows in sheets.items():
        rows = [trim_right(r) for r in rows]
        if not rows:
            continue
        try:
            header_idx = reader.find_header_row(rows, mapping["header_anchors"])
        except UnreadableExport:
            continue  # 이 시트는 해당 화면이 아님
        parsed_any_sheet = True

        # 헤더가 여러 행에 걸쳐 있으면 (행오프셋, 열인덱스) 로 위치를 잡는다.
        # 0112 거래내역조회가 그렇다 — 1행에 거래일자/수량/거래금액,
        # 2행에 종목명/단가/수수료 가 각각 같은 열 아래 쌓여 있다.
        positions: dict[str, tuple[int, int]] = {}
        for row_offset in range(header_rows):
            line = rows[header_idx + row_offset] if header_idx + row_offset < len(rows) else []
            for col, label in enumerate(text(c) for c in line):
                if (field := colmap.get(label)) is not None:
                    positions.setdefault(field, (row_offset, col))

        unmapped = [f for f in colmap.values() if f not in positions]
        if unmapped:
            warnings.append(
                f"시트 '{sheet_name}' 에서 매핑하지 못한 컬럼: {unmapped} "
                "— YAML 의 columns 를 실제 헤더와 대조하세요 "
                "(python tools/inspect_export.py <파일> 로 실제 헤더 확인)"
            )

        body = rows[header_idx + header_rows:]
        for start in range(0, len(body), record_rows):
            block = body[start:start + record_rows]
            offset = header_idx + header_rows + start
            if all(is_blank(c) for line in block for c in line):
                continue
            raw_text = " ".join(text(c) for line in block for c in line)

            def cell(field: str, _block=block):
                pos = positions.get(field)
                if pos is None:
                    return None
                row_offset, col = pos
                if row_offset >= len(_block) or col >= len(_block[row_offset]):
                    return None
                return _block[row_offset][col]

            row: dict = {"traded_at": parse_date(cell("traded_at"), fmt)}
            for field in positions:
                if field == "traded_at":
                    continue
                row[field] = (text(cell(field)) if field in TEXT_FIELDS
                              else parse_number(cell(field), fmt))
            row.setdefault("note", "")
            row.setdefault("name", "")

            if (reason := should_drop(row, raw_text, filters)) is not None:
                skipped.append(schema.SkippedRow(offset, reason, raw_text[:70]))
                continue

            side = decide_side(row, mapping.get("side_rules", []))
            if side is None:
                note = row.get("note") or row.get("side_text") or ""
                skipped.append(
                    schema.SkippedRow(offset, f"매수/매도 판정 실패 (구분='{note}')", raw_text[:70])
                )
                continue
            if row["traded_at"] is None:
                skipped.append(
                    schema.SkippedRow(offset, f"날짜 파싱 실패 ('{text(cell('traded_at'))}')",
                                      raw_text[:70])
                )
                continue

            # 세금이 여러 컬럼에 흩어져 있으면 (거래세 + 농특세 + 소득세 …) 합산한다.
            # 하나도 없으면 None 을 유지한다 — 0 과 구분해야 한다.
            tax_values = [row.get(f) for f in tax_fields if row.get(f) is not None]
            tax = sum(tax_values) if tax_values else None

            amount = resolve_amount(row, side)
            records.append({
                "trade_id": f"{path.stem}:{sheet_name}:{offset}",
                "traded_at": row["traded_at"],
                "ticker": row.get("ticker") or None,
                "name": row["name"],
                "side": side,
                "quantity": abs(row["quantity"]) if row.get("quantity") else None,
                "price": row.get("price"),
                "amount": abs(amount) if amount else None,
                "fee": row.get("fee"),      # 화면이 안 주면 None (0 아님)
                "tax": tax,
                "source": path.name,
                "source_row": offset,
                "note": row.get("note") or row.get("side_text") or "",
            })

    if not parsed_any_sheet:
        raise UnreadableExport(
            f"{path.name} 에서 '{mapping['screen']}' 형태의 표를 찾지 못했습니다.\n"
            f"앵커={mapping['header_anchors']}\n"
            f"→ python tools/inspect_export.py {path} 로 실제 구조를 확인하고 "
            f"YAML 의 header_anchors/columns 를 고치세요."
        )

    trades = schema.coerce(pd.DataFrame(records)) if records else schema.empty_trades()
    trades = trades.sort_values(["traded_at", "source_row"]).reset_index(drop=True)

    if trades.empty:
        warnings.append(
            "거래 행이 0건입니다. 조회 기간을 계좌개설일까지 넓혀서 다시 export 하거나, "
            "스킵 사유 목록을 보고 row_filters 가 과하지 않은지 확인하세요."
        )

    return schema.ParseResult(trades=trades, skipped=skipped,
                              warnings=warnings, source=path.name)


def build_ticker_map(path: str | Path) -> dict[str, str]:
    """0377 종목별주문/체결집계 export 에서 {종목명: 종목코드} 사전을 뽑는다.

    0112 거래내역에는 종목코드가 없다. pykrx 로 역매핑할 수도 있지만
    사명 변경·우선주·상장폐지 종목에서 깨진다. 0377 은 **거래 당시 이름과 코드가
    같은 행에 있으므로** 그 문제가 없다 — 매매한 날짜별로 뽑아 합치면
    이 계좌에 필요한 코드 사전이 완성된다.

        codes = {}
        for f in Path("data/raw").glob("0377_*.xls"):
            codes |= build_ticker_map(f)
        trades, unresolved = resolve_tickers(trades, cache=codes, use_pykrx=False)
    """
    mapping = yaml.safe_load(
        (MAPPING_DIR / "kb_0377_executions.yaml").read_text(encoding="utf-8"))
    colmap: dict[str, str] = mapping["columns"]

    result: dict[str, str] = {}
    for rows in reader.read_sheets(Path(path)).values():
        rows = [trim_right(r) for r in rows]
        if not rows:
            continue
        try:
            header_idx = reader.find_header_row(rows, mapping["header_anchors"])
        except UnreadableExport:
            continue
        positions = {colmap[label]: col
                     for col, label in enumerate(text(c) for c in rows[header_idx])
                     if label in colmap}
        name_col, code_col = positions.get("name"), positions.get("ticker")
        if name_col is None or code_col is None:
            continue

        for raw in rows[header_idx + 1:]:
            if name_col >= len(raw) or code_col >= len(raw):
                continue
            name, code = text(raw[name_col]), normalize_ticker(raw[code_col])
            if name and code:
                result[name] = code
    return result


def normalize_ticker(cell) -> str | None:
    """종목번호 셀 → 6자리 문자열.

    ⚠ 엑셀이 '035720' 을 숫자 35720 으로 저장해버리는 일이 흔하다. 그러면
    셀 값이 float 35720.0 으로 읽히는데, 여기서 소수점만 지우면 '357200' 이라는
    엉뚱한 코드가 나온다 (다른 회사 코드일 수도 있어서 조용히 틀리는 유형).
    반드시 정수로 만든 뒤에 앞자리 0 을 채운다.
    """
    if cell is None:
        return None
    if isinstance(cell, float) and cell.is_integer():
        cell = int(cell)
    if isinstance(cell, int) and not isinstance(cell, bool):
        digits = str(cell)
    else:
        s = str(cell).strip()
        # '035720.0' 처럼 문자열로 들어온 소수 표기도 정수부만 취한다
        digits = re.sub(r"\D", "", s.split(".")[0])
    return digits.zfill(6) if digits and len(digits) <= 6 else None


def resolve_tickers(trades: pd.DataFrame, *, cache: dict[str, str] | None = None,
                    use_pykrx: bool = True) -> tuple[pd.DataFrame, list[str]]:
    """종목명 → 종목코드 역매핑.

    거래내역 화면에 종목코드가 없어서 필요한 단계다. 완벽하지 않다:
      · 사명이 바뀐 종목 (거래 당시 이름 ≠ 현재 이름)
      · 우선주 표기 흔들림 ('삼성전자우' vs '삼성전자 1우B')
      · 상장폐지 종목은 아예 안 나옴
    해결 못 한 건 ticker=None 으로 남고 목록으로 돌려준다 — 그 종목은 엔진에서 제외된다.
    """
    trades = trades.copy()
    cache = dict(cache or {})
    unresolved: list[str] = []

    names = [n for n in trades["name"].dropna().unique() if n not in cache]
    if names and use_pykrx:
        try:
            from pykrx import stock

            today = datetime.now().strftime("%Y%m%d")
            lookup: dict[str, str] = {}
            for market in ("KOSPI", "KOSDAQ"):
                for ticker in stock.get_market_ticker_list(today, market=market):
                    lookup[stock.get_market_ticker_name(ticker)] = ticker
            for name in names:
                if (code := lookup.get(name)) is not None:
                    cache[name] = code
        except Exception as exc:  # 네트워크 없음 / KRX 차단 등
            unresolved.append(f"pykrx 조회 실패: {exc}")

    trades["ticker"] = trades["name"].map(lambda n: cache.get(n))
    missing = sorted(trades.loc[trades["ticker"].isna(), "name"].dropna().unique())
    unresolved.extend(missing)
    return trades, unresolved
