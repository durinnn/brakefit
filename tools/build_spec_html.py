"""docs/spec.md → docs/spec.html (브라우저에서 Ctrl+P → PDF 저장용 단일 HTML).

사용법:
    uv run python tools/build_spec_html.py            # docs/spec.html 생성
    uv run python tools/build_spec_html.py --out /tmp/x.html

이 환경에는 chrome·pandoc 이 없다. 변환(HTML→PDF)은 사람이 브라우저에서 한다:
    1) 이 스크립트로 docs/spec.html 생성
    2) 브라우저로 열고 mermaid 다이어그램이 다 그려질 때까지 1~2초 기다림
    3) Ctrl+P → 대상 "PDF로 저장", 여백 "기본", **배경 그래픽 켜기**(표 헤더·코드 배경이 나오게)

산출물이 자급자족(self-contained)이어야 하는 이유:
  - 스크린샷은 base64 data URI 로 인라인한다. 인쇄 시 상대경로가 깨지면 그림만 조용히
    사라지는데, 제출 직전에 그걸 알아채기 어렵다.
  - 반대로 mermaid 는 CDN 에서 받는다. 오프라인이면 다이어그램만 안 나오고 나머지는 멀쩡하다
    (다이어그램을 SVG 로 미리 굽는 건 chrome 이 있어야 해서 이 환경에선 불가).

입력:
  docs/spec.md          본문 (표지 정보는 상단 목록에서 파싱)
  docs/architecture.md  첫 mermaid 블록 → spec §9 위치에 삽입
  docs/user-flow.md     → 부록 D 로 붙임 (spec §2 의 링크가 이 부록을 가리키게 바꿈)
"""

from __future__ import annotations

import argparse
import base64
import html
import re
import sys
from pathlib import Path

try:
    import markdown
except ModuleNotFoundError:  # pragma: no cover - 안내가 목적
    sys.exit("markdown 패키지가 없다. `uv sync --extra web --extra docs` 먼저 실행할 것.")

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"

# 상대 링크(`[..](web/src/...)`)를 GitHub 절대 링크로 바꾼다 — PDF 안에서는 상대경로가 무의미하다.
GITHUB_BLOB = "https://github.com/durinnn/brakefit/blob/main"

MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"

# 한글 폰트는 시스템에 있는 것만 쓴다. 외부 폰트를 로드하면 오프라인·인쇄 대기에서 깨진다.
FONT_STACK = '"Pretendard", "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", sans-serif'
MONO_STACK = '"D2Coding", "Consolas", "DejaVu Sans Mono", monospace'

USER_FLOW_ANCHOR = "appendix-user-flow"

# 마크다운 변환 전에 mermaid 블록을 빼놓을 때 쓰는 자리표시자.
# 마크다운 문법으로 해석될 문자가 없어야 해서 영문 대문자만 쓴다.
_MERMAID_TOKEN = "MERMAIDBLOCKPLACEHOLDER{}ENDMERMAIDBLOCK"


# --------------------------------------------------------------------------- 파싱


