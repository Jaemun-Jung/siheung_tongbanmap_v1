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
JIBRE = re.compile(r"([가-힣]{2,4}[동리])\s*(산?\d+(?:-\d+)?)")

def aptname(raw):
    """별표 관할구역에서 아파트 단지명만 추출(법정동·지번·동번호·호 제거)."""
    s = re.sub(r"[()（）]", " ", str(raw))
    s = re.sub(r"^[가-힣]{2,4}[동리]\s*", "", s)
    s = re.sub(r"산?\d[\d\-~ㆍ]*", "", s)
    s = re.sub(r"\d+동.*$", "", s)
    s = re.sub(r"\d+호.*$", "", s)
    s = re.sub(r"상가|아파트|유치원", "", s)
    return s.strip()

def nrows(path):
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8-sig") as f:
        return max(sum(1 for _ in f) - 1, 0)

def main():
    # 담당자 확인 override(미표시 통 위치 잡는 데도 사용)
    ov = {}
    ovp = "data/apt_jibun_overrides.csv"
    if os.path.exists(ovp):
        for o in csv.DictReader(open(ovp, encoding="utf-8-sig")):
            ov.setdefault(str(o["code"]), {}).setdefault(int(o["통"]), (o["법정동"].strip(), o["지번"].strip()))
    issues = {}
    for cfgp in sorted(glob.glob("data/3*/config.json")):
        cfg = json.load(open(cfgp, encoding="utf-8"))
        code, dong = cfg["admin_code"], cfg["admin_dong"]
        beops = set(cfg["legal_dongs"].values())
        csvp = f"data/{code}/관할구역.csv"
        tongp = f"{OUT}/{code}/{dong}_tong.geojson"
        if not (os.path.exists(csvp) and os.path.exists(tongp)):
            continue
        table = set()
        apt_tongs = set()                       # 별표에 아파트 동/호 표기가 있는 통
        tong_jibun = {}                          # 통 → 첫 (법정동,지번) (위치 잡기용)
        tong_cluster = {}                        # 통 → 아파트명(단지) — 같은 단지 통끼리 위치 공유
        cluster_jibun = {}                       # 아파트명 → (법정동,지번)
        for r in csv.DictReader(open(csvp, encoding="utf-8-sig")):
            t = int(r["통"]); table.add(t)
            raw = str(r.get("관할구역", ""))
            if APT_BUILDING.search(raw):
                apt_tongs.add(t)
            m = JIBRE.search(raw.replace("～", "~"))
            ji = (m.group(1), m.group(2)) if (m and m.group(1) in beops) else None
            if t not in tong_jibun and ji:
                tong_jibun[t] = ji
            cl = aptname(raw)
            if t not in tong_cluster and cl:
                tong_cluster[t] = cl
            if ji and cl and cl not in cluster_jibun:
                cluster_jibun[cl] = ji
        drawn = set(int(t) for t in gpd.read_file(tongp)["통"].unique())
        # 필지 중심점 (법정동,지번) → [lat,lon] (미표시 통 클릭 이동용)
        par = gpd.read_file(f"{OUT}/{code}/{dong}_parcels.geojson")
        cen = {}
        for _, pr in par.iterrows():
            key = (str(pr.get("법정동")), str(pr.get("지번")))
            if key not in cen and pr.geometry is not None and not pr.geometry.is_empty:
                c = pr.geometry.representative_point()
                cen[key] = [round(c.y, 7), round(c.x, 7)]
        # 미표시 통 + 사유(짧게) + 위치
        reasons = {}
        mr = f"{OUT}/{code}/report_missing_tong.csv"
        if os.path.exists(mr):
            for r in csv.DictReader(open(mr, encoding="utf-8-sig")):
                reasons[int(r["통"])] = {"유형": r.get("유형", ""), "사유": r.get("사유", "")}
        missing = []
        for t in sorted(table - drawn):
            info = dict(reasons.get(t, {"유형": "", "사유": ""}))
            s = info.get("사유", "")
            if t in apt_tongs:
                info["유형"] = "아파트"
                info["사유"] = "아파트 동별 분할 — 아파트명+동 검색"
            elif "충돌" in s or "흡수" in s:
                info["사유"] = "인접 통에 포함됨"
            else:
                info["사유"] = "지번 확인 필요"
            # 위치: override 지번 → 별표 첫 지번 → 같은 단지(아파트명)의 지번
            key = ov.get(code, {}).get(t) or tong_jibun.get(t) or cluster_jibun.get(tong_cluster.get(t, ""))
            if key and tuple(key) in cen:
                info["loc"] = cen[tuple(key)]
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
