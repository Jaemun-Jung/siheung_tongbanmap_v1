#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
시흥시 통·반 별표 HWPX → 동별 관할구역 CSV(행정동,통,반,관할구역) 추출
------------------------------------------------------------
표 구조: 동명 | 통명 | 반명 | 관할구역.
- 한 통이 한 행. 동명은 동이 바뀌는 행에만 있고(셀 병합) 이후 행은 carry-forward.
- 관할구역 셀은 반마다 별도 문단(hp:p) → 문단 순서 = 반 1..N.
- 반명("1234")은 반 번호 연결 → 문단 수와 일치하는지로 분할 검증.
- 표는 페이지마다 별도 <hp:tbl>로 쪼개져 헤더가 반복됨(헤더행은 skip).

사용:
  python extract_hwpx_tables.py "시흥시 통반의 명칭 및 관할구역.hwpx" \
      --codes data/siheung_admin_codes.json --out data
출력: data/{admin_code}/관할구역.csv  (행정동,통,반,관할구역)
"""
import argparse, csv, json, os, re, zipfile
import xml.etree.ElementTree as ET

def _lt(e):
    return e.tag.split('}')[-1]

def _cell_text(tc):
    return "".join(t.text or "" for t in tc.iter() if _lt(t) == "t").strip()

def _cell_paras(tc):
    """셀 내부 문단별 텍스트(빈 문단 제외)."""
    out = []
    for p in [e for e in tc.iter() if _lt(e) == "p"]:
        s = "".join(t.text or "" for t in p.iter() if _lt(t) == "t").strip()
        if s:
            out.append(s)
    return out

def _starts_jibun(p):
    """문단이 순수 지번(숫자 또는 '산'+숫자)으로 시작 = 같은 반의 줄바꿈 이어쓰기."""
    p = p.lstrip()
    return bool(p) and (p[0].isdigit() or bool(re.match(r"^산\s*\d", p)))

def _group_bans(paras):
    """문단들을 반 단위로 묶는다.
    이어쓰기(같은 반) = 지번(숫자/산N)으로 시작하는 문단.
    새 반 = 법정동명·아파트명 등 한글/괄호로 새로 시작하는 문단."""
    groups = []
    for seg in paras:
        if groups and _starts_jibun(seg):
            groups[-1].append(seg)
        else:
            groups.append([seg])
    return [" ".join(g) for g in groups]

def parse_hwpx(hwpx_path):
    """반환: (rows[(행정동,통,반,관할구역)], warnings[(행정동,통,반명,기대,실제)])."""
    xml = zipfile.ZipFile(hwpx_path).read("Contents/section0.xml").decode("utf-8")
    root = ET.fromstring(xml)
    rows, warns = [], []
    cur = None
    for tbl in [e for e in root.iter() if _lt(e) == "tbl"]:
        for tr in [r for r in tbl.iter() if _lt(r) == "tr"]:
            tcs = [c for c in tr if _lt(c) == "tc"]
            if not tcs:
                continue
            head = _cell_text(tcs[0])
            if head == "동명":                        # 반복 헤더행
                continue
            if len(tcs) == 4:
                dong = _cell_text(tcs[0]) or cur
                tong, ban, area_tc = _cell_text(tcs[1]), _cell_text(tcs[2]), tcs[3]
                cur = dong
            elif len(tcs) == 3:                       # 동명 병합 → carry-forward
                dong = cur
                tong, ban, area_tc = _cell_text(tcs[0]), _cell_text(tcs[1]), tcs[2]
            else:
                continue
            if not dong:
                continue
            paras = _cell_paras(area_tc)
            if not paras:
                continue
            ban_areas = _group_bans(paras)
            # 검증: 반명 숫자열이 '1..N' 재구성과 일치하는지
            actual = re.sub(r"\D", "", ban)
            expected = "".join(str(i) for i in range(1, len(ban_areas) + 1))
            if actual != expected:
                warns.append((dong, tong, ban, expected, actual))
            tn = int(re.sub(r"\D", "", tong))
            for i, seg in enumerate(ban_areas, start=1):
                rows.append((dong, tn, i, seg))
    return rows, warns

def main():
    ap = argparse.ArgumentParser(description="시흥시 통·반 별표 HWPX → 동별 CSV 추출")
    ap.add_argument("hwpx", help="별표 HWPX 경로")
    ap.add_argument("--codes", default="data/siheung_admin_codes.json",
                    help="행정동명→admin_code 매핑 JSON")
    ap.add_argument("--out", default="data", help="출력 루트 (data/{admin_code}/관할구역.csv)")
    ap.add_argument("--skip-existing", action="store_true",
                    help="이미 관할구역.csv가 있는 동은 건너뜀(군자동 골든 보존)")
    args = ap.parse_args()

    codes = {k: v for k, v in json.load(open(args.codes, encoding="utf-8")).items()
             if not k.startswith("_")}
    rows, warns = parse_hwpx(args.hwpx)

    by_dong = {}
    for dong, tong, ban, area in rows:
        by_dong.setdefault(dong, []).append((dong, tong, ban, area))

    print(f"행정동 {len(by_dong)}개, 총 {len(rows)}행(반)")
    missing = [d for d in by_dong if d not in codes]
    if missing:
        print("⚠ admin_code 매핑 없는 동:", missing)
    for dong in by_dong:
        code = codes.get(dong)
        if not code:
            continue
        d = os.path.join(args.out, code)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "관할구역.csv")
        if args.skip_existing and os.path.exists(path):
            print(f"  {code} {dong:7s} (기존 파일 보존 → skip)")
            continue
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["행정동", "통", "반", "관할구역"])
            w.writerows(by_dong[dong])
        n_tong = len({r[1] for r in by_dong[dong]})
        print(f"  {code} {dong:7s} 통 {n_tong:>3}, 반 {len(by_dong[dong]):>4}  → {path}")

    # 검증 경고(반명↔반그룹수 불일치)를 리포트로 — 해당 통은 반 라벨 수동 검토 대상(통 경계는 무관)
    wpath = os.path.join(args.out, "_extract_warnings.csv")
    os.makedirs(args.out, exist_ok=True)
    with open(wpath, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["행정동", "통", "반명", "기대(1..N)", "실제반명"])
        w.writerows(warns)
    if warns:
        print(f"\n⚠ 반명↔반그룹수 불일치 {len(warns)}건 → {wpath} (반 라벨만 영향, 통 경계는 정상)")
        for w in warns:
            print(f"   {w[0]} {w[1]}통 반명'{w[2]}' 기대'{w[3]}' 실제'{w[4]}'")
    else:
        print("\n✔ 모든 통에서 반명 = 반그룹수(1..N) 일치")

if __name__ == "__main__":
    main()
