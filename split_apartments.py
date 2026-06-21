#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
아파트 동(棟)별 통 분할 — 한 지번을 별표가 통을 동별로 나눠 둔 경우의 정식 반영.

예) 군자동 거모동 612-1 동보아파트: 별표가 101~103동=23통, 104~107동=24통으로
정해 두었으나 지적도엔 612-1이 단일 필지라 파서가 못 쪼갠다. 이 스크립트는
OSM 건물 위치(데이터 building_splits.json)로 그 필지를 Voronoi 분할해
_parcels.geojson / _tong.geojson 에 23·24통을 정식으로 만든다(별표가 정한 통을 완성).

분할 대상이 아닌 피처는 그대로 두어 diff를 최소화한다.
사용: python split_apartments.py   (build/별표 변경 후, gen_address_index·gen_issues·gen_overview 재실행 전)
"""
import json, os
from shapely.geometry import shape, mapping, MultiPoint, Point
from shapely.ops import voronoi_diagram, unary_union, transform
from pyproj import Transformer

CFG = "data/building_splits.json"
TO_M = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True).transform
TO_DEG = Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True).transform


def rep_lonlat(geom_deg):
    p = geom_deg.representative_point()
    return round(p.x, 7), round(p.y, 7)


def split_dong(code, specs):
    cfg = json.load(open(f"data/{code}/config.json", encoding="utf-8"))
    dong = cfg["admin_dong"]
    parcels_path = f"out/{code}/{dong}_parcels.geojson"
    tong_path = f"out/{code}/{dong}_tong.geojson"
    parcels = json.load(open(parcels_path, encoding="utf-8"))
    tong = json.load(open(tong_path, encoding="utf-8"))

    for spec in specs:
        jibun, beop = spec["지번"], spec.get("법정동")
        blds = spec["buildings"]
        # 대상 필지(같은 지번 여러 필지면 합침) — _parcels에서 제거 후 분할 결과로 대체
        targ_idx = [i for i, f in enumerate(parcels["features"])
                    if str(f["properties"].get("지번")) == str(jibun)
                    and (beop is None or f["properties"].get("법정동") == beop)]
        if not targ_idx:
            print(f"  ! {code} 지번 {jibun} 없음 — 스킵"); continue
        proto = parcels["features"][targ_idx[0]]["properties"]
        keep_t = int(proto["통"])                       # 현재 필지가 속한 통(보존 통)
        base_deg = unary_union([shape(parcels["features"][i]["geometry"]) for i in targ_idx])
        base_m = transform(TO_M, base_deg)

        # 건물점(5186) + 통
        pts = [(Point(*TO_M(b["lon"], b["lat"])), int(b["통"])) for b in blds]
        vor = voronoi_diagram(MultiPoint([p for p, _ in pts]), envelope=base_m)

        region_m = {}                                   # 통 -> geom(5186)
        for cell in vor.geoms:
            c = cell.intersection(base_m)
            if c.is_empty:
                continue
            owner = next((t for p, t in pts if c.contains(p)), None)
            if owner is None:                           # 안전망: 최근접 건물의 통
                owner = min(pts, key=lambda pt: pt[0].distance(c.representative_point()))[1]
            region_m.setdefault(owner, []).append(c)
        region_m = {t: unary_union(g) for t, g in region_m.items()}
        new_tongs = sorted(t for t in region_m if t != keep_t)

        # --- _parcels: 대상 필지 제거 후 통별 조각으로 대체 ---
        for i in sorted(targ_idx, reverse=True):
            parcels["features"].pop(i)
        for t, gm in region_m.items():
            gd = transform(TO_DEG, gm)
            props = dict(proto); props["통"] = t
            if t != keep_t:
                props["반"] = 0
            parcels["features"].append({"type": "Feature", "properties": props,
                                        "geometry": mapping(gd)})

        # --- _tong: 보존 통에서 새 통 영역 제거 + 새 통 추가 ---
        carve_m = unary_union([region_m[t] for t in new_tongs]) if new_tongs else None
        for f in tong["features"]:
            if int(f["properties"]["통"]) == keep_t:
                g = transform(TO_M, shape(f["geometry"]))
                if carve_m is not None:
                    g = g.difference(carve_m)
                gd = transform(TO_DEG, g)
                f["geometry"] = mapping(gd)
                lon, lat = rep_lonlat(gd)
                f["properties"]["lon"], f["properties"]["lat"] = lon, lat
        for t in new_tongs:
            gd = transform(TO_DEG, region_m[t])
            lon, lat = rep_lonlat(gd)
            tong["features"].append({"type": "Feature",
                "properties": {"통": t, "lon": lon, "lat": lat, "근사": 0},
                "geometry": mapping(gd)})

        print(f"  ✔ {code} {dong} {beop} {jibun}: {keep_t}통 → "
              f"{keep_t} + {'+'.join(map(str, new_tongs))}통 "
              f"(건물 {len(blds)}, Voronoi 분할)")

    json.dump(parcels, open(parcels_path, "w", encoding="utf-8"), ensure_ascii=False)
    tong["features"].sort(key=lambda f: int(f["properties"]["통"]))
    json.dump(tong, open(tong_path, "w", encoding="utf-8"), ensure_ascii=False)


def main():
    if not os.path.exists(CFG):
        raise SystemExit(f"설정 없음: {CFG}")
    cfg = json.load(open(CFG, encoding="utf-8"))
    for code, specs in cfg.items():
        if code.startswith("_"):
            continue
        split_dong(code, specs)
    print("→ 완료. 이어서 gen_address_index.py · gen_issues.py · gen_overview.py 재실행 권장.")


if __name__ == "__main__":
    main()
