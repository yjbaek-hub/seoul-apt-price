"""실거래 원자료 + 주담대 금리 → 분석용 패널 데이터셋

실행: python scripts/preprocess.py   (seoul-apt-rate 폴더에서, geocode.py 실행 후)
출력 (data/processed/):
  seoul_month.csv  서울 전체 × 월
  gu_month.csv     자치구 × 월
  dong_month.csv   행정동 × 월 (3개월 이동 집계 포함)
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "processed"
OUT.mkdir(exist_ok=True)

BASE = "2021-09"     # 지수 기준월 (=100)
DONG_MIN_N = 10      # 행정동 3개월 이동 집계의 최소 표본 수

# ---------- 원자료 ----------
df = pd.read_csv(DATA / "seoul_apt_trades_202109_202608.csv", dtype=str)
n_raw = len(df)
df = df[df["해제여부"].isna()].copy()
df["price"] = df["거래금액(만원)"].astype(float)
df["area"] = df["전용면적(㎡)"].astype(float)
df["ppm"] = df["price"] / df["area"]                      # 만원/㎡
df["ym"] = df["계약일"].str[:7]

geo = pd.read_csv(DATA / "geocode.csv", dtype=str)
df = df.merge(geo[["자치구", "법정동", "지번", "행정동코드", "행정동"]],
              on=["자치구", "법정동", "지번"], how="left")
# 구 경계 부근에서 이웃 구의 행정동으로 잡힌 경우(코드 앞 5자리 ≠ 거래 자치구 코드)는 매핑 실패로 처리
bad = df["행정동코드"].notna() & (df["행정동코드"].str[:5] != df["자치구코드"])
df.loc[bad, ["행정동코드", "행정동"]] = np.nan
print(f"이웃 구 행정동으로 잡힌 거래 {bad.sum():,}건 제외")

rate = pd.read_csv(DATA / "mortgage_rate.csv").rename(columns={"month": "ym"})
months = rate["ym"].tolist()

print(f"원자료 {n_raw:,}건 → 해제 제외 {len(df):,}건, 행정동 매핑 실패 {df['행정동'].isna().sum():,}건")


def summarize(g):
    return pd.Series({
        "n": len(g),
        "median_ppm": g["ppm"].median(),
        "mean_ppm": g["ppm"].mean(),
        "median_price": g["price"].median(),
    })


def finish(panel, keys):
    """지수화, 전월 대비 변동률, 3개월 이동평균, 금리 결합"""
    panel = panel.sort_values(keys + ["ym"]).reset_index(drop=True)
    grp = panel.groupby(keys, sort=False) if keys else None

    def per(s, fn):
        return grp[s].transform(fn) if keys else fn(panel[s])

    base = per("median_ppm", lambda s: s.where(panel.loc[s.index, "ym"] == BASE).ffill().bfill())
    panel["index"] = panel["median_ppm"] / base * 100
    panel["mom_pct"] = per("median_ppm", lambda s: s.pct_change() * 100)
    panel["median_ppm_ma3"] = per("median_ppm", lambda s: s.rolling(3, min_periods=3).mean())
    panel["index_ma3"] = per("index", lambda s: s.rolling(3, min_periods=3).mean())
    panel = panel.merge(rate, on="ym", how="left")
    return panel


def full_grid(panel, keys, levels):
    """거래가 없는 월도 행을 남김 (n=0)"""
    idx = pd.MultiIndex.from_product(levels + [months], names=keys + ["ym"])
    return panel.set_index(keys + ["ym"]).reindex(idx).reset_index().fillna({"n": 0})


# ---------- 서울 전체 ----------
seoul = df.groupby("ym").apply(summarize, include_groups=False).reset_index()
seoul = finish(seoul, [])
seoul.to_csv(OUT / "seoul_month.csv", index=False, encoding="utf-8-sig")

# ---------- 자치구 ----------
gu = df.groupby(["자치구", "ym"]).apply(summarize, include_groups=False).reset_index()
gu = full_grid(gu, ["자치구"], [sorted(df["자치구"].unique())])
gu = finish(gu, ["자치구"])
gu.to_csv(OUT / "gu_month.csv", index=False, encoding="utf-8-sig")

# ---------- 행정동 ----------
# 월별 표본이 희소하므로 t-2 ~ t 3개월 거래를 합쳐 중위값을 산출 (pooled rolling median)
dd = df.dropna(subset=["행정동"])
dong_keys = dd[["자치구", "행정동코드", "행정동"]].drop_duplicates().sort_values(["자치구", "행정동"])
mi = {m: i for i, m in enumerate(months)}
dd = dd.assign(t=dd["ym"].map(mi))

rows = []
for code, g in dd.groupby("행정동코드"):
    by_t = {t: x["ppm"].to_numpy() for t, x in g.groupby("t")}
    for t, m in enumerate(months):
        cur = by_t.get(t, np.array([]))
        pool = np.concatenate([by_t.get(k, np.array([])) for k in (t - 2, t - 1, t)])
        rows.append({
            "행정동코드": code, "ym": m,
            "n": len(cur),
            "median_ppm": np.median(cur) if len(cur) else np.nan,
            "n_3m": len(pool),
            "median_ppm_3m": np.median(pool) if len(pool) >= DONG_MIN_N and t >= 2 else np.nan,
        })
dong = pd.DataFrame(rows).merge(dong_keys, on="행정동코드")
base = dong[dong["ym"] == "2021-11"].set_index("행정동코드")["median_ppm_3m"]  # 첫 3개월 이동 집계 시점
dong["index_3m"] = dong["median_ppm_3m"] / dong["행정동코드"].map(base) * 100
dong = dong.merge(rate, on="ym", how="left")
dong = dong[["자치구", "행정동코드", "행정동", "ym", "n", "median_ppm", "n_3m", "median_ppm_3m", "index_3m", "mortgage_rate"]]
dong.to_csv(OUT / "dong_month.csv", index=False, encoding="utf-8-sig")

# ---------- 요약 ----------
print(f"서울 × 월: {len(seoul)}행 | 자치구 × 월: {len(gu)}행 | 행정동 × 월: {len(dong)}행 ({dong['행정동코드'].nunique()}개 행정동)")
ok = dong.groupby("행정동코드")["median_ppm_3m"].apply(lambda s: s.notna().mean())
print(f"행정동 중 3개월 이동 집계가 80% 이상 산출되는 곳: {(ok >= .8).sum()}개 / {len(ok)}개")
s = seoul.set_index("ym")
print(f"서울 ㎡당 중위가격: {s.loc[BASE, 'median_ppm']:.0f} → {s.loc[months[-1], 'median_ppm']:.0f} 만원 "
      f"(지수 {s.loc[months[-1], 'index']:.1f})")
