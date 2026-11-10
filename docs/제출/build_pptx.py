"""기획서 PPTX를 만든다. 수치는 build_docs.py와 같은 계산(표준 테이블·평가 결과)에서 가져오고 손으로 옮기지 않는다.
실행: .venv/bin/python docs/제출/build_pptx.py   (python-pptx 필요: .venv/bin/pip install python-pptx)
입력: 사용자 템플릿 ../_PPT/KAMP2026_템플릿_사용자마스터.pptx(프로젝트 폴더 기준 상대 경로, 없으면 TEMPLATE 환경 변수)
출력: docs/제출/기획서.pptx. PDF 변환은 사용자가 한다(2026-11-10 사용자 결정).
구조: 대회 필수 항목(구현 목표·서비스 제안·Agent 구성·데이터 계획·개발·탑재 계획)을 참고 기획안의
문제 정의 → 솔루션 개요 → 데이터·기술 → 사용자 시나리오 → 도입 효과·확장 순서에 맞췄다.
"""
import copy
import os
import sys
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import build_docs as B  # noqa: E402  (실행하면 HTML·MD 문서도 같은 값으로 다시 만든다)

TEMPLATE = Path(os.environ.get("TEMPLATE", ROOT.parent / "_PPT" / "KAMP2026_템플릿_사용자마스터.pptx"))
OUT = HERE / "기획서.pptx"
CONTEST = "2026 제주 AI·빅데이터 활용 AI Agent 개발 챌린지"
DATE = "2026. 11. 10."

# 색(사용자 지시 2026-11-10): LOTTE·포트폴리오 템플릿처럼 흰 배경에 강조색 하나(주황)만 강하게 쓴다.
# WHITE는 본문 글자색 이름으로 남겨 두었고 실제 값은 검정에 가깝다.
WHITE, SUB, MUTE = RGBColor(0x11, 0x11, 0x11), RGBColor(0x4A, 0x4A, 0x4A), RGBColor(0x8C, 0x8C, 0x8C)
ORANGE, CARD, LINE = RGBColor(0xFF, 0x6F, 0x0F), RGBColor(0xF4, 0xF4, 0xF4), RGBColor(0xD0, 0xD0, 0xD0)
PURE = RGBColor(0xFF, 0xFF, 0xFF)
L, R = 0.45, 12.88  # 본문 왼쪽·오른쪽 끝(인치)
TOTAL = 14


# ---------- 공통 그리기 ----------
def _runs(item):
    """문자열 또는 (글자, 옵션) 목록을 받아 run 목록으로 바꾼다."""
    return [(item, {})] if isinstance(item, str) else item


def _bullet(p, level=0):
    pPr = p._p.get_or_add_pPr()
    pPr.set("marL", str(int(Inches(0.22 + 0.22 * level))))
    pPr.set("indent", str(int(-Inches(0.2))))
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum"):
        for e in pPr.findall(qn(tag)):
            pPr.remove(e)
    bu = etree.SubElement(pPr, qn("a:buChar"))
    bu.set("char", "•")


def text(sl, x, y, w, h, paras, size=14, color=WHITE, bold=False, align=None, anchor=MSO_ANCHOR.TOP, space=4, name=None):
    """paras: 문자열·run 목록·dict(runs, bullet, size, color, bold, space) 의 목록."""
    tb = sl.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.04)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    for i, item in enumerate(paras if isinstance(paras, list) else [paras]):
        d = item if isinstance(item, dict) else {"runs": item}
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if align:
            p.alignment = align
        p.space_after = Pt(d.get("space", space))
        if d.get("bullet"):
            _bullet(p, d.get("level", 0))
        for t, o in _runs(d["runs"]):
            r = p.add_run()
            r.text = t
            f = r.font
            f.size = Pt(o.get("size", d.get("size", size)))
            f.bold = o.get("bold", d.get("bold", bold))
            f.color.rgb = o.get("color", d.get("color", color))
    return tb


def card(sl, x, y, w, h, accent=False):
    """보통 카드는 옅은 회색 면, 강조 카드는 흰 면에 주황 테두리."""
    s = sl.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    s.adjustments[0] = 0.04 if min(w, h) < 2 else 0.02
    s.fill.solid()
    s.fill.fore_color.rgb = PURE if accent else CARD
    if accent:
        s.line.color.rgb = ORANGE
        s.line.width = Pt(1.75)
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    s.text_frame.text = ""
    return s


def arrow(sl, x, y, w=0.38, h=0.32):
    a = sl.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    a.fill.solid()
    a.fill.fore_color.rgb = ORANGE
    a.line.fill.background()
    a.shadow.inherit = False


def _border_bottom(cell, color="D0D0D0", w=6350):
    tcPr = cell._tc.get_or_add_tcPr()
    ln = etree.Element(qn("a:lnB"), w=str(w))
    sf = etree.SubElement(ln, qn("a:solidFill"))
    etree.SubElement(sf, qn("a:srgbClr"), val=color)
    tcPr.insert(0, ln)


