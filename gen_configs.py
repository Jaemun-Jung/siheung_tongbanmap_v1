#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
동별 config.json 생성
------------------------------------------------------------
data/siheung_legal_codes.json(행정동→법정동코드/이름) + 공통 옵션을 합쳐
data/{admin_code}/config.json 을 생성. 기존 config(군자동 등)는 --force 없으면 보존.
"""
import argparse, json, os

LEGAL = "data/siheung_legal_codes.json"

def main():
    ap = argparse.ArgumentParser(description="동별 config.json 생성")
    ap.add_argument("--force", action="store_true", help="기존 config.json 덮어쓰기")
    args = ap.parse_args()

    legal = json.load(open(LEGAL, encoding="utf-8"))
    made, skipped = 0, 0
    for code, info in sorted(legal.items()):
        d = f"data/{code}"
        os.makedirs(d, exist_ok=True)
        path = f"{d}/config.json"
        if os.path.exists(path) and not args.force:
            print(f"  {code} {info['admin_dong']:7s} (기존 보존 → skip)")
            skipped += 1
            continue
        cfg = {
            "admin_dong": info["admin_dong"],
            "admin_code": code,
            "legal_dongs": info["legal_dongs"],
            "target_beopjeong": info["target_beopjeong"],
            "table_csv": "관할구역.csv",
            "source_crs_fallback": "EPSG:5186",
            "shp_encoding": "cp949",
            "conflict_policy": "min_tong",
            "bonbun_fallback": True,
            "road_fill": True,
            "road_jimok": ["도"],
            "road_split_sliver_m2": 5.0,
            "palette": "default",
            "split_parcel_tong": [],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print(f"  {code} {info['admin_dong']:7s} 법정동 {info['target_beopjeong']} → {path}")
        made += 1
    print(f"\n생성 {made}, 보존 {skipped}")

if __name__ == "__main__":
    main()
