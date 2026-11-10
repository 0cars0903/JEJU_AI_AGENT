"""기획서 PPTX를 만든다. 수치는 build_docs.py와 같은 계산(표준 테이블·평가 결과)에서 가져오고 손으로 옮기지 않는다.
실행: .venv/bin/python docs/제출/build_pptx.py   (python-pptx 필요: .venv/bin/pip install python-pptx)
입력: 사용자 템플릿 ../_PPT/포트폴리오_템플릿_참고자료.pptx(프로젝트 폴더 기준 상대 경로, 없으면 TEMPLATE 환경 변수),
      화면 캡처 docs/제출/화면/*.png(web/e2e/doc-shots.spec.ts가 실제 실행 화면을 찍는다)
출력: docs/제출/기획서.pptx. PDF 변환은 사용자가 한다(2026-11-10 사용자 결정).
디자인(사용자 지시 2026-11-10): KAMP 템플릿은 쓰지 않는다. 흰 배경에 강조색(주황) 하나. 제목은 주장 문장,
본문은 '라벨: 내용' 개조식, 쪽마다 실제 결과물(화면·차트·작업 기록)을 넣는다. 카드 격자·장식 화살표는 쓰지 않는다.
"""
import os
import sys
from pathlib import Path

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import build_docs as B  # noqa: E402  (실행하면 HTML·MD 문서도 같은 값으로 다시 만든다)

tl = B.tl
TEMPLATE = Path(os.environ.get("TEMPLATE", ROOT.parent / "_PPT" / "포트폴리오_템플릿_참고자료.pptx"))
OUT = HERE / "기획서.pptx"
SHOT = HERE / "화면"
CONTEST = "2026 제주 AI·빅데이터 활용 AI Agent 개발 챌린지"
FONT = "Pretendard"  # 템플릿 글꼴

BLACK, BODY, GRAY, LIGHT = RGBColor(0, 0, 0), RGBColor(0x5E, 0x50, 0x50), RGBColor(0x8C, 0x8C, 0x8C), RGBColor(0xE7, 0xE7, 0xE7)
ORANGE, WHITE, RULE = RGBColor(0xFF, 0x6F, 0x0F), RGBColor(0xFF, 0xFF, 0xFF), RGBColor(0xD9, 0xD9, 0xD9)
L, R = 0.66, 12.67
TOTAL = 15
M = B.M

# EDA 문서(docs/조사/06_EDA_H1H3.md)에 기록된 값. 정방동 95.9%는 이름 연결 전 1차 매핑 값이라 지금 표로는 다시 계산되지 않는다.
BUS_BEFORE_FIX = 95.9
STABILITY = [("버스 일평균", 0.997), ("방문/거주 지수", 0.983), ("근무/거주 지수", 0.975), ("음식점 폐업률(3년 묶음)", 0.402), ("음식점 폐업률(1년)", 0.267)]


# ---------- 그리기 ----------
def _font(run, size, bold=False, color=BODY):
    f = run.font
    f.size, f.bold, f.color.rgb, f.name = Pt(size), bold, color, FONT
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        e = rPr.find(qn(tag))
        if e is None:
            e = etree.SubElement(rPr, qn(tag))
        e.set("typeface", FONT)


def text(sl, x, y, w, h, paras, size=14, color=BODY, bold=False, align=None, anchor=MSO_ANCHOR.TOP, space=6):
    """paras: 문단 목록. 문단은 문자열 또는 (글자, {size,bold,color}) 목록. dict면 runs·size·color·bold·space를 따로 준다."""
    tb = sl.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, item in enumerate(paras if isinstance(paras, list) else [paras]):
        d = item if isinstance(item, dict) else {"runs": item}
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if align:
            p.alignment = align
        p.space_after = Pt(d.get("space", space))
        runs = [(d["runs"], {})] if isinstance(d["runs"], str) else d["runs"]
        for t, o in runs:
            r = p.add_run()
            r.text = t
            _font(r, o.get("size", d.get("size", size)), o.get("bold", d.get("bold", bold)), o.get("color", d.get("color", color)))
    return tb


def label(t, rest):
    """'라벨: 내용' 한 문단. 라벨만 굵게."""
    return [(f"{t}: ", {"bold": True, "color": BLACK}), (rest, {})]


def bar(sl, x, y, w, t, h=0.36):
    """템플릿의 강조색 띠 라벨."""
    s = sl.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = ORANGE
    s.line.fill.background()
    s.shadow.inherit = False
    tf = s.text_frame
    tf.margin_left, tf.margin_top, tf.margin_bottom = Inches(0.12), 0, 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    r = tf.paragraphs[0].add_run()
    r.text = t
    _font(r, 15, True, WHITE)