def _split_head_body(text: str) -> tuple[str, str]:
    """spec.md 를 (표지 재료가 든 머리말, `## 1.` 부터의 본문) 으로 가른다."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## "):
            return "\n".join(lines[:i]), "\n".join(lines[i:])
    raise SystemExit("docs/spec.md 에 `## ` 섹션이 없다 — 구조가 바뀌었는지 확인할 것.")


def _parse_cover(head: str) -> dict[str, object]:
    """머리말에서 표지에 쓸 값을 뽑는다.

    형식이 바뀌어도 죽지 않게 전부 optional 로 다룬다 — 못 찾으면 그 줄만 표지에서 빠진다.
    """
    title_match = re.search(r"^#\s+(.+)$", head, re.MULTILINE)
    contest_match = re.search(r"(\d{4}\s*[^\s]*\s*AI Challenge)", head)
    submit_match = re.search(r"제출:\s*([0-9]{4}-[0-9]{2}-[0-9]{2}(?:\s+[0-9:]+)?)", head)

    # `- 레이블: 값` 목록을 순서대로 보존한다 (서비스 URL / API 문서 / 레포 / 팀).
    items: list[tuple[str, str]] = []
    for line in head.splitlines():
        item = re.match(r"^-\s+([^:]{1,20}):\s*(.+)$", line.strip())
        if item:
            items.append((item.group(1).strip(), item.group(2).strip()))

    return {
        "title": title_match.group(1).strip() if title_match else "기능 명세서",
        "contest": contest_match.group(1).strip() if contest_match else "",
        "submit": submit_match.group(1).strip() if submit_match else "",
        "items": items,
    }


def _extract_first_mermaid(text: str) -> str:
    """architecture.md 의 첫 mermaid 펜스 내용을 그대로 돌려준다."""
    match = re.search(r"^```mermaid\n(.*?)^```", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise SystemExit("docs/architecture.md 에서 mermaid 블록을 못 찾았다.")
    return match.group(1).rstrip()


# --------------------------------------------------------------------------- 조립


def _insert_architecture_diagram(body: str, diagram: str) -> str:
    """"시스템 아키텍처" 절 제목 바로 아래에 아키텍처 다이어그램을 끼워 넣는다.

    절 번호가 아니라 제목 키워드로 찾는다 — 목차를 재배열할 때마다 번호가 바뀌어서 번호에
    묶어두면 조용히 빠진다.
    """
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^##\s+\d+\.\s+.*(아키텍처|시스템 구성)", line):
            block = ["", "```mermaid", diagram, "```", ""]
            return "\n".join(lines[: i + 1] + block + lines[i + 1 :])
    print("경고: 시스템 아키텍처 절을 못 찾아 다이어그램을 넣지 못했다.", file=sys.stderr)
    return body


def _build_user_flow_appendix(text: str) -> str:
    """user-flow.md 를 spec 부록 계층(`###`)에 맞춰 낮춘다."""
    lines = []
    for line in text.splitlines():
        if line.startswith("# "):  # 원본 제목은 부록 제목으로 대체
            continue
        if line.startswith("## "):
            lines.append("#### " + line[3:])
            continue
        lines.append(line)
    header = f"### 부록 D. 사용자 흐름도 {{: #{USER_FLOW_ANCHOR} }}"
    return header + "\n" + "\n".join(lines).strip() + "\n"


# --------------------------------------------------------------------------- 치환


def _iter_non_fence(text: str):
    """(줄, 코드펜스 안인지) 를 순서대로 내놓는다. 펜스 안은 손대면 안 된다."""
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            yield line, True
            continue
        yield line, in_fence


_LIST_RE = re.compile(r"^\s{0,3}(?:[-*+]|\d{1,9}[.)])\s+\S")


def _loosen_lists(text: str) -> str:
    """문단 바로 다음 줄에서 시작하는 목록 앞에 빈 줄을 넣는다.

    spec.md 는 `**표시 항목**` 다음 줄에 바로 `- ...` 를 붙여 쓴다. GitHub(GFM)는 이걸
    목록으로 그려주지만 python-markdown 은 앞 문단의 이어쓰기로 봐서 `- ` 가 본문에 그대로
    찍힌다. §4 전체가 줄글로 뭉개져서, 원문을 고치는 대신 변환 직전에만 빈 줄을 끼운다.
    """
    out: list[str] = []
    prev = ""
    for line, in_fence in _iter_non_fence(text):
        if (
            not in_fence
            and _LIST_RE.match(line)
            and prev.strip()
            and not _LIST_RE.match(prev)
            # 제목·인용·표 다음은 이미 블록 경계라 빈 줄이 필요 없다
            and not prev.lstrip().startswith(("#", ">", "|"))
        ):
            out.append("")
        out.append(line)
        prev = line
    return "\n".join(out)


def _inline_images(text: str, base_dir: Path) -> tuple[str, int]:
    """`![alt](img/x.png)` 을 base64 data URI 로 바꾼다."""
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        alt, src = match.group(1), match.group(2).strip()
        if src.startswith(("http://", "https://", "data:")):
            return match.group(0)
        path = (base_dir / src).resolve()
        if not path.is_file():
            print(f"경고: 이미지 없음 — {src}", file=sys.stderr)
            return match.group(0)
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        count += 1
        return f"![{alt}](data:{mime};base64,{encoded})"

    out = []
    for line, in_fence in _iter_non_fence(text):
        out.append(line if in_fence else re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", repl, line))
    return "\n".join(out), count


def _rewrite_links(text: str) -> tuple[str, int]:
    """레포 상대 링크를 GitHub 절대 링크로. `path.py:45` 는 `#L45` 로 옮긴다."""
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        label, target = match.group(1), match.group(2).strip()
        if target.startswith(("http://", "https://", "data:", "#", "mailto:")):
            return match.group(0)
        # spec §2 → 부록 D 내부 링크 (같은 HTML 안에 이미 들어있다)
        if target in ("user-flow.md", "docs/user-flow.md"):
            count += 1
            return f"[{label}](#{USER_FLOW_ANCHOR})"

        line_ref = ""
        line_match = re.match(r"^(.*?):(\d+)(?:-\d+)?$", target)
        if line_match:
            target, line_ref = line_match.group(1), f"#L{line_match.group(2)}"

        # docs/ 안의 파일을 docs 기준 상대경로로 쓴 경우를 레포 루트 기준으로 되돌린다.
        if not (REPO_ROOT / target).exists() and (DOCS_DIR / target).exists():
            target = f"docs/{target}"
        count += 1
        return f"[{label}]({GITHUB_BLOB}/{target}{line_ref})"

    out = []
    for line, in_fence in _iter_non_fence(text):
        out.append(line if in_fence else re.sub(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)", repl, line))
    return "\n".join(out), count


def _extract_mermaid(text: str) -> tuple[str, list[str]]:
    """mermaid 펜스를 자리표시자로 바꾸고 원문을 모아둔다.

    fenced_code 로 그냥 두면 `<pre><code class="language-mermaid">` 가 되어 mermaid 가
    못 찾는다. 변환 후에 `<pre class="mermaid">` 로 직접 되돌린다.
    """
    blocks: list[str] = []

    def repl(match: re.Match[str]) -> str:
        blocks.append(match.group(1).rstrip())
        return _MERMAID_TOKEN.format(len(blocks) - 1)

    return re.sub(r"^```mermaid\n(.*?)^```", repl, text, flags=re.MULTILINE | re.DOTALL), blocks


def _restore_mermaid(html_text: str, blocks: list[str]) -> str:
    for i, block in enumerate(blocks):
        token = _MERMAID_TOKEN.format(i)
        pre = f'<pre class="mermaid">{html.escape(block)}</pre>'
        # 자리표시자만 있는 문단은 통째로 갈아끼운다.
        html_text = html_text.replace(f"<p>{token}</p>", pre).replace(token, pre)
    return html_text


def _mark_todo(html_text: str) -> str:
    """`TODO` 와 제목의 `[담당]` 표식을 노랗게. 마감 전에 다 지울 것이라 눈에 띄어야 한다."""
    # 태그 안(속성·id)은 건드리지 않도록 태그/텍스트를 갈라서 텍스트만 치환한다.
    parts = re.split(r"(<[^>]*>)", html_text)
    for i, part in enumerate(parts):
        if part.startswith("<"):
            continue
        parts[i] = re.sub(r"\bTODO\b", '<span class="todo">TODO</span>', part)
    html_text = "".join(parts)

    def heading_repl(match: re.Match[str]) -> str:
        inner = re.sub(
            r"\[([A-D](?:\s*(?:→|,|·)\s*[^\]]{0,20})?)\]",
            r'<span class="todo">[\1]</span>',
            match.group(2),
        )
        return match.group(1) + inner + match.group(3)

    return re.sub(r"(<h[1-6][^>]*>)(.*?)(</h[1-6]>)", heading_repl, html_text, flags=re.DOTALL)


# --------------------------------------------------------------------------- CSS


CSS = f"""
@page {{
  size: A4;
  margin: 18mm;
}}