def table(sl, x, y, w, rows, colw, size=12, rowh=0.36, bold_first_col=False):
    gf = sl.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y), Inches(w), Inches(rowh * len(rows)))
    tbl = gf.table
    tbl._tbl.tblPr.find(qn("a:tableStyleId")).text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"  # 스타일 없음
    tbl.first_row = tbl.horz_banding = False
    for j, cw in enumerate(colw):
        tbl.columns[j].width = Inches(cw)
    for i, row in enumerate(rows):
        tbl.rows[i].height = Inches(rowh)
        for j, val in enumerate(row):
            c = tbl.cell(i, j)
            c.fill.solid()
            c.fill.fore_color.rgb = ORANGE if i == 0 else PURE
            c.margin_left = c.margin_right = Inches(0.08)
            c.margin_top = c.margin_bottom = Inches(0.04)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = c.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            for t, o in _runs(val):
                r = p.add_run()
                r.text = t
                r.font.size = Pt(o.get("size", size))
                r.font.bold = o.get("bold", i == 0 or (bold_first_col and j == 0))
                r.font.color.rgb = o.get("color", PURE if i == 0 else WHITE)
            _border_bottom(c)
    return tbl


def stat(sl, x, y, w, big, label, accent=True, size=30):
    text(sl, x, y, w, 0.62, [[(big, {"bold": True, "color": ORANGE if accent else WHITE, "size": size})]])
    text(sl, x, y + 0.66, w, 0.6, label, size=13, color=SUB)


def header(sl, num, title, sub, section, page):
    """포트폴리오 템플릿처럼 굵은 제목 + 오른쪽 위 강조색 알약 라벨(장 이름)."""
    text(sl, 0.40, 0.34, 0.75, 0.55, [[(f"{num:02d}.", {"bold": True, "size": 24, "color": ORANGE})]])
    text(sl, 1.12, 0.34, 9.4, 0.55, [[(title, {"bold": True, "size": 24})]])
    text(sl, 0.42, 0.93, 12.4, 0.36, sub, size=14, color=SUB)
    pill = sl.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(10.95), Inches(0.4), Inches(1.93), Inches(0.42))
    pill.adjustments[0] = 0.5
    pill.fill.solid()
    pill.fill.fore_color.rgb = ORANGE
    pill.line.fill.background()
    pill.shadow.inherit = False
    tf = pill.text_frame
    tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = section
    r.font.size, r.font.bold, r.font.color.rgb = Pt(12), True, PURE
    page_no(sl, page)


def page_no(sl, page):
    text(sl, 12.1, 7.08, 0.8, 0.3, [[(f"{page} / {TOTAL}", {"size": 10})]], color=MUTE, align=PP_ALIGN.RIGHT)


def image(sl, path, x, y, w, caption):
    pic = sl.shapes.add_picture(str(path), Inches(x), Inches(y), width=Inches(w))
    pic.line.color.rgb = LINE
    pic.line.width = Pt(0.75)
    h = pic.height / 914400
    text(sl, x, y + h + 0.08, w, 0.5, caption, size=11, color=SUB)
    return pic


# ---------- 템플릿 손질 ----------
def set_runs(shape, lines):
    """도형의 문단별 첫 run 글자만 바꾸고 서식은 유지한다. 남는 문단은 지운다."""
    ps = shape.text_frame.paragraphs
    for i, p in enumerate(ps):
        if i < len(lines):
            runs = p.runs
            if runs:
                runs[0].text = lines[i]
                for r in runs[1:]:
                    r._r.getparent().remove(r._r)
            else:
                p.add_run().text = lines[i]
        else:
            p._p.getparent().remove(p._p)


def find(shapes, name):
    for s in shapes:
        if s.name == name:
            return s
        if s.shape_type == 6:
            hit = find(s.shapes, name)
            if hit is not None:
                return hit
    return None


