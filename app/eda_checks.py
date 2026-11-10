"""eda_gates.py 결과 중 의심값과 매핑 정확도를 검증한다. 출력: data/interim/eda/checks.json"""
import json, re, sys
from collections import Counter
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from eda_gates import IN, OUT, stores, rest, sd, M, DONGS
from stats import bh, km_at, spearman, wilson
C = {}
# 1. 우편번호 규칙 정확도: 793은 정답 행정동이 있으므로, 여러 행정동으로 나뉘는 법정동에 같은 규칙을 적용해 맞춘다(자기 자신 제외 없이 다수결 → 상한값)
st = stores.dropna(subset=["신우편번호"])
cnt = st.groupby("법정동명")["행정동명"].nunique(); split = cnt[cnt > 1].index
sub = st[st["법정동명"].isin(split)]
vote = sub.groupby(["법정동명", "신우편번호"])["행정동명"].agg(lambda x: x.value_counts().idxmax())
pred = [vote[(a, b)] for a, b in zip(sub["법정동명"], sub["신우편번호"])]
C["postal_rule_acc_793"] = {"n": len(sub), "acc": round(float((np.array(pred) == sub["행정동명"].to_numpy()).mean()), 4), "split_legal": list(split)}
# 2. 612 '최근접 점포' 규칙 정확도: 주소 토큰이 있는 곳에서 두 방법 비교
s = pd.read_parquet(IN / "api" / "612_stations.parquet")
s["lon"], s["lat"] = pd.to_numeric(s["longitude"], errors="coerce"), pd.to_numeric(s["latitude"], errors="coerce")
admin = set(DONGS); xy = stores[["경도", "위도"]].to_numpy(); sdn = stores["행정동명"].to_numpy()
s["tok"] = [next((t for t in str(a or "").split() if t in admin), None) for a in s["stationAddress"]]
ok = s[s["tok"].notna() & s["lon"].notna()]
near = [sdn[np.argmin((xy[:, 0] - a) ** 2 + (xy[:, 1] - b) ** 2)] for a, b in zip(ok["lon"], ok["lat"])]
agree = np.array(near) == ok["tok"].to_numpy()
C["nearest_vs_address_612"] = {"n": len(ok), "agree": round(float(agree.mean()), 4), "disagree_top": Counter(zip(ok["tok"][~agree], np.array(near)[~agree])).most_common(8)}
C["612_좌표없음"] = int(s["lon"].isna().sum())
C["612_우도"] = int(s["stationAddress"].fillna("").str.contains("우도").sum())
# 3. 우도면·버스
C["sd_우도"] = sd[sd["station_name"].str.contains("우도")][["station_name", "users_total", "dong"]].values.tolist()[:10]
C["sd_dong_우도면"] = int((sd["dong"] == "우도면").sum())
# 4. 버스 증감 큰 동네: 정류소별 기여
def by_st(y):
    b = pd.read_parquet(IN / "bus_daily" / f"{y}.parquet")
    return b.groupby("station_name")["user_count"].sum() / b["base_date"].nunique()
a, b = by_st(2023), by_st(2024)
for d in ["정방동", "중앙동", "추자면"]:
    names = sd[sd["dong"] == d]["station_name"]
    t = pd.DataFrame({"y23": a.reindex(names), "y24": b.reindex(names)}).fillna(0)
    t["diff"] = t["y24"] - t["y23"]
    C[f"bus_{d}"] = {"y23": round(t["y23"].sum(), 1), "y24": round(t["y24"].sum(), 1), "top": t.reindex(t["diff"].abs().nlargest(4).index).round(1).reset_index().values.tolist()}
# 정류소명이 해마다 얼마나 바뀌는가
def dong_year(y):
    x = pd.read_parquet(IN / "bus_daily" / f"{y}.parquet").merge(sd[["station_name", "dong", "weight"]], on="station_name")
    return (x["user_count"] * x["weight"]).groupby(x["dong"]).sum() / x["base_date"].nunique()
_g = (dong_year(2024) / dong_year(2023) - 1).sort_values()
C["bus_change_dong"] = {"low": _g.head(4).round(3).to_dict(), "high": _g.tail(5).round(3).to_dict(), "median": round(_g.median(), 3)}
C["bus_names_only_2023"] = int(len(a.index.difference(b.index))); C["bus_names_only_2024"] = int(len(b.index.difference(a.index)))
# 5. 2022 빠진 날
d22 = pd.to_datetime(pd.read_parquet(IN / "bus_daily" / "2022.parquet", columns=["base_date"])["base_date"].unique())
miss = pd.date_range("2022-01-01", "2022-12-31").difference(d22)
C["bus_2022_missing"] = {"n": len(miss), "first": str(miss.min().date()), "last": str(miss.max().date()), "contiguous": bool((miss.max() - miss.min()).days + 1 == len(miss))}
# 6. 폐업률 묶음 안정성
r = rest[rest["admin_dong"].isin(DONGS)]
def pooled(ys):
    k, n = pd.Series(0.0, index=DONGS), pd.Series(0.0, index=DONGS)
    for y in ys:
        s0, e0 = pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y}-12-31")
        n += r[(r["open_date"] < s0) & (r["close_date"].isna() | (r["close_date"] >= s0))].groupby("admin_dong").size().reindex(DONGS).fillna(0)
        k += r[(r["open_date"] < s0) & r["close_date"].between(s0, e0)].groupby("admin_dong").size().reindex(DONGS).fillna(0)
    return k, n
