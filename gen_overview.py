#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
out/overview/all_tong.geojson, all_admin.geojson 생성 — 전체지도 모드용(단순화 통합).
동별 통/행정동 경계를 EPSG:5186에서 단순화 후 4326으로, 동 code/dong 속성 부여해 합친다.
사용: python gen_overview.py [--tol-tong 8] [--tol-admin 12]
"""
import argparse, glob, json, os
import geopandas as gpd
import pandas as pd

OUT = "out"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol-tong", type=float, default=8.0, help="통 단순화 허용오차(m)")
    ap.add_argument("--tol-admin", type=float, default=12.0, help="행정동 단순화 허용오차(m)")
    args = ap.parse_args()
    os.makedirs(f"{OUT}/overview", exist_ok=True)

    tong_parts, admin_parts = [], []
    for cfgp in sorted(glob.glob("data/3*/config.json")):
        cfg = json.load(open(cfgp, encoding="utf-8"))
        code, dong = cfg["admin_code"], cfg["admin_dong"]
        tp, apth = f"{OUT}/{code}/{dong}_tong.geojson", f"{OUT}/{code}/{dong}_admin.geojson"
        if os.path.exists(tp):
            g = gpd.read_file(tp).to_crs("EPSG:5186")
            g["geometry"] = g.geometry.simplify(args.tol_tong, preserve_topology=True)
            g = g.to_crs("EPSG:4326")
            g["code"], g["dong"] = code, dong
            tong_parts.append(g[["code", "dong", "통", "geometry"]])
        if os.path.exists(apth):
            a = gpd.read_file(apth).to_crs("EPSG:5186")
            a["geometry"] = a.geometry.simplify(args.tol_admin, preserve_topology=True)
            a = a.to_crs("EPSG:4326")
            a["code"], a["dong"] = code, dong
            admin_parts.append(a[["code", "dong", "geometry"]])

    tong = gpd.GeoDataFrame(pd.concat(tong_parts, ignore_index=True), crs="EPSG:4326")
    admin = gpd.GeoDataFrame(pd.concat(admin_parts, ignore_index=True), crs="EPSG:4326")
    tp_out, ap_out = f"{OUT}/overview/all_tong.geojson", f"{OUT}/overview/all_admin.geojson"
    tong.to_file(tp_out, driver="GeoJSON")
    admin.to_file(ap_out, driver="GeoJSON")

    # 시흥시 전체 외곽 경계(20개 행정동 union) — 전체지도 강조/스포트라이트용
    city_geom = admin.to_crs("EPSG:5186").union_all().buffer(2).buffer(-2).simplify(15)
    city = gpd.GeoDataFrame(geometry=[city_geom], crs="EPSG:5186").to_crs("EPSG:4326")
    cp_out = f"{OUT}/overview/city_boundary.geojson"
    city.to_file(cp_out, driver="GeoJSON")
    print(f"overview: 통 {len(tong)}개({os.path.getsize(tp_out)//1024}KB), "
          f"행정동 {len(admin)}개({os.path.getsize(ap_out)//1024}KB), "
          f"시흥시 경계({os.path.getsize(cp_out)//1024}KB)")

if __name__ == "__main__":
    main()
