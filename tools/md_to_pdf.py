"""제출 문서(.md)를 PDF로 바꾼다(2026-11-18 마스터: 평가 위원이 Windows에서 메모장 대신 바로 읽게).
제출 문서에 쓰인 문법만 처리한다: 제목, 문단, 글머리·번호 목록(들여쓰기 한 단계), 표, 그림, 인용, 글자 안의 코드·굵게·링크.
HTML로 바꾼 뒤 web의 Playwright(Chromium)로 A4 PDF를 찍는다(tools/md_to_pdf.mjs). 개발 PC에서 패키지를 만들 때만 쓴다.
사용: .venv/bin/python tools/md_to_pdf.py <문서.md> [<문서.md> ...]   → 같은 폴더에 같은 이름의 .pdf
"""
import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = """
@page { size: A4; margin: 16mm 14mm; }
body { font-family: 'Pretendard', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif; font-size: 10pt; line-height: 1.55; color: #111; }
h1 { font-size: 18pt; margin: 0 0 8pt; } h2 { font-size: 13.5pt; margin: 16pt 0 6pt; border-bottom: 1px solid #ccc; padding-bottom: 2pt; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt; } p { margin: 4pt 0; } ul, ol { margin: 3pt 0 3pt 16pt; padding: 0; } li { margin: 1.5pt 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 9pt; page-break-inside: auto; } tr { page-break-inside: avoid; }
th, td { border: 1px solid #bbb; padding: 3pt 5pt; vertical-align: top; text-align: left; word-break: keep-all; overflow-wrap: anywhere; min-width: 3.2em; } th { background: #f1f3f5; font-size: 9.5pt; white-space: nowrap; }
code { font-family: 'D2Coding', Menlo, Consolas, monospace; font-size: 8.8pt; background: #f3f4f6; padding: 0 2pt; border-radius: 2pt; word-break: break-all; }
img { max-width: 100%; border: 1px solid #ddd; margin: 4pt 0; } blockquote { margin: 6pt 0; padding: 4pt 8pt; border-left: 3px solid #256ef4; background: #f6f8fb; }
a { color: #1d4ed8; text-decoration: none; }
"""


def _plain(t):
    """링크가 없는 글: `코드`, **굵게**. 코드 안은 바꾸지 않는다."""
    out = []
    for p in re.split(r"(`[^`]+`)", t):
        if p.startswith("`") and p.endswith("`") and len(p) > 1:
            out.append(f"<code>{html.escape(p[1:-1])}</code>")
        else:
            out.append(re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(p, quote=False)))
    return "".join(out)


def inline(t):
    """글자 안 문법: [글](링크)를 먼저 찾고(글 안의 `코드`도 살림), 나머지는 _plain."""
    out, last = [], 0
    for m in re.finditer(r"\[([^\]]+)\]\(([^)\s]+)\)", t):
        out.append(_plain(t[last:m.start()]))
        href = m.group(2)
        if re.match(r"https?://", href):
            out.append(f'<a href="{html.escape(href)}">{_plain(m.group(1))}</a>')
        else:  # 상대 링크는 PDF에서 개발 PC 절대 경로로 바뀌고 다른 PC에서 열리지 않는다 → 경로 글자로만 둔다
            out.append(_plain(m.group(1)))
        last = m.end()
    out.append(_plain(t[last:]))
    return "".join(out)


def cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def to_html(md, base=None):
    lines = md.splitlines()
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", ln)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
            i += 1
            continue
        img = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", ln)
        if img:
            src = (base / img.group(2)).as_uri() if base else img.group(2)
            out.append(f'<p><img src="{html.escape(src)}" alt="{html.escape(img.group(1))}"></p>')
            i += 1
            continue
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{3,}", lines[i + 1]):
            head = cells(ln)
            i += 2
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            t = "<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
            t += "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table>"
            out.append(t)
            continue
        if ln.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip("> ").rstrip())
                i += 1
            out.append("<blockquote>" + "<br>".join(inline(b) for b in buf) + "</blockquote>")
            continue
        if re.match(r"^(\s*)([-*]|\d+\.)\s+", ln):
            out.append(lists(lines, i))
            while i < len(lines) and (re.match(r"^(\s*)([-*]|\d+\.)\s+", lines[i]) or (lines[i].startswith("  ") and lines[i].strip())):
                i += 1
            continue
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,4}\s|\||>|!\[|\s*([-*]|\d+\.)\s)", lines[i]):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>" + "<br>".join(inline(b) for b in buf) + "</p>")
    return "\n".join(out)


def lists(lines, i):
    """글머리·번호 목록. 들여쓴 줄(2칸 이상)은 앞 항목 아래 목록으로 넣는다."""
    items = []  # (깊이, 번호 목록인가, 글)
    while i < len(lines):
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)", lines[i])
        if m:
            items.append((1 if len(m.group(1)) >= 2 else 0, m.group(2)[0].isdigit(), m.group(3)))
        elif lines[i].startswith("  ") and lines[i].strip() and items:
            d, o, t = items[-1]
            items[-1] = (d, o, t + " " + lines[i].strip())
        else:
            break
        i += 1
    html_out, open_tags = [], []
    for d, o, t in items:
        tag = "ol" if o else "ul"
        while len(open_tags) > d + 1:
            html_out.append(f"</li></{open_tags.pop()}>")
        if len(open_tags) < d + 1:
            html_out.append(f"<{tag}>")
            open_tags.append(tag)
        elif html_out and not html_out[-1].endswith(f"<{tag}>"):
            html_out.append("</li>")
        html_out.append(f"<li>{inline(t)}")
    while open_tags:
        html_out.append(f"</li></{open_tags.pop()}>")
    return "".join(html_out)


def convert(paths):
    jobs = []
    tmp = Path(tempfile.mkdtemp(prefix="md_pdf_"))
    for k, p in enumerate(paths):
        p = Path(p).resolve()
        body = to_html(p.read_text(encoding="utf-8"), p.parent)
        page = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
                f"<title>{html.escape(p.stem)}</title><style>{CSS}</style></head><body>{body}</body></html>")
        h = tmp / f"{k}.html"
        h.write_text(page, encoding="utf-8")
        jobs.append(f"{h}\t{p.with_suffix('.pdf')}")
    subprocess.run(["node", str(ROOT / "tools" / "md_to_pdf.mjs")], input="\n".join(jobs), text=True, check=True, cwd=ROOT / "web")
    return [Path(p).with_suffix(".pdf") for p in paths]


if __name__ == "__main__":
    for f in convert(sys.argv[1:]):
        print(f)