k1, n1 = pooled([2019, 2020, 2021]); k2, n2 = pooled([2022, 2023, 2024])
base = k2.sum() / n2.sum(); ci = [wilson(a0, b0) for a0, b0 in zip(k2, n2)]
lo, hi = np.array(ci).T; rate = k2 / n2
C["close_pooled"] = {"jeju": round(base, 4), "spearman_19_21_vs_22_24": spearman(k1 / n1, rate), "ci_excl": int(((lo > base) | (hi < base)).sum()), "min": round(rate.min(), 4), "q1": round(rate.quantile(.25), 4), "med": round(rate.median(), 4), "q3": round(rate.quantile(.75), 4), "max": round(rate.max(), 4), "low": rate.nsmallest(3).round(4).to_dict(), "high": rate.nlargest(3).round(4).to_dict(), "n_lt_300": n2[n2 < 300].astype(int).to_dict()}
# 7. 생존 곡선 코호트 분할 안정성
end = rest[["open_date", "close_date"]].max().max()
def km3(c0, c1):
    g = r[(r["open_date"] >= c0) & (r["open_date"] <= c1)].copy(); g["e"] = g["close_date"].notna()
    g["y"] = ((g["close_date"].fillna(end) - g["open_date"]).dt.days / 365.25).clip(lower=0)
    return pd.Series({d: km_at(x["y"].to_numpy(), x["e"].to_numpy(), 3)[0] for d, x in g.groupby("admin_dong")})
C["km3_spearman_2015_17_vs_2018_20"] = spearman(km3("2015-01-01", "2017-12-31"), km3("2018-01-01", "2020-12-31"))
# 7-1. 이중 검토 006 지적 확인: 폐업 분자, 5년 추적 가능 코호트, FDR 보정
from math import erfc, sqrt
C["close_numerator_2024"] = {"same_cohort_close_all_mapped": int(M["폐업_2024"].sum()), "all_close_2024_raw": int((rest["close_date"].dt.year == 2024).sum()), "open_and_close_2024": int(((rest["open_date"].dt.year == 2024) & (rest["close_date"].dt.year == 2024)).sum())}
pcl = pd.Series({d: erfc(abs(k2[d] / n2[d] - base) / sqrt(base * (1 - base) / n2[d]) / sqrt(2)) for d in DONGS})
C["close_pooled"]["fdr05"], C["close_pooled"]["fdr10"] = bh(pcl, .05), bh(pcl, .10)
C["close_pooled"]["ci_dongs"] = {d: round(float(rate[d]), 4) for d, l, h in zip(DONGS, lo, hi) if l > base or h < base}
C["close_pooled"]["sel"] = {d: [int(n2[d]), round(float(rate[d]), 4)] for d in ["연동", "노형동", "일도1동", "이도2동", "영천동", "송산동"]}
lim = r[(r["open_date"] >= "2015-01-01") & (r["open_date"] <= "2020-08-30")].copy(); lim["e"] = lim["close_date"].notna()
lim["y"] = ((lim["close_date"].fillna(end) - lim["open_date"]).dt.days / 365.25).clip(lower=0)
kl = {d: km_at(x["y"].to_numpy(), x["e"].to_numpy(), 5) for d, x in lim.groupby("admin_dong")}
kl = pd.DataFrame.from_dict(kl, orient="index", columns=["s5", "se", "n"])
j5, jse, jn = km_at(lim["y"].to_numpy(), lim["e"].to_numpy(), 5)
pk = 2 * pd.Series({d: 0.5 * erfc(abs(v.s5 - j5) / sqrt(v.se ** 2 + 1e-12) / sqrt(2)) for d, v in kl.iterrows()})
C["km_limited"] = {"n": int(jn), "jeju5": round(j5, 4), "spearman_vs_all_cohort": spearman(M["생존5년"], kl["s5"]), "min": round(kl["s5"].min(), 4), "max": round(kl["s5"].max(), 4), "ci_excl": int((((kl["s5"] - 1.96 * kl["se"]) > j5) | ((kl["s5"] + 1.96 * kl["se"]) < j5)).sum()), "fdr05": bh(pk, .05), "fdr10": bh(pk, .10), "high": kl["s5"].nlargest(3).round(3).to_dict(), "low": kl["s5"].nsmallest(3).round(3).to_dict(), "sel_n": kl["n"].reindex(["영천동", "송산동", "이호동", "우도면"]).astype(int).to_dict()}
# 7-2. 모호 이름 후보(612): 터미널 등 / 743 칸 확인 / '우도' 이름 / 일평균
s612 = s[s["stationName"].fillna("").str.contains("제주버스터미널|시민회관")][["stationName", "tok", "stationAddress"]]
C["612_terminal"] = s612.astype(str).values.tolist()[:12]
ud = sd[sd["station_name"].str.contains("우도")]
C["udo_names_total"] = {"names": ud["station_name"].tolist(), "users_total": int(ud["users_total"].sum())}
C["fwer_43"] = round(1 - .95 ** 43, 4)
# 8. 사례 후보
L = lambda c, n=3: (M[c].nlargest(n).round(3).to_dict(), M[c].nsmallest(n).round(3).to_dict())
C["cases"] = {c: L(c) for c in ["LQ_숙박", "LQ_소매", "생존5년", "방문거주비", "근무거주비", "거주_60대이상비중", "버스_경로비중"]}
C["km_n_small"] = M["KM_n"][M["KM_n"] < 150].astype(int).to_dict()
(OUT / "checks.json").write_text(json.dumps(C, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(json.dumps(C, ensure_ascii=False, default=str))
