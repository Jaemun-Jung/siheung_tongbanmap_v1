#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
'통에 둘러싸인 구멍' 필지 추출 — out/{code}/{동}_holes.geojson.

배정 필지(통)들이 사방을 둘러쌌는데 정작 통에 안 들어간 빈 필지("왜 여기 뚫렸지").
별표 오류 의심 지점이라, 셸에서 (미배정 대지 토글과 무관하게) 기본으로 클릭 시
지번을 확인할 수 있게 한다. 모든 지목(대지·도로·전답 등) 포함.

방법: 배정 필지들을 합쳐 covered, 내부 구멍을 메운 filled를 만들고,
      filled∖covered(=둘러싸인 빈칸)에 들어가는 미배정 필지를 모은다.
      (통 폴리곤은 작은 구멍이 메워져 있어 원본 필지로 직접 계산)
사용: python gen_holes.py   (build 후, 원본 지적도 SHP 필요)
"""
import glob, json, os, re
import geopandas as gpd
from shapely.ops import unary_union
from shapely.geometry import Polygon
from shapely.prepared import prep

SHP = "LSMD_CONT_LDREG_41390_202606.shp"
MIN_AREA = 8.0          # 이보다 작은 미세 슬리버 필지는 제외(m²)


def canon_pnu(pnu):
    pnu = str(pnu)
    if len(pnu) < 19 or not pnu[:19].isdigit():
        return None, None
    bon = int(pnu[11:15]); bu = int(pnu[15:19])
    return pnu[:10], ('산' if pnu[10] == '2' else '') + str(bon) + (f'-{bu}' if bu else '')


def jimok(j):
    m = re.match(r'^산?\d[\d-]*(\D*)$', str(j))
    return m.group(1).strip() if m else ''


def fill_holes(geom):
    parts = geom.geoms if geom.geom_type == 'MultiPolygon' else [geom]
    return unary_union([Polygon(p.exterior) for p in parts])


def main():
    if not os.path.exists(SHP):
        raise SystemExit(f"⚠ 지적도 SHP 없음: {SHP}")
    shp = gpd.read_file(SHP)
    shp["_bjd"], shp["_jib"] = zip(*shp["PNU"].map(canon_pnu))
    shp["_jm"] = shp["JIBUN"].map(jimok)
    total = 0
    for cfgp in sorted(glob.glob("data/3*/config.json")):
        cfg = json.load(open(cfgp, encoding="utf-8"))
        code, dong, leg = cfg["admin_code"], cfg["admin_dong"], cfg["legal_dongs"]
        pp = f"out/{code}/{dong}_parcels.geojson"
        ap = f"out/{code}/{dong}_admin.geojson"
        if not (os.path.exists(pp) and os.path.exists(ap)):
            continue
        assigned = set(zip(gpd.read_file(pp)["법정동"].astype(str),
                           gpd.read_file(pp)["지번"].astype(str)))
        sub = shp[shp["_bjd"].isin(leg.keys())].copy()
        sub["법정동"] = sub["_bjd"].map(leg)
        admin = gpd.read_file(ap).to_crs(sub.crs).geometry.union_all()
        sub = sub[sub.geometry.representative_point().within(admin)]
        is_as = [(b, j) in assigned for b, j in zip(sub["법정동"], sub["_jib"])]
        asg = sub[is_as]
        un = sub[[not x for x in is_as]].copy()
        if asg.empty or un.empty:
            continue
        covered = unary_union(list(asg.geometry))
        holes = fill_holes(covered).difference(covered)      # 둘러싸인 빈칸
        if holes.is_empty:
            continue
        ph = prep(holes)
        un["rep"] = un.geometry.representative_point()
        keep = un[[ph.contains(p) and g.area >= MIN_AREA
                   for p, g in zip(un["rep"], un.geometry)]]
        if keep.empty:
            continue
        out = (keep[["법정동", "_jib", "_jm", "geometry"]]
               .rename(columns={"_jib": "지번", "_jm": "지목"}).to_crs("EPSG:4326"))
        op = f"out/{code}/{dong}_holes.geojson"
        out.to_file(op, driver="GeoJSON")
        total += len(out)
        print(f"  {code} {dong:7s} 통 둘러싼 구멍필지 {len(out):>4} ({os.path.getsize(op)//1024}KB)")
    print(f"→ 총 구멍 필지 {total}")


if __name__ == "__main__":
    main()
