"""답 문장 검사 도구: 숫자 대조, 금지 표현, 근거 없는 해석, 한국어 판정. 검수(verify.py)와 결과 생성(result.py)이 쓴다."""
import json
import re
import unicodedata

NUM = re.compile(r"-?\d[\d,]*\.?\d*")
EXCLUDE = re.compile(r"\d{4}-\d{2}|[A-Z]+-\d+|\d{4}\s*년|(?<!\d)(?:0?[1-9]|1[0-2])\s*[~∼–-]\s*(?=(?:0?[1-9]|1[0-2])\s*월)"
                     r"|(?<!\d)(?:0?[1-9]|1[0-2])\s*월|(?<!\d)\d{1,2}\s*개월")
PCT = re.compile(r"(-?\d[\d,]*\.?\d*)\s*%")
KO_NUM = re.compile(r"[일이삼사오육칠팔구십백천만]+(?:점[일이삼사오육칠팔구영공]+)?\s*(?:%|퍼센트|곳|명)")
DONG_NUM = re.compile(r"[가-힣]+\d+동")  # '이도2동'의 2는 수치가 아니다
BANNED = re.compile(r"유망|망할|반드시|확실히|보장|추천합니다|\d+\s*위.{0,12}(폐업|생존)|(폐업|생존).{0,12}\d+\s*위")
UNFOUNDED = re.compile(r"관광객|안정적|호황|활발|침체|경향|때문|덕분|것으로 보입니다|아마")  # 도구 결과로 뒷받침되지 않는 해석


def _norm(text):
    return unicodedata.normalize("NFKC", text or "")


def numbers(text):
    text = EXCLUDE.sub(" ", DONG_NUM.sub(" ", _norm(text)))
    out = []
    for s in NUM.findall(text):
        try:
            out.append(float(s.replace(",", "").rstrip(".")))
        except ValueError:
            pass
    return out


def check_numbers(answer, tool_results):
    """답의 숫자 중 도구 결과에 없는 것을 돌려준다. 질문의 숫자는 허용하지 않는다."""
    allowed = set()
    for r in tool_results:
        allowed |= {abs(x) for x in numbers(json.dumps(r, ensure_ascii=False))}
    # 정수 반올림은 허용하지 않는다: 없는 값 "12%"가 11.6의 반올림으로 통과할 수 있다
    bad = [n for n in numbers(answer) if not any(abs(abs(n) - a) < 0.005 or round(a, 1) == abs(n) for a in allowed)]
    return bad + [k for k in KO_NUM.findall(DONG_NUM.sub(" ", _norm(answer))) if re.sub(r"\s", "", k) != "이곳"]  # '이곳'은 '이 장소'(2026-11-14 오탐)


def is_korean(text):
    if re.search(r"[一-鿿]", text):
        return False
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum("가" <= c <= "힣" for c in letters) / len(letters) >= 0.3
