"""발표 자료(deck.html)용 데이터 → web/deck.js (window.DECK = {...})

실행: python scripts/build_deck.py   (repeat_sales.py, preprocess.py 실행 후)
- 서울 반복매매지수 × 주담대 금리, 월별 거래량
- 금리 변화와 집값 변화의 시차 상관 (금리가 k개월 먼저 움직였을 때)
- 금리 국면별 변화, 구별 5년 상승률, 금리 급등기 하락률·이후 회복률
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
P = ROOT / "data" / "processed"

rs = pd.read_csv(P / "rs_seoul.csv")
sm = pd.read_csv(P / "seoul_month.csv").set_index("ym")
rg = pd.read_csv(P / "rs_gu.csv")
gm = pd.read_csv(P / "gu_month.csv")
months = rs["ym"].tolist()
idx, rate = rs["index"].to_numpy(), rs["mortgage_rate"].to_numpy()


def lag_corr(dx, dy, max_lag=12):
    """금리 변화 dx 가 k개월 먼저일 때 집값 변화 dy 와의 상관계수"""
    out = []
    for k in range(max_lag + 1):
        x, y = (dx[:-k], dy[k:]) if k else (dx, dy)
        m = ~(np.isnan(x) | np.isnan(y))
        out.append(round(float(np.corrcoef(x[m], y[m])[0, 1]), 3))
    return out


# 3개월 변화 기준 (월 단위는 잡음이 커서 3개월 누적 변화로 비교)
d_rate3 = pd.Series(rate).diff(3).to_numpy()
d_price3 = pd.Series(np.log(idx)).diff(3).to_numpy() * 100
d_rate1 = np.diff(rate)
d_price1 = np.diff(np.log(idx)) * 100

phases = [("Ⅰ", "금리 급등기", "2021-09", "2022-10"), ("Ⅱ", "금리 하락기", "2022-10", "2024-07"),
          ("Ⅲ", "금리 반등·정체기", "2024-07", "2025-09"), ("Ⅳ", "금리 재상승기", "2025-09", "2026-08")]
t = rs.set_index("ym")
phase_rows = [{"id": a, "name": n, "start": s, "end": e,
               "d_rate": round(float(t.loc[e, "mortgage_rate"] - t.loc[s, "mortgage_rate"]), 2),
               "d_price": round(float((t.loc[e, "index"] / t.loc[s, "index"] - 1) * 100), 1)}
              for a, n, s, e in phases]

# 구별: 5년 상승률, 금리 급등기 하락률(2021.11→2023.01), 저점 이후 회복률(2023.01→2026.08) — 월별 지수 그대로(이동평균 없음)
p = rg.pivot(index="자치구", columns="ym", values="index")
rise = (p[months[-1]] - 100)
drop = (p["2023-01"] / p["2021-11"] - 1) * 100
reb = (p[months[-1]] / p["2023-01"] - 1) * 100
lvl = gm[gm["ym"] <= "2021-11"].groupby("자치구")["median_ppm"].median()   # 2021.09~11 ㎡당 중위가격
gu = pd.DataFrame({"rise": rise, "drop": drop, "rebound": reb, "lvl": lvl}).round(1)

# 금리가 내린 달 / 오른 달 → 2개월 뒤 집값이 같은 방향(반대 부호)으로 움직인 비율
LAG = 2
x, y = d_rate1[:-LAG], d_price1[LAG:]
cut, hike = x < 0, x > 0
response = {
    "lag": LAG,
    "cut_n": int(cut.sum()), "cut_up": int((y[cut] > 0).sum()), "cut_mean": round(float(y[cut].mean()), 2),
    "hike_n": int(hike.sum()), "hike_down": int((y[hike] < 0).sum()), "hike_mean": round(float(y[hike].mean()), 2),
}
# 시차 0~6개월별: 금리 내린 달 → 집값 오른 비율 / 금리 오른 달 → 집값 내린 비율
by_lag = []
for k in range(0, 7):
    xk, yk = (d_rate1[:-k], d_price1[k:]) if k else (d_rate1, d_price1)
    c, h = xk < 0, xk > 0
    by_lag.append({"lag": k, "cut_n": int(c.sum()), "cut_up_pct": round(float((yk[c] > 0).mean() * 100), 1),
                   "hike_n": int(h.sum()), "hike_down_pct": round(float((yk[h] < 0).mean() * 100), 1)})

# 상관계수가 2022년 급등기 한 번에 좌우되는지 확인: 2021.09~2023.06 을 빼고 다시 계산
mm = np.array(months)
keep = ~((mm >= "2021-09") & (mm <= "2023-06"))
lag3_ex = []
for k in range(0, 7):
    x, y = (d_rate3[:-k], d_price3[k:]) if k else (d_rate3, d_price3)
    ok = ~(np.isnan(x) | np.isnan(y)) & (keep[k:] if k else keep)
    lag3_ex.append(round(float(np.corrcoef(x[ok], y[ok])[0, 1]), 3))

# 저점 기준 금리 하락기 (시차 때문에 집값 바닥은 금리 고점 3개월 뒤)
trough_cut = {"d_rate": round(float(t.loc["2024-07", "mortgage_rate"] - t.loc["2023-01", "mortgage_rate"]), 2),
              "d_price": round(float((t.loc["2024-07", "index"] / t.loc["2023-01", "index"] - 1) * 100), 1)}

# 서울 25개 구 경계 (수업 lecture04 의 통계청 시군구 경계 → 위경도 변환·단순화, data/seoul_gu_boundary.geojson)
# 지도 위 구 이름·상승률 표시 위치 = 각 구 경계의 대표점 (도형 안쪽이 보장되는 점)
geo = json.loads((ROOT / "data" / "seoul_gu_boundary.geojson").read_text(encoding="utf-8"))
try:
    from math import cos, radians
    from shapely.affinity import scale
    from shapely.geometry import shape
    from shapely.ops import polylabel
    # 글자 위치 = 구 안에서 경계선과 가장 먼 점(polylabel). 지도(메르카토르)처럼 경도를 cos(위도)배로 줄여서 계산
    K = cos(radians(37.55))

    def _label(geom):
        g = scale(shape(geom), xfact=K, yfact=1, origin=(0, 0))
        if g.geom_type == "MultiPolygon":
            g = max(g.geoms, key=lambda x: x.area)
        pt = polylabel(g, tolerance=1e-5)
        return pt.x / K, pt.y

    label_pt = {f["properties"]["gu"]: _label(f["geometry"]) for f in geo["features"]}
except ImportError:   # shapely 가 없으면 꼭짓점 평균으로 대신
    def _avg(coords):
        pts = [c for ring in coords for c in ring] if isinstance(coords[0][0][0], float) else [c for poly in coords for ring in poly for c in ring]
        return (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
    label_pt = {f["properties"]["gu"]: _avg(f["geometry"]["coordinates"]) for f in geo["features"]}

# ---------- 전망용: 기준금리와 금리 구간별 반응 ----------
base = pd.read_csv(ROOT / "data" / "base_rate.csv").set_index("month")["base_rate"]   # 한국은행 ECOS 722Y001
vol = sm["n"].reindex(months)
reg = pd.DataFrame({"rate": rate, "idx": idx, "vol": vol.to_numpy()}, index=months)
reg["dr3"] = reg["rate"].diff(3)                                  # 직전 3개월 주담대 금리 변화
reg["idx_fut"] = (reg["idx"].shift(-3) / reg["idx"] - 1) * 100     # 3개월 뒤 집값 변화
REG_TH = 0.3
regimes = []
for key, name, m in [("up", f"금리 상승 (3개월 +{REG_TH}%p 이상)", reg["dr3"] >= REG_TH),
                     ("flat", f"금리 횡보 (±{REG_TH}%p 이내)", reg["dr3"].abs() < REG_TH),
                     ("down", f"금리 하락 (3개월 −{REG_TH}%p 이상)", reg["dr3"] <= -REG_TH)]:
    x = reg[m].dropna(subset=["idx_fut"])
    regimes.append({"key": key, "name": name, "n": int(len(x)),
                    "price_mean": round(float(x["idx_fut"].mean()), 1),
                    "price_up_pct": round(float((x["idx_fut"] > 0).mean() * 100))})
now = {"month": months[-1], "dr3": round(float(reg["dr3"].iloc[-1]), 2),
       "rate": float(rate[-1]), "base": float(base[months[-1]])}

# ---------- 질문 2: 구 × 연도 변화 방향, 가격대·유형별 지수 (segments.py 결과) ----------
YEARS = [("2021-09", "2022-08"), ("2022-08", "2023-08"), ("2023-08", "2024-08"), ("2024-08", "2025-08"), ("2025-08", "2026-08")]
yearly = {g: [round(float((p.loc[g, b] / p.loc[g, a] - 1) * 100), 1) for a, b in YEARS] for g in p.index}
seoul_idx = rs.set_index("ym")["index"]
yearly_seoul = [round(float((seoul_idx[b] / seoul_idx[a] - 1) * 100), 1) for a, b in YEARS]
seg = json.loads((P / "segments.json").read_text(encoding="utf-8"))

deck = {
    "years": [f"{a[2:4]}.{a[5:]}→{b[2:4]}.{b[5:]}" for a, b in YEARS],
    "yearly": yearly,
    "yearly_seoul": yearly_seoul,
    "segments": seg,
    "base_rate": [float(base[m]) for m in months],
    "regimes": regimes,
    "now": now,
    "gu_geo": geo,
    "gu_label": {g: [round(x, 5), round(y, 5)] for g, (x, y) in label_pt.items()},
    "by_lag": by_lag,
    "lag3_ex2022": lag3_ex,
    "response": response,
    "trough_cut": trough_cut,
    "months": months,
    "rate": [float(v) for v in rate],
    "index": [round(float(v), 2) for v in idx],
    "volume": [int(sm.loc[m, "n"]) for m in months],
    "lag3": lag_corr(d_rate3, d_price3),
    "lag1": lag_corr(d_rate1, d_price1),
    "level_corr": round(float(np.corrcoef(idx, rate)[0, 1]), 2),
    "phases": phase_rows,
    "gu": {g: r.to_dict() for g, r in gu.iterrows()},
    "corr_lvl_drop": round(float(np.corrcoef(gu["lvl"], gu["drop"])[0, 1]), 2),
    "corr_lvl_reb": round(float(np.corrcoef(gu["lvl"], gu["rebound"])[0, 1]), 2),
}
(ROOT / "web" / "deck.js").write_text("window.DECK = " + json.dumps(deck, ensure_ascii=False) + ";\n", encoding="utf-8")
print("lag3", deck["lag3"][:7], "level", deck["level_corr"], "lvl~drop", deck["corr_lvl_drop"], "lvl~reb", deck["corr_lvl_reb"])
print(phase_rows)