def prepare(prs):
    # 슬라이드는 모두 지우고 마스터·레이아웃만 쓴다.
    sldIdLst = prs.slides._sldIdLst
    for sldId in list(sldIdLst):
        prs.part.drop_rel(sldId.rId)
        sldIdLst.remove(sldId)
    set_runs(find(prs.slide_master.shapes, "Text 1"), [CONTEST])
    # 흰 배경: 마스터 배경을 흰색으로, 템플릿 글자가 쓰는 bg1(원래 흰색)이 검정이 되도록 색 매핑을 뒤집는다.
    m = prs.slide_master._element
    for c in m.iter(qn("a:srgbClr")):
        if c.getparent().getparent().tag == qn("p:bgPr"):
            c.set("val", "FFFFFF")
    cm = m.find(qn("p:clrMap"))
    cm.set("bg1", "dk1"), cm.set("tx1", "lt1"), cm.set("bg2", "dk2"), cm.set("tx2", "lt2")
    # 테마의 한글(동아시아) 글꼴이 비어 있어 PC마다 다른 글꼴로 바뀔 수 있다. 맑은 고딕으로 고정한다.
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    theme = prs.slide_master.part.part_related_by(RT.THEME)
    theme._blob = theme.blob.replace('<a:ea typeface=""/>'.encode(), '<a:ea typeface="맑은 고딕"/>'.encode())
    # 템플릿 마스터의 그림 2개(다른 대회 로고, 슬라이드 밖 색상표)는 지운다. 흰 배경에서 로고가 드러난다.
    for pic in [s for s in prs.slide_master.shapes if s.shape_type == 13]:
        rid = pic._element.blipFill.blip.rEmbed
        pic._element.getparent().remove(pic._element)
        prs.slide_master.part.drop_rel(rid)
    title, toc, body, end = prs.slide_layouts
    tb = find(title.shapes, "TextBox 9")
    set_runs(tb, ["동네 생활 진단 Agent", "질문 하나로 우리 동네의 상권·인구·교통을", "과거 기록으로 확인합니다"])
    for p in tb.text_frame.paragraphs[1:]:
        for r in p.runs:
            r.font.size, r.font.bold = Pt(24), False
            r.font.color.rgb = SUB
            r._r.get_or_add_rPr().set("spc", "0")  # 템플릿 자간(-1.5pt)이 부제에서는 글자를 붙여 보이게 한다
    for r in tb.text_frame.paragraphs[0].runs:
        r._r.get_or_add_rPr().set("spc", "-50")
    p0 = tb.text_frame.paragraphs[0]  # 제목 끝 'Agent'만 강조색
    p0.runs[0].text = "동네 생활 진단 "
    acc = copy.deepcopy(p0.runs[0]._r)
    p0._p.append(acc)
    p0.runs[-1].text = "Agent"
    p0.runs[-1].font.color.rgb = ORANGE
    date = find(title.shapes, "날짜 개체 틀 3")
    for fld in date._element.iter(qn("a:fld")):  # 날짜 필드를 고정 날짜로 바꾼다.
        r = etree.Element(qn("a:r"))
        r.append(fld.find(qn("a:rPr")) if fld.find(qn("a:rPr")) is not None else etree.Element(qn("a:rPr")))
        t = etree.SubElement(r, qn("a:t"))
        t.text = DATE
        fld.addprevious(r)
        fld.getparent().remove(fld)
        break
    else:
        set_runs(date, [DATE])
    set_runs(find(title.shapes, "TextBox 14"), ["제주"])
    # 색 매핑을 뒤집어 tx1을 물려받는 글자는 흰색이 된다. 날짜는 색을 직접 준다.
    date.width = Inches(1.7)
    date.text_frame.word_wrap = False
    for rPr in date._element.iter(qn("a:rPr")):
        rPr.set("sz", "1200")
        for old in rPr.findall(qn("a:solidFill")):
            rPr.remove(old)
        fill = etree.Element(qn("a:solidFill"))
        etree.SubElement(fill, qn("a:srgbClr"), val="4A4A4A")
        rPr.insert(0, fill)
    # PRESENTER 상자가 좁아 줄이 바뀌므로 오른쪽 끝을 지킨 채 넓힌다.
    for lay, names in ((title, ("TextBox 15", "TextBox 16")), (end, ("TextBox 2", "TextBox 3"))):
        for n in names:
            sh = find(lay.shapes, n)
            right = sh.left + sh.width
            sh.width = Inches(1.9)
            sh.left = right - sh.width
            sh.text_frame.word_wrap = False
    set_runs(find(toc.shapes, "TextBox 6"), ["목차"])
    box = find(toc.shapes, "직사각형 203")
    box.line.color.rgb = LINE
    closing = find(end.shapes, "TextBox 1")
    set_runs(closing, ["틀린 답을 그럴듯하게 내지 않는", "동네 생활 진단 "])
    for q in closing.text_frame.paragraphs:
        for r in q.runs:
            r.font.color.rgb = WHITE
    q1 = closing.text_frame.paragraphs[1]
    q1._p.append(copy.deepcopy(q1.runs[0]._r))
    q1.runs[-1].text = "Agent"
    q1.runs[-1].font.color.rgb = ORANGE
    set_runs(find(end.shapes, "TextBox 5"), ["읽어 주셔서 감사합니다."])
    return title, toc, body, end


# ---------- 값 ----------
V = B.VALUE
lodge_hi, lodge_lo = V(B.lodge, "한경면"), V(B.lodge, "이도2동")
visit_hi, visit_lo = V(B.visit, "예래동"), V(B.visit, "동홍동")
elder_hi, elder_lo = V(B.elder, "한경면"), V(B.elder, "아라동")
M = B.M


