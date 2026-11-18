"""업종 대응표: 질문의 업종 이름 → 음식점 인허가(780) 원자료의 업종 이름 목록."""
REST_MAP = {"카페": ["커피숍", "까페", "다방", "전통찻집", "키즈카페", "떡카페", "라이브카페"], "한식": ["한식", "식육(숯불구이)", "탕류(보신용)", "냉면집"],
            "일식": ["일식", "횟집", "복어취급"], "횟집": ["횟집"], "중식": ["중국식"], "치킨": ["통닭(치킨)", "호프/통닭"], "분식": ["분식", "김밥(도시락)"],
            "주점": ["호프/통닭", "정종/대포집/소주방", "감성주점"], "편의점": ["편의점"], "음식": None}


def biz_rate_ok(tgt, dongs, metric):
    """동네 × 업종 생존율·폐업률 값이 있는가(app/build_biz_survival.py, 표본 50곳 이상). 동네가 없으면 그 업종 표가 있는지만."""
    if not REST_MAP.get(tgt or "") or metric not in ("5년생존율", "폐업률"):
        return False
    import pandas as pd
    from pathlib import Path
    tab = Path(__file__).resolve().parents[1] / "data" / "tables" / ("km_biz.parquet" if metric == "5년생존율" else "close_biz.parquet")
    if not tab.exists():
        return False
    b = pd.read_parquet(tab)
    b = b[(b["group"] == tgt) & ((b["n"] if metric == "5년생존율" else b["store_years"]) >= 50)]
    return bool(len(b)) and (not dongs or all(d in set(b["dong"]) for d in dongs))
