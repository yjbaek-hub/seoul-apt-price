"""단지 용적률 수집: 실거래 주소(자치구·법정동·지번) → 건축물대장(건축HUB) 용적률(vlRat) → data/far.csv

실행: python scripts/far.py   (seoul-apt-rate 폴더에서, households.py 와 같은 키·법정동 코드 사용)
1) 총괄표제부(getBrRecapTitleInfo)의 용적률 — 여러 동으로 된 단지 전체 기준
2) 총괄표제부에 없거나 0이면 표제부(getBrTitleInfo) 주건축물 중 가장 큰 값
중단 후 다시 실행하면 받은 주소는 건너뛴다. '오류'(요청 제한 등)는 다시 시도한다.
"""
import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

import households as h   # call(), BJD, BJD_BY_NAME, parse_jibun 재사용

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "far.csv"
FIELDS = ["자치구", "법정동", "지번", "용적률", "출처"]


def lookup(row):
    gu, dong, jibun = row
    codes = h.BJD.get((gu, dong)) or h.BJD_BY_NAME.get(dong)
    pj = h.parse_jibun(jibun)
    if not codes or not pj:
        return [gu, dong, jibun, "", "주소해석불가"]
    args = dict(sigunguCd=codes[0], bjdongCd=codes[1], platGbCd=pj[0], bun=pj[1], ji=pj[2])
    recap = h.call("getBrRecapTitleInfo", **args)
    if recap is None:
        return [gu, dong, jibun, "", "오류"]
    v = max([float(x.get("vlRat") or 0) for x in recap] or [0])
    if v > 0:
        return [gu, dong, jibun, round(v, 1), "총괄표제부"]
    title = h.call("getBrTitleInfo", **args)
    if title is None:
        return [gu, dong, jibun, "", "오류"]
    main = [x for x in title if x.get("mainAtchGbCd") == "0"]
    v = max([float(x.get("vlRat") or 0) for x in main] or [0])
    return [gu, dong, jibun, round(v, 1) if v > 0 else "", "표제부" if v > 0 else "용적률없음"]


def main():
    g = pd.read_csv(ROOT / "data" / "geocode.csv", dtype=str)
    addrs = list(g[["자치구", "법정동", "지번"]].drop_duplicates().itertuples(index=False, name=None))
    done = set()
    if OUT.exists():
        prev = pd.read_csv(OUT, dtype=str)
        prev = prev[prev["출처"] != "오류"]
        done = set(zip(prev["자치구"], prev["법정동"], prev["지번"]))
        prev.to_csv(OUT, index=False, encoding="utf-8-sig")
    todo = [a for a in addrs if a not in done]
    print(f"전체 {len(addrs)}개 주소, 남은 {len(todo)}개", flush=True)
    new_file = not OUT.exists()
    with open(OUT, "a", newline="", encoding="utf-8-sig") as f, ThreadPoolExecutor(max_workers=2) as pool:
        w = csv.writer(f)
        if new_file:
            w.writerow(FIELDS)
        for i, res in enumerate(pool.map(lookup, todo), 1):
            w.writerow(res)
            if i % 200 == 0:
                f.flush()
                print(f"{i}/{len(todo)}", flush=True)
    print(pd.read_csv(OUT, dtype=str)["출처"].value_counts().to_string(), flush=True)


if __name__ == "__main__":
    main()
