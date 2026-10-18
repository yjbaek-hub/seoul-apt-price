"""서울 25개 구 경계 GeoJSON 만들기 → data/seoul_gu_boundary.geojson

실행: python scripts/make_gu_boundary.py <bnd_sigungu_00_2025_2Q.shp 경로>
입력: 통계청 SGIS 시군구 경계 (수업 lecture04 의 bnd_all_00_2025_2Q, 좌표계 EPSG:5179)
처리: 서울(시군구코드 11로 시작)만 남김 → 위경도(EPSG:4326)로 변환 → 웹 지도용으로 단순화(약 40m)
"""
import sys
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
src = sys.argv[1] if len(sys.argv) > 1 else "bnd_sigungu_00_2025_2Q.shp"

g = gpd.read_file(src)
seoul = g[g["SIGUNGU_CD"].str.startswith("11")].to_crs(4326)
seoul["geometry"] = seoul.geometry.simplify(0.0004, preserve_topology=True)
seoul = seoul[["SIGUNGU_NM", "geometry"]].rename(columns={"SIGUNGU_NM": "gu"})

out = ROOT / "data" / "seoul_gu_boundary.geojson"
seoul.to_file(out, driver="GeoJSON", COORDINATE_PRECISION=5)
print(f"{out.name}: {len(seoul)}개 구, {out.stat().st_size // 1024} KB")