def build():
    prs = Presentation(str(TEMPLATE))
    L_TITLE, L_TOC, L_BODY, L_END = prepare(prs)
    new = lambda lay: prs.slides.add_slide(lay)  # noqa: E731

    # 1 표지
    s = new(L_TITLE)
    page_no(s, 1)

    # 2 목차
    s = new(L_TOC)
    toc = [
        ("01", "문제 정의", ["목표와 품질 기준", "결합을 막는 장벽", "동네 간 실제 차이"]),
        ("02", "Agent 구성", ["전체 구조", "Workflow와 설계 이유", "모델·도구·자율 범위"]),
        ("03", "데이터 계획", ["데이터 6종과 이용 조건", "전처리·결합", "신뢰도 표시 규칙"]),
        ("04", "서비스 제안", ["사용자 시나리오", "화면 구성"]),
        ("05", "개발·탑재 계획", ["센터 실행 환경", "검증과 도입 효과"]),
    ]
    pos = [(4.9, 0.9), (9.25, 0.9), (0.6, 4.3), (4.9, 4.3), (9.25, 4.3)]
    for (n, t, items), (x, y) in zip(toc, pos):
        ln = s.shapes.add_connector(1, Inches(x), Inches(y), Inches(x + 3.4), Inches(y))
        ln.line.color.rgb = ORANGE
        ln.line.width = Pt(1.5)
        text(s, x, y + 0.12, 3.4, 0.4, [[(f"{n}  ", {"color": ORANGE, "bold": True, "size": 16}), (t, {"bold": True, "size": 16})]])
        for k, it in enumerate(items):
            yy = y + 0.62 + k * 0.44
            l2 = s.shapes.add_connector(1, Inches(x), Inches(yy), Inches(x + 3.4), Inches(yy))
            l2.line.color.rgb = LINE
            l2.line.width = Pt(0.5)
            text(s, x, yy + 0.07, 3.4, 0.34, it, size=13, color=SUB)
    page_no(s, 2)

    # 3 문제 정의
    s = new(L_BODY)
    header(s, 1, "문제 정의", "자료는 제주데이터허브에 있지만, 비전문가가 직접 묶어 보기 어렵습니다", "문제 정의", 3)
    card(s, L, 1.55, 5.0, 5.35, accent=True)
    text(s, L + 0.3, 1.8, 4.4, 5.0, [
        {"runs": [("목표", {"bold": True, "color": ORANGE, "size": 16})], "space": 6},
        {"runs": "IT 비전문가 도민이 제주빅데이터센터 PC에서 평소 말로 묻고, 근거·기준 시점·한계가 붙은 답을 받게 합니다.", "space": 16},
        {"runs": [("품질 기준", {"bold": True, "color": ORANGE, "size": 16})], "space": 6},
        {"runs": "틀린 답을 그럴듯하게 내지 않는 것을 가장 중요하게 봅니다. 예측값을 만들지 않고, 결합한 과거 기록과 그 한계를 함께 답합니다.", "space": 16},
        {"runs": [("대상 사용자", {"bold": True, "color": ORANGE, "size": 16})], "space": 6},
        {"runs": "예비 창업자, 소상공인, 생활 도민, 센터 상담 직원"},
    ])
    barriers = [
        ("지역 단위가 다름", "780 음식점은 법정동 주소, 583 유동인구는 읍면동, 743 버스는 정류소 이름으로 기록됩니다."),
        ("기간이 다름", "793 상가는 2025-09 한 시점, 780은 2025-08까지, 743은 2025-10까지, 579 기상은 2025-03까지입니다."),
        ("이름이 바뀜", "743 정류소 이름이 특정 날짜에 일괄 바뀝니다. 그대로 쓰면 정방동 버스 이용이 95.9% 늘어난 것처럼 보입니다."),
        ("값의 뜻이 불명확", "583 값은 API 문서에도 집계 단위 설명이 없습니다. 사람 수로 읽으면 틀립니다."),
    ]
    cw, chh = 3.54, 2.6
    for k, (t, d) in enumerate(barriers):
        x = 5.7 + (k % 2) * (cw + 0.1)
        y = 1.55 + (k // 2) * (chh + 0.15)
        card(s, x, y, cw, chh)
        text(s, x + 0.22, y + 0.2, cw - 0.44, chh - 0.3, [
            {"runs": [(f"장벽 {k + 1}", {"color": ORANGE, "bold": True, "size": 12})], "space": 2},
            {"runs": [(t, {"bold": True, "size": 16})], "space": 8},
            {"runs": d, "size": 13, "color": SUB},
        ])

    # 4 동네 간 실제 차이
    s = new(L_BODY)
    header(s, 1, "동네마다 실제로 다릅니다", "제주 43개 읍면동의 과거 기록으로 확인한 차이(2024년 기준)", "문제 정의", 4)
    cols = [
        ("숙박 특화계수", "제주 평균 = 1", ("한경면", f"{lodge_hi:.2f}"), ("이도2동", f"{lodge_lo:.2f}"), "업종 구성이 동네마다 다릅니다. 창업 입지에서 먼저 볼 값입니다."),
        ("방문/거주 지수", "사람 수가 아닌 비율", ("예래동", f"{visit_hi:.2f}"), ("동홍동", f"{visit_lo:.2f}"), "거주 대비 방문 비율이 10배 넘게 차이 납니다."),
        ("버스 이용자 중 경로 비중", "2024년", ("한경면", f"{elder_hi:.1f}%"), ("아라동", f"{elder_lo:.1f}%"), "어르신 이동 수요가 동네마다 두 배 차이 납니다."),
    ]
    w3 = (R - L - 0.4) / 3
    for k, (t, unit, hi, lo, note) in enumerate(cols):
        x = L + k * (w3 + 0.2)
        card(s, x, 1.55, w3, 3.85)
        text(s, x + 0.3, 1.75, w3 - 0.6, 0.7, [{"runs": [(t, {"bold": True, "size": 17})], "space": 0}, {"runs": unit, "size": 12, "color": MUTE}])
        stat(s, x + 0.3, 2.6, w3 - 0.6, f"{hi[0]} {hi[1]}", "높은 동네", size=28)
        stat(s, x + 0.3, 3.75, w3 - 0.6, f"{lo[0]} {lo[1]}", "낮은 동네", accent=False, size=28)
        text(s, x + 0.3, 4.75, w3 - 0.6, 0.6, note, size=13, color=SUB)
    card(s, L, 5.6, R - L, 1.3)
    text(s, L + 0.3, 5.75, R - L - 0.6, 1.1, [
        {"runs": [("시사점  ", {"bold": True, "color": ORANGE}), ("동네를 고르는 판단에 쓸 만한 차이가 자료에 이미 있습니다. 문제는 값을 묶는 과정이므로, Agent는 예측이 아니라 결합과 설명을 맡습니다.", {})]},
        {"runs": "폐업률은 해마다 동네 순위가 바뀌어(순위 상관 0.267) 순위로 쓰지 않습니다. 03장의 신뢰도 규칙을 따릅니다.", "size": 12, "color": MUTE},
    ])

    # 5 전체 구조
    s = new(L_BODY)
    header(s, 2, "전체 구조", "자료 → Agent → 결과의 세 층으로 동작합니다", "Agent 구성", 5)
    layers = [
        ("Data Layer", "표준 테이블(행정동 43곳)", ["상가 793 · 음식점 780", "유동인구 583 · 기상 579", "버스 743 + 정류소 612", "실행 중 데이터 API 호출 없음"], False),
        ("Agent Layer", "해석 → 계획 → 실행 → 검증", ["LLM은 도구와 인자만 고름", "도구 5종이 표를 계산", "숫자 대조·표현 검사", "실패하면 1회 재계획"], True),
        ("Output Layer", "근거가 붙은 답", ["코드가 쓴 수치 문장", "근거·기준 시점·한계", "차트·지도·동네 비교표", "A4 인쇄(출력일·출처)"], False),
    ]
    lw = (R - L - 2 * 0.7) / 3
    for k, (t, sub, items, acc) in enumerate(layers):
        x = L + k * (lw + 0.7)
        card(s, x, 1.55, lw, 3.95, accent=acc)
        text(s, x + 0.3, 1.75, lw - 0.6, 3.6, [
            {"runs": [(t, {"bold": True, "color": ORANGE, "size": 13})], "space": 2},
            {"runs": [(sub, {"bold": True, "size": 17})], "space": 12},
        ] + [{"runs": it, "bullet": True, "size": 14, "space": 7} for it in items])
        if k < 2:
            arrow(s, x + lw + 0.16, 3.36)
    card(s, L, 5.7, R - L, 1.2)
    text(s, L + 0.3, 5.85, 3.0, 0.9, [{"runs": [("사용자", {"bold": True, "color": ORANGE})], "space": 2}, {"runs": "예비 창업자 · 소상공인 · 생활 도민 · 센터 상담 직원", "size": 13, "color": SUB}])
    text(s, 4.6, 5.85, 4.0, 0.9, [{"runs": [("화면 메뉴", {"bold": True, "color": ORANGE})], "space": 2}, {"runs": "질문하기 · 동네 진단(지도) · 동네 비교", "size": 13, "color": SUB}])
    text(s, 8.7, 5.85, 4.0, 0.9, [{"runs": [("LLM 경로", {"bold": True, "color": ORANGE})], "space": 2}, {"runs": "로컬 qwen3:1.7b(기본) · Claude(선택) · 없음", "size": 13, "color": SUB}])

    # 6 Workflow
    s = new(L_BODY)
    header(s, 2, "Agent Workflow", "LLM은 도구만 고르고, 계산과 수치 문장은 결정론적 코드가 만듭니다", "Agent 구성", 6)
    steps = [("① 해석", "동네·업종·기간 추출, 범위 판정", "코드"), ("② 계획", "도구와 인자 선택", "LLM"), ("점검·재계획", "문제를 알려 1회 다시 계획", "코드 + LLM"),
             ("③ 실행", "고정 도구 5종", "코드"), ("④ 검증", "숫자 대조·표현 검사", "코드"), ("⑤ 설명", "수치 문장·표·차트·지도", "코드(요약은 Claude)")]
    sw, gap = 1.78, 0.37
    for k, (t, d, who) in enumerate(steps):
        x = L + k * (sw + gap)
        llm = "LLM" in who
        card(s, x, 1.6, sw, 2.25, accent=llm)
        text(s, x + 0.15, 1.75, sw - 0.3, 2.0, [
            {"runs": [(t, {"bold": True, "size": 16})], "space": 8},
            {"runs": d, "size": 13, "color": SUB, "space": 10},
            {"runs": [(who, {"bold": True, "size": 12, "color": ORANGE if llm else WHITE})]},
        ])
        if k < len(steps) - 1:
            arrow(s, x + sw + 0.05, 2.58, w=0.27, h=0.26)
    half = (R - L - 0.2) / 2
    card(s, L, 4.1, half, 2.8)
    text(s, L + 0.3, 4.3, half - 0.6, 2.5, [
        {"runs": [("재계획 규칙", {"bold": True, "color": ORANGE, "size": 16})], "space": 8},
        {"runs": "계획에 빠진 호출이나 틀린 인자가 있으면 점검 코드가 문제를 LLM에 알리고, LLM이 1회 다시 계획합니다.", "bullet": True, "size": 13},
        {"runs": "그래도 빠진 호출만 코드의 기본 계획으로 채웁니다.", "bullet": True, "size": 13},
        {"runs": f"평가셋에서 qwen3:1.7b는 16문항 중 {B.replan_n}건을 재계획했고, 끝내 코드로 채운 문항은 {B.fill_n}건입니다.", "bullet": True, "size": 13},
    ])
    card(s, L + half + 0.2, 4.1, half, 2.8)
    text(s, L + half + 0.5, 4.3, half - 0.6, 2.5, [
        {"runs": [("이렇게 설계한 이유", {"bold": True, "color": ORANGE, "size": 16})], "space": 8},
        {"runs": "처음에는 LLM이 답 전체를 썼습니다. 시험에서 \"한림읍 어르신 일평균 1,474명\"이라는 답이 나왔는데, 이 값은 전체 이용자 수였습니다.", "size": 13, "space": 8},
        {"runs": "도구 결과에 있는 숫자라 숫자 대조로는 잡히지 않았습니다. 그래서 수치 문장은 코드만 쓰도록 구조를 바꿨습니다.", "size": 13},
    ])

    # 7 모델과 도구
    s = new(L_BODY)
    header(s, 2, "모델과 도구", "LLM 경로가 무엇이든 수치 문장은 같습니다", "Agent 구성", 7)
    text(s, L, 1.5, 5.0, 0.4, [[("LLM 경로 3가지", {"bold": True, "color": ORANGE, "size": 15})]])
    table(s, L, 1.95, 5.1, [
        ["경로", "조건", "LLM이 하는 일"],
        ["로컬 Ollama qwen3:1.7b (기본)", "Ollama 실행 중, 모델 1.4GB", "계획"],
        ["Claude claude-opus-5-5 (선택)", "환경 변수에 API 키", "계획, 숫자 없는 요약"],
        ["LLM 없음", "위 둘 다 없을 때", "없음(기본 계획)"],
    ], [2.05, 1.65, 1.4], size=12, rowh=0.62)
    text(s, L, 4.6, 5.1, 2.3, [
        {"runs": "도구는 로컬 표준 테이블만 읽습니다.", "bullet": True, "size": 13, "color": SUB},
        {"runs": "앱이 호출하는 API는 선택한 LLM 경로뿐입니다(Ollama 로컬 또는 Claude).", "bullet": True, "size": 13, "color": SUB},
        {"runs": "제주데이터허브 API는 표준 테이블을 만들 때만 호출합니다.", "bullet": True, "size": 13, "color": SUB},
    ])
    text(s, 5.85, 1.5, 7.0, 0.4, [[("도구 5종", {"bold": True, "color": ORANGE, "size": 15})]])
    table(s, 5.85, 1.95, R - 5.85, [
        ["도구", "하는 일", "데이터"],
        ["dong_profile", "상권·생존·인구·교통 요약, 배지 4개", "793, 780, 583, 743+612"],
        ["biz_diagnostic", "업종 점포 수·특화계수, 음식점 개업·폐업·생존", "793, 780"],
        ["population_mix", "방문·근무·거주 지수, 연령 구성, 비 오는 날 변화", "583, 579"],
        ["bus_usage", "일평균 이용, 이용자 유형 비중, 증감, 비 오는 날", "743+612, 579"],
        ["compare_rank", "동네 비교표·순위(폐업·생존은 순위 없음)", "표준 테이블"],
    ], [1.65, 3.6, 1.78], size=12, rowh=0.62)

    # 8 자율 범위 + 작업 과정 화면
    s = new(L_BODY)
    header(s, 2, "자율 범위와 작업 과정", "Agent가 한 일을 답 위에 항상 보여 줍니다", "Agent 구성", 8)
    lw8 = 5.6
    card(s, L, 1.55, lw8, 1.75, accent=True)
    text(s, L + 0.25, 1.7, lw8 - 0.5, 1.55, [
        {"runs": [("Agent가 스스로 함", {"bold": True, "color": ORANGE, "size": 15})], "space": 6},
        {"runs": "도구 선택, 질문 표현이 넓을 때 지표 선택", "bullet": True, "size": 13},
        {"runs": "계획·실행 실패 뒤 재계획", "bullet": True, "size": 13},
    ])
    card(s, L, 3.45, lw8, 1.95)
    text(s, L + 0.25, 3.6, lw8 - 0.5, 1.8, [
        {"runs": [("Agent가 할 수 없음", {"bold": True, "size": 15})], "space": 6},
        {"runs": "SQL·코드 생성, 데이터 수정, 수치 문장 작성", "bullet": True, "size": 13},
        {"runs": "질문에 없는 업종·기간 사용", "bullet": True, "size": 13},
        {"runs": "기본 계획 밖 호출 2개 이상", "bullet": True, "size": 13},
    ])
    card(s, L, 5.55, lw8, 1.35)
    text(s, L + 0.25, 5.68, lw8 - 0.5, 1.2, [
        {"runs": [("범위 밖·모호한 질문", {"bold": True, "size": 15})], "space": 4},
        {"runs": "미래 예측·매출·실시간 질문은 이유를 밝혀 거절하고 답할 수 있는 질문을 제안합니다. 동네가 모호하면 되묻습니다.", "size": 12, "color": SUB},
    ])
    image(s, HERE / "화면" / "질문_답변.png", 6.35, 1.55, 6.5, "질문하기 화면(로컬 모델 경로). 답 위에 다섯 단계를 보여 주고, 자세한 기록은 따로 엽니다.")

    # 9 데이터 6종
    s = new(L_BODY)
    header(s, 3, "데이터 6종", "제주데이터허브 자료를 행정동 43곳 기준으로 묶습니다", "데이터 계획", 9)
    table(s, L, 1.55, R - L, [
        ["ID", "데이터", "형식", "사용 기간", "만드는 지표"],
        ["793", "제주특별자치도 상가(상권) 정보", "파일", "2025-09 단면", "점포 수, 업종 특화계수"],
        ["780", "제주특별자치도 음식점 목록(통합)", "파일", f"{M['rest_last']}까지 이력", "개업·폐업, 폐업률, 5년 생존율"],
        ["583", "읍면동 단위 내국인 유동인구", "API", f"{M['pop_first']} ~ {M['pop_last']} ({M['pop_days']}일)", "방문/거주, 근무/거주, 연령 구성"],
        ["743", "이용자 유형별 버스정류소 이용 인원", "파일", f"2019-01 ~ {M['bus_last'][:7]}", "일평균 이용, 경로·청소년 비중, 증감"],
        ["612", "버스 정류소 기본 정보", "API", "전량", "정류소 → 행정동 연결"],
        ["579", "일별 기상 정보", "API", f"{M['wx_start']} ~ {M['wx_end']}", "강수일(1mm 이상)"],
    ], [0.7, 3.75, 0.8, 3.3, 3.88], size=13, rowh=0.5, bold_first_col=True)
    card(s, L, 5.25, R - L, 1.65)
    text(s, L + 0.3, 5.4, R - L - 0.6, 1.45, [
        {"runs": [("이용 조건", {"bold": True, "color": ORANGE, "size": 15})], "space": 4},
        {"runs": "모든 데이터는 제주데이터허브(jejudatahub.net)에서 프로젝트 키로 받았습니다. 출처를 번호와 함께 표기합니다.", "bullet": True, "size": 13},
        {"runs": "원본 파일은 제출물에 넣지 않고, 표준 테이블에는 업소명 없이 동네 단위 집계만 담습니다.", "bullet": True, "size": 13},
    ])

    # 10 전처리·신뢰도
    s = new(L_BODY)
    header(s, 3, "전처리와 신뢰도 규칙", "결합 정확도를 따로 재고, 불확실한 값은 순위를 내지 않습니다", "데이터 계획", 10)
    stats = [("43곳", "793 ↔ 583 행정동 이름 완전 일치"), ("99.45%", "780 음식점 행정동 확정(법정동 → 우편번호 → 도로명)"), (f"{M['bus_mapped_pct_2024']}%", "2024년 버스 이용자 행정동 연결(이름 일치 → 수동 매핑표)")]
    for k, (big, lab) in enumerate(stats):
        x = L + k * (w3 + 0.2)
        card(s, x, 1.55, w3, 1.75)
        stat(s, x + 0.3, 1.7, w3 - 0.6, big, lab, size=30)
    card(s, L, 3.5, half, 3.4, accent=True)
    text(s, L + 0.3, 3.65, half - 0.6, 3.2, [
        {"runs": [("신뢰도 표시 규칙", {"bold": True, "color": ORANGE, "size": 15})], "space": 6},
        {"runs": "폐업·생존은 순위 없이 값, 95% 구간, 표본 수를 함께 보입니다.", "bullet": True, "size": 13},
        {"runs": f"다중 비교 보정(Benjamini–Hochberg, q=0.10) 뒤에도 차이가 남는 동네만 높음·낮음으로 표시합니다(3년 폐업률 {len(B.close_sig)}곳, 5년 생존율 {len(B.km_sig)}곳).", "bullet": True, "size": 13},
        {"runs": "우도면·추자면은 순위에서 빼고 \"표본 적음\"으로 표시합니다.", "bullet": True, "size": 13},
        {"runs": "583은 비율·지수로만 씁니다.", "bullet": True, "size": 13},
    ])
    card(s, L + half + 0.2, 3.5, half, 3.4)
    text(s, L + half + 0.5, 3.65, half - 0.6, 3.2, [
        {"runs": [("이상값과 쓰지 않은 데이터", {"bold": True, "size": 15})], "space": 6},
        {"runs": "743은 2022년에 105일이 빠져 있어 비교할 때 표시합니다.", "bullet": True, "size": 13},
        {"runs": "579에서 같은 행이 두 번 든 날 2일은 중복을 지웁니다.", "bullet": True, "size": 13},
        {"runs": "후보 동네가 여럿인 정류소는 612 정류소 수에 비례해 나눕니다.", "bullet": True, "size": 13},
        {"runs": "카드 소비(597·502·504)는 읍면동 단위가 없어 동네 지표에 넣지 않았습니다. 묶으면 없는 차이를 만듭니다.", "bullet": True, "size": 13},
    ])

    # 11 사용자 시나리오
    s = new(L_BODY)
    header(s, 4, "사용자 시나리오", "실제 대표 질문으로 본 사용 흐름", "서비스 제안", 11)
    cases = [
        ("Case 1  창업 입지 확인", "예비 창업자", "애월읍에 카페를 낼지 고민. 동네별 카페 수와 개업·폐업 흐름을 직접 묶기 어려움",
         ["\"애월읍에 카페가 많은 편이야?\"를 입력", "상권 진단 도구가 카페 점포 수·특화계수와 음식점 개업·폐업, 영업 지속 곡선을 제시", "근거·한계를 확인하고 동네 진단 화면에서 다른 동네와 비교"]),
        ("Case 2  센터 방문 상담", "센터 상담 직원", "이사를 고민하는 도민이 아라동과 이도2동 비교를 원함",
         ["동네 비교 메뉴에서 두 동네를 선택", "점포 수, 폐업률 판정, 방문/거주 지수, 버스 이용을 한 표로 확인", "A4로 인쇄해 건넴(출력일·자료 출처 포함)"]),
    ]
    for k, (t, actor, cond, flow) in enumerate(cases):
        y = 1.55 + k * 2.75
        card(s, L, y, 6.0, 2.6, accent=(k == 0))
        text(s, L + 0.25, y + 0.15, 5.5, 2.4, [
            {"runs": [(t, {"bold": True, "color": ORANGE, "size": 15})], "space": 6},
            {"runs": [("Actors  ", {"bold": True}), (actor, {"color": SUB})], "size": 12, "space": 2},
            {"runs": [("Conditions  ", {"bold": True}), (cond, {"color": SUB})], "size": 12, "space": 4},
        ] + [{"runs": f"{i + 1}. {f}", "size": 12, "space": 2} for i, f in enumerate(flow)])
    image(s, HERE / "화면" / "동네진단.png", 6.75, 1.55, 6.1, "동네 진단 화면. 인터넷 없이 점포 좌표로 지도 윤곽을 그리고, 동네를 누르면 배지·차트가 바뀝니다.")

    # 12 센터 탑재
    s = new(L_BODY)
    header(s, 5, "센터 탑재 계획", "센터 PC에서 인터넷 없이도 동작하게 만들었습니다", "개발·탑재 계획", 12)
    text(s, L, 1.5, 6.0, 0.4, [[("센터 실행 환경", {"bold": True, "color": ORANGE, "size": 15})]])
    table(s, L, 1.95, half, [
        ["항목", "내용"],
        ["대상 PC", "Intel i7-8700, GTX 1060, RAM 32GB"],
        ["설치", "Python 3.9, scripts\\setup_windows.bat(처음 1회)"],
        ["실행", "scripts\\run_windows.bat 실행 후 브라우저에서 localhost 접속"],
        ["데이터", "표준 테이블을 함께 제공, 실행 중 데이터 API 호출 없음"],
    ], [1.3, half - 1.3], size=12, rowh=0.62, bold_first_col=True)
    text(s, L + half + 0.2, 1.5, 6.0, 0.4, [[("외부 의존성과 없을 때 동작", {"bold": True, "color": ORANGE, "size": 15})]])
    table(s, L + half + 0.2, 1.95, half, [
        ["의존 대상", "없을 때 동작"],
        ["Ollama와 qwen3:1.7b", "코드의 기본 계획으로 답함"],
        ["Claude API(선택, 키 필요)", "키가 없으면 쓰지 않음. 실패 시 요약 없이 답함"],
        ["지도 배경", "쓰지 않음. 점포 격자로 직접 그려 외부 요청 없음"],
        ["Python 패키지 설치", "처음 1회만 인터넷 필요"],
    ], [2.2, half - 2.2], size=12, rowh=0.62, bold_first_col=True)
    card(s, L, 5.35, R - L, 1.55)
    text(s, L + 0.3, 5.5, R - L - 0.6, 1.35, [
        {"runs": [("생성형 AI와 오픈소스", {"bold": True, "size": 14})], "space": 4},
        {"runs": "개발에 Anthropic Claude Code(구현)와 Google Gemini(설계·코드 교차 검토)를 썼습니다. 오픈소스: Next.js, React, Tailwind CSS, shadcn/ui, Recharts, FastAPI, pandas, pyarrow 등.", "size": 12, "color": SUB, "space": 2},
        {"runs": "화면 색과 크기는 KRDS(대한민국 정부 디자인 시스템) 토큰을 따랐고, 정부 사이트가 아닙니다. API 키는 환경 변수로만 받습니다.", "size": 12, "color": SUB},
    ])

    # 13 검증과 도입 효과
    s = new(L_BODY)
    header(s, 5, "검증과 도입 효과", "평가셋 기대값은 도구와 따로 계산해 대조했습니다", "개발·탑재 계획", 13)
    evals = [(f"{B.rule_p}/{B.rule_n}", "LLM 없음(기본 계획)"), (f"{B.ol_p}/{B.ol_n}", "로컬 qwen3:1.7b(제출본 기본)"), (f"{B.cl_p}/{B.cl_n}", "Claude(Q21은 별도 실행)")]
    for k, (big, lab) in enumerate(evals):
        x = L + k * (w3 + 0.2)
        card(s, x, 1.55, w3, 1.6)
        stat(s, x + 0.3, 1.68, w3 - 0.6, big, f"평가셋 통과 · {lab}", size=30)
    card(s, L, 3.35, R - L, 1.35)
    text(s, L + 0.3, 3.48, R - L - 0.6, 1.2, [
        {"runs": [("그 밖의 검증", {"bold": True, "size": 14})], "space": 4},
        {"runs": "화면 자동 시험(데스크톱·휴대폰): 대표 질문 9건의 수치와 화면 요소, 지도 선택, 오류·로딩, A4 인쇄, 접근성 검사 통과. 제출 zip을 새 폴더에 설치해 시험 통과.", "size": 12, "color": SUB, "space": 2},
        {"runs": "아직 못 한 것: 센터 PC 실행과 응답 시간 측정.", "size": 12, "color": SUB},
    ])
    effects = [("방문 상담", "상담 직원이 창업 입지·이사를 고민하는 도민에게 동네 진단·비교 결과를 출력해 줍니다."),
               ("전처리 자산 재사용", "정류소-행정동 매핑표와 표준 테이블을 센터의 다른 분석에 다시 씁니다."),
               ("자료 갱신", "수집·정제 스크립트를 다시 실행하면 추가 개발 없이 기준 시점을 옮깁니다.")]
    for k, (t, d) in enumerate(effects):
        x = L + k * (w3 + 0.2)
        card(s, x, 4.9, w3, 2.0, accent=(k == 0))
        text(s, x + 0.3, 5.05, w3 - 0.6, 1.8, [
            {"runs": [("도입 효과" if k == 0 else "확장 가능성", {"bold": True, "color": ORANGE, "size": 12})], "space": 2},
            {"runs": [(t, {"bold": True, "size": 15})], "space": 6},
            {"runs": d, "size": 13, "color": SUB},
        ])

    # 14 마무리
    s = new(L_END)
    page_no(s, 14)

    prs.save(str(OUT))
    print(f"{OUT.relative_to(ROOT)} · 슬라이드 {len(prs.slides)}장")


if __name__ == "__main__":
    build()