def head(sl, title, section, lead=None, page=None):
    text(sl, L, 0.55, 10.2, 0.6, [[(title, {"size": 28, "bold": True, "color": BLACK})]])
    pill = sl.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(11.0), Inches(0.46), Inches(1.67), Inches(0.38))
    pill.adjustments[0] = 0.5
    pill.fill.solid()
    pill.fill.fore_color.rgb = ORANGE
    pill.line.fill.background()
    pill.shadow.inherit = False
    tf = pill.text_frame
    tf.margin_top = tf.margin_bottom = tf.margin_left = tf.margin_right = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = section
    _font(r, 12, False, WHITE)
    if lead:
        text(sl, L, 1.3, R - L, 0.6, lead if isinstance(lead, list) else [lead], size=15)
    foot(sl, page)


def foot(sl, page=None):
    if page is None:  # 쪽 번호는 추가된 순서로 정한다(순서를 바꿔도 맞게)
        page = len(sl.part.package.presentation_part.presentation.slides)
    if page > 1:  # 대회명은 왼쪽 위(제목 위)에 둔다. 아래쪽 출처 각주와 섞이지 않게(사용자 지시 2026-11-10). 표지는 본문에 이미 있다.
        text(sl, L, 0.2, 8.0, 0.25, [[(CONTEST, {"size": 10, "color": GRAY})]])
    text(sl, 11.6, 7.05, R - 11.6, 0.25, [[(f"{page} / {TOTAL}", {"size": 9, "color": GRAY})]], align=PP_ALIGN.RIGHT)


def source(sl, t):
    text(sl, L, 6.72, R - L, 0.25, [[(t, {"size": 10, "color": GRAY})]])


def image(sl, name, x, y, w=None, h=None, caption=None):
    """비율을 지켜 넣는다. w나 h 중 하나만 주면 다른 쪽을 계산하고, 둘 다 주면 그 안에 맞춘다."""
    path = SHOT / name
    iw, ih = Image.open(path).size
    if w and h:
        if iw / ih > w / h:
            h = w * ih / iw
        else:
            w = h * iw / ih
    elif w:
        h = w * ih / iw
    else:
        w = h * iw / ih
    pic = sl.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w), Inches(h))
    pic.line.color.rgb = RULE
    pic.line.width = Pt(0.75)
    if caption:
        text(sl, x, y + h + 0.08, max(w, 3.0), 0.3, [[(caption, {"size": 11, "color": GRAY})]])
    return w, h


def table(sl, x, y, w, rows, colw, size=12, rowh=0.38):
    gf = sl.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y), Inches(w), Inches(rowh * len(rows)))
    tbl = gf.table
    tbl._tbl.tblPr.find(qn("a:tableStyleId")).text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"
    tbl.first_row = tbl.horz_banding = False
    for j, cw in enumerate(colw):
        tbl.columns[j].width = Inches(cw)
    for i, row in enumerate(rows):
        tbl.rows[i].height = Inches(rowh)
        for j, val in enumerate(row):
            c = tbl.cell(i, j)
            c.fill.solid()
            c.fill.fore_color.rgb = LIGHT if i == 0 else WHITE
            c.margin_left = c.margin_right = Inches(0.08)
            c.margin_top = c.margin_bottom = Inches(0.03)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            c.text_frame.word_wrap = True
            r = c.text_frame.paragraphs[0].add_run()
            r.text = str(val)
            _font(r, size, i == 0, BLACK if i == 0 else BODY)
            tcPr = c._tc.get_or_add_tcPr()
            ln = etree.Element(qn("a:lnB"), w="6350")
            etree.SubElement(etree.SubElement(ln, qn("a:solidFill")), qn("a:srgbClr"), val="D9D9D9")
            tcPr.insert(0, ln)
    return tbl


def chart(sl, x, y, w, h, cats, vals, highlight=(), horizontal=False, fmt="0.00", size=10, label_all=True):
    cd = CategoryChartData()
    cd.categories = cats
    cd.add_series("값", vals)
    kind = XL_CHART_TYPE.BAR_CLUSTERED if horizontal else XL_CHART_TYPE.COLUMN_CLUSTERED
    ch = sl.shapes.add_chart(kind, Inches(x), Inches(y), Inches(w), Inches(h), cd).chart
    ch.has_legend = False
    ch.has_title = False
    ch.font.size, ch.font.name = Pt(size), FONT
    ch.font.color.rgb = BODY
    plot = ch.plots[0]
    plot.gap_width = 40 if not horizontal else 60
    s = plot.series[0]
    s.format.fill.solid()
    s.format.fill.fore_color.rgb = RGBColor(0xC9, 0xC9, 0xC9)
    for i in highlight:
        pt = s.points[i]
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = ORANGE
    if label_all:
        plot.has_data_labels = True
        dl = plot.data_labels
        dl.number_format, dl.number_format_is_linked = fmt, False
        dl.position = XL_LABEL_POSITION.OUTSIDE_END
        dl.font.size = Pt(size)
    va = ch.value_axis
    va.has_major_gridlines = False
    va.visible = False
    ca = ch.category_axis
    ca.format.line.color.rgb = RULE
    ca.tick_labels.font.size = Pt(size)
    if horizontal:
        ca.reverse_order = True
    return ch


