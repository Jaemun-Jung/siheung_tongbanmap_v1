#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
별표 기반 통(_tong.geojson)의 통 내부 잡선 정리.
미매칭 슬리버가 내부 구멍으로 남아 검은 외곽선으로 보이던 것을 제거.
작은 구멍(<MAX_HOLE)·작은 조각(<MIN_PART)만 정리, 큰 공백은 보존(법적 뷰 정밀 유지).
사용: python clean_tong.py
"""
import glob, json, os
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon

MIN_PART = 500       # 이보다 작은 통 조각(슬리버) 제거(m2)
MAX_HOLE = 3000      # 이보다 작은 내부 구멍 메움(슬리버 잡선 제거, m2)

def clean_geom(geom):
    parts = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    out = []
    for p in parts:
        if p.area < MIN_PART:
            continue
        holes = [r for r in p.interiors if Polygon(r).area >= MAX_HOLE]
        out.append(Polygon(p.exterior, holes))
    if not out:
        return geom
    return out[0] if len(out) == 1 else MultiPolygon(out)

def main():
    n = 0
    for cfgp in sorted(glob.glob("data/3*/config.json")):
        cfg = json.load(open(cfgp, encoding="utf-8"))
        code, dong = cfg["admin_code"], cfg["admin_dong"]
        path = f"out/{code}/{dong}_tong.geojson"
        if not os.path.exists(path):
            continue
        g = gpd.read_file(path).to_crs("EPSG:5186")
        before = sum(len(p.interiors) for _, r in g.iterrows()
                     for p in (list(r.geometry.geoms) if isinstance(r.geometry, MultiPolygon) else [r.geometry]))
        g["geometry"] = g.geometry.apply(clean_geom)
        after = sum(len(p.interiors) for _, r in g.iterrows()
                    for p in (list(r.geometry.geoms) if isinstance(r.geometry, MultiPolygon) else [r.geometry]))
        g = g.to_crs("EPSG:4326")
        lp = g.representative_point()
        g["lon"], g["lat"] = lp.x.round(7), lp.y.round(7)
        g.to_file(path, driver="GeoJSON")
        print(f"  {code} {dong:7s} 내부구멍 {before} → {after}")
        n += 1
    print(f"\n정리 완료: {n}개 동 _tong.geojson")

if __name__ == "__main__":
    main()
