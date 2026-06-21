#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""미배정 대지 이상 진단 — '본번은 통에 배정됐는데 부번이 미배정으로 빠진' 패턴 탐색.
771(부번지 포함)처럼 파서가 본번폴백을 못 건 케이스를 찾아 담당자 확인용으로 보고.
사용: python scan_unassigned_anomalies.py"""
import build_tongban_map as B
import json, glob, os
from collections import defaultdict

bon = lambda j: str(j).split('-')[0]

rows = []
for cfgp in sorted(glob.glob('data/3*/config.json')):
    cfg = json.load(open(cfgp, encoding='utf-8'))
    code, dong = cfg['admin_code'], cfg['admin_dong']
    leg = set(cfg['legal_dongs'].values())
    pp, up = f'out/{code}/{dong}_parcels.geojson', f'out/{code}/{dong}_unassigned.geojson'
    if not (os.path.exists(pp) and os.path.exists(up)):
        continue
    recs, apt, failed = B.expand_table(f'data/{code}/관할구역.csv', leg)
    bare = defaultdict(set)                       # (법정동,본번) → {통}  별표 bare 본번(폴백 의도, 비아파트)
    for (t, b, d, j, a) in recs:
        if '-' not in j and not a:
            bare[(d, j)].add(t)
    bon_tong = defaultdict(set)                   # (법정동,본번) → {통}  실제 배정된 본번
    for f in json.load(open(pp, encoding='utf-8'))['features']:
        p = f['properties']; bon_tong[(p['법정동'], bon(p['지번']))].add(int(p['통']))
    un = defaultdict(list)                         # (법정동,본번) → [미배정 부번...]
    for f in json.load(open(up, encoding='utf-8'))['features']:
        p = f['properties']; un[(p['법정동'], bon(p['지번']))].append(p['지번'])
    for (d, bb), jibuns in un.items():
        tongs = bon_tong.get((d, bb), set())
        if not tongs and (d, bb) not in bare:
            continue                               # 본번도 미배정이면 별개(별표 누락) — 여기선 스킵
        rows.append({'dong': dong, 'd': d, 'bon': bb, 'n': len(jibuns),
                     'tong': sorted(tongs), 'bare': sorted(bare.get((d, bb), set())),
                     'samp': sorted(jibuns)[:4]})

# 우선순위: 별표 bare 본번(강한 신호) > 단일 통 배정 > 미배정 수
rows.sort(key=lambda r: (-(1 if r['bare'] else 0), -(1 if len(r['tong']) == 1 else 0), -r['n']))

by_dong = defaultdict(lambda: [0, 0])
for r in rows:
    by_dong[r['dong']][0] += 1; by_dong[r['dong']][1] += r['n']
print('=== 동별 의심 본번 수 / 미배정 부번 합 ===')
for dg, (c, n) in sorted(by_dong.items(), key=lambda t: -t[1][1]):
    print(f'  {dg:7s} 의심본번 {c:>3} · 미배정부번 {n:>4}')
print(f'\n=== 강한 의심: 별표 bare 본번인데 부번 미배정 (상위 30) ===')
strong = [r for r in rows if r['bare']]
print(f'(총 {len(strong)}건)')
for r in strong[:30]:
    print('  {} {} {}(별표 {}통) → 미배정 {}부번 {} | 본번배정통 {}'.format(
        r['dong'], r['d'], r['bon'], r['bare'], r['n'], r['samp'], r['tong']))
print('\n=== 중간 의심: 본번이 한 통에만 배정 + 부번 미배정 (상위 20, bare 제외) ===')
med = [r for r in rows if not r['bare'] and len(r['tong']) == 1]
print('(총 {}건)'.format(len(med)))
for r in med[:20]:
    print('  {} {} {} → {}통에 본번배정, 미배정 {}부번 {}'.format(
        r['dong'], r['d'], r['bon'], r['tong'][0], r['n'], r['samp']))
