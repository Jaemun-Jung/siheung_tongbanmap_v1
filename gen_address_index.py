#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
주소 검색용 인덱스 — out/address_index.json.
전 동 별표지번(parcel_match) 필지에서 "법정동|지번" → [code, dong, 통, 반] 매핑.
6단계: 도로명주소 → (juso) 지번 변환 → 이 인덱스로 통 조회.
사용: python gen_address_index.py
"""
import glob, json, os
import geopandas as gpd

def main():
    idx = {}
    dup = 0
    for cfgp in sorted(glob.glob("data/3*/config.json")):
        cfg = json.load(open(cfgp, encoding="utf-8"))
        code, dong = cfg["admin_code"], cfg["admin_dong"]
        p = f"out/{code}/{dong}_parcels.geojson"
        if not os.path.exists(p):
            continue
        g = gpd.read_file(p)
        for _, r in g.iterrows():
            if r.get("fill_method") != "parcel_match":
                continue
            key = f"{r['법정동']}|{r['지번']}"
            if key in idx:
                dup += 1
                continue
            ban = r["반"]
            idx[key] = [code, dong, int(r["통"]), int(ban) if ban not in (None, "") else 0]
    json.dump({"index": idx}, open("out/address_index.json", "w", encoding="utf-8"),
              ensure_ascii=False)
    size = os.path.getsize("out/address_index.json")
    print(f"주소 인덱스 {len(idx)}건 (중복 {dup} 스킵) → out/address_index.json ({size//1024}KB)")

if __name__ == "__main__":
    main()
