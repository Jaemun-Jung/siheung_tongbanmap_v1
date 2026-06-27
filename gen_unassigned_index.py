#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
미배정 대지 위치 인덱스 — out/unassigned_index.json
  형식: { "법정동|지번": [행정동코드, 행정동명, lat, lon] }

검색(지번/도로명)이 '별표'에서 못 찾을 때(=별표 누락 의심 미배정 대지),
그 필지 '위치'로 빨간 핀을 찍기 위한 인덱스. (셸이 fetch 해서 폴백 검색에 사용)
좌표는 폴리곤 내부 대표점(representative_point) — 핀이 항상 필지 안에 찍히게.

사용: PYTHONUTF8=1 python gen_unassigned_index.py   (gen_unassigned.py 후 실행)
"""
import glob
import json
import os

import geopandas as gpd


def main():
    idx = {}
    files = sorted(glob.glob(os.path.join("out", "3*", "*_unassigned.geojson")))
    for up in files:
        code = os.path.basename(os.path.dirname(up))
        dong = os.path.basename(up).replace("_unassigned.geojson", "")
        try:
            g = gpd.read_file(up)
        except Exception:
            continue
        if g.empty or "법정동" not in g.columns or "지번" not in g.columns:
            continue
        rep = g.geometry.representative_point()
        for bjd, jib, pt in zip(g["법정동"].astype(str), g["지번"].astype(str), rep):
            idx[f"{bjd}|{jib}"] = [code, dong, round(float(pt.y), 6), round(float(pt.x), 6)]

    os.makedirs("out", exist_ok=True)
    op = os.path.join("out", "unassigned_index.json")
    with open(op, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)
    print(f"→ {op}  {len(idx)}건 (동 파일 {len(files)}개)")


if __name__ == "__main__":
    main()
