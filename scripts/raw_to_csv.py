"""collect.js 가 받은 구·월별 원자료(data/raw/*.json)를 엑셀에서 열 수 있는 CSV 하나로 합침

실행: python scripts/raw_to_csv.py
출력: data/seoul_apt_trades_202109_202608.csv (UTF-8 BOM, 거래 1건 = 1행, 해제 거래 포함·표시)
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "seoul_apt_trades_202109_202608.csv"

GU = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구", "11215": "광진구",
    "11230": "동대문구", "11260": "중랑구", "11290": "성북구", "11305": "강북구", "11320": "도봉구",
    "11350": "노원구", "11380": "은평구", "11410": "서대문구", "11440": "마포구", "11470": "양천구",
    "11500": "강서구", "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구", "11740": "강동구",
}
HEAD = ["자치구코드", "자치구", "법정동", "지번", "단지명", "동", "계약일", "거래금액(만원)", "전용면적(㎡)",
        "층", "건축연도", "거래유형", "매수자", "매도자", "해제여부", "해제사유발생일"]

n = 0
with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(HEAD)
    for path in sorted(RAW.glob("*.json")):
        for r in json.loads(path.read_text(encoding="utf-8")):
            date = f"{r['dealYear']}-{r['dealMonth'].zfill(2)}-{r['dealDay'].zfill(2)}"
            w.writerow([r["sggCd"], GU.get(r["sggCd"], ""), r["umdNm"], r["jibun"], r["aptNm"], r["aptDong"], date,
                        r["dealAmount"].replace(",", ""), r["excluUseAr"], r["floor"], r["buildYear"],
                        r["dealingGbn"], r["buyerGbn"], r["slerGbn"],
                        "해제" if r["cdealType"] == "O" else "", r["cdealDay"]])
            n += 1
print(f"{OUT.name}: {n:,}건")
