"""구별 월간 ㎡당 거래가격 분포 → web/monthly.js

실행: python scripts/build_monthly.py   (seoul-apt-rate 폴더에서)
각 자치구(+서울 전체) × 60개월에 대해 ㎡당 가격(만원)의 분위수(10·25·50·75·90%)와 거래 건수를 계산한다.
"""
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web"
OUT.mkdir(exist_ok=True)

df = pd.read_csv(ROOT / "data" / "seoul_apt_trades_202109_202608.csv", dtype=str)
df = df[df["해제여부"].isna()].copy()
df["ppm"] = df["거래금액(만원)"].astype(float) / df["전용면적(㎡)"].astype(float)
df["ym"] = df["계약일"].str[:7]
months = sorted(df["ym"].unique())

# ---------- 단지 세대수 ----------
# 우선순위: ① K-apt 지번 일치 → ② K-apt 같은 법정동 안 단지명 일치 → ③ 건축물대장(households.py)
# 건축물대장은 동이 여러 지번에 흩어진 오래된 대단지(예: 상계주공)를 적게 잡을 수 있어 K-apt를 우선한다.
def norm(name):
    return re.sub(r"\(.*?\)|아파트|\s", "", str(name))


kapt = pd.read_csv(ROOT / "data" / "kapt.csv", dtype=str)
kapt["세대수"] = pd.to_numeric(kapt["세대수"], errors="coerce")
kapt = kapt[kapt["세대수"] > 0]   # 세대수 0으로 등록된 단지(주상복합 일부 등)는 건축물대장 값으로 대체
by_addr = kapt.groupby(["자치구", "법정동", "지번"])["세대수"].max()
by_name = {}
for r in kapt.itertuples(index=False):
    by_name.setdefault((r.자치구, r.법정동), []).append((norm(r.단지명), r.세대수))

bld = pd.read_csv(ROOT / "data" / "households.csv", dtype=str)
bld = bld.set_index(["자치구", "법정동", "지번"])["세대수"].pipe(pd.to_numeric, errors="coerce")

def households(gu, dong, jibun, apt):
    key = (gu, dong, jibun)
    if key in by_addr.index:
        return by_addr[key], "K-apt 지번"
    n = norm(apt)
    hits = [hh for k, hh in by_name.get((gu, dong), []) if n and k and (n in k or k in n)]
    if len(hits) == 1:
        return hits[0], "K-apt 단지명"
    if key in bld.index and pd.notna(bld[key]):
        return bld[key], "건축물대장"
    return None, "미확인"


units = df[["자치구", "법정동", "지번", "단지명"]].drop_duplicates()
res = [households(*u) for u in units.itertuples(index=False)]
units["세대수"] = [r[0] for r in res]
units["세대수출처"] = [r[1] for r in res]
df = df.merge(units, on=["자치구", "법정동", "지번", "단지명"], how="left")
print("세대수 출처 (거래 건수 기준):", df["세대수출처"].value_counts().to_dict())
df = df.drop(columns="세대수출처")

Q = [0.10, 0.25, 0.50, 0.75, 0.90]


def dist(g):
    s = g.groupby("ym")["ppm"]
    q = s.quantile(Q).unstack().reindex(months)
    n = s.size().reindex(months).fillna(0).astype(int)
    out = {"n": n.tolist()}
    for k, col in zip(["p10", "p25", "p50", "p75", "p90"], Q):
        out[k] = [None if pd.isna(v) else round(v) for v in q[col]]
    return out


