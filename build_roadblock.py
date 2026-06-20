#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
도로망 기반 통 경계(구로구식 중심선) — 전 동 생성.
OSM 도로망 + 행정동경계로 블록 polygonize → 블록을 별표지번(통)으로 배정
(빈/희소 블록 제외, 혼합 블록은 내부 최근접 분할) → 통별 병합.
입력: out/{code}/{동}_parcels.geojson(통·fill_method), _admin.geojson, out/overview/osm_roads.geojson
출력: out/{code}/{동}_tong_roadblock.geojson (통, lon, lat)
사용: python build_roadblock.py   (osm_roads.geojson 필요 — probe_osm_roads.py로 먼저 생성)
"""
import glob, json, os
from collections import Counter
import geopandas as gpd
import pandas as pd
from shapely.ops import polygonize, unary_union, voronoi_diagram
from shapely.geometry import LineString, MultiLineString, GeometryCollection, MultiPoint
from shapely import STRtree

COV_MIN = 0.10          # 블록 면적 대비 별표필지 커버리지 하한(미만=빈땅 제외)
MIN_PARCELS = 2
SLIVER = 2.0

def to_lines(geom):
    out = []
    if geom is None or geom.is_empty: return out
    if isinstance(geom, LineString): out.append(geom)
    elif isinstance(geom, MultiLineString): out += list(geom.geoms)
    elif isinstance(geom, GeometryCollection):
        for g in geom.geoms: out += to_lines(g)
    return out

def roadblock_for(code, dong, roads_all):
    admin = gpd.read_file(f"out/{code}/{dong}_admin.geojson").to_crs("EPSG:5186")
    parcels = gpd.read_file(f"out/{code}/{dong}_parcels.geojson").to_crs("EPSG:5186")
    au = admin.union_all()
    roads = roads_all[roads_all.intersects(au)].copy()
    if len(roads):
        roads["geometry"] = roads.geometry.intersection(au)
    # 1) 블록 polygonize
    lines = []
    for g in roads.geometry: lines += to_lines(g)
    lines += to_lines(au.boundary)
    blocks = [p for p in polygonize(unary_union(lines))]
    bg = gpd.GeoDataFrame({"bid": range(len(blocks))}, geometry=blocks, crs="EPSG:5186")
    bg["geometry"] = bg.buffer(0)
    bg = bg[bg.geometry.area > 1].reset_index(drop=True)
    block_geom = bg.set_index("bid").geometry
    # 2) 배정(별표필지 다수결, 빈블록 제외, 혼합 내부분할)
    res = parcels[parcels["fill_method"] == "parcel_match"].copy()
    if res.empty:
        return None, dict(blocks=len(bg), single=0, mixed=0, skipped=0, tong=0)
    res["통"] = res["통"].astype(int)
    respt = gpd.GeoDataFrame(res[["통"]].copy(), geometry=res.representative_point(), crs="EPSG:5186")
    respt["pa"] = res.geometry.area.values
    sj = gpd.sjoin(respt, bg[["bid", "geometry"]], predicate="within", how="inner")
    pieces, single, mixed, skipped = [], 0, 0, 0
    for bid, grp in sj.groupby("bid"):
        blk = block_geom.loc[bid]
        if len(grp) < MIN_PARCELS or grp["pa"].sum() / blk.area < COV_MIN:
            skipped += 1; continue
        tongs = grp["통"].unique()
        if len(tongs) == 1:
            pieces.append((int(tongs[0]), blk)); single += 1; continue
        mixed += 1
        pts, labs = list(grp.geometry), list(grp["통"])
        try:
            cells = voronoi_diagram(MultiPoint(pts), envelope=blk)
        except Exception:
            pieces.append((int(grp["통"].mode().iloc[0]), blk)); continue
        tree = STRtree(pts); byt = {}
        for cell in cells.geoms:
            hit = tree.query(cell, predicate="contains")
            lab = labs[int(hit[0])] if len(hit) else labs[int(tree.nearest(cell.representative_point()))]
            clip = cell.intersection(blk)
            if not clip.is_empty:
                byt.setdefault(int(lab), []).append(clip)
        for t, gs in byt.items():
            g = unary_union(gs)
            if not g.is_empty and g.area >= SLIVER:
                pieces.append((t, g))
    if not pieces:
        return None, dict(blocks=len(bg), single=single, mixed=mixed, skipped=skipped, tong=0)
    pg = gpd.GeoDataFrame(pd.DataFrame(pieces, columns=["통", "geometry"]),
                          geometry="geometry", crs="EPSG:5186")
    newt = pg.dissolve("통").reset_index()[["통", "geometry"]]
    newt["geometry"] = newt.buffer(0)
    newt = newt.to_crs("EPSG:4326")
    lp = newt.representative_point()
    newt["lon"], newt["lat"] = lp.x.round(7), lp.y.round(7)
    return newt, dict(blocks=len(bg), single=single, mixed=mixed, skipped=skipped, tong=len(newt))

def main():
    roads_all = gpd.read_file("out/overview/osm_roads.geojson").to_crs("EPSG:5186")
    for cfgp in sorted(glob.glob("data/3*/config.json")):
        cfg = json.load(open(cfgp, encoding="utf-8"))
        code, dong = cfg["admin_code"], cfg["admin_dong"]
        if not os.path.exists(f"out/{code}/{dong}_parcels.geojson"):
            continue
        try:
            newt, st = roadblock_for(code, dong, roads_all)
        except Exception as e:
            print(f"  {code} {dong}: 실패 {e}"); continue
        if newt is None or not len(newt):
            print(f"  {code} {dong:7s} 통 0 (배정 실패)"); continue
        out = f"out/{code}/{dong}_tong_roadblock.geojson"
        newt.to_file(out, driver="GeoJSON")
        print(f"  {code} {dong:7s} 블록{st['blocks']:>4} → 통 {st['tong']:>3} "
              f"(단일{st['single']} 분할{st['mixed']} 빈블록제외{st['skipped']})")

if __name__ == "__main__":
    main()
