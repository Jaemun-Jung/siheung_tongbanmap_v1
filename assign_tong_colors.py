#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""통 색 슬롯 배정 — 인접한 통끼리 색이 다르게(지도 4색 문제). _tong.geojson에 cidx 추가.

각 동에서 통 폴리곤을 25m 버퍼로 인접 그래프를 만든 뒤, 그리디(차수 큰 통부터)로
'이웃과 색상환 거리가 최대 + 전체에서 덜 쓴 슬롯'을 골라 cidx(0..N-1) 배정.
셸/출력은 cidx로 색을 정해 맞닿은 통이 또렷이 구분된다. 기하는 안 건드리고 속성만 추가.
사용: python assign_tong_colors.py   (clean_tong 뒤, gen_overview 전 권장)
"""
import json, glob, os
from shapely.geometry import shape
from shapely.ops import transform
from shapely.strtree import STRtree
from pyproj import Transformer

TO_M = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True).transform
N = 12          # 색 슬롯 수
BUF = 25        # 인접 판정 버퍼(m) — 도로로 갈린 통도 인접으로


def cdist(a, b):                       # 색상환(원형) 거리
    d = abs(a - b) % N
    return min(d, N - d)


def main():
    for tp in sorted(glob.glob("out/3*/*_tong.geojson")):
        t = json.load(open(tp, encoding="utf-8"))
        feats = t["features"]
        n = len(feats)
        if not n:
            continue
        gm = [transform(TO_M, shape(f["geometry"])).buffer(BUF) for f in feats]
        tree = STRtree(gm)
        adj = [set() for _ in range(n)]
        for i in range(n):
            for j in tree.query(gm[i]):
                j = int(j)
                if j > i and gm[i].intersects(gm[j]):
                    adj[i].add(j); adj[j].add(i)
        order = sorted(range(n), key=lambda i: -len(adj[i]))
        cidx = [None] * n
        slotcount = [0] * N
        for i in order:
            used = {cidx[j] for j in adj[i] if cidx[j] is not None}
            best = max(range(N), key=lambda s: (
                min((cdist(s, u) for u in used), default=N), -slotcount[s]))
            cidx[i] = best; slotcount[best] += 1
        for f, c in zip(feats, cidx):
            f["properties"]["cidx"] = int(c)
        json.dump(t, open(tp, "w", encoding="utf-8"), ensure_ascii=False)
        # 인접 통 같은 색 충돌 수(검증)
        clash = sum(1 for i in range(n) for j in adj[i] if j > i and cidx[i] == cidx[j])
        dong = os.path.basename(tp).replace("_tong.geojson", "")
        print(f"  {dong:8s} 통 {n:>3}  인접쌍 {sum(len(a) for a in adj)//2:>3}  같은색 충돌 {clash}")
    print("→ _tong.geojson 에 cidx 부여 완료")


if __name__ == "__main__":
    main()
