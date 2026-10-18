"""실거래 주소(자치구 + 법정동 + 지번) → 좌표·행정동 변환 (카카오 로컬 API)

실행: python scripts/geocode.py   (seoul-apt-rate 폴더에서, ../.env 의 KAKAO_REST_KEY 사용)
결과는 data/geocode.csv 에 누적 저장되므로 중단 후 다시 실행하면 이어서 진행한다.
"""
import csv
import json
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TRADES = ROOT / "data" / "seoul_apt_trades_202109_202608.csv"
OUT = ROOT / "data" / "geocode.csv"
FIELDS = ["자치구", "법정동", "지번", "단지명", "x", "y", "행정동코드", "행정동", "방법"]


def load_key():
    for line in (ROOT.parent / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("KAKAO_REST_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("KAKAO_REST_KEY가 .env에 없습니다")


KEY = load_key()


def kakao(path, **params):
    url = f"https://dapi.kakao.com/v2/local/{path}.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {KEY}"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)
        except Exception:
            time.sleep(1 + attempt * 2)
    return {"documents": []}


def to_hdong(x, y):
    """좌표 → 행정동(H) 코드·이름"""
    for d in kakao("geo/coord2regioncode", x=x, y=y)["documents"]:
        if d["region_type"] == "H":
            return d["code"], d["region_3depth_name"]
    return "", ""


def geocode(row):
    gu, dong, jibun, apt = row
    # 1차: 지번 주소 검색 (응답에 행정동 코드 포함)
    docs = kakao("search/address", query=f"서울 {gu} {dong} {jibun}")["documents"]
    for d in docs:
        a = d.get("address")
        if a and a.get("h_code") and a["region_2depth_name"] == gu:
            return [gu, dong, jibun, apt, a["x"], a["y"], a["h_code"], a["region_3depth_h_name"], "지번"]
    # 2차: 단지명 키워드 검색 → 좌표로 행정동 조회
    docs = kakao("search/keyword", query=f"{gu} {dong} {apt}")["documents"]
    for d in docs:
        if gu in d.get("address_name", ""):
            code, name = to_hdong(d["x"], d["y"])
            if code:
                return [gu, dong, jibun, apt, d["x"], d["y"], code, name, "단지명"]
    return [gu, dong, jibun, apt, "", "", "", "", "실패"]


def main():
    df = pd.read_csv(TRADES, dtype=str)
    df = df[df["해제여부"].isna()]
    addrs = df.groupby(["자치구", "법정동", "지번"])["단지명"].first().reset_index()

    done = set()
    if OUT.exists():
        prev = pd.read_csv(OUT, dtype=str)
        done = set(zip(prev["자치구"], prev["법정동"], prev["지번"]))
    todo = [tuple(r) for r in addrs.itertuples(index=False) if (r[0], r[1], r[2]) not in done]
    print(f"전체 {len(addrs)}개 주소, 남은 {len(todo)}개")

    new_file = not OUT.exists()
    with open(OUT, "a", newline="", encoding="utf-8-sig") as f, ThreadPoolExecutor(max_workers=6) as pool:
        w = csv.writer(f)
        if new_file:
            w.writerow(FIELDS)
        for i, res in enumerate(pool.map(geocode, todo), 1):
            w.writerow(res)
            if i % 500 == 0:
                f.flush()
                print(f"{i}/{len(todo)}")

    res = pd.read_csv(OUT, dtype=str)
    print(res["방법"].value_counts().to_string())


if __name__ == "__main__":
    main()
