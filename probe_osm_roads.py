#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[조사용] OSM에서 시흥시 도로 중심선을 받아 도로망 기반 경계(path A) 가능성 점검."""
import json, urllib.request, urllib.parse
import geopandas as gpd
from shapely.geometry import LineString

city = gpd.read_file("out/overview/city_boundary.geojson")           # EPSG:4326
minx, miny, maxx, maxy = city.total_bounds
bbox = f"{miny},{minx},{maxy},{maxx}"                                 # S,W,N,E
q = f"""[out:json][timeout:180];
(way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|motorway_link|trunk_link|primary_link|secondary_link)$"]({bbox}););
out geom;"""
endpoints = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter"]
data = None
for ep in endpoints:
    try:
        print("요청:", ep)
        req = urllib.request.Request(ep, data=urllib.parse.urlencode({"data": q}).encode(),
                                     method="POST")
        with urllib.request.urlopen(req, timeout=200) as r:
            data = json.load(r)
        break
    except Exception as e:
        print("  실패:", e)
if data is None:
    raise SystemExit("Overpass 접근 실패")

rows = []
for e in data.get("elements", []):
    if e.get("type") == "way" and e.get("geometry"):
        co = [(p["lon"], p["lat"]) for p in e["geometry"]]
        if len(co) >= 2:
            rows.append({"hw": e.get("tags", {}).get("highway"),
                         "name": e.get("tags", {}).get("name", ""),
                         "geometry": LineString(co)})
g = gpd.GeoDataFrame(rows, crs="EPSG:4326")
cityu = city.to_crs("EPSG:5186").union_all()
gm = g.to_crs("EPSG:5186")
gm = gm[gm.intersects(cityu)].copy()
gm["geometry"] = gm.geometry.intersection(cityu)
gm = gm[~gm.geometry.is_empty]
gm["km"] = gm.geometry.length / 1000

area_km2 = cityu.area / 1e6
total_km = gm["km"].sum()
print(f"\n시흥시 면적 {area_km2:.1f} km², 도로 세그먼트 {len(gm)}개, 총 연장 {total_km:.1f} km")
print(f"도로밀도 {total_km/area_km2:.1f} km/km²  (도시지역 보통 8~15)")
print("\n도로유형별:")
print(gm.groupby("hw")["km"].agg(["count", "sum"]).round(1).sort_values("sum", ascending=False).to_string())
named = (gm["name"].astype(str).str.len() > 0).sum()
print(f"\n이름 있는 세그먼트 {named}/{len(gm)} ({named/len(gm)*100:.0f}%)")
gm.to_crs("EPSG:4326").to_file("out/overview/osm_roads.geojson", driver="GeoJSON")
print("→ out/overview/osm_roads.geojson 저장(시각 점검용)")
