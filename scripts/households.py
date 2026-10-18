"""단지 세대수 수집: 실거래 주소(자치구·법정동·지번) → 건축물대장(건축HUB) 세대수

실행: python scripts/households.py   (seoul-apt-rate 폴더에서, ../.env 의 DATA_GO_KR_KEY 사용)
1) 총괄표제부(getBrRecapTitleInfo)의 세대수(hhldCnt) — 여러 동으로 된 단지 전체 세대수
2) 총괄표제부가 없으면 표제부(getBrTitleInfo)의 주건축물 세대수를 합산 — 동이 하나뿐인 건물
결과는 data/households.csv 에 누적 저장 (중단 후 재실행하면 이어서 진행).
"""
import csv
import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "households.csv"
FIELDS = ["자치구", "법정동", "지번", "세대수", "출처", "건물명"]

GU_CODE = {
    "종로구": "11110", "중구": "11140", "용산구": "11170", "성동구": "11200", "광진구": "11215",
    "동대문구": "11230", "중랑구": "11260", "성북구": "11290", "강북구": "11305", "도봉구": "11320",
    "노원구": "11350", "은평구": "11380", "서대문구": "11410", "마포구": "11440", "양천구": "11470",
    "강서구": "11500", "구로구": "11530", "금천구": "11545", "영등포구": "11560", "동작구": "11590",
    "관악구": "11620", "서초구": "11650", "강남구": "11680", "송파구": "11710", "강동구": "11740",
}


def load_key():
    for line in (ROOT.parent / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATA_GO_KR_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DATA_GO_KR_KEY가 .env에 없습니다")


KEY = load_key()

# 법정동 코드: seoul_rent_api 에서 쓰던 자치구별 법정동 목록 재사용
_m = json.loads((ROOT.parent / "seoul_rent_api" / "data" / "gu_dong.json").read_text(encoding="utf-8"))
BJD = {(g, d["name"]): (v["code"], d["code"]) for g, v in _m.items() for d in v["dongs"]}
BJD_BY_NAME = {}
for (g, name), codes in BJD.items():
    BJD_BY_NAME.setdefault(name, codes)


def call(op, **params):
    q = urllib.parse.urlencode({**params, "_type": "json", "numOfRows": 100, "pageNo": 1})
    url = f"https://apis.data.go.kr/1613000/BldRgstHubService/{op}?serviceKey={KEY}&{q}"
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                d = json.loads(r.read().decode("utf-8"))
            items = d["response"]["body"].get("items") or {}
            item = items.get("item", []) if isinstance(items, dict) else []
            return item if isinstance(item, list) else [item]
        except Exception:
            time.sleep(1.5 * (attempt + 1))   # 초당 요청 제한·일시 오류 시 재시도
    return None


def parse_jibun(j):
    """'316' → (0,'0316','0000'), '416-12' → (0,'0416','0012'), '산28-9' → (1,'0028','0009')"""
    plat = "0"
    if j.startswith("산"):
        plat, j = "1", j[1:]
    parts = j.split("-")
    if not all(p.isdigit() for p in parts) or len(parts) > 2:
        return None
    bun = parts[0].zfill(4)
    ji = (parts[1] if len(parts) == 2 else "0").zfill(4)
    return plat, bun, ji


def lookup(row):
    gu, dong, jibun = row
    codes = BJD.get((gu, dong)) or BJD_BY_NAME.get(dong)   # 구 경계 예외는 동 이름으로 보정
    pj = parse_jibun(jibun)
    if not codes or not pj:
        return [gu, dong, jibun, "", "주소해석불가", ""]
    sgg, bjd = codes
    plat, bun, ji = pj
    args = dict(sigunguCd=sgg, bjdongCd=bjd, platGbCd=plat, bun=bun, ji=ji)

    recap = call("getBrRecapTitleInfo", **args)
    if recap is None:
        return [gu, dong, jibun, "", "오류", ""]
    hh = [int(x.get("hhldCnt") or 0) for x in recap]
    if hh and max(hh) > 0:
        best = recap[hh.index(max(hh))]
        return [gu, dong, jibun, max(hh), "총괄표제부", best.get("bldNm", "").strip()]

    title = call("getBrTitleInfo", **args)
    if title is None:
        return [gu, dong, jibun, "", "오류", ""]
    main = [x for x in title if x.get("mainAtchGbCd") == "0"]
    total = sum(int(x.get("hhldCnt") or 0) for x in main)
    if total > 0:
        return [gu, dong, jibun, total, "표제부합산", main[0].get("bldNm", "").strip()]
    return [gu, dong, jibun, "", "세대수없음", ""]


def main():
    g = pd.read_csv(ROOT / "data" / "geocode.csv", dtype=str)
    addrs = list(g[["자치구", "법정동", "지번"]].drop_duplicates().itertuples(index=False, name=None))

    done = set()
    if OUT.exists():
        prev = pd.read_csv(OUT, dtype=str)
        prev = prev[prev["출처"] != "오류"]          # 오류난 건 다시 시도
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
            if i % 500 == 0:
                f.flush()
                print(f"{i}/{len(todo)}", flush=True)

    res = pd.read_csv(OUT, dtype=str)
    print(res["출처"].value_counts().to_string())


if __name__ == "__main__":
    main()
