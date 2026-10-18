"""매매가 쪼개 보기: 건축연도·가격대·평형별 반복매매지수 + 2021년 고점 회복률 → data/processed/segments.json

실행: python scripts/segments.py   (seoul-apt-rate 폴더에서)
- 그룹별 지수는 repeat_sales.py 와 같은 방법(같은 단지·같은 평형 고정효과, 2021.09 = 100)
- 가격대는 대출 규제선 기준(9억·15억·25억, 이하/초과), 단지·평형의 출발 시점(2021.09~2022.08) 중위 거래가로 고정
  (5년 평균으로 나누면 많이 오른 단지가 비싼 구간으로 옮겨 가 고가 구간이 좋아 보이는 편향이 생김)
  출발 시점에 거래가 없던 단지·평형은 가격대 분석에서 빠짐
- 전용면적은 60㎡ 미만 / 60~85㎡ 미만 / 85㎡ 이상, 용적률은 건축물대장 값(data/far.csv, 없는 단지는 용적률 분석에서 빠짐)
- 고점 회복: 2021.09~2022.06(고점 구간) 중위 거래가 vs 2026.03~08 중위 거래가, 두 시기 모두 거래된 단지·평형만
  (최고가끼리 비교하면 최근 거래가 많은 단지가 유리해지는 편향이 있어 중위가로 비교)
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "processed" / "segments.json"

df = pd.read_csv(ROOT / "data" / "seoul_apt_trades_202109_202608.csv", dtype=str)
df = df[df["해제여부"].isna()].copy()
df["price"] = df["거래금액(만원)"].astype(float)
df["lnp"] = np.log(df["price"])
df["area_raw"] = df["전용면적(㎡)"].astype(float)
df["area"] = df["area_raw"].round()
df["built"] = pd.to_numeric(df["건축연도"], errors="coerce")
df["ym"] = df["계약일"].str[:7]
months = sorted(df["ym"].unique())
mi = {m: i for i, m in enumerate(months)}
df["t"] = df["ym"].map(mi)
UNIT = ["자치구", "법정동", "지번", "단지명", "area"]

# 그룹 정의 (단지·평형 단위로 고정)
start_price = df[df["ym"].between("2021-09", "2022-08")].groupby(UNIT)["price"].median().rename("start_price")
df = df.join(start_price, on=UNIT)
df["g_built"] = pd.cut(df["built"], [0, 1995, 2005, 2015, 2100],
                       labels=["1995년 이전", "1996~2005년", "2006~2015년", "2016년 이후 (신축)"])
# 번외: 2026.08 기준 연식 5구간. 실거래 자료의 건축연도는 '연도'만 있어 월(08/09) 경계 대신 연도로 나눔
#   (40년 이상 = 1986년 이전, 30년 이상 = 1987~1996, 20년 이상 = 1997~2006, 10년 이상 = 2007~2016, 10년 미만 = 2017년 이후)
df["g_age5"] = pd.cut(df["built"], [0, 1986, 1996, 2006, 2016, 2100],
                      labels=["40년 이상 (~1986)", "30년 이상 (1987~1996)", "20년 이상 (1997~2006)", "10년 이상 (2007~2016)", "10년 미만 (2017~)"])
# 경계는 대출 규제와 같이 "이하 / 초과" (10·15 대책: 15억 이하 6억, 15억 초과~25억 이하 4억, 25억 초과 2억 / 9억 = 고가주택 기준)
df["g_price"] = pd.cut(df["start_price"], [0, 90000, 150000, 250000, 1e9], right=True,
                       labels=["9억 이하", "9억 초과~15억 이하", "15억 초과~25억 이하", "25억 초과"])
# 전용면적: 60㎡ 미만 / 60㎡ 이상~85㎡ 미만 / 85㎡ 이상 (반올림 전 면적 기준 — 59.9㎡가 60㎡로 올라가지 않도록)
df["g_area"] = pd.cut(df["area_raw"], [0, 60, 85, 1000], right=False, labels=["60㎡ 미만", "60~85㎡ 미만", "85㎡ 이상"])
# 용적률: 건축물대장(far.py → data/far.csv), 주소(자치구·법정동·지번) 단위
FAR_LABELS = ["200% 이하", "200% 초과~250% 이하", "250% 초과~300% 이하", "300% 초과"]
def _far(name):
    t = pd.read_csv(ROOT / "data" / name, dtype=str).dropna(subset=["용적률"])
    t = t.drop_duplicates(["자치구", "법정동", "지번"]).set_index(["자치구", "법정동", "지번"])["용적률"].astype(float)
    return t[t.between(50, 1000)]   # 50% 미만·1,000% 초과(예: 249,024%)는 입력 오류로 보고 제외
far = _far("far.csv")                      # 건축물대장 용적률
calc_path = ROOT / "data" / "far_calc.csv"   # 대장에 없던 단지: 연면적 ÷ 대지면적(V-World 토지대장)으로 계산 (far_fill.py)
if calc_path.exists():
    calc = _far("far_calc.csv")
    far = pd.concat([far, calc[~calc.index.isin(far.index)]])
df = df.join(far.rename("far"), on=["자치구", "법정동", "지번"])
df["g_far"] = pd.cut(df["far"], [0, 200, 250, 300, 1e5], right=True, labels=FAR_LABELS)
# 번외: 용적률 5구간 (미만 / 이상 경계)
df["g_far5"] = pd.cut(df["far"], [0, 150, 200, 250, 300, 1e5], right=False,
                      labels=["150% 미만", "150~200% 미만", "200~250% 미만", "250~300% 미만", "300% 이상"])

# 연식 × 용적률 비교는 100세대 이상 단지만 (세대수: build_monthly.py 와 같은 순서 — K-apt 지번 → K-apt 단지명 → 건축물대장)
HH_MIN = 100
import re
norm = lambda n: re.sub(r"\(.*?\)|아파트|\s", "", str(n))
kapt = pd.read_csv(ROOT / "data" / "kapt.csv", dtype=str)
kapt["세대수"] = pd.to_numeric(kapt["세대수"], errors="coerce")
kapt = kapt[kapt["세대수"] > 0]
by_addr = kapt.groupby(["자치구", "법정동", "지번"])["세대수"].max()
by_name = {}
for r in kapt.itertuples(index=False):
    by_name.setdefault((r.자치구, r.법정동), []).append((norm(r.단지명), r.세대수))
bld = pd.read_csv(ROOT / "data" / "households.csv", dtype=str).set_index(["자치구", "법정동", "지번"])["세대수"].pipe(pd.to_numeric, errors="coerce")
bld = bld[~bld.index.duplicated()]
def households(gu, dong, jibun, apt):
    if (gu, dong, jibun) in by_addr.index:
        return by_addr[(gu, dong, jibun)]
    n = norm(apt)
    hits = [hh for k, hh in by_name.get((gu, dong), []) if n and k and (n in k or k in n)]
    if len(hits) == 1:
        return hits[0]
    return bld.get((gu, dong, jibun), np.nan)
cu = df[["자치구", "법정동", "지번", "단지명"]].drop_duplicates()
cu["hh"] = [households(*u) for u in cu.itertuples(index=False)]
df["hh"] = pd.MultiIndex.from_frame(df[["자치구", "법정동", "지번", "단지명"]]).map(cu.set_index(["자치구", "법정동", "지번", "단지명"])["hh"])

# 지수: 같은 단지·평형 안의 모든 거래를 한꺼번에 비교하는 고정효과 회귀 (fe_index.py, repeat_sales.py 와 같은 방법)
from fe_index import fe_index

df["unit"] = df[UNIT].astype(str).agg("|".join, axis=1)


def index_of(d):
    idx, n = fe_index(d["unit"], d["t"], d["lnp"], len(months))
    return pd.Series(idx, index=months), n                 # (월별 지수, 쓰인 거래 수)


out = {"months": months, "groups": {}}
for col, title in [("g_built", "건축연도"), ("g_price", "가격대"), ("g_area", "평형"), ("g_far", "용적률"), ("g_age5", "연식5"), ("g_far5", "용적률5")]:
    out["groups"][title] = []
    for name, p in df.groupby(col, observed=True):
        s, n = index_of(p)
        out["groups"][title].append({
            "name": str(name), "pairs": int(n),
            "index": [round(float(v), 2) for v in s],
            "trough": round(float(s.min()), 1), "trough_month": s.idxmin(),
            "now": round(float(s.iloc[-1]), 1),
            "since_2407": round(float((s.iloc[-1] / s["2024-07"] - 1) * 100), 1),   # 금리 반등 이후(2024.07 → 2026.08)
        })

# 2021년 고점 회복
early = df[df["ym"].between("2021-09", "2022-06")].groupby(UNIT)["price"].median().rename("peak")
late = df[df["ym"].between("2026-03", "2026-08")].groupby(UNIT)["price"].median().rename("recent")
both = pd.concat([early, late], axis=1, join="inner").reset_index()
both["recovered"] = both["recent"] >= both["peak"]
by_gu = both.groupby("자치구")["recovered"].agg(["mean", "size"]).sort_values("mean", ascending=False)
out["recovery"] = {
    "units": int(len(both)), "share": round(float(both["recovered"].mean() * 100), 1),
    "by_gu": [{"gu": g, "share": round(float(r["mean"] * 100), 1), "n": int(r["size"])} for g, r in by_gu.iterrows()],
}
built_unit = df.groupby(UNIT)["g_built"].first()
price_unit = df.groupby(UNIT)["g_price"].first()
area_unit = df.groupby(UNIT)["g_area"].first()
far_unit = df.groupby(UNIT)["g_far"].first()
age5_unit = df.groupby(UNIT)["g_age5"].first()
far5_unit = df.groupby(UNIT)["g_far5"].first()
both = both.join(built_unit, on=UNIT).join(price_unit, on=UNIT).join(area_unit, on=UNIT).join(far_unit, on=UNIT).join(age5_unit, on=UNIT).join(far5_unit, on=UNIT)
out["recovery"]["by_built"] = {str(k): round(float(v * 100), 1) for k, v in both.groupby("g_built", observed=True)["recovered"].mean().items()}
out["recovery"]["by_area"] = {str(k): round(float(v * 100), 1) for k, v in both.groupby("g_area", observed=True)["recovered"].mean().items()}
out["recovery"]["by_far"] = {str(k): round(float(v * 100), 1) for k, v in both.groupby("g_far", observed=True)["recovered"].mean().items()}
out["recovery"]["by_age5"] = {str(k): round(float(v * 100), 1) for k, v in both.groupby("g_age5", observed=True)["recovered"].mean().items()}
out["recovery"]["by_far5"] = {str(k): round(float(v * 100), 1) for k, v in both.groupby("g_far5", observed=True)["recovered"].mean().items()}
out["far_coverage"] = round(float(df["far"].notna().mean() * 100), 1)   # 용적률을 찾은 거래 비율
out["recovery"]["by_price"] = {str(k): round(float(v * 100), 1) for k, v in both.groupby("g_price", observed=True)["recovered"].mean().items()}

# 연식 × 용적률 격자: 칸마다 지수 (쓰인 거래가 적은 칸은 값이 흔들리므로 표시만 흐리게)
MIN_PAIRS = 1500
# 연식 5구간 × 용적률 5구간 (번외 장과 같은 구분)
B_LABELS = [str(x) for x in df["g_age5"].cat.categories]
F_LABELS = [str(x) for x in df["g_far5"].cat.categories]
cross = {"rows": B_LABELS, "cols": F_LABELS, "min_pairs": MIN_PAIRS, "hh_min": HH_MIN, "now": [], "pairs": []}
for b in B_LABELS:
    row_now, row_n = [], []
    for f in F_LABELS:
        si, n = index_of(df[(df["g_age5"] == b) & (df["g_far5"] == f) & (df["hh"] >= HH_MIN)])
        row_n.append(int(n))
        row_now.append(round(float(si.iloc[-1]), 1) if n >= 200 else None)
    cross["now"].append(row_now); cross["pairs"].append(row_n)
out["cross_built_far"] = cross

# 번외: 준공 연도 10구간(5년) × 용적률 8구간(50%p) — 30세대 이상 (세대수 모르는 단지 제외)
#   연도는 양 끝 포함(1981~1985 = 1981년부터 1985년까지), 용적률은 '이상~미만'
A10 = ["~1980", "1981~1985", "1986~1990", "1991~1995", "1996~2000", "2001~2005", "2006~2010", "2011~2015", "2016~2020", "2021~"]
F10 = ["100% 미만", "100~150", "150~200", "200~250", "250~300", "300~350", "350~400", "400% 이상"]
df["g_a10"] = pd.cut(df["built"], [0, 1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2100], labels=A10)
df["g_f10"] = pd.cut(df["far"], [0, 100, 150, 200, 250, 300, 350, 400, 1e5], right=False, labels=F10)
HH10 = 30
c10 = {"rows": A10, "cols": F10, "min_pairs": MIN_PAIRS, "hh_min": HH10, "now": [], "pairs": []}
big = df[df["hh"] >= HH10]
for a_ in A10:
    row_now, row_n = [], []
    for f_ in F10:
        si, n = index_of(big[(big["g_a10"] == a_) & (big["g_f10"] == f_)])
        row_n.append(int(n))
        row_now.append(round(float(si.iloc[-1]), 1) if n >= 200 and pd.notna(si.iloc[-1]) else None)
    c10["now"].append(row_now); c10["pairs"].append(row_n)
out["cross10"] = c10

# 단지 산점도: 단지(주소)별 ㎡당 중위가 2021.09~2022.08 → 2025.09~2026.08, 두 시기 모두 5건 이상 거래된 단지
ADDR = ["자치구", "법정동", "지번"]
df["ppm"] = df["price"] / df["area_raw"]
e = df[df["ym"].between("2021-09", "2022-08")].groupby(ADDR)["ppm"].agg(["median", "size"])
l = df[df["ym"].between("2025-09", "2026-08")].groupby(ADDR)["ppm"].agg(["median", "size"])
cx = e.join(l, lsuffix="_e", rsuffix="_l", how="inner")
cx = cx[(cx["size_e"] >= 5) & (cx["size_l"] >= 5)]
info = df.groupby(ADDR).agg(name=("단지명", "first"), built=("built", "median"), far=("far", "first"), hh=("hh", "max"))
cx = cx.join(info).dropna(subset=["built", "far"])
cx = cx[cx["hh"] >= HH_MIN]
cx["chg"] = (cx["median_l"] / cx["median_e"] - 1) * 100
out["complex_scatter"] = {
    "n": int(len(cx)),
    "gu": [k[0] for k in cx.index], "name": cx["name"].tolist(),
    "hh_min": HH_MIN, "hh": [int(v) for v in cx["hh"]],
    "built": [int(v) for v in cx["built"]], "far": [round(float(v), 1) for v in cx["far"]],
    "chg": [round(float(v), 1) for v in cx["chg"]],
}

OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
for title, rows in out["groups"].items():
    print(f"\n[{title}]")
    for r in rows:
        print(f"  {r['name']:<22} 거래 {r['pairs']:>6,} | 저점 {r['trough']} ({r['trough_month']}) | 2026.08 {r['now']} | 2024.07→2026.08 {r['since_2407']:+.1f}%")
rc = out["recovery"]
print(f"\n[2021년 고점 회복] {rc['units']:,}개 단지·평형 중 {rc['share']}%")
print("  건축연도별:", rc["by_built"]); print("  가격대별:", rc["by_price"])
print("[연식×용적률]", out["cross_built_far"]["now"], out["cross_built_far"]["pairs"])
print("[단지 산점도]", out["complex_scatter"]["n"], "단지")
print("  상위 구:", [(x['gu'], x['share']) for x in rc["by_gu"][:5]]); print("  하위 구:", [(x['gu'], x['share']) for x in rc["by_gu"][-5:]])
