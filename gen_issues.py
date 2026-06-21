#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8단계 검증 데이터 — out/issues.json 생성.
동별 표통수/지도통수/미표시통+사유/충돌/미배정을 모아 셸 안내에 쓴다.
입력: data/{code}/관할구역.csv, out/{code}/{동}_tong.geojson, report_*.csv
사용: python gen_issues.py
"""
import csv, glob, json, os, re
import geopandas as gpd

OUT = "out"
# 별표 관할구역에 아파트 동(棟)/호 표기가 있으면 '같은 지번을 동별로 분할'한 통(아파트)
APT_BUILDING = re.compile(r"아파트|빌라|연립|단지|타운|마을|Ⓐ|\d+동|\d+호|\(")

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
        apt_tongs = set()                       # 별표에 아파트 동/호 표기가 있는 통
        for r in csv.DictReader(open(csvp, encoding="utf-8-sig")):
            t = int(r["통"]); table.add(t)
            if APT_BUILDING.search(str(r.get("관할구역", ""))):
                apt_tongs.add(t)
        drawn = set(int(t) for t in gpd.read_file(tongp)["통"].unique())
        # 미표시 통 + 사유
        reasons = {}
        mr = f"{OUT}/{code}/report_missing_tong.csv"
        if os.path.exists(mr):
            for r in csv.DictReader(open(mr, encoding="utf-8-sig")):
                reasons[int(r["통"])] = {"유형": r.get("유형", ""), "사유": r.get("사유", "")}
        missing = []
        for t in sorted(table - drawn):
            info = dict(reasons.get(t, {"유형": "", "사유": "사유 미상"}))
            # 같은 지번을 아파트 동별로 나눈 통(지적도엔 같은 지번 1개라 흡수됨) → 수동 그리기 안내
            if t in apt_tongs and ("충돌" in info.get("사유", "") or "흡수" in info.get("사유", "")):
                info["유형"] = "아파트"
                info["사유"] = "같은 지번을 아파트 동(棟)별로 분할 — 수동 그리기 필요"
            missing.append({"통": t, **info})
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
