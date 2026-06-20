#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
통반 검증 — 담당자 재검토용 점검을 한 번에.
 (1) 미표시 통: 시행규칙 별표에는 있으나 지도에 안 그려진 통(issues.json의 missing).
 (2) 떨어진 조각 통(split): 한 통의 필지가 본체에서 멀리 떨어진 군집으로 나뉜 경우.
     → 별표 지번에 엉뚱한 지번이 섞여 들어갔을 가능성.
 (3) 누락 대지(omission): 어느 통에도 안 들어간 '대' 필지가 한 통에 둘러싸인 경우.
     → 그 통에서 빠진 지번일 가능성(예: 군자동 도일로92번길 일대 → 25통).
 (4) 겹친 통(overlap): 도로망(깔끔) 통 폴리곤이 서로 공간적으로 겹치는 경우.
     → 같은 땅이 두 통에 들어간 셈(별표 관할 재정리 대상).

자동 수정이 아니라 '의심 안내'다(담당자 확인용).

split 등급: 조각필지 ≤10 = 지번오류의심 / 11~60 = 블록분리 / >60 = 과대확장의심.

출력: out/review.json(코드별 split·omission·overlap), out/report_review.csv(통합 표)
사용: python verify_tongban.py   (gen_issues.py 실행 뒤에 돌릴 것; 원본 지적도 SHP 필요)
"""
import argparse, csv, glob, json, os, re
from collections import defaultdict, Counter
import geopandas as gpd
import numpy as np
from shapely.strtree import STRtree

OUT = "out"
META = {"통", "반", "지번", "geometry", "fill_method", "근사"}
SHP_PATH = "LSMD_CONT_LDREG_41390_202606.shp"
BUILT_JIMOK = {"대"}          # 누락 판정 대상 지목(주거·대지). 임야·전·답·도로 등은 제외(빈 땅)
JIBUN_RE = re.compile(r"^(산?\d[\d-]*)(\D*)$")


def parse_jibun(j):
    m = JIBUN_RE.match(str(j))
    return (m.group(1), m.group(2)) if m else (str(j), "")


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


def find_overlaps(code, dong, overlap_min):
    """도로망(깔끔) 통 폴리곤이 서로 겹치는 쌍을 찾는다(겹친 통)."""
    rbp = f"{OUT}/{code}/{dong}_tong_roadblock.geojson"
    if not os.path.exists(rbp):
        return []
    rb = gpd.read_file(rbp)
    if rb.empty:
        return []
    rb = rb.to_crs("EPSG:5186")
    rb["통"] = rb["통"].astype(int)
    by = rb.dissolve(by="통")["geometry"]
    tongs = list(by.index)
    out = []
    for i in range(len(tongs)):
        for j in range(i + 1, len(tongs)):
            gi, gj = by.iloc[i], by.iloc[j]
            if gi.intersects(gj):
                a = gi.intersection(gj).area
                if a >= overlap_min:
                    out.append({"통": [int(tongs[i]), int(tongs[j])], "면적m2": int(round(a))})
    out.sort(key=lambda o: -o["면적m2"])
    return out


def find_omissions(dong_names, assigned, shp):
    """미배정 '대' 필지가 한 통에 둘러싸이면 그 통에서 빠진 지번으로 본다(누락 대지).
    dong_names: 이 행정동의 법정동명 집합, assigned: 배정 필지(GDF, 5186, 통 보유), shp: 동 지적도(GDF, 5186)."""
    sub = shp[shp["법정동"].isin(dong_names)]
    if sub.empty or assigned.empty:
        return []
    asg_set = set(zip(assigned["법정동"].astype(str), assigned["지번"].astype(str)))
    mask_jimok = sub["지목"].isin(BUILT_JIMOK).values
    notasg = np.array([(str(d), str(j)) not in asg_set for d, j in zip(sub["법정동"], sub["지번"])])
    cand = sub[mask_jimok & notasg]
    if cand.empty:
        return []
    ageoms = list(assigned.geometry)
    aT = assigned["통"].astype(int).values
    tree = STRtree(ageoms)
    flagged = defaultdict(list)
    for _, r in cand.iterrows():
        g = r.geometry
        if g is None or g.is_empty:
            continue
        idx = tree.query(g.buffer(15))
        near = [(int(aT[k]), ageoms[k].distance(g)) for k in idx]
        near = [(t, d) for t, d in near if d <= 15]
        if not near:
            continue
        cnt = Counter(t for t, _ in near)
        top, c = cnt.most_common(1)[0]
        if c / len(near) >= 0.8:                       # 인접의 80%+가 한 통 → 그 통 누락 의심
            flagged[top].append(f"{r['법정동']} {r['지번']}")
    res = [{"통": int(t), "필지수": len(v), "지번": v} for t, v in flagged.items()]
    res.sort(key=lambda o: -o["필지수"])
    return res


def main():
    ap = argparse.ArgumentParser(description="통반 검증(미표시·분리·누락·겹침)")
    ap.add_argument("--link", type=float, default=150.0, help="군집 연결 거리(m)")
    ap.add_argument("--gap", type=float, default=300.0, help="본체에서 분리로 볼 거리(m)")
    ap.add_argument("--overlap-min", type=float, default=200.0, help="겹침으로 볼 최소 면적(㎡)")
    ap.add_argument("--no-shp", action="store_true", help="지적도 없이 실행(누락 점검 생략)")
    args = ap.parse_args()

    # 원본 지적도(누락 점검용): 한 번만 읽고 법정동명·지번·지목 부여
    shp = None
    if not args.no_shp and os.path.exists(SHP_PATH):
        pnu2name = {}
        for v in json.load(open("data/siheung_legal_codes.json", encoding="utf-8")).values():
            pnu2name.update(v.get("legal_dongs", {}))
        shp = gpd.read_file(SHP_PATH).to_crs("EPSG:5186")
        shp["법정동"] = shp["PNU"].str[:10].map(pnu2name)
        shp = shp[shp["법정동"].notna()].copy()
        jp = [parse_jibun(j) for j in shp["JIBUN"]]
        shp["지번"] = [a for a, _ in jp]
        shp["지목"] = [b for _, b in jp]

    issues_path = f"{OUT}/issues.json"
    issues = json.load(open(issues_path, encoding="utf-8")) if os.path.exists(issues_path) else {}

    # 행정동코드 → 법정동명 목록(누락 점검에서 동 범위 한정)
    legmap = {k: list(v.get("legal_dongs", {}).values())
              for k, v in json.load(open("data/siheung_legal_codes.json", encoding="utf-8")).items()}

    review = {}
    rows = []
    n_missing = n_split = n_overlap = n_omit = 0
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
        # (4) 겹친 통 — 도로망 폴리곤 중첩
        overlaps = find_overlaps(code, dong, args.overlap_min)
        for o in overlaps:
            rows.append(["겹침", dong, f"{o['통'][0]}∩{o['통'][1]}", "", o["면적m2"], "도로망 통 폴리곤 중첩"])
            n_overlap += 1

        # (3) 누락 대지 — 미배정 '대'가 한 통에 둘러싸임
        omissions = []
        if shp is not None:
            names = set(legmap.get(code, []))
            if names:
                omissions = find_omissions(names, g, shp)
                for om in omissions:
                    rows.append(["누락", dong, om["통"], om["필지수"], "",
                                 " / ".join(om["지번"][:15])])
                    n_omit += om["필지수"]

        entry = {"dong": dong}
        if splits:
            splits.sort(key=lambda s: -s["거리m"])
            entry["n_split"] = len(splits); entry["split"] = splits
        if omissions:
            entry["n_omit"] = sum(o["필지수"] for o in omissions); entry["omission"] = omissions
        if overlaps:
            entry["n_overlap"] = len(overlaps); entry["overlap"] = overlaps
        if len(entry) > 1:
            review[code] = entry

    os.makedirs(OUT, exist_ok=True)
    json.dump(review, open(f"{OUT}/review.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    order = {"미표시": 0, "누락": 1, "겹침": 2}
    rows.sort(key=lambda r: (order.get(r[0], 3), -(r[4] if isinstance(r[4], int) else 0)))
    with open(f"{OUT}/report_review.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["유형", "행정동", "통", "필지수", "거리/면적", "상세/사유/지번"])
        w.writerows(rows)

    print(f"미표시 통 {n_missing} · 떨어진 조각 통 {n_split}"
          f"(지번오류의심 {by_grade['지번오류의심']}/블록분리 {by_grade['블록분리']}/과대확장 {by_grade['과대확장의심']})"
          f" · 누락 대지 {n_omit}필지 · 겹친 통 {n_overlap}쌍")
    print(f"→ out/review.json, out/report_review.csv")


if __name__ == "__main__":
    main()
