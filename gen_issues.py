#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8단계 검증 데이터 — out/issues.json 생성.
동별 표통수/지도통수/미표시통+사유/충돌/미배정을 모아 셸 안내에 쓴다.
입력: data/{code}/관할구역.csv, out/{code}/{동}_tong.geojson, report_*.csv
사용: python gen_issues.py
"""
import csv, glob, json, os
import geopandas as gpd

OUT = "out"

def nrows(path):
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8-sig") as f:
        return max(sum(1 for _ in f) - 1, 0)

def main():
    issues = {}
    for cfgp in sorted(glob.glob("data/3*/config.json")):
        cfg = json.load(open(cfgp, encoding="utf-8"))
        code, dong = cfg["admin_code"], cfg["admin_dong"]
        csvp = f"data/{code}/관할구역.csv"
        tongp = f"{OUT}/{code}/{dong}_tong.geojson"
        if not (os.path.exists(csvp) and os.path.exists(tongp)):
            continue
        table = set()
        for r in csv.DictReader(open(csvp, encoding="utf-8-sig")):
            table.add(int(r["통"]))
        drawn = set(int(t) for t in gpd.read_file(tongp)["통"].unique())
        # 미표시 통 + 사유
        reasons = {}
        mr = f"{OUT}/{code}/report_missing_tong.csv"
        if os.path.exists(mr):
            for r in csv.DictReader(open(mr, encoding="utf-8-sig")):
                reasons[int(r["통"])] = {"유형": r.get("유형", ""), "사유": r.get("사유", "")}
        missing = [{"통": t, **reasons.get(t, {"유형": "", "사유": "사유 미상"})}
                   for t in sorted(table - drawn)]
        issues[code] = {
            "dong": dong,
            "n_table": len(table),
            "n_drawn": len(drawn),
            "n_missing": len(missing),
            "missing": missing,
            "n_conflict": nrows(f"{OUT}/{code}/report_conflicts.csv"),
            "n_unassigned": nrows(f"{OUT}/{code}/report_unassigned_parcels.csv"),
        }
        print(f"  {code} {dong:7s} 표{len(table):>3} 지도{len(drawn):>3} "
              f"미표시{len(missing):>3} 충돌{issues[code]['n_conflict']:>3}")
    json.dump(issues, open(f"{OUT}/issues.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    tot_t = sum(v["n_table"] for v in issues.values())
    tot_d = sum(v["n_drawn"] for v in issues.values())
    print(f"\n→ {OUT}/issues.json  (동 {len(issues)}, 표 통 {tot_t}, 지도 통 {tot_d}, "
          f"미표시 {tot_t - tot_d})")

if __name__ == "__main__":
    main()