# ---------- 값 ----------
V = B.VALUE
lodge_all = sorted(tl.compare_rank("숙박특화계수", M["dongs"])["values"]["rows"], key=lambda r: -r["value"])
bus_jb = tl.bus_usage("정방동")["values"]["change_prev_pct"]
replan, fill = B.replan_n, B.fill_n


def build():
    prs = Presentation(str(TEMPLATE))
    ids = prs.slides._sldIdLst
    for sid in list(ids):
        prs.part.drop_rel(sid.rId)
        ids.remove(sid)
    blank = next(lay for lay in prs.slide_layouts if lay.name == "Blank")
    new = lambda: prs.slides.add_slide(blank)  # noqa: E731

    # 1 표지
    s = new()
    text(s, L, 0.9, 6.0, 0.4, [[(CONTEST, {"size": 14, "bold": True, "color": ORANGE})]])
    text(s, L, 1.45, 6.0, 1.9, [
        {"runs": [("동네 생활 진단 ", {"size": 44, "bold": True, "color": BLACK}), ("Agent", {"size": 44, "bold": True, "color": ORANGE})], "space": 10},
        {"runs": "제주 도민이 평소 말로 묻고,", "size": 20},
        {"runs": "근거가 붙은 과거 기록으로 답을 받습니다", "size": 20},
    ])
    text(s, L, 4.2, 5.6, 1.6, [
        label("만든 것", "제주데이터허브 자료 6종을 동네 단위로 묶어 답하는 AI Agent"),
        label("실행 환경", "제주빅데이터센터 PC, 설치 뒤에는 인터넷 없이 동작"),
        label("기획서 구성", "문제 → 사용 사례 → Agent 구성 → 데이터 → 탑재"),
    ], size=13)
    text(s, L, 6.35, 5.6, 0.3, [[("송준희 · 2026. 11.", {"size": 12, "color": GRAY})]])
    image(s, "질문_답변.png", 6.75, 0.9, w=5.92, caption="실제 화면: 예비 창업자의 질문에 답한 결과")
    foot(s)

    # 2 문제
    s = new()
    head(s, "같은 동네가 자료마다 다른 방식으로 적혀 있습니다", "문제 정의",
         [label("개요", "창업할 곳이나 이사할 동네를 고를 때 필요한 자료는 제주데이터허브에 이미 있습니다. 하지만 비전문가가 직접 묶기는 어렵습니다.")])
    bar(s, L, 2.15, 5.2, "상황과 목표")
    text(s, L + 0.05, 2.7, 5.1, 3.9, [
        {"runs": label("상황", "도민은 동네를 고를 때 상권, 오가는 사람, 버스를 함께 본다."), "space": 12},
        {"runs": label("문제", "자료마다 동네를 적는 방식과 기간이 다르다. 유동인구(583)는 값의 집계 단위가 문서에 없다."), "space": 12},
        {"runs": label("목표", "센터 PC에서 평소 말로 묻고, 근거·기준 시점·한계가 붙은 답을 받게 한다."), "space": 12},
        {"runs": label("품질 기준", "틀린 답을 그럴듯하게 내지 않는다. 그래서 예측은 하지 않고 과거 기록만 답한다."), "space": 12},
    ], size=14)
    bar(s, 6.1, 2.15, R - 6.1, "자료별로 동네를 적는 방식")
    table(s, 6.1, 2.65, R - 6.1, [
        ["자료", "동네를 적는 방식", "기간"],
        ["상가 793", "행정동", "2025-09 한 시점"],
        ["음식점 780", "법정동 주소", f"{M['rest_last']}까지"],
        ["유동인구 583", "행정동, 단위 설명 없음", f"{M['pop_first'][:7]} ~ {M['pop_last'][:7]}"],
        ["버스 이용 743", "정류소 이름(ID 없음)", f"2019-01 ~ {M['bus_last'][:7]}"],
        ["기상 579", "관측소", f"~ {M['wx_end'][:7]}"],
    ], [1.6, 2.65, 2.32], size=12, rowh=0.52)
    source(s, "자료: 제주데이터허브. 번호는 데이터 ID")

    # 3 동네 차이
    s = new()
    head(s, "묶어 보면 동네마다 차이가 뚜렷합니다", "문제 정의",
         [label("개요", "제주 43개 읍면동의 숙박 특화계수입니다. 1이면 숙박 업소 비중이 제주 평균과 같습니다.")])
    hi = [0, 1, len(lodge_all) - 1]
    chart(s, L - 0.1, 1.95, 8.6, 4.65, [r["dong"] for r in lodge_all], [r["value"] for r in lodge_all], highlight=hi, fmt="0.0", size=9, label_all=False)
    top, low = lodge_all[0], lodge_all[-1]
    bar(s, 9.25, 2.15, R - 9.25, "같은 방식으로 본 다른 지표")
    text(s, 9.3, 2.7, R - 9.3, 3.9, [
        {"runs": label("숙박 특화계수", f"{top['dong']} {top['value']:.2f}, {low['dong']} {low['value']:.2f}"), "space": 10},
        {"runs": label("방문/거주 지수", f"예래동 {V(B.visit, '예래동'):.2f}, 동홍동 {V(B.visit, '동홍동'):.2f}"), "space": 10},
        {"runs": label("버스 이용자 중 경로 비중", f"한경면 {V(B.elder, '한경면'):.1f}%, 아라동 {V(B.elder, '아라동'):.1f}%"), "space": 16},
        {"runs": "동네를 고를 때 쓸 만한 차이는 자료에 이미 있습니다. 부족한 것은 자료를 묶어 설명하는 과정입니다.", "color": BLACK, "space": 8},
        {"runs": "방문/거주 지수는 사람 수가 아니라 비율입니다.", "size": 12, "color": GRAY},
    ], size=13)
    source(s, "자료: 상가 793(2025-09), 유동인구 583(2024), 버스 743(2024). 주황 막대는 위 두 곳과 맨 아래 한 곳")

    # 12 사용 사례 1
    s = new()
    head(s, "예비 창업자는 카페 입지를 질문 하나로 확인합니다", "서비스 제안",
         [label("개요", "동네별 카페 수와 음식점 개업·폐업 흐름을 직접 묶지 않아도 됩니다.")])
    bar(s, L, 2.15, 4.9, "Case 1. 창업 입지 확인")
    text(s, L + 0.05, 2.7, 4.8, 3.9, [
        {"runs": label("사용자", "애월읍에 카페를 낼지 고민하는 예비 창업자"), "space": 12},
        {"runs": label("상황", "동네별 카페 수와 개업·폐업 흐름을 따로 찾아 묶기 어렵다."), "space": 12},
        {"runs": [("흐름", {"bold": True, "color": BLACK})], "space": 4},
        "1. \"애월읍에 카페가 많은 편이야?\"를 입력",
        "2. 카페 점포 수·특화계수, 음식점 개업·폐업, 영업 지속 곡선을 확인",
        "3. 근거와 한계를 읽고, 동네 진단 화면에서 다른 동네와 비교",
    ], size=13)
    image(s, "질문_답변.png", 5.9, 2.15, w=R - 5.9, h=4.5)

    # 13 사용 사례 2
    s = new()
    head(s, "상담 직원은 동네 비교표를 A4로 출력해 건넵니다", "서비스 제안",
         [label("개요", "센터를 찾은 도민에게 두 동네를 한 장으로 비교해 줍니다. 출력물에는 출력일과 자료 출처가 찍힙니다.")])
    bar(s, L, 2.15, 4.9, "Case 2. 센터 방문 상담")
    text(s, L + 0.05, 2.7, 4.8, 3.9, [
        {"runs": label("사용자", "제주빅데이터센터 상담 직원"), "space": 12},
        {"runs": label("상황", "이사를 고민하는 도민이 아라동과 이도2동을 비교해 달라고 한다."), "space": 12},
        {"runs": [("흐름", {"bold": True, "color": BLACK})], "space": 4},
        "1. 동네 비교 메뉴에서 두 동네를 고름",
        "2. 점포 수, 폐업률 판정, 방문/거주 지수, 버스 이용을 한 표로 확인",
        "3. A4 인쇄 버튼으로 출력",
    ], size=13)
    image(s, "인쇄_비교.png", 5.9, 2.15, h=4.5, caption="실제 인쇄 미리보기(A4)")
    image(s, "비교표.png", 9.35, 2.15, w=R - 9.35, caption="화면의 비교표")

    # 4 솔루션 개요
    s = new()
    head(s, "질문 하나에 근거와 한계를 붙여 답합니다", "Agent 구성",
         [label("개요", "도민은 평소 말로 묻습니다. Agent는 도구를 골라 계산하고, 숫자를 검사한 뒤 설명합니다.")])
    bar(s, L, 2.15, 4.9, "도민이 하는 일")
    text(s, L + 0.05, 2.7, 4.8, 1.6, [
        "1. 질문 입력: \"연동 오가는 사람 구성이랑 버스는 어떻게 바뀌었나?\"",
        "2. 답, 차트, 근거, 한계를 확인",
        "3. 필요하면 지도에서 다른 동네를 고르거나 A4로 인쇄",
    ], size=13)
    bar(s, L, 4.35, 4.9, "Agent가 하는 일")
    text(s, L + 0.05, 4.9, 4.8, 1.8, [
        label("해석(코드)", "동네·업종·기간을 뽑고 답할 수 있는 질문인지 판정"),
        label("계획(LLM)", "도구 5종 중 무엇을 부를지 결정"),
        label("실행·검증·설명(코드)", "표를 계산하고, 답의 숫자를 도구 결과와 대조"),
    ], size=13)
    w, h = image(s, "작업과정.png", 5.9, 2.15, w=R - 5.9)
    image(s, "답변.png", 5.9, 2.15 + h + 0.15, w=R - 5.9, h=6.55 - (2.15 + h + 0.15))
    source(s, "실제 화면: 로컬 모델(qwen3:1.7b) 경로. 위는 Agent 작업 과정, 아래는 답변")

    # 5 실제 작업 기록
    s = new()
    head(s, "LLM이 빠뜨린 도구는 점검 코드가 찾아 다시 계획시킵니다", "Agent 구성",
         [label("개요", "앞 쪽 질문의 실제 작업 기록입니다. 질문에 인구와 버스가 함께 있는데, LLM은 두 번 모두 하나를 빠뜨렸습니다.")])
    image(s, "작업기록.png", L, 2.1, h=4.55)
    x2 = 6.75
    bar(s, x2, 2.15, R - x2, "기록에서 일어난 일")
    text(s, x2 + 0.05, 2.7, R - x2 - 0.05, 3.2, [
        label("1차 계획(LLM)", "버스 도구만 골랐다."),
        label("점검(코드)", "질문에 있는 인구 주제의 호출이 없음을 LLM에 알렸다."),
        label("재계획(LLM)", "이번에는 인구 도구만 골라 버스를 빠뜨렸다."),
        label("보충(코드)", "끝내 빠진 호출 1건만 기본 계획으로 채웠다."),
        label("검증(코드)", "답의 숫자가 모두 도구 결과에 있는지 대조했다."),
    ], size=13, space=9)
    text(s, x2 + 0.05, 5.8, R - x2 - 0.05, 0.8, [
        [(f"평가 {len(B.ol_q)}문항에서 qwen3:1.7b는 ", {}), (f"{replan}건을 재계획", {"bold": True, "color": ORANGE}), ("했고, ", {}),
         (f"{fill}건은 코드가 보충", {"bold": True, "color": ORANGE}), ("했습니다.", {})],
    ], size=13)

    # 6 설계 판단
    s = new()
    head(s, "수치 문장은 LLM이 아니라 코드가 씁니다", "Agent 구성",
         [label("개요", "처음에는 LLM이 답 전체를 썼습니다. 숫자 대조 검사로는 막지 못한 오류가 나와 구조를 바꿨습니다.")])
    cw = (R - L - 0.3) / 2
    for k, (t, rows) in enumerate([
        ("처음 설계: LLM이 답 전체를 작성", [("가설", "답의 숫자를 도구 결과와 대조하면 틀린 답을 막을 수 있다."),
                                      ("시험", "\"한림읍 어르신 일평균 1,474명\"이라는 답이 나왔다. 1,474명은 어르신이 아니라 전체 이용자 수였다."),
                                      ("결과", "1,474는 도구 결과에 있는 숫자라 대조 검사를 통과했다. 숫자는 맞고 뜻이 틀린 답은 대조로 막지 못한다.")]),
        ("바꾼 설계: 코드가 수치 문장을 작성", [("가설", "LLM은 도구와 인자만 고르고, 수치 문장은 코드가 정해진 문형으로 쓴다."),
                                       ("시험", "같은 평가셋 21문항을 LLM 경로 3가지로 실행했다."),
                                       ("결과", f"LLM 없음 {B.rule_p}/{B.rule_n}, qwen3:1.7b {B.ol_p}/{B.ol_n}, Claude {B.cl_p}/{B.cl_n} 통과. 수치 문장은 코드가 쓰므로 LLM 경로와 관계없이 같다.")]),
    ]):
        x = L + k * (cw + 0.3)
        bar(s, x, 2.15, cw, t)
        y = 2.75
        for i, (lab, body) in enumerate(rows):
            text(s, x + 0.05, y, cw - 0.1, 1.0, [label(lab, body)], size=13)
            y += 1.05
            if i < 2:
                tri = s.shapes.add_shape(MSO_SHAPE.ISOSCELES_TRIANGLE, Inches(x + cw / 2 - 0.15), Inches(y - 0.22), Inches(0.3), Inches(0.18))
                tri.rotation = 180
                tri.fill.solid()
                tri.fill.fore_color.rgb = ORANGE
                tri.line.fill.background()
                tri.shadow.inherit = False
    source(s, "Claude 결과는 Q01~Q20(2026-11-06)과 Q21(2026-11-07)을 따로 실행한 값")

    # 7 모델과 도구
    s = new()
    head(s, "LLM 경로가 달라도 같은 도구로 계산합니다", "Agent 구성",
         [label("개요", "센터 PC의 인터넷 사정을 모르므로 세 경로를 모두 지원합니다. LLM이 없어도 코드의 기본 계획으로 답합니다.")])
    bar(s, L, 2.15, 4.75, "LLM 경로 3가지")
    table(s, L, 2.65, 4.75, [
        ["경로", "조건", "LLM이 하는 일"],
        ["로컬 qwen3:1.7b(기본)", "Ollama 실행 중", "도구 선택"],
        ["Claude(선택)", "API 키가 있을 때", "도구 선택, 숫자 없는 요약"],
        ["LLM 없음", "위 둘 다 없을 때", "없음(기본 계획)"],
    ], [1.75, 1.35, 1.65], size=12, rowh=0.55)
    text(s, L + 0.05, 4.95, 4.7, 1.6, [
        "도구는 로컬 표준 테이블만 읽습니다.",
        "제주데이터허브 API는 표를 만들 때만 부르고, 실행 중에는 부르지 않습니다.",
    ], size=12, color=GRAY)
    x2 = 5.75
    bar(s, x2, 2.15, R - x2, "도구 5종")
    table(s, x2, 2.65, R - x2, [
        ["도구", "하는 일", "자료"],
        ["dong_profile", "동네 요약(상권·생존·인구·교통)과 배지 4개", "793, 780, 583, 743"],
        ["biz_diagnostic", "업종 점포 수·특화계수, 음식점 개업·폐업·생존", "793, 780"],
        ["population_mix", "방문·근무·거주 지수, 연령 구성, 비 오는 날", "583, 579"],
        ["bus_usage", "일평균 이용, 이용자 유형 비중, 증감", "743, 612, 579"],
        ["compare_rank", "동네 비교표(폐업·생존은 순위 없음)", "표준 테이블"],
    ], [1.55, 3.85, 1.52], size=12, rowh=0.55)

    # 8 자율 범위
    s = new()
    head(s, "Agent가 스스로 정하는 일과 코드가 맡는 일을 나눴습니다", "Agent 구성",
         [label("개요", "답할 수 없는 질문은 이유를 밝히고 답할 수 있는 질문을 제안합니다. 동네가 모호하면 되묻습니다.")])
    bar(s, L, 2.15, 4.9, "Agent가 스스로 하는 일")
    text(s, L + 0.05, 2.7, 4.8, 1.3, ["도구 선택", "질문 표현이 넓을 때 지표 선택", "계획·실행이 실패한 뒤 다시 계획"], size=13)
    bar(s, L, 4.05, 4.9, "Agent가 하지 않는 일")
    text(s, L + 0.05, 4.6, 4.8, 2.0, ["SQL·코드 생성, 데이터 수정", "수치 문장 작성(코드가 씀)", "질문에 없는 업종·기간 사용", "미래 예측, 매출·임대료, 실시간 정보"], size=13)
    bar(s, 5.9, 2.15, R - 5.9, "실제 화면: \"내일 동문시장 매출 얼마나 나올까?\"")
    image(s, "범위밖.png", 5.9, 2.7, w=R - 5.9)

    # 9 데이터 6종
    s = new()
    head(s, "제주데이터허브 자료 6종을 행정동 43곳 기준으로 묶습니다", "데이터 계획",
         [label("개요", "원본은 제출물에 넣지 않습니다. 업소명 없이 동네 단위로 집계한 표준 테이블만 앱에 담습니다.")])
    table(s, L, 2.15, R - L, [
        ["ID", "데이터", "형식", "사용 기간", "만드는 지표"],
        ["793", "제주특별자치도 상가(상권) 정보", "파일", "2025-09 한 시점", "점포 수, 업종 특화계수"],
        ["780", "제주특별자치도 음식점 목록(통합)", "파일", f"{M['rest_last']}까지 이력", "개업·폐업, 폐업률, 5년 생존율"],
        ["583", "읍면동 단위 내국인 유동인구", "API", f"{M['pop_first']} ~ {M['pop_last']}({M['pop_days']}일)", "방문/거주, 근무/거주, 연령 구성"],
        ["743", "이용자 유형별 버스정류소 이용 인원", "파일", f"2019-01 ~ {M['bus_last'][:7]}", "일평균 이용, 경로·청소년 비중, 증감"],
        ["612", "버스 정류소 기본 정보", "API", "전량", "정류소를 행정동에 연결"],
        ["579", "일별 기상 정보", "API", f"{M['wx_start']} ~ {M['wx_end']}", "강수일(1mm 이상)"],
    ], [0.7, 3.6, 0.8, 3.2, 3.71], size=13, rowh=0.5)
    text(s, L, 5.85, R - L, 0.8, [
        label("이용 조건", "모든 자료는 제주데이터허브에서 프로젝트 키로 받았고, 출처를 번호와 함께 표기합니다."),
        label("쓰지 않은 자료", "카드 소비(597·502·504)는 읍면동 단위가 없어 동네 지표에 넣지 않았습니다."),
    ], size=13)

    # 10 결합 검증
    s = new()
    head(s, "버스 이용 95.9% 증가는 정류소 이름이 바뀐 탓이었습니다", "데이터 계획",
         [label("개요", "자료를 묶은 뒤 값이 이상하면 원인을 찾아 연결 방법을 고쳤습니다. 정방동이 그 예입니다.")])
    chart(s, L - 0.1, 2.0, 4.6, 4.5, ["이름 연결 전", "이름 연결 후"], [BUS_BEFORE_FIX, bus_jb], highlight=[0], fmt='0.0"%"', size=12)
    x2 = 5.6
    bar(s, x2, 2.15, R - x2, "정방동 버스 이용 증감(2023 → 2024)")
    text(s, x2 + 0.05, 2.7, R - x2 - 0.05, 2.3, [
        {"runs": label("가설", "동네 하나의 버스 이용이 1년 만에 두 배가 되기는 어렵다."), "space": 9},
        {"runs": label("확인", "2024년에 새로 나타난 정류소 이름 \"NH농협 남제주지점\"이 증가분 대부분이었다. 743 정류소 이름은 특정 날짜에 일괄 바뀐다."), "space": 9},
        {"runs": label("결과", f"바뀐 이름을 같은 동네로 이으니 증감이 {BUS_BEFORE_FIX}%에서 {bus_jb}%가 됐다."), "space": 9},
    ], size=13)
    bar(s, x2, 5.0, R - x2, "연결 정확도")
    text(s, x2 + 0.05, 5.5, R - x2 - 0.05, 1.2, [
        label("음식점 780", "행정동 확정 99.45%(법정동 → 우편번호 → 도로명 순서)"),
        label("버스 743", f"2024년 이용자의 {M['bus_mapped_pct_2024']}%를 행정동에 연결"),
    ], size=13)
    source(s, "95.9%는 이름을 잇기 전 1차 매핑의 기록값(2026-11-06 EDA), 9.6%는 현재 표준 테이블 값")

    # 11 신뢰도 규칙
    s = new()
    head(s, "음식점 폐업률은 해마다 동네 순위가 바뀌어 순위를 매기지 않습니다", "데이터 계획",
         [label("개요", "기간을 둘로 나눠 동네 순위가 얼마나 유지되는지 쟀습니다. 1에 가까울수록 순위가 그대로입니다.")])
    chart(s, L - 0.1, 2.0, 6.0, 4.5, [n for n, _ in STABILITY], [v for _, v in STABILITY], highlight=[3, 4], horizontal=True, fmt="0.000", size=12)
    x2 = 7.0
    bar(s, x2, 2.15, R - x2, "그래서 정한 표시 규칙")
    text(s, x2 + 0.05, 2.7, R - x2 - 0.05, 2.0, [
        "폐업·생존은 값, 95% 구간, 표본 수를 함께 보인다.",
        "다중 비교 보정(Benjamini–Hochberg, q=0.10) 뒤에도 차이가 남는 동네만 높음·낮음으로 쓴다.",
        f"그런 동네는 3년 폐업률 {len(B.close_sig)}곳, 5년 생존율 {len(B.km_sig)}곳이다.",
        "나머지는 \"차이 확인 안 됨\"으로 쓴다. 우도면·추자면은 \"표본 적음\"으로 쓴다.",
    ], size=13, space=8)
    source(s, "순위 안정성: 동네 순위의 스피어만 상관. 폐업률은 2023↔2024, 3년 묶음은 2019~21↔2022~24, 나머지는 기간을 둘로 나눔")

    # 14 센터 탑재와 검증
    s = new()
    head(s, "설치만 끝나면 센터 PC에서 인터넷 없이 실행됩니다", "탑재 계획",
         [label("개요", "패키지 설치 때 한 번만 인터넷이 필요합니다. Windows 설치·실행은 자동 시험으로 확인했고, 센터 PC 실측은 아직 못 했습니다.")])
    bar(s, L, 2.15, 5.85, "실행 환경과 외부 의존성")
    table(s, L, 2.65, 5.85, [
        ["항목", "내용"],
        ["대상 PC", "Intel i7-8700, GTX 1060, RAM 32GB"],
        ["설치·실행", "setup_windows.bat 1회 → run_windows.bat"],
        ["로컬 모델", "qwen3:1.7b, 1.4GB(GTX 1060 메모리 3·6GB보다 작음)"],
        ["Ollama가 없을 때", "코드의 기본 계획으로 답함"],
        ["Claude 키가 없을 때", "쓰지 않음, 요약 없이 답함"],
        ["지도 배경", "점포 좌표로 직접 그림, 외부 요청 없음"],
    ], [1.75, 4.1], size=12, rowh=0.55)
    x2 = 6.85
    bar(s, x2, 2.15, R - x2, "검증한 것")
    text(s, x2 + 0.05, 2.7, R - x2 - 0.05, 3.9, [
        {"runs": label("평가셋 21문항", f"기대값을 도구와 따로 계산해 대조. LLM 없음 {B.rule_p}/{B.rule_n}, qwen3:1.7b {B.ol_p}/{B.ol_n}, Claude {B.cl_p}/{B.cl_n}. 동네 배정과 지표 정의는 도구와 같아 이 평가로 검증되지 않음"), "space": 10},
        {"runs": label("화면 자동 시험", "대표 질문 9건의 수치, 지도 선택, 오류 화면, A4 인쇄, 접근성 검사(데스크톱·휴대폰)"), "space": 10},
        {"runs": label("Windows", "GitHub Actions(windows-latest)에서 설치, 단위 시험, 서버 응답 통과"), "space": 10},
        {"runs": label("설치 재현", "제출 zip을 새 폴더에 풀어 새로 설치하고 시험 통과"), "space": 10},
        {"runs": label("아직 못 한 것", "센터 PC 실행과 응답 시간 측정"), "space": 10},
    ], size=13)

    # 15 도입 효과
    s = new()
    head(s, "센터에서 바로 쓰고, 자료가 바뀌면 다시 만들어 씁니다", "탑재 계획",
         [label("개요", "상담 도구로 쓰고, 만든 자료는 다른 분석에 다시 씁니다.")])
    w3 = (R - L - 0.6) / 3
    for k, (t, body) in enumerate([
        ("방문 상담", "상담 직원이 창업 입지나 이사를 고민하는 도민에게 동네 진단과 비교 결과를 출력해 준다."),
        ("전처리 자료 재사용", "정류소-행정동 연결표와 동네 단위 표준 테이블을 센터의 다른 분석에 다시 쓴다."),
        ("기준 시점 갱신", "수집·정제 스크립트를 다시 실행하면 추가 개발 없이 최신 자료로 바뀐다."),
    ]):
        x = L + k * (w3 + 0.3)
        bar(s, x, 2.15, w3, t)
        text(s, x + 0.05, 2.7, w3 - 0.1, 1.5, [body], size=13)
    text(s, L, 4.0, R - L, 1.6, [
        {"runs": [("동네 생활 진단 ", {"bold": True, "color": BLACK, "size": 22}), ("Agent", {"bold": True, "color": ORANGE, "size": 22})], "space": 6},
        {"runs": "틀린 답을 그럴듯하게 내지 않는 것을 첫째 기준으로 만들었습니다.", "size": 15},
    ])
    text(s, L, 6.3, R - L, 0.3, [[("개발 도구: Claude Code(구현), Gemini(교차 검토). 화면 색과 크기는 KRDS 디자인 토큰을 따랐고 정부 사이트가 아닙니다.", {"size": 10, "color": GRAY})]])

    prs.save(str(OUT))
    print(f"{OUT.relative_to(ROOT)} · 슬라이드 {len(prs.slides)}장")


if __name__ == "__main__":
    build()
