"""반복매매지수: 같은 단지·같은 평형의 거래가 변화로 월별 가격지수를 추정

실행: python scripts/repeat_sales.py   (seoul-apt-rate 폴더에서)

방법 (반복매매 계열, 고정효과 회귀):
  같은 '주택 유형'(자치구·법정동·지번·단지명·전용면적 반올림)의 모든 거래에 대해
      ln(P) = 유형 고유값 + b_월 + e
  를 최소제곱으로 풀어 월별 로그 지수 b_월 을 구한다 (기준월 b = 0 → 지수 100). 같은 유형 안의 모든 거래끼리 비교하는 셈.
  → 그달 어떤 집이 팔렸는지(구성 효과)에 영향을 받지 않는다.
출력 (data/processed/):
  rs_seoul.csv  서울 전체 월별 지수
  rs_gu.csv     자치구별 월별 지수
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "processed"
OUT.mkdir(exist_ok=True)

df = pd.read_csv(DATA / "seoul_apt_trades_202109_202608.csv", dtype=str)
df = df[df["해제여부"].isna()].copy()
df["lnp"] = np.log(df["거래금액(만원)"].astype(float))
df["area"] = df["전용면적(㎡)"].astype(float).round()
df["date"] = df["계약일"]
months = sorted(df["계약일"].str[:7].unique())
mi = {m: i for i, m in enumerate(months)}
df["t"] = df["계약일"].str[:7].map(mi)

unit = ["자치구", "법정동", "지번", "단지명", "area"]
df = df.sort_values(unit + ["date"])

# 같은 단지·평형 안의 모든 거래를 한꺼번에 비교 (fe_index.py — 고정효과 회귀)
# ※ 예전 방식(바로 앞 거래와만 비교, 같은 달 쌍 제외)은 같은 달 안의 가격 변화를 버려 상승·하락 폭을 작게 잡았음
#   (2022년 서울 연간: 예전 −17.3% vs 이 방식 −21.7% vs 한국부동산원 실거래가격지수 −21.78%)
from fe_index import fe_index

df["unit"] = df[unit].astype(str).agg("|".join, axis=1)


def estimate(d):
    idx, n = fe_index(d["unit"], d["t"], d["lnp"], len(months))
    support = np.bincount(d["t"], minlength=len(months))
    return pd.DataFrame({"ym": months, "index": idx, "trades": support})


print(f"거래 {len(df):,}건 (같은 단지·평형 고정효과 지수)")


def add_cols(r):
    r["index_ma3"] = r["index"].rolling(3, min_periods=1).mean()
    r["mom_pct"] = r["index"].pct_change() * 100
    return r


rate = pd.read_csv(DATA / "mortgage_rate.csv").rename(columns={"month": "ym"})

seoul = add_cols(estimate(df)).merge(rate, on="ym")
seoul.to_csv(OUT / "rs_seoul.csv", index=False, encoding="utf-8-sig")

gus = []
for gu, p in df.groupby("자치구"):
    r = add_cols(estimate(p))
    r.insert(0, "자치구", gu)
    gus.append(r)
gu = pd.concat(gus).merge(rate, on="ym")
gu.to_csv(OUT / "rs_gu.csv", index=False, encoding="utf-8-sig")

# ---------- 요약 ----------
s = seoul.set_index("ym")["index"]
print("\n서울 반복매매지수 (2021-09 = 100)")
for m in ["2021-09", "2022-06", "2022-12", "2023-06", "2024-06", "2025-06", "2025-12", "2026-08"]:
    print(f"  {m}: {s[m]:6.1f}")
lo = s.idxmin()
print(f"  최저점 {lo} ({s[lo]:.1f}) → 최종 {s.iloc[-1]:.1f}")

last = gu[gu["ym"] == months[-1]].set_index("자치구")["index"].sort_values(ascending=False)
print("\n자치구별 2026-08 지수")
print(last.round(1).to_string())
