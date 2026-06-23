#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
별표 ↔ 지도 정합성 검사 — 별표(관할구역) 지번이 지도에 '올바른 통'으로 그려졌는지 전수 대조.

오탐을 줄이려고 '전 동을 통틀어(global)' 본다:
  - 정확   : 별표가 지정한 그 동·그 통에 해당 필지가 그려짐
  - 오배정 : 그 필지가 '같은 동'에서 '다른 통'으로 그려짐  ← 진짜 오류(예: 호수 오인)
  - 누락   : 지적도엔 있는데 '어느 동에도' 안 그려짐        ← 진짜 누락(예: 공백 버그)
  - 타동(클립): 별표는 A동인데 공유 법정동이라 B동에 그려짐  ← 의도된 정리(clip_to_admin), 오류 아님
  - 본번처리 : 부번이 본번 폴백으로 처리됨(아파트 공유본번 등)  ← 통 단위 단정 부적합, 오류 아님
  - 폐번   : 지적도에 아예 없음                              ← 별표 구지번 등, 오류 아님

빌드할 때마다 돌려 '정확 / (오배정+누락)' 숫자를 보면, 조용한 오류가 생기면 바로 드러난다.
한계: 별표 '해석(파싱)' 단계 오류는 빌드 파서를 함께 쓰므로 못 잡을 수 있음(통수 대조로 별도 확인).
사용: PYTHONUTF8=1 python verify_byeolpyo.py   →  콘솔 요약 + out/_audit/정합성_불일치.csv
"""
import build_tongban_map as B
import geopandas as gpd
import json, glob, os, csv
from collections import defaultdict

SHP = "LSMD_CONT_LDREG_41390_202606.shp"


def canon(pnu):
    pnu = str(pnu)
    if len(pnu) < 19 or not pnu[:19].isdigit():
        return None, None
    return pnu[:10], ('산' if pnu[10] == '2' else '') + str(int(pnu[11:15])) + \
        (f'-{int(pnu[15:19])}' if int(pnu[15:19]) else '')


def bon(j):
    return str(j).split('-')[0]


def main():
    cfgs = [json.load(open(p, encoding='utf-8')) for p in sorted(glob.glob("data/3*/config.json"))]

    # --- 전 동 통합: 지도에 그려진 (법정동,지번)->[(동,통)] , (법정동,본번)->{(동,통)} ---
    g_draw, g_draw_bon = defaultdict(list), defaultdict(set)
    for cfg in cfgs:
        pp = f"out/{cfg['admin_code']}/{cfg['admin_dong']}_parcels.geojson"
        if not os.path.exists(pp):
            continue
        for f in json.load(open(pp, encoding='utf-8'))['features']:
            p = f['properties']; t = int(p['통']); d = cfg['admin_dong']
            g_draw[(str(p['법정동']), str(p['지번']))].append((d, t))
            g_draw_bon[(str(p['법정동']), bon(p['지번']))].add((d, t))

    # --- 지적도(SHP)에 존재하는 (법정동명,지번)/(법정동명,본번) ---
    shp = gpd.read_file(SHP)
    shp['_bjd'], shp['_jib'] = zip(*shp['PNU'].map(canon))
    legname = {}                       # 법정동코드 -> 법정동명(전 동 통합)
    for cfg in cfgs:
        legname.update(cfg['legal_dongs'])
    inshp, inshp_bon = set(), set()
    sub = shp[shp['_bjd'].isin(legname.keys())]
    for b, j in zip(sub['_bjd'], sub['_jib']):
        nm = legname[b]; inshp.add((nm, j)); inshp_bon.add((nm, bon(j)))

    summary, bad = [], []
    for cfg in cfgs:
        code, dong, leg = cfg['admin_code'], cfg['admin_dong'], cfg['legal_dongs']
        csvp = f"data/{code}/관할구역.csv"
        if not os.path.exists(csvp) or not os.path.exists(f"out/{code}/{dong}_parcels.geojson"):
            continue
        recs, _, _ = B.expand_table(csvp, set(leg.values()))
        # 별표가 각 지번에 부여한 '모든 통'(같은 지번이 두 통에 적힌 경우 포함) + 비-아파트 여부
        byp_t = defaultdict(set); nonapt = set()
        for (t, r, d, j, apt) in recs:
            byp_t[(d, j)].add(int(t))
            if not apt:
                nonapt.add((d, j))
        ok = mis = drop = moved = bonb = pye = 0
        for (d, j), tongs in byp_t.items():
            here = set(tt for (dd, tt) in g_draw.get((d, j), []) if dd == dong)
            other = any(dd != dong for (dd, tt) in g_draw.get((d, j), []))
            if here:                                   # 이 동에 그려짐
                if here & tongs:                       # 별표가 부여한 통 중 하나와 일치 → 정확
                    ok += 1
                else:
                    mis += 1; bad.append([dong, d, j, '오배정', f'별표 {sorted(tongs)}통 → 지도 {sorted(here)}통'])
            elif (d, j) not in nonapt:                 # 아파트 전용 지번이 안 그려짐 = 미표시(정상)
                continue
            elif other:                                # 공유 법정동 → 다른 동에 그려짐(클립)
                moved += 1
            elif (d, bon(j)) in g_draw_bon:            # 본번 폴백 처리(아파트 공유본번 등)
                bonb += 1
            elif (d, j) in inshp or (d, bon(j)) in inshp_bon:
                drop += 1; bad.append([dong, d, j, '누락', f'어느 동에도 안 그려짐(별표 {sorted(tongs)}통)'])
            else:
                pye += 1
        tot = ok + mis + drop
        summary.append((dong, ok, mis, drop, moved, bonb, pye, ok / tot * 100 if tot else 100.0))

    print(f"{'행정동':9}{'정확':>6}{'오배정':>7}{'누락':>6}{'타동':>6}{'본번':>6}{'폐번':>6}{'정합도':>8}")
    T = [0] * 6
    for s in summary:
        fl = '  ⚠' if (s[2] or s[3]) else ''
        print(f"{s[0]:9}{s[1]:>6}{s[2]:>7}{s[3]:>6}{s[4]:>6}{s[5]:>6}{s[6]:>6}{s[7]:>7.1f}%{fl}")
        for i in range(6): T[i] += s[i + 1]
    tt = T[0] + T[1] + T[2]
    print(f"\n합계: 정확 {T[0]} · 오배정 {T[1]} · 누락 {T[2]} · 타동(클립){T[3]} · 본번{T[4]} · 폐번{T[5]}")
    print(f"진짜 점검 대상(오배정+누락) = {T[1] + T[2]}건 / 핵심 정합도 {T[0] / tt * 100:.2f}%")
    if bad:
        os.makedirs('out/_audit', exist_ok=True)
        op = 'out/_audit/정합성_불일치.csv'
        with open(op, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f); w.writerow(['행정동', '법정동', '지번', '유형', '상세']); w.writerows(bad)
        print(f"⚠ 오배정·누락 {len(bad)}건 → {op}")
    else:
        print("✅ 오배정·누락 0 — 별표가 지도에 정확히 반영됨")


if __name__ == '__main__':
    main()
