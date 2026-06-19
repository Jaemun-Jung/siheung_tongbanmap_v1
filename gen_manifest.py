#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
out/manifest.json 생성 — 셸(index.html)이 동 목록·줌범위를 읽는다.
각 동의 {동}_tong.geojson(EPSG:4326) bounds로 center/bounds 계산.
사용: python gen_manifest.py
"""
import glob, json, os
import geopandas as gpd

OUT = "out"

def main():
    rows = []
    for cfgp in sorted(glob.glob("data/3*/config.json")):
        cfg = json.load(open(cfgp, encoding="utf-8"))
        code, dong = cfg["admin_code"], cfg["admin_dong"]
        tongp = f"{OUT}/{code}/{dong}_tong.geojson"
        if not os.path.exists(tongp):
            print(f"  skip(no tong): {code} {dong}")
            continue
        g = gpd.read_file(tongp)
        minx, miny, maxx, maxy = (round(v, 6) for v in g.total_bounds)
        rows.append({
            "code": code, "dong": dong,
            "center": [round((miny + maxy) / 2, 6), round((minx + maxx) / 2, 6)],
            "bounds": [[miny, minx], [maxy, maxx]],   # Leaflet [[S,W],[N,E]]
            "n_tong": int(g["통"].nunique()),
        })
    rows.sort(key=lambda r: r["dong"])
    os.makedirs(OUT, exist_ok=True)
    json.dump({"city": "시흥시", "dongs": rows},
              open(f"{OUT}/manifest.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"manifest: {len(rows)}개 동 → {OUT}/manifest.json")

if __name__ == "__main__":
    main()
