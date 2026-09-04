"""증권사 export 파일을 '행의 리스트'로 읽어들이는 층.

포맷 판별과 인코딩 싸움을 여기서 전부 끝낸다.
윗층(kb_hts.py)은 항상 list[list[cell]] 만 본다.

== 실측으로 확인된 사실 (2026-08-27, KB증권) ==================================
KB HTS(H-able)의 '엑셀로 보내기'는 Crownix Report 엔진이 만든 구형 .xls(BIFF)다.
이 파일은 SST 레코드가 살짝 깨져 있어서 xlrd 로 열면 터진다:

    xlrd.open_workbook(...)  →  struct.error: unpack requires a buffer of 2 bytes
    pd.read_excel(...)       →  같은 이유로 터짐 (pandas 기본 .xls 엔진이 xlrd)

엑셀·LibreOffice 로는 멀쩡히 열리기 때문에 "파일은 정상인데 파이썬만 죽는" 상황이
되어 원인 찾기가 오래 걸린다. python-calamine 은 이걸 읽는다.

    uv add python-calamine

한편 웹(kbsec.com)에서 받는 거래내역은 진짜 .xlsx 라서 openpyxl 로 읽힌다.
같은 회사인데 화면마다 포맷이 다르므로 확장자를 믿지 말고 매직 바이트로 판별한다.
==============================================================================
"""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path

Cell = object
Rows = list[list[Cell]]

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
TEXT_ENCODINGS = ("utf-8-sig", "cp949", "euc-kr", "utf-8")


class UnreadableExport(RuntimeError):
    """포맷을 알아볼 수 없거나 읽는 데 실패했을 때."""


def detect_kind(path: Path) -> str:
    """확장자가 아니라 내용으로 포맷을 판별한다.

    반환: "xls-ole" | "xlsx" | "html-table" | "text"
    """
    head = path.read_bytes()[:512]
    if head[:8] == OLE_MAGIC:
        return "xls-ole"
    if head[:2] == b"PK":
        try:
            with zipfile.ZipFile(path) as z:
                if any(n.startswith("xl/") for n in z.namelist()):
                    return "xlsx"
        except zipfile.BadZipFile:
            pass
        raise UnreadableExport(f"zip 이지만 엑셀이 아닙니다: {path.name}")
    lowered = head.lower()
    if b"<html" in lowered or b"<table" in lowered:
        return "html-table"
    return "text"


def sniff_encoding(path: Path) -> str:
    for enc in TEXT_ENCODINGS:
        try:
            path.read_text(encoding=enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "cp949"  # 국내 증권사 기본값. errors="replace" 와 함께 쓸 것


def read_sheets(path: Path | str) -> dict[str, Rows]:
    """{시트명: 행 리스트} 로 통일해서 돌려준다."""
    path = Path(path)
    if not path.exists():
        raise UnreadableExport(f"파일이 없습니다: {path}")

    kind = detect_kind(path)

    if kind in ("xls-ole", "xlsx"):
        try:
            from python_calamine import CalamineWorkbook
        except ImportError as exc:  # pragma: no cover
            raise UnreadableExport(
                "python-calamine 이 필요합니다 (uv add python-calamine). "
                "KB HTS 의 .xls 는 xlrd 로 열리지 않습니다."
            ) from exc
        try:
            wb = CalamineWorkbook.from_path(str(path))
        except Exception as exc:
            raise UnreadableExport(f"{path.name} 을 열지 못했습니다: {exc}") from exc
        return {name: wb.get_sheet_by_name(name).to_python() for name in wb.sheet_names}

    if kind == "html-table":
        import pandas as pd

        tables = pd.read_html(path, encoding=sniff_encoding(path))
        return {
            f"table[{i}]": [list(t.columns), *t.values.tolist()]
            for i, t in enumerate(tables)
        }

    text = path.read_text(encoding=sniff_encoding(path), errors="replace")
    if not text.strip():
        return {"csv": []}
    try:
        dialect = csv.Sniffer().sniff(text[:4096])
    except csv.Error:
        dialect = csv.excel
    return {"csv": [row for row in csv.reader(text.splitlines(), dialect)]}


# ── 셀 유틸 ──────────────────────────────────────────────────────────────────

def is_blank(cell: Cell) -> bool:
    return cell is None or (isinstance(cell, str) and not cell.strip())


def text(cell: Cell) -> str:
    """셀을 공백 정리한 문자열로. Crownix 는 헤더에 줄바꿈·공백을 섞어 넣는다."""
    if cell is None:
        return ""
    return " ".join(str(cell).split())


def trim_right(row: list[Cell]) -> list[Cell]:
    """오른쪽 빈 셀 제거. Crownix export 는 빈 칸을 20개씩 붙여 내보낸다."""
    end = len(row)
    while end > 0 and is_blank(row[end - 1]):
        end -= 1
    return row[:end]


def find_header_row(rows: Rows, anchors: list[str], search_limit: int = 40) -> int:
    """앵커 텍스트가 모두 들어있는 행을 헤더로 본다.

    행 번호를 하드코딩하면 안 되는 이유: KB export 는 화면 위에
    제목/계좌번호/출력일자 같은 안내 행을 붙이는데 그 개수가 화면마다 다르다.
    """
    wanted = [a.strip() for a in anchors]
    for i, row in enumerate(rows[:search_limit]):
        cells = {text(c) for c in row if not is_blank(c)}
        if all(any(w == c or w in c for c in cells) for w in wanted):
            return i
    raise UnreadableExport(
        f"헤더 행을 찾지 못했습니다. 앵커={anchors}\n"
        f"→ python tools/inspect_export.py <파일> 로 실제 구조를 먼저 확인하세요."
    )
