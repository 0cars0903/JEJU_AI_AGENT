"""제주 행정동 43곳 경계 → 화면용 SVG 경로(data/tables/jeju_map.json) (v3 지도, 사용자 결정 2026-11-12: 경계 색칠 지도).

원자료: vuski/admdongkor ver20261001 HangJeongDong_ver20261001.geojson (WGS84). 데이터 CC BY 4.0, 원 경계는 통계청 SGIS 공공누리 제1유형.
- 제주 43곳만 골라 더글러스-포이커 방식으로 단순화하고(허용 오차 약 25m), 위도 보정 등장방형 투영으로 SVG 좌표를 만든다.
- 추자면은 본섬 북쪽 약 45km에 있어 그대로 그리면 지도가 길어진다. 왼쪽 위 보조 틀 안으로 당겨 그린다(틀과 '추자면(위치 옮김)' 표시).
- 화면은 이 파일만 읽는다(지도 배경 타일·API 키·인터넷 없음).
실행: .venv/bin/python app/build_map.py <내려받은 geojson 경로>
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "tables" / "jeju_map.json"
TOL = 0.00025  # 도(degree), 약 25m
W = 1000  # SVG 가로
ATTRIBUTION = ("본 데이터는 통계청 통계지리정보서비스(SGIS, https://sgis.kostat.go.kr)에서 공공누리 제1유형으로 개방한 행정동 경계를 가공한 것이며"
               "(가공: vuski/admdongkor, https://github.com/vuski/admdongkor), CC BY 4.0으로 배포됩니다.")


def dp(pts, tol):
    """더글러스-포이커 단순화(닫힌 고리는 끝점을 유지)."""
    if len(pts) < 5:
        return pts
    keep = np.zeros(len(pts), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        p, q = pts[a], pts[b]
        seg = q - p
        n = np.hypot(*seg)
        mid = pts[a + 1:b]
        d = np.abs(seg[0] * (mid[:, 1] - p[1]) - seg[1] * (mid[:, 0] - p[0])) / n if n > 0 else np.hypot(*(mid - p).T)
        i = int(np.argmax(d))
        if d[i] > tol:
            keep[a + 1 + i] = True
            stack += [(a, a + 1 + i), (a + 1 + i, b)]
    return pts[keep]


def main(src):
    g = json.loads(Path(src).read_text(encoding="utf-8"))
    feats = [f for f in g["features"] if f["properties"]["adm_nm"].startswith("제주특별자치도")]
    dongs = set(json.loads((ROOT / "data" / "tables" / "meta.json").read_text(encoding="utf-8"))["dongs"])
    rings = {}
    for f in feats:
        name = f["properties"]["adm_nm"].split()[-1]
        polys = f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiPolygon" else [f["geometry"]["coordinates"]]
        rs = []
        for poly in polys:
            outer = dp(np.array(poly[0], float), TOL)  # 바깥 고리만(구멍은 없음 수준)
            if len(outer) >= 4:
                rs.append(outer)
        rings[name] = rs
    assert set(rings) == dongs, (set(rings) ^ dongs)
    # 추자면을 본섬 왼쪽 위로 옮긴다
    main_pts = np.vstack([r for k, rs in rings.items() if k != "추자면" for r in rs])
    lon0, lon1 = main_pts[:, 0].min(), main_pts[:, 0].max()
    lat0, lat1 = main_pts[:, 1].min(), main_pts[:, 1].max()
    ch = np.vstack(rings["추자면"])
    shift = np.array([lon0 + 0.02 - ch[:, 0].min(), lat1 + 0.005 - ch[:, 1].max()])
    rings["추자면"] = [r + shift for r in rings["추자면"]]
    inset = [ch[:, 0].min() + shift[0] - 0.01, ch[:, 1].min() + shift[1] - 0.01, ch[:, 0].max() + shift[0] + 0.01, ch[:, 1].max() + shift[1] + 0.01]
    k = np.cos(np.radians((lat0 + lat1) / 2))
    allp = np.vstack([r for rs in rings.values() for r in rs])
    x0, x1 = allp[:, 0].min(), allp[:, 0].max()
    y0, y1 = allp[:, 1].min(), allp[:, 1].max()
    s = W / ((x1 - x0) * k)
    H = (y1 - y0) * s

    def xy(p):
        return np.column_stack([(p[:, 0] - x0) * k * s, (y1 - p[:, 1]) * s])

    out, npts = [], 0
    for name in sorted(rings):
        parts, cen = [], []
        for r in rings[name]:
            q = xy(r)
            npts += len(q)
            parts.append("M" + "L".join(f"{a:.1f},{b:.1f}" for a, b in q) + "Z")
            cen.append((q.mean(0), len(q)))
        c = max(cen, key=lambda t: t[1])[0]  # 가장 큰 조각의 가운데(이름 표시 위치)
        area = sum(abs(np.dot(q[:, 0], np.roll(q[:, 1], 1)) - np.dot(q[:, 1], np.roll(q[:, 0], 1))) / 2 for q in (xy(r) for r in rings[name]))
        out.append({"dong": name, "d": "".join(parts), "cx": round(float(c[0]), 1), "cy": round(float(c[1]), 1), "area": round(float(area))})
    ix = xy(np.array([[inset[0], inset[3]], [inset[2], inset[1]]]))
    res = {"viewBox": [0, 0, W, round(float(H), 1)], "dongs": out,
           "inset": {"x": round(float(ix[0][0]), 1), "y": round(float(ix[0][1]), 1), "w": round(float(ix[1][0] - ix[0][0]), 1), "h": round(float(ix[1][1] - ix[0][1]), 1), "label": "추자면(위치 옮김)"},
           "attribution": ATTRIBUTION, "source": "vuski/admdongkor ver20261001", "points": npts}
    OUT.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(f"동네 {len(out)}곳, 점 {npts}개, {OUT.stat().st_size / 1024:.0f}KB, viewBox {res['viewBox']}")


if __name__ == "__main__":
    main(sys.argv[1])
