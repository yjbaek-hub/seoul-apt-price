"""K-apt(공동주택관리정보시스템) 단지별 세대수 수집 → data/kapt.csv

실행: python scripts/kapt.py   (seoul-apt-rate 폴더에서, ../.env 의 DATA_GO_KR_KEY 사용)
1) 단지 목록 (AptListService4/getSigunguAptList4): 서울 25개 구의 단지코드
2) 기본정보 (AptBasisInfoServiceV5/getAphusBassInfoV5): 지번 주소(kaptAddr)와 세대수(kaptdaCnt)
건축물대장은 동이 여러 지번에 흩어진 오래된 대단지의 세대수를 적게 잡는 경우가 있어,
단지 단위로 관리되는 K-apt 세대수를 우선 사용한다 (build_monthly.py).
"""
import csv
import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "kapt.csv"
GU_CODES = ["11110", "11140", "11170", "11200", "11215", "11230", "11260", "11290", "11305", "11320",
            "11350", "11380", "11410", "11440", "11470", "11500", "11530", "11545", "11560", "11590",
            "11620", "11650", "11680", "11710", "11740"]


def load_key():
    for line in (ROOT.parent / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATA_GO_KR_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DATA_GO_KR_KEY가 .env에 없습니다")


KEY = load_key()


def get(path, **params):
    url = f"https://apis.data.go.kr/1613000/{path}?serviceKey={KEY}&" + urllib.parse.urlencode(params)
    for attempt in range(8):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                d = json.loads(r.read().decode("utf-8"))
            if d.get("response", {}).get("header", {}).get("resultCode") == "00":
                return d["response"]["body"]
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))   # 초당 요청 제한·일시 오류 시 재시도
    return None


def list_gu(code):
    out, page = [], 1
    while True:
        b = get("AptListService4/getSigunguAptList4", sigunguCode=code, numOfRows=1000, pageNo=page)
        items = (b or {}).get("items") or []
        out += items
        if not b or len(out) >= int(b.get("totalCount", 0)) or not items:
            return out
        page += 1


# "서울특별시 강남구 도곡동 964 도곡현대그린" → (강남구, 도곡동, 964)
ADDR = re.compile(r"서울특별시\s+(\S+구)\s+(\S+동\d*가?)\s+(산?\d+(?:-\d+)?)")


def basis(apt):
    b = get("AptBasisInfoServiceV5/getAphusBassInfoV5", kaptCode=apt["kaptCode"])
    it = (b or {}).get("item") or {}
    addr = (it.get("kaptAddr") or "").strip()
    m = ADDR.search(addr)
    gu, dong, jibun = m.groups() if m else ("", "", "")
    hh = it.get("kaptdaCnt")
    return [apt["kaptCode"], (it.get("kaptName") or apt.get("kaptName") or "").strip(), addr,
            gu, dong, jibun, "" if hh is None else int(float(hh)), "" if b else "오류"]


def retry_errors():
    """이미 받은 kapt.csv 에서 '오류' 행만 다시 조회해 덮어쓴다."""
    import pandas as pd
    df = pd.read_csv(OUT, dtype=str)
    bad = df.index[df["비고"] == "오류"].tolist()
    print(f"오류 {len(bad)}개 재시도", flush=True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        rows = list(pool.map(lambda i: basis({"kaptCode": df.at[i, "단지코드"], "kaptName": df.at[i, "단지명"]}), bad))
    for i, row in zip(bad, rows):
        df.loc[i] = [str(v) for v in row]   # CSV를 문자열로 읽었으므로 숫자도 문자열로 넣어야 함
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"남은 오류 {(df['비고'] == '오류').sum()}개", flush=True)


def main():
    if OUT.exists() and "--retry" in __import__("sys").argv:
        return retry_errors()
    apts = []
    for code in GU_CODES:
        apts += list_gu(code)
    print(f"서울 단지 목록 {len(apts)}개", flush=True)

    with open(OUT, "w", newline="", encoding="utf-8-sig") as f, ThreadPoolExecutor(max_workers=2) as pool:
        w = csv.writer(f)
        w.writerow(["단지코드", "단지명", "주소", "자치구", "법정동", "지번", "세대수", "비고"])
        for i, row in enumerate(pool.map(basis, apts), 1):
            w.writerow(row)
            if i % 500 == 0:
                f.flush()
                print(f"{i}/{len(apts)}", flush=True)
    print("완료", flush=True)


if __name__ == "__main__":
    main()
