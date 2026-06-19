#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
법정동명 → 법정동코드(10자리) 자동 도출
------------------------------------------------------------
군자동에서 쓴 공간검증(행정동경계 내부 + 표지번 겹침)을 전체 동으로 일반화.
각 행정동 경계 안 필지의 PNU(법정동코드+지번)와, 그 동 CSV의 (법정동명,지번)을 맞춰
법정동명마다 가장 많이 일치하는 코드를 투표로 결정한다.

전제: data/{admin_code}/관할구역.csv (extract_hwpx_tables.py 산출), SHP, 행정동경계 zip.
출력: data/siheung_legal_codes.json
      { admin_code: {admin_dong, legal_dongs:{코드:이름}, target_beopjeong:[이름...]} }
"""
import csv as csvmod
import glob, json, os, re, zipfile
from collections import defaultdict, Counter
import geopandas as gpd
import build_tongban_map as B

_DONG_TOK = re.compile(r"^([가-힣]{2,4}[동리])\s+(.+)$")

def territory_pairs(area):
    """관할구역 텍스트 → [(법정동명, 지번)...].
    한 반 안에서 법정동이 바뀌는 것을 토큰별로 추적(expand_table의 '첫 동만' 한계 보완)."""
    area = B.normalize(area)
    area = re.sub(r"\([^)]*\)", "", area)          # 괄호 주석(아파트명 등) 제거
    cur, out = None, []
    for tok in area.split(","):
        tok = tok.strip()
        if not tok:
            continue
        m = _DONG_TOK.match(tok)
        if m and not re.match(r"^산\d", tok):       # 동/리명 + 지번 (단 '산79'는 지번)
            cur, rest = m.group(1), m.group(2)
        else:
            rest = tok
        if not cur:
            continue
        for j in (B.parse_token(rest) or []):
            out.append((cur, j))
    return out

SHP = "LSMD_CONT_LDREG_41390_202606.shp"
ADMIN_CODES = "data/siheung_admin_codes.json"
OUT = "data/siheung_legal_codes.json"
LEGAL_RE = re.compile(r"^[가-힣]{2,4}[동리]$")   # 순수 법정동명만(아파트·지구·지번 노이즈 배제)
GLOBAL_MIN = 10     # 전역 득표 이 미만이면 실제 법정동 아님(노이즈)으로 간주

def load_admin_polys():
    os.makedirs("_admtmp", exist_ok=True)
    zp = glob.glob("*행정동경계*.zip")[0]
    with zipfile.ZipFile(zp) as z:
        z.extractall("_admtmp")
    shp = glob.glob("_admtmp/*.shp")[0]
    # DBF 3번째 필드명(행정동명)이 10byte 한계로 잘려 GDAL 디코딩 실패 → ASCII로 패치(빌드와 동일)
    dbf = shp[:-4] + ".dbf"
    data = bytearray(open(dbf, "rb").read())
    off = 32 + 2 * 32
    if data[off:off + 6] != b"ADM_NM":
        data[off:off + 11] = b"ADM_NM\x00\x00\x00\x00\x00"
        open(dbf, "wb").write(data)
    a = gpd.read_file(shp)[["ADM_CD", "geometry"]].to_crs("EPSG:5186")
    a["ADM_CD"] = a["ADM_CD"].astype(str)
    return a

def main():
    admin_codes = {k: v for k, v in json.load(open(ADMIN_CODES, encoding="utf-8")).items()
                   if not k.startswith("_")}

    print("▶ SHP 로드 + 지번 키")
    g = gpd.read_file(SHP, encoding="cp949")
    if g.crs is None:
        g.set_crs("EPSG:5186", inplace=True)
    g = g.to_crs("EPSG:5186")
    canon = g["PNU"].map(B.canon_from_pnu)
    g["_bjd"] = canon.map(lambda x: x[0])
    g["_jib"] = canon.map(lambda x: x[1])
    g = g.dropna(subset=["_bjd", "_jib"]).reset_index(drop=True)

    print("▶ 필지 → 행정동 귀속(점 within 경계)")
    pts = gpd.GeoDataFrame(g[["_bjd", "_jib"]].copy(),
                           geometry=g.representative_point(), crs="EPSG:5186")
    adm = load_admin_polys()
    j = gpd.sjoin(pts, adm, predicate="within", how="left")
    j = j[~j.index.duplicated(keep="first")]
    g["_adm"] = j["ADM_CD"].reindex(g.index).values

    # --- 1패스: 행정동별 (법정동명→코드) 득표 수집 ---
    per_dong, global_map = {}, defaultdict(Counter)
    for adm_code, dong in sorted(((v, k) for k, v in admin_codes.items())):
        sub = g[g["_adm"] == adm_code]
        jib2codes = defaultdict(set)
        for bjd, jib in zip(sub["_bjd"], sub["_jib"]):
            jib2codes[jib].add(bjd)
        csvp = f"data/{adm_code}/관할구역.csv"
        if not os.path.exists(csvp):
            continue
        votes = defaultdict(Counter)
        for row in csvmod.DictReader(open(csvp, encoding="utf-8-sig")):
            for legal, jib in territory_pairs(row["관할구역"]):
                if not LEGAL_RE.match(legal):      # 아파트/지구/지번 노이즈 배제
                    continue
                codes = jib2codes.get(jib)
                if codes and len(codes) == 1:      # 경계 내 한 코드로만 매칭되는 지번만(충돌 배제)
                    votes[legal][next(iter(codes))] += 1
        per_dong[adm_code] = (dong, votes)
        for legal, cnt in votes.items():
            global_map[legal] += cnt

    # --- 전역 1:1 그리디 배정: 높은 득표부터, 코드 중복 금지(법정동↔코드 단사) ---
    eligible = {nm: cnt for nm, cnt in global_map.items()
                if sum(cnt.values()) >= GLOBAL_MIN}
    weak = sorted(((nm, cnt.most_common(1)[0][0], sum(cnt.values()))
                   for nm, cnt in global_map.items() if sum(cnt.values()) < GLOBAL_MIN),
                  key=lambda x: -x[2])
    triples = sorted(((n, nm, code) for nm, cnt in eligible.items()
                      for code, n in cnt.items()), reverse=True)
    name2code, used_c, used_n, lowconf = {}, set(), set(), []
    for n, nm, code in triples:
        if nm in used_n or code in used_c:
            continue
        name2code[nm] = code
        used_n.add(nm); used_c.add(code)
        total = sum(eligible[nm].values())
        if n / total < 0.5 or n < 5:               # 차순위로 밀렸거나 표 적음 → 수동 확인 권장
            lowconf.append((nm, code, n, total))

    # --- 2패스: 동별 config 항목 구성(전역 코드 사용) ---
    out = {}
    for adm_code, (dong, votes) in per_dong.items():
        names = sorted(nm for nm in votes if nm in name2code)
        legal_dongs = {name2code[nm]: nm for nm in names}
        out[adm_code] = {"admin_dong": dong,
                         "legal_dongs": dict(sorted(legal_dongs.items())),
                         "target_beopjeong": names}
        print(f"  {adm_code} {dong:7s} {names}")

    # 무결성: 한 코드에 두 법정동명이 매핑되면 도출 오류
    code2names = defaultdict(list)
    for nm, code in name2code.items():
        code2names[code].append(nm)
    dup = {c: n for c, n in code2names.items() if len(n) > 1}

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n→ {OUT}  (행정동 {len(out)}, 법정동 {len(name2code)})")
    if dup:
        print("⚠ 한 코드에 복수 법정동명(도출 오류):")
        for c, n in dup.items():
            print(f"   {c} → {n}")
    else:
        print("✔ 코드↔법정동명 1:1 (단사 보장)")
    if lowconf:
        print(f"⚠ 저신뢰 배정 {len(lowconf)}건 (빌드 매칭률로 확인 권장):")
        for nm, code, n, total in lowconf:
            print(f"   {nm} → {code}  ({n}/{total}표, {n/total*100:.0f}%)")
    if weak:
        print(f"ℹ 노이즈 배제(전역 {GLOBAL_MIN}표 미만): "
              + ", ".join(f"{nm}({t})" for nm, c, t in weak))

if __name__ == "__main__":
    main()
