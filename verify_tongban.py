#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
통반 검증 — 담당자 재검토용 두 가지 점검을 한 번에.
 (1) 미표시 통: 시행규칙 별표에는 있으나 지도에 안 그려진 통(issues.json의 missing).
 (2) 떨어진 조각 통: 한 통의 필지가 본체에서 멀리 떨어진 군집으로 나뉜 경우.
     → 별표 지번에 엉뚱한 지번이 섞여 들어갔을 가능성(담당자 재검토 대상).

판정: 통의 필지 중앙점을 LINK(m) 이내로 이어 군집을 만들고, 본체(최대 군집)에서
GAP_FLAG(m) 넘게 떨어진 군집을 '분리'로 본다. 자동 수정이 아니라 '의심 안내'다.

등급: 조각필지 ≤10 = 지번오류의심(원거리 소수, 오기 가능성 큼)
      11~60        = 블록분리(군자동 1통 류, 관할 재확인)
      >60          = 과대확장의심(공유 법정동 본번폴백; NEXT_STEPS #1 빌드 보정 대상)

출력: out/review.json (코드별 split 목록), out/report_review.csv (미표시+분리 통합 표)
사용: python verify_tongban.py   (gen_issues.py 실행 뒤에 돌릴 것)
"""
import argparse, csv, glob, json, os
from collections import defaultdict
import geopandas as gpd
import numpy as np

OUT = "out"
META = {"통", "반", "지번", "geometry", "fill_method", "근사"}


def clusters_of(cx, cy, link):
    """필지 중앙점이 link(m) 이내면 같은 군집(union-find). 큰 군집부터 정렬해 반환."""
    n = len(cx)
    par = list(range(n))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a

    link2 = link * link
    for i in range(n):
        for j in range(i + 1, n):
            if (cx[i] - cx[j]) ** 2 + (cy[i] - cy[j]) ** 2 <= link2:
                par[find(i)] = find(j)
    cl = defaultdict(list)
    for i in range(n):
        cl[find(i)].append(i)
    return sorted(cl.values(), key=len, reverse=True)


def grade(n):
    if n <= 10:
        return "지번오류의심"
    if n <= 60:
        return "블록분리"
    return "과대확장의심"


def main():
    ap = argparse.ArgumentParser(description="통반 검증(미표시 통 + 떨어진 조각 통)")
    ap.add_argument("--link", type=float, default=150.0, help="군집 연결 거리(m)")
    ap.add_argument("--gap", type=float, default=300.0, help="본체에서 분리로 볼 거리(m)")
    args = ap.parse_args()

    issues_path = f"{OUT}/issues.json"
    issues = json.load(open(issues_path, encoding="utf-8")) if os.path.exists(issues_path) else {}

    review = {}
    rows = []
    n_missing = n_split = 0
    by_grade = defaultdict(int)

    for cfgp in sorted(glob.glob("data/3*/config.json")):
        cfg = json.load(open(cfgp, encoding="utf-8"))
        code, dong = cfg["admin_code"], cfg["admin_dong"]

        # (1) 미표시 통 — issues.json에서 표로 옮김
        for m in issues.get(code, {}).get("missing", []):
            rows.append(["미표시", dong, m.get("통"), "", "", m.get("사유") or m.get("유형", "")])
            n_missing += 1

        # (2) 떨어진 조각 통
        p = f"{OUT}/{code}/{dong}_parcels.geojson"
        if not os.path.exists(p):
            continue
        g = gpd.read_file(p).to_crs("EPSG:5186")
        g = g[g.geometry.notna()]
        ldcol = next((x for x in g.columns if x not in META), None)

        splits = []
        for tong, sub in g.groupby(g["통"].astype(int)):
            sub = sub.reset_index(drop=True)
            if len(sub) < 2:
                continue
            cent = sub.geometry.centroid
            cx, cy = cent.x.values, cent.y.values
            cls = clusters_of(cx, cy, args.link)
            if len(cls) < 2:
                continue
            main = cls[0]
            for sec in cls[1:]:
                nd = min(np.hypot(cx[i] - cx[j], cy[i] - cy[j]) for i in sec for j in main)
                if nd < args.gap:
                    continue
                jib = [((str(sub.iloc[i][ldcol]) + " ") if ldcol else "") + str(sub.iloc[i]["지번"]) for i in sec]
                gr = grade(len(sec))
                splits.append({"통": int(tong), "등급": gr, "조각필지": len(sec),
                               "거리m": int(round(nd)), "지번": jib})
                rows.append([f"분리/{gr}", dong, int(tong), len(sec), int(round(nd)), " / ".join(jib[:15])])
                by_grade[gr] += 1
                n_split += 1
        if splits:
            splits.sort(key=lambda s: -s["거리m"])
            review[code] = {"dong": dong, "n_split": len(splits), "split": splits}

    os.makedirs(OUT, exist_ok=True)
    json.dump(review, open(f"{OUT}/review.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    # 미표시 먼저, 그 다음 거리 먼 순
    rows.sort(key=lambda r: (r[0] != "미표시", -(r[4] if isinstance(r[4], int) else 0)))
    with open(f"{OUT}/report_review.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["유형", "행정동", "통", "조각필지수", "본체에서_거리(m)", "상세/사유/지번"])
        w.writerows(rows)

    print(f"미표시 통 {n_missing}건 · 떨어진 조각 통 {n_split}건"
          f"(지번오류의심 {by_grade['지번오류의심']} / 블록분리 {by_grade['블록분리']} / 과대확장의심 {by_grade['과대확장의심']})")
    print(f"→ out/review.json, out/report_review.csv")


if __name__ == "__main__":
    main()
