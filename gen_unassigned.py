#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
미배정 대지 레이어 생성 — out/{code}/{동}_unassigned.geojson.
통 배정을 못 받은(별표에 없는) 필지 중 '대지'(주소 있는 땅)만, 행정동 경계로 클립.
셸에서 '미배정 대지' 토글을 켜면 옅게 표시되고 클릭하면 지번을 확인할 수 있다.
사용: python gen_unassigned.py   (build 후, 원본 지적도 SHP 필요)
"""
import glob, json, os, re
import geopandas as gpd
import numpy as np

SHP = "LSMD_CONT_LDREG_41390_202606.shp"


def canon_pnu(pnu):
    pnu = str(pnu)
    if len(pnu) < 19 or not pnu[:19].isdigit():
        return None, None
    san = pnu[10] == '2'
    bon = int(pnu[11:15]); bu = int(pnu[15:19])
    return pnu[:10], ('산' if san else '') + str(bon) + (f'-{bu}' if bu else '')


def jimok(j):
    m = re.match(r'^산?\d[\d-]*(\D*)$', str(j))
    return m.group(1) if m else ''


def main():
    if not os.path.exists(SHP):
        raise SystemExit(f"⚠ 지적도 SHP 없음: {SHP}")
    shp = gpd.read_file(SHP)
    shp["_bjd"], shp["_jib"] = zip(*shp["PNU"].map(canon_pnu))
    shp["_jm"] = shp["JIBUN"].map(jimok)
    total = 0
    for cfgp in sorted(glob.glob("data/3*/config.json")):
        cfg = json.load(open(cfgp, encoding="utf-8"))
        code, dong = cfg["admin_code"], cfg["admin_dong"]
        leg = cfg["legal_dongs"]
        pp = f"out/{code}/{dong}_parcels.geojson"
        ap = f"out/{code}/{dong}_admin.geojson"
        if not (os.path.exists(pp) and os.path.exists(ap)):
            continue
        g = gpd.read_file(pp)
        assigned = set(zip(g["법정동"].astype(str), g["지번"].astype(str)))
        sub = shp[shp["_bjd"].isin(leg.keys())].copy()
        sub["법정동"] = sub["_bjd"].map(leg)
        # 미배정 + 대지(주소 있는 땅)
        keep = np.array([(b, j) not in assigned for b, j in zip(sub["법정동"], sub["_jib"])])
        un = sub[keep & sub["_jm"].str.startswith("대").values].copy()
        # 행정동 경계 안만(공유 법정동 다른 동 필지 제외)
        admin = gpd.read_file(ap).to_crs(un.crs)
        ag = admin.geometry.union_all()
        un = un[un.geometry.representative_point().within(ag)]
        out = (un[["법정동", "_jib", "_jm", "geometry"]]
               .rename(columns={"_jib": "지번", "_jm": "지목"}).to_crs("EPSG:4326"))
        op = f"out/{code}/{dong}_unassigned.geojson"
        out.to_file(op, driver="GeoJSON")
        total += len(out)
        print(f"  {code} {dong:7s} 미배정 대지 {len(out):>4} ({os.path.getsize(op)//1024}KB)")
    print(f"→ 총 미배정 대지 {total}")


if __name__ == "__main__":
    main()
