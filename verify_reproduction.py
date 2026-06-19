#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1단계 동일 재현 검증
------------------------------------------------------------
새 구조 산출물(out/{admin_code}/{동명}_*.geojson)이 기존 골든 산출물
(out/ 루트의 gunja_*.geojson, report_*.csv)과 동일한지 비교한다.

전제: 골든을 만든 것과 같은 시기의 연속지적도 SHP(202606)로 빌드해야
      필지가 일치한다. 다른 시기 SHP면 통 집합/필지 키 차이는 SHP 차이일 수 있음.

사용:
  python build_tongban_map.py --config data/31150680/config.json --shp <연속지적도.shp>
  python verify_reproduction.py            # 기본값: 군자동/31150680
  python verify_reproduction.py --new out/31150680 --dong 군자동 --golden out
"""
import argparse, os
import geopandas as gpd

REPORTS = ["report_conflicts.csv", "report_unassigned_parcels.csv",
           "report_table_not_in_shp.csv", "report_missing_tong.csv"]
AREA_CRS = "EPSG:5186"      # 면적 비교용 미터 좌표계
REL_TOL  = 1e-6            # 통별 대칭차/면적 허용 상대오차


def cmp_tong(new_dir, dong, golden_dir):
    a = gpd.read_file(os.path.join(new_dir, f"{dong}_tong.geojson"))
    b = gpd.read_file(os.path.join(golden_dir, "gunja_tong.geojson"))
    sa, sb = set(a["통"]), set(b["통"])
    print(f"[통]   new {len(a)}개 / golden {len(b)}개  | 통 집합 동일: {sa == sb}")
    if sa != sb:
        print("       new-only:", sorted(sa - sb), " golden-only:", sorted(sb - sa))
    am = a.to_crs(AREA_CRS).dissolve("통").geometry
    bm = b.to_crs(AREA_CRS).dissolve("통").geometry
    worst = 0.0
    for t in sorted(sa & sb):
        ga, gb = am.loc[t], bm.loc[t]
        rel = ga.symmetric_difference(gb).area / max(gb.area, 1e-9)
        worst = max(worst, rel)
        if rel > REL_TOL:
            print(f"       통 {t}: 상대 대칭차 {rel:.2e}")
    ok = (sa == sb) and (worst < REL_TOL)
    print(f"       최대 상대 대칭차 {worst:.2e}  → {'OK' if ok else '검토 필요'}")
    return ok


def cmp_parcels(new_dir, dong, golden_dir):
    a = gpd.read_file(os.path.join(new_dir, f"{dong}_parcels.geojson"))
    b = gpd.read_file(os.path.join(golden_dir, "gunja_parcels.geojson"))
    ka = set(zip(a["법정동"], a["지번"]))
    kb = set(zip(b["법정동"], b["지번"]))
    ok = (len(a) == len(b)) and (ka == kb)
    print(f"[필지] new {len(a)} / golden {len(b)}  | (법정동,지번) 키 동일: {ka == kb}")
    if ka != kb:
        print("       new-only:", list(ka - kb)[:5], " golden-only:", list(kb - ka)[:5])
    return ok


def cmp_reports(new_dir, golden_dir):
    def nrows(p):
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8-sig") as f:
            return max(sum(1 for _ in f) - 1, 0)
    allok = True
    for name in REPORTS:
        na = nrows(os.path.join(new_dir, name))
        nb = nrows(os.path.join(golden_dir, name))
        same = na == nb
        allok &= same
        print(f"[{name}] new {na} / golden {nb}  | 행수 동일: {same}")
    return allok


def main():
    ap = argparse.ArgumentParser(description="1단계 동일 재현 검증")
    ap.add_argument("--new", default="out/31150680", help="새 산출물 폴더")
    ap.add_argument("--dong", default="군자동", help="동명(출력 파일 접두사)")
    ap.add_argument("--golden", default="out", help="골든 산출물 폴더(gunja_*)")
    args = ap.parse_args()

    print(f"새 산출물: {args.new}/{args.dong}_*  ↔  골든: {args.golden}/gunja_*\n")
    r1 = cmp_tong(args.new, args.dong, args.golden)
    r2 = cmp_parcels(args.new, args.dong, args.golden)
    r3 = cmp_reports(args.new, args.golden)
    print()
    if r1 and r2 and r3:
        print("✔ 동일 재현 확인 — 1단계 완료 기준 충족")
    else:
        print("⚠ 차이 있음 — 위 항목 검토 (SHP 시기 차이일 수도 있음)")


if __name__ == "__main__":
    main()