def write_trades(gu, code, g):
    """개별 거래(점 + 마우스오버 정보)를 구별 파일 web/trades/<구코드>.js 로 저장.
    file:// 로 열어도 되도록 JSON 대신 <script>로 읽는 JS 파일 형식.
    행 형식: [㎡당가격, 단지번호, 전용면적, 층, 거래금액(만원), 계약일(일)]
    단지 목록 형식: [단지명, 법정동, 세대수(모르면 null)]"""
    apts = g[["단지명", "법정동", "지번", "세대수"]].drop_duplicates(["단지명", "법정동", "지번"]).reset_index(drop=True)
    idx = {k: i for i, k in enumerate(zip(apts["단지명"], apts["법정동"], apts["지번"]))}
    by = {m: [] for m in months}
    for r in g.itertuples(index=False):
        by[r.ym].append([round(r.ppm), idx[(r.단지명, r.법정동, r.지번)], float(r._8), int(r.층),
                         int(r._7), int(r.계약일[-2:])])
    apts = apts.astype(object).where(apts.notna(), None)
    apts["세대수"] = [None if v is None else int(v) for v in apts["세대수"]]
    payload = {"apt": apts[["단지명", "법정동", "세대수"]].values.tolist(), "m": [sorted(by[m]) for m in months]}
    js = (f"window.TRADES = window.TRADES || {{}};\nwindow.TRADES[{json.dumps(gu, ensure_ascii=False)}] = "
          + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n")
    (TRADES_DIR / f"{code}.js").write_text(js, encoding="utf-8")
    return len(js)


TRADES_DIR = OUT / "trades"
TRADES_DIR.mkdir(exist_ok=True)


data = {"months": months, "gu": {"서울 전체": dist(df)}}

# 구 순서: 5년 상승률 높은 순. 상승률은 반복매매지수(같은 단지·같은 평형 비교, repeat_sales.py 결과)의
# 마지막 달 3개월 평균 지수 기준 (2021.09 = 100) — 그달 어떤 집이 팔렸는지에 흔들리지 않음
rs_gu = pd.read_csv(ROOT / "data" / "processed" / "rs_gu.csv")
rs_seoul = pd.read_csv(ROOT / "data" / "processed" / "rs_seoul.csv")
rise = (rs_gu[rs_gu["ym"] == months[-1]].set_index("자치구")["index"] - 100).round(1)
order = rise.sort_values(ascending=False).index.tolist()
data["rise"] = rise.to_dict()
data["rise"]["서울 전체"] = round(float(rs_seoul["index"].iloc[-1]) - 100, 1)
data["codes"] = {}
trade_bytes = 0
for gu in order:
    sub = df[df["자치구"] == gu]
    data["gu"][gu] = dist(sub)
    code = sub["자치구코드"].iloc[0]
    data["codes"][gu] = code
    trade_bytes += write_trades(gu, code, sub)
data["order"] = ["서울 전체"] + order

# 단지 검색 목록: [단지명, 법정동, 자치구, 거래 건수, K-apt 공식 단지명(별칭)] — 거래 많은 순
# 실거래 단지명이 짧게 등록된 경우(예: 잠원동 157 "동아" = K-apt "잠원동아")를 위해 같은 지번의 K-apt 이름을 별칭으로 붙임
kapt_name = kapt.groupby(["자치구", "법정동", "지번"])["단지명"].first()
alias = {}
for (apt, dong, gu, jibun) in df[["단지명", "법정동", "자치구", "지번"]].drop_duplicates().itertuples(index=False):
    kn = kapt_name.get((gu, dong, jibun))
    if isinstance(kn, str) and norm(kn) != norm(apt):
        alias[(apt, dong, gu)] = kn.strip()
srch = df.groupby(["단지명", "법정동", "자치구"]).size().sort_values(ascending=False).reset_index(name="n")
srch["별칭"] = [alias.get(k, "") for k in zip(srch["단지명"], srch["법정동"], srch["자치구"])]
data["search"] = srch.values.tolist()
print(f"검색 별칭(K-apt 공식 단지명) {sum(1 for v in srch['별칭'] if v):,}개 단지")

# 시장금리: 예금은행 주택담보대출 금리 (신규취급액 기준, 한국은행 ECOS 121Y006)
rate = pd.read_csv(ROOT / "data" / "mortgage_rate.csv").set_index("month")["mortgage_rate"]
data["rate"] = [float(rate[m]) for m in months]
print(f"web/trades/*.js 합계 {trade_bytes / 1024 / 1024:.1f} MB")

js = "window.MONTHLY = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"
(OUT / "monthly.js").write_text(js, encoding="utf-8")
print(f"web/monthly.js {len(js) / 1024:.0f} KB · {len(order)}개 구 × {len(months)}개월")