/* 하단 중앙 페이지 번호. @page 여백박스는 Chrome 이 아직 지원하지 않아 조용히 무시된다
   (Chrome 은 인쇄 대화상자의 "머리글/바닥글" 옵션이 대신 해준다).
   파서가 통째로 버려도 위 size/margin 은 살아남게 규칙을 일부러 분리해 뒀다. */
@page {{
  @bottom-center {{ content: counter(page); font-size: 9pt; color: #666; }}
}}

* {{ box-sizing: border-box; }}

body {{
  font-family: {FONT_STACK};
  font-size: 10.5pt;
  line-height: 1.65;
  color: #111;
  background: #fff;
  margin: 0;
}}

h1, h2, h3, h4 {{ line-height: 1.35; font-weight: 700; page-break-after: avoid; }}
h2 {{ font-size: 16pt; margin: 0 0 14px; padding-bottom: 6px; border-bottom: 2px solid #222; }}
h3 {{ font-size: 12.5pt; margin: 20px 0 8px; }}
h4 {{ font-size: 11pt; margin: 16px 0 6px; color: #333; }}
p, li {{ orphans: 2; widows: 2; }}
ul, ol {{ padding-left: 1.4em; }}
li {{ margin: 2px 0; }}
hr {{ border: 0; border-top: 1px solid #ddd; margin: 20px 0; }}

a {{ color: #14509b; }}

table {{
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0;
  font-size: 9.5pt;
  page-break-inside: auto;
}}
th, td {{
  border: 1px solid #b8b8b8;
  padding: 5px 7px;
  text-align: left;
  vertical-align: top;
  word-break: break-word;
}}
th {{ background: #ececec; font-weight: 700; }}
tr {{ page-break-inside: avoid; page-break-after: auto; }}
thead {{ display: table-header-group; }}  /* 표가 페이지를 넘으면 헤더를 다시 그린다 */

code {{
  font-family: {MONO_STACK};
  font-size: 9.5pt;
  background: #f0f0f0;
  padding: 0 3px;
  border-radius: 2px;
  word-break: break-all;
}}
pre {{
  font-family: {MONO_STACK};
  font-size: 9pt;
  line-height: 1.45;
  background: #f5f5f5;
  border: 1px solid #e0e0e0;
  border-radius: 3px;
  padding: 8px 10px;
  margin: 10px 0;
  /* JSON 한 줄이 길어도 페이지 밖으로 안 나가게 */
  white-space: pre-wrap;
  word-break: break-all;
  overflow-wrap: anywhere;
}}
pre code {{ background: none; padding: 0; font-size: inherit; }}

blockquote {{
  margin: 10px 0;
  padding: 2px 0 2px 12px;
  border-left: 3px solid #c4c4c4;
  color: #3a3a3a;
}}
blockquote p {{ margin: 4px 0; }}

img {{
  max-width: 100%;
  /* 스크린샷 세로가 길어 한 페이지를 넘기지 않게 A4 본문 높이(약 261mm) 안으로 묶는다 */
  max-height: 180mm;
  height: auto;
  display: block;
  margin: 10px auto;
  border: 1px solid #ddd;
  page-break-inside: avoid;
}}

.mermaid {{
  background: #fff;
  border: 0;
  padding: 4px 0;
  text-align: center;
  page-break-inside: avoid;
  /* mermaid 가 렌더되면 내용이 SVG 로 바뀐다. CDN 이 막혀 렌더가 안 되면 다이어그램 소스가
     그대로 남는데, pre-wrap 이면 최소한 읽을 수는 있다(normal 이면 한 덩어리로 뭉갠다). */
  white-space: pre-wrap;
  word-break: normal;
}}
.mermaid svg {{ max-width: 100%; height: auto; }}

.todo {{ background: #ffe98a; padding: 0 3px; border-radius: 2px; }}

/* --- 표지 --- */
.cover {{ page-break-after: always; padding-top: 55mm; text-align: center; }}
.cover .doc-title {{ font-size: 26pt; font-weight: 700; margin: 0 0 10px; letter-spacing: -0.5px; }}
.cover .contest {{ font-size: 13pt; color: #444; margin: 0 0 4px; }}
.cover .submit {{ font-size: 11pt; color: #666; margin: 0 0 40px; }}
.cover table {{ width: 78%; margin: 0 auto; font-size: 10pt; }}
.cover th {{ width: 30%; white-space: nowrap; }}
.cover td {{ word-break: break-all; }}

/* --- 목차 --- */
.toc-page h2 {{ border-bottom: 2px solid #222; }}
.toc ul {{ list-style: none; padding-left: 0; margin: 0; }}
.toc > ul > li {{ margin-top: 7px; font-weight: 600; }}
.toc ul ul {{ padding-left: 16px; margin: 2px 0; }}
.toc ul ul li {{ font-weight: 400; font-size: 10pt; color: #333; }}
.toc a {{ text-decoration: none; color: inherit; }}

/* 표지 다음부터는 각 `##` 섹션이 새 페이지에서 시작한다.
   목차 페이지에 page-break-after 를 주면 첫 섹션 앞에 빈 페이지가 하나 생기므로 주지 않는다. */
.content > h2 {{ page-break-before: always; }}

.build-note {{ font-size: 9pt; color: #777; margin-top: 26px; }}

@media screen {{
  body {{ max-width: 900px; margin: 0 auto; padding: 28px 24px 60px; }}
  .cover {{ padding-top: 20mm; }}
}}

@media print {{
  body {{ max-width: none; margin: 0; padding: 0; }}
  a {{ text-decoration: none; color: #111; }}
  /* 링크 뒤에 URL 을 붙이지 않는다 — 각주가 본문보다 길어져 지저분해진다 */
  a[href^="http"]::after {{ content: none; }}
  .build-note {{ display: none; }}
}}
"""


# --------------------------------------------------------------------------- 렌더


def _render_cover(cover: dict[str, object]) -> str:
    # 표지 값에도 TODO 하이라이트를 건다 — 서비스 URL·API 문서는 마감 직전에 채우는
    # 칸이라 본문과 달리 노랗게 안 뜨면 그대로 제출될 수 있다(본문은 _mark_todo 가 처리).
    rows = "\n".join(
        f"      <tr><th>{html.escape(k)}</th><td>{_mark_todo(html.escape(v))}</td></tr>"
        for k, v in cover["items"]  # type: ignore[union-attr]
    )
    contest = html.escape(str(cover["contest"]))
    submit = html.escape(str(cover["submit"]))
    return f"""<section class="cover">
  <p class="doc-title">{html.escape(str(cover["title"]))}</p>
  <p class="contest">{contest}</p>
  <p class="submit">제출 {submit}</p>
  <table>
    <tbody>
{rows}
    </tbody>
  </table>
</section>"""


def build(spec_path: Path, out_path: Path) -> Path:
    spec_md = spec_path.read_text(encoding="utf-8")
    head, body = _split_head_body(spec_md)
    cover = _parse_cover(head)

    body = _insert_architecture_diagram(
        body, _extract_first_mermaid((DOCS_DIR / "architecture.md").read_text(encoding="utf-8"))
    )
    appendix = _build_user_flow_appendix((DOCS_DIR / "user-flow.md").read_text(encoding="utf-8"))
    combined = body.rstrip() + "\n\n" + appendix

    combined = _loosen_lists(combined)
    combined, image_count = _inline_images(combined, DOCS_DIR)
    combined, link_count = _rewrite_links(combined)
    combined, mermaid_blocks = _extract_mermaid(combined)

    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "attr_list"],
        extension_configs={"toc": {"toc_depth": "2-3"}},
        # spec.md 는 중첩 목록을 2칸 들여쓰기로 쓴다(GitHub 기준). 기본값 4 면 중첩이 안 잡혀
        # 하위 항목이 형제로 평평해진다(§2 시나리오 1~4, §5 PGR/PLR 등).
        # 문서에 "2칸 들여쓴 비-목록 줄"이 없어서 들여쓴 코드블록으로 오인될 위험은 없다.
        tab_length=2,
    )
    content = md.convert(combined)
    content = _restore_mermaid(content, mermaid_blocks)
    content = _mark_todo(content)
    toc = _mark_todo(md.toc)

    doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{html.escape(str(cover["title"]))}</title>
<style>{CSS}</style>
</head>
<body>
{_render_cover(cover)}
<section class="toc-page">
  <h2>목차</h2>
  {toc}
  <p class="build-note">
    이 문서는 <code>tools/build_spec_html.py</code> 가 <code>docs/spec.md</code> 로 생성했다.
    PDF 로 만들려면 다이어그램이 다 그려진 뒤 Ctrl+P → "PDF로 저장",
    <strong>배경 그래픽 켜기</strong>. (이 안내문은 인쇄에 나오지 않는다.)
  </p>
</section>
<main class="content">
{content}
</main>
<script src="{MERMAID_CDN}"></script>
<script>
  // CDN 이 막힌 환경(오프라인)에서는 다이어그램만 빠지고 나머지 문서는 그대로 인쇄된다.
  if (window.mermaid) {{
    window.mermaid.initialize({{
      startOnLoad: true,
      theme: "neutral",
      fontFamily: {FONT_STACK!r},
    }});
  }}
</script>
</body>
</html>
"""
    out_path.write_text(doc, encoding="utf-8")
    size_kb = out_path.stat().st_size / 1024
    print(f"생성: {out_path}  ({size_kb:,.0f} KB)")
    print(
        f"  이미지 인라인 {image_count}장 · mermaid {len(mermaid_blocks)}개 · "
        f"링크 {link_count}개 절대화"
    )
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="docs/spec.md → 인쇄용 docs/spec.html")
    parser.add_argument("--spec", type=Path, default=DOCS_DIR / "spec.md")
    parser.add_argument("--out", type=Path, default=DOCS_DIR / "spec.html")
    args = parser.parse_args()
    build(args.spec, args.out)


if __name__ == "__main__":
    main()
