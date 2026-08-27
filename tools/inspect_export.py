"""KB증권 HTS/웹 export 파일 구조 덤프기.

사용법:
    python tools/inspect_export.py <파일경로>              # 구조 출력
    python tools/inspect_export.py <파일경로> --redact     # 마스킹 사본 생성 (공유용)
    python tools/inspect_export.py <파일경로> --rows 50    # 더 많은 행 보기

어떤 화면을 export 했든 이걸 먼저 돌려라. 출력 결과를 팀에 붙여넣으면
그대로 컬럼 매핑(YAML)을 만들 수 있다.

--redact 를 붙이면 계좌번호/계좌명/주민번호 패턴을 지운 사본을
같은 폴더에 <원본이름>.redacted.txt 로 떨군다. 원본은 절대 커밋하지 말 것.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

# ── 개인정보 패턴 ────────────────────────────────────────────────────────────
ACCOUNT_RE = re.compile(r"\b\d{3}-\d{3}-\d{3,4}(-\d{2})?\b")   # 394-297-826-01
RRN_RE = re.compile(r"\b\d{6}-[1-4]\d{6}\b")                    # 주민등록번호
PHONE_RE = re.compile(r"\b01[016-9]-?\d{3,4}-?\d{4}\b")
NAME_LABEL_RE = re.compile(r"(계좌명|성명|고객명|예금주)")

SENSITIVE_LABELS = ("계좌번호", "계좌명", "성명", "고객명", "예금주", "주민")


def redact(value):
    """셀 값 하나에서 개인정보로 보이는 부분을 가린다."""
    if not isinstance(value, str):
        return value
    out = ACCOUNT_RE.sub("***-***-***-**", value)
    out = RRN_RE.sub("******-*******", out)
    out = PHONE_RE.sub("010-****-****", out)
    return out


def detect_kind(path: Path) -> str:
    """확장자를 믿지 말고 매직 바이트로 실제 포맷을 판별한다.

    증권사는 .xls 확장자로 (a) 구형 BIFF (b) 사실은 HTML 테이블
    (c) 사실은 CSV 를 주는 일이 흔하다.
    """
    head = path.read_bytes()[:512]
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "xls-ole"          # 구형 엑셀 (BIFF) — Crownix Report 계열
    if head[:2] == b"PK":
        # xlsx 는 zip. 안에 xl/workbook.xml 이 있는지로 확인
        try:
            with zipfile.ZipFile(path) as z:
                if any(n.startswith("xl/") for n in z.namelist()):
                    return "xlsx"
        except zipfile.BadZipFile:
            pass
        return "zip-unknown"
    lowered = head.lower()
    if b"<html" in lowered or b"<table" in lowered:
        return "html-table"       # 확장자만 xls 인 HTML
    return "text"                 # csv / tsv / 기타


def sniff_text_encoding(path: Path) -> str:
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            path.read_text(encoding=enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "unknown"


def load_rows(path: Path, kind: str) -> dict[str, list[list]]:
    """{시트명: [[셀,...], ...]} 형태로 통일해서 돌려준다."""
    if kind in ("xls-ole", "xlsx"):
        try:
            from python_calamine import CalamineWorkbook
        except ImportError:
            sys.exit(
                "python-calamine 이 필요합니다.  uv add python-calamine\n"
                "(KB HTS 가 뽑는 .xls 는 파일이 살짝 깨져 있어서 xlrd 로는 안 열립니다)"
            )
        wb = CalamineWorkbook.from_path(str(path))
        return {name: wb.get_sheet_by_name(name).to_python() for name in wb.sheet_names}

    if kind == "html-table":
        import pandas as pd
        tables = pd.read_html(path, encoding=sniff_text_encoding(path))
        return {
            f"table[{i}]": [list(t.columns)] + t.values.tolist()
            for i, t in enumerate(tables)
        }

    if kind == "text":
        import csv
        enc = sniff_text_encoding(path)
        text = path.read_text(encoding=enc if enc != "unknown" else "cp949",
                              errors="replace")
        dialect = csv.Sniffer().sniff(text[:4096]) if text.strip() else csv.excel
        return {"csv": [r for r in csv.reader(text.splitlines(), dialect)]}

    sys.exit(f"알 수 없는 포맷입니다: {kind}")


def is_blank(cell) -> bool:
    return cell is None or (isinstance(cell, str) and not cell.strip())


def trim(row: list) -> list:
    """오른쪽 빈 셀을 잘라낸다 (Crownix 는 빈 칸을 잔뜩 붙여서 내보낸다)."""
    end = len(row)
    while end > 0 and is_blank(row[end - 1]):
        end -= 1
    return row[:end]


def score_header(row: list) -> int:
    """헤더 행일 가능성 점수 — 문자열 비율이 높고 비어있지 않은 행."""
    cells = [c for c in row if not is_blank(c)]
    if len(cells) < 3:
        return 0
    strings = sum(1 for c in cells if isinstance(c, str))
    return strings * 10 + len(cells) if strings == len(cells) else strings


def describe_value(cell) -> str:
    if is_blank(cell):
        return "·"
    return f"{cell!r}<{type(cell).__name__}>"


def redact_row(row: list) -> list:
    """행 단위 마스킹.

    두 가지를 지운다:
      1. 값 자체가 계좌번호/주민번호/전화번호 패턴인 셀
      2. '계좌명:' 같은 라벨 셀 바로 뒤에 오는 값 셀 (이름은 패턴으로 못 잡음)
    """
    out = [redact(c) for c in row]
    for i, cell in enumerate(row):
        if isinstance(cell, str) and any(lbl in cell for lbl in SENSITIVE_LABELS):
            for j in range(i + 1, len(out)):
                if not is_blank(out[j]):
                    out[j] = "***"
                    break
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="KB증권 export 파일 구조 덤프")
    ap.add_argument("path", type=Path)
    ap.add_argument("--rows", type=int, default=25, help="시트당 출력할 행 수 (기본 25)")
    ap.add_argument("--redact", action="store_true", help="마스킹 사본(.redacted.txt) 생성")
    ap.add_argument("--types", action="store_true", help="셀 값의 파이썬 타입까지 표시")
    args = ap.parse_args()

    path: Path = args.path
    if not path.exists():
        sys.exit(f"파일이 없습니다: {path}")

    kind = detect_kind(path)
    safe_lines: list[str] = []

    def emit(s: str = "", safe: str | None = None) -> None:
        """콘솔에는 s 를, 마스킹 사본에는 safe(없으면 s를 패턴 마스킹한 것)를 쓴다."""
        safe_lines.append(redact(s) if safe is None else safe)
        print(s)

    emit("=" * 72)
    emit(f"파일       : {path.name}")
    emit(f"크기       : {path.stat().st_size:,} bytes")
    emit(f"실제 포맷  : {kind}   (확장자: {path.suffix or '없음'})")
    if kind == "text":
        emit(f"인코딩     : {sniff_text_encoding(path)}")
    if kind == "xls-ole":
        emit("읽는 법    : pd.read_excel(..., engine='calamine')  ← xlrd 는 터짐")
    elif kind == "xlsx":
        emit("읽는 법    : pd.read_excel(..., engine='openpyxl')")
    elif kind == "html-table":
        emit("읽는 법    : pd.read_html(...)  ← 확장자만 xls 인 HTML 표")
    emit("=" * 72)

    sheets = load_rows(path, kind)
    warnings: list[str] = []

    for name, rows in sheets.items():
        rows = [trim(r) for r in rows]
        width = max((len(r) for r in rows), default=0)
        emit()
        emit(f"── 시트 '{name}' · {len(rows)}행 × 최대 {width}열 " + "─" * 20)

        if not rows:
            emit("   (빈 시트)")
            continue

        # 헤더 후보 찾기
        best = max(range(len(rows)), key=lambda i: score_header(rows[i]))
        data_rows = [r for i, r in enumerate(rows) if i > best and any(not is_blank(c) for c in r)]

        for i, row in enumerate(rows[: args.rows]):
            marker = " ←헤더 후보" if i == best else ""

            def render(r: list) -> str:
                cells = [describe_value(c) if args.types else (c if not is_blank(c) else "·")
                         for c in r]
                return f"  [{i:>3}]{marker} {cells}"

            emit(render(row), safe=render(redact_row(row)))

            # 개인정보 스캔
            joined = " ".join(str(c) for c in row if c is not None)
            if ACCOUNT_RE.search(joined) or RRN_RE.search(joined) or NAME_LABEL_RE.search(joined):
                warnings.append(f"시트 '{name}' {i}행에 개인정보로 보이는 값이 있습니다")

        if len(rows) > args.rows:
            emit(f"  ... (총 {len(rows)}행 중 {args.rows}행만 표시. --rows 로 늘리세요)")

        emit()
        emit(f"  헤더 후보 : {best}행 → {trim(rows[best])}",
             safe=f"  헤더 후보 : {best}행 → {redact_row(trim(rows[best]))}")
        emit(f"  데이터 행 : {len(data_rows)}개")
        if not data_rows:
            emit("  ⚠ 데이터 행이 없습니다. 조회 기간을 넓혀서 다시 export 하세요.")

    if warnings:
        emit()
        emit("!" * 72)
        emit("개인정보 경고 — 이 파일은 레포/단톡에 올리지 마세요")
        for w in dict.fromkeys(warnings):
            emit(f"  · {w}")
        emit("  공유해야 하면 --redact 로 마스킹 사본을 만들어 그것만 보내세요")
        emit("!" * 72)

    if args.redact:
        out = path.with_suffix(path.suffix + ".redacted.txt")
        out.write_text("\n".join(safe_lines), encoding="utf-8")
        print()
        print(f"마스킹 사본 생성: {out}")
        print("이 파일은 공유해도 됩니다. 그래도 한 번 눈으로 훑어보세요.")


if __name__ == "__main__":
    main()
