"""용적률 빈칸 채우기: 건축물대장에 용적률이 없는 주소(far.csv 의 '용적률없음' 등) → 직접 계산 → data/far_calc.csv

용적률 = 용적률 산정용 연면적 ÷ 대지면적 × 100
- 연면적: 건축물대장 총괄표제부 vlRatEstmTotArea(용적률 산정용 연면적), 없으면 표제부 주건축물 합,
          그것도 0이면 총괄표제부 totArea(지하 포함 연면적 → 약간 크게 나옴, 출처에 표시)
- 대지면적: 건축물대장의 platArea 가 오래된 단지는 0이라, V-World 토지대장(ladfrlList)의 필지 면적 사용.
  단지가 여러 필지에 걸쳐 있으면 건축물대장 부속지번(getBrAtchJibunInfo)의 필지 면적을 모두 더함
  (그래도 빠진 필지가 있으면 용적률이 크게 나올 수 있음 → segments.py 에서 50~1000% 범위 밖은 제외)
실행: python scripts/far_fill.py   (키: 클로드\\.env 의 VWORLD_KEY, 건축HUB 키는 households.py 와 같음)
"""
import csv
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

import households as h

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "far_calc.csv"
FIELDS = ["자치구", "법정동", "지번", "용적률", "출처", "연면적", "대지면적", "필지수"]
ENV = ROOT.parent / ".env"
VKEY = next(l.split("=", 1)[1].strip() for l in ENV.read_text(encoding="utf-8").splitlines() if l.startswith("VWORLD_KEY="))


def land_area(sigungu, bjdong, plat_gb, bun, ji):
    pnu = sigungu + bjdong + ("2" if plat_gb == "1" else "1") + bun + ji   # 건축HUB 대지구분 1 = 산
    q = urllib.parse.urlencode(dict(key=VKEY, pnu=pnu, format="json", numOfRows=5, pageNo=1, domain="http://localhost"))
    for _ in range(3):
        try:
            r = json.loads(urllib.request.urlopen(f"https://api.vworld.kr/ned/data/ladfrlList?{q}", timeout=20).read())
            rows = r["ladfrlVOList"]["ladfrlVOList"]
            return float(rows[0]["lndpclAr"]) if rows else 0.0
        except Exception:
            continue
    return None


def lookup(row):
    gu, dong, jibun = row
    codes = h.BJD.get((gu, dong)) or h.BJD_BY_NAME.get(dong)
    pj = h.parse_jibun(jibun)
    if not codes or not pj:
        return [gu, dong, jibun, "", "주소해석불가", "", ""]
    args = dict(sigunguCd=codes[0], bjdongCd=codes[1], platGbCd=pj[0], bun=pj[1], ji=pj[2])
    recap = h.call("getBrRecapTitleInfo", **args)
    if recap is None:
        return [gu, dong, jibun, "", "오류", "", ""]
    area, src = max([float(x.get("vlRatEstmTotArea") or 0) for x in recap] or [0]), "용적률산정연면적"
    if area <= 0:
        title = h.call("getBrTitleInfo", **args) or []
        area = sum(float(x.get("vlRatEstmTotArea") or 0) for x in title if x.get("mainAtchGbCd") == "0")
    if area <= 0:
        area, src = max([float(x.get("totArea") or 0) for x in recap] or [0]), "연면적(지하 포함)"
    if area <= 0:
        return [gu, dong, jibun, "", "연면적없음", "", ""]
    lots = {(pj[0], pj[1], pj[2])}
    for a in h.call("getBrAtchJibunInfo", **args) or []:
        if a.get("atchBun"):
            gb = "1" if str(a.get("atchPlatGbCd")) == "1" else "0"
            lots.add((gb, str(a["atchBun"]).zfill(4), str(a.get("atchJi") or "0").zfill(4)))
    areas = [land_area(codes[0], codes[1], *lot) for lot in lots]
    if any(x is None for x in areas):
        return [gu, dong, jibun, "", "오류", area, ""]
    land = sum(areas)
    if land <= 0:
        return [gu, dong, jibun, "", "대지면적없음", area, ""]
    return [gu, dong, jibun, round(area / land * 100, 1), "계산:" + src, round(area, 1), round(land, 1), len(lots)]


def main():
    far = pd.read_csv(ROOT / "data" / "far.csv", dtype=str)
    v = pd.to_numeric(far["용적률"], errors="coerce")
    todo = far[~v.between(50, 1000)][["자치구", "법정동", "지번"]]          # 비었거나 오류 범위인 주소
    todo = list(todo.drop_duplicates().itertuples(index=False, name=None))
    if OUT.exists():
        prev = pd.read_csv(OUT, dtype=str)
        prev = prev[prev["출처"] != "오류"]
        prev.to_csv(OUT, index=False, encoding="utf-8-sig")
        done = set(zip(prev["자치구"], prev["법정동"], prev["지번"]))
        todo = [a for a in todo if a not in done]
    print(f"계산할 주소 {len(todo)}개", flush=True)
    new_file = not OUT.exists()
    with open(OUT, "a", newline="", encoding="utf-8-sig") as f, ThreadPoolExecutor(max_workers=2) as pool:
        w = csv.writer(f)
        if new_file:
            w.writerow(FIELDS)
        for i, res in enumerate(pool.map(lookup, todo), 1):
            w.writerow(res)
            if i % 100 == 0:
                f.flush()
                print(f"{i}/{len(todo)}", flush=True)
    print(pd.read_csv(OUT, dtype=str)["출처"].str.split(":").str[0].value_counts().to_string(), flush=True)


if __name__ == "__main__":
    main()
