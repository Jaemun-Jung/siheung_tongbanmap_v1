#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
시흥시 통반경계도 빌드 파이프라인  (군자동 행정동부터)
------------------------------------------------------------
입력 : 1) 통·반 표 CSV  (행정동,통,반,관할구역)  -- 이미 추출됨
       2) 연속지적도 SHP (시흥시)               -- 사용자가 다운로드
출력 : gunja_parcels.geojson, gunja_tong.geojson,
       리포트 CSV(미매칭/충돌), gunja_map.html (단독 실행 인터랙티브 지도)

실행 환경 : geopandas / shapely / pyproj 필요 (이 채팅 샌드박스 아님 → Claude Code/로컬)
사용법 : 1) pip install -r requirements.txt
        2) 아래 CONFIG에서 SHP_PATH 설정
        3) python build_tongban_map.py
        4) 처음엔 SHP 컬럼 스키마가 출력됨 → 필드명이 자동탐지와 다르면 CONFIG 수정 후 재실행
"""

import os, re, sys, json
from collections import defaultdict

# ===================== CONFIG =====================
TABLE_CSV  = "군자동_통반_관할구역.csv"
SHP_PATH   = "LSMD_CONT_LDREG_41390_202606.shp"   # 시흥시(41390) 연속지적도 2026.06

# 연속지적도 필드명 (출처마다 다름). 자동탐지하되 필요시 직접 지정.
PNU_FIELD_CANDIDATES   = ["PNU", "pnu", "A1", "ADDR_PNU", "pnu_cd"]
JIBUN_FIELD_CANDIDATES = ["JIBUN", "jibun", "지번", "A5", "BONBUN", "ADDR"]
BJDNAME_FIELD_CANDIDATES = ["EMD_NM", "EMD_KOR_NM", "LDONG_NM", "법정동명", "DONG_NM", "ADM_NM"]

TARGET_BEOPJEONG = ["거모동", "군자동"]   # 군자동 행정동이 관할하는 법정동

# 연속지적도엔 법정동'명' 필드가 없고 PNU 앞10자리(법정동코드)만 있음.
# 코드→법정동명 매핑. 행정동경계 폴리곤 내부 포함 + 표지번 겹침으로 공간검증 확정.
# (주의: 작은 본번이 타 법정동과 우연히 겹칠 수 있어 '지번 겹침'만으로는 오매칭 가능)
BJD_CODE_TO_NAME = {
    "4139012700": "거모동",
    "4139012800": "군자동",   # 4139010300(0% 내부) 오류 → 4139012800(72.9% 내부)로 정정
}

# 행정동 경계(선택): 있으면 공식 '군자동 행정동' 폴리곤을 외곽선+검증에 사용.
ADMIN_SHP_GLOB = "shp_admin/*.shp"
ADMIN_ZIP_GLOB = "*행정동경계*.zip"
GUNJA_ADM_CD   = "31150680"        # 군자동 행정동 코드(행정동경계 파일 ADM_CD)
SHP_ENCODING = "cp949"                    # 한글 깨지면 'utf-8' 또는 'euc-kr' 시도
SOURCE_CRS_FALLBACK = "EPSG:5186"         # .prj 없을 때 가정 (중부원점 GRS80)

OUT_DIR = "out"
CONFLICT_POLICY = "min_tong"              # 충돌 시 낮은 통 번호 우선
# 별표는 '본번 범위'(예: 1659~1669)인데 지적도는 부번분할(1659-1,-2…)이라 정확매칭이 빠짐.
# 본번만 적힌(부번 없는) 표 항목에 한해, 그 본번의 모든 부번 필지를 같은 통으로 채움.
# 단일 통으로만 귀속될 때(충돌 없을 때)만 적용 → 빈 구역 보완, 오배정 방지.
BONBUN_FALLBACK = True

# 별표에 '지번'이 없는 아파트 통(서희스타힐스)을, 실제 토지 필지를
# '도로(근사 위도)' 기준으로 남/북으로 갈라 통 폴리곤으로 표시.
# (법정동, 본번, 분할위도, 남쪽통, 북쪽통, 설명)  ※위치: Nominatim 지오코딩으로 거모동 1859 확정.
SPLIT_PARCEL_TONG = [
    ("거모동", "1859", 37.3638, 31, 32,
     "군자서희스타힐스(916세대) — 중앙 도로 기준 남=31통(101~108동)/북=32통(109~115동)"),
]
# ==================================================

os.makedirs(OUT_DIR, exist_ok=True)

# ---------- 1. 지번 전개 로직 (실데이터로 검증 완료) ----------
APT = re.compile(r'아파트|Ⓐ|상가|\d+호|\(')

def normalize(s):
    return s.replace('～', '~').replace('〜', '~').replace('∼', '~').replace('·', 'ㆍ')

def parse_token(tok):
    tok = tok.strip().strip(',')
    if not tok:
        return []
    san = tok.startswith('산')
    core = tok[1:].strip() if san else tok
    if 'ㆍ' in core:
        parts = core.split('ㆍ')
        res = []
        if '-' in parts[0]:
            base = parts[0].split('-')[0]
            seq = [parts[0]] + [p if '-' in p else f"{base}-{p}" for p in parts[1:]]
        else:
            seq = parts
        for p in seq:
            r = parse_token(('산' if san else '') + p)
            if r is None:
                return None
            res += r
        return res
    if '~' in core:
        a, b = [x.strip() for x in core.split('~', 1)]
        try:
            if '-' in a and '-' not in b:                      # 부번 범위
                base, sub = a.split('-', 1)
                out = [f"{base}-{n}" for n in range(int(sub), int(b) + 1)]
            elif '-' not in a and '-' not in b:                # 본번 범위
                out = [str(n) for n in range(int(a), int(b) + 1)]
            elif '-' not in a and '-' in b:                    # 본번범위 + 끝부번
                bmain = b.split('-')[0]
                out = [str(n) for n in range(int(a), int(bmain) + 1)] + [b]
            else:
                return None
        except ValueError:
            return None
    else:
        out = [core]
    return ['산' + x for x in out] if san else out

def expand_table(csv_path):
    import csv
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    recs, apt_rows, failed = [], [], []
    for r in rows:
        tong, ban = int(r['통']), int(r['반'])
        raw = normalize(r['관할구역'])
        dong = raw.split()[0]
        rest = raw[len(dong):].strip()
        is_apt = bool(APT.search(rest))
        if is_apt:
            m = re.match(r'([\d]+(?:-[\d]+)?)', rest)
            base = m.group(1) if m else ''
            apt_rows.append((tong, ban, dong, base, r['관할구역']))
            if base:
                recs.append((tong, ban, dong, base, True))
            continue
        for tok in rest.split(','):
            tok = tok.strip()
            if not tok:
                continue
            res = parse_token(tok)
            if res is None:
                failed.append((tong, ban, dong, tok))
            else:
                for j in res:
                    recs.append((tong, ban, dong, j, False))
    return recs, apt_rows, failed

# ---------- 2. SHP 측 지번 정규화 ----------
def canon_from_pnu(pnu):
    """PNU 19자리 → (법정동코드10, 지번문자열 '산?본번-부번?')"""
    pnu = str(pnu).strip()
    if len(pnu) < 19 or not pnu[:19].isdigit():
        return None, None
    bjd = pnu[:10]
    san = pnu[10] == '2'
    bon = int(pnu[11:15]); bu = int(pnu[15:19])
    jib = ('산' if san else '') + str(bon) + (f"-{bu}" if bu else '')
    return bjd, jib

def canon_from_jibun(s):
    """지번 문자열(지목 접미사 등 포함) → '산?본번-부번?'"""
    s = str(s)
    san = '산' in s
    m = re.search(r'(\d+)(?:-(\d+))?', s)
    if not m:
        return None
    bon = int(m.group(1)); bu = int(m.group(2)) if m.group(2) else 0
    return ('산' if san else '') + str(bon) + (f"-{bu}" if bu else '')

def pick(cols, candidates):
    low = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand in cols: return cand
        if cand.lower() in low: return low[cand.lower()]
    return None

def load_admin_outline():
    """공식 행정동경계에서 '군자동 행정동' 폴리곤을 EPSG:4326으로 반환. 없으면 None."""
    import glob, os, zipfile
    import geopandas as gpd
    paths = glob.glob(ADMIN_SHP_GLOB)
    if not paths:                                   # 압축만 있으면 자동 해제
        zips = glob.glob(ADMIN_ZIP_GLOB)
        if zips:
            os.makedirs("shp_admin", exist_ok=True)
            with zipfile.ZipFile(zips[0]) as z:
                z.extractall("shp_admin")
            paths = glob.glob(ADMIN_SHP_GLOB)
    if not paths:
        return None
    shp = paths[0]
    # 이 파일은 .cpg=UTF-8이나 3번째 필드명(행정동명)이 dbf 10byte 한계에서 잘려
    # GDAL이 필드명 디코딩에 실패함 → 해당 필드명을 ASCII(ADM_NM)로 패치(멱등).
    dbf = shp[:-4] + ".dbf"
    try:
        data = bytearray(open(dbf, "rb").read())
        off = 32 + 2 * 32
        if data[off:off+6] != b"ADM_NM":
            data[off:off+11] = b"ADM_NM\x00\x00\x00\x00\x00"
            open(dbf, "wb").write(data)
    except Exception:
        pass
    try:
        a = gpd.read_file(shp)
    except Exception as e:
        print("   (행정동경계 읽기 실패:", e, ")")
        return None
    a = a[a["ADM_CD"].astype(str) == GUNJA_ADM_CD]
    return a.to_crs("EPSG:4326")[["geometry"]] if len(a) else None

# ---------- 3. 메인 ----------
def main():
    import geopandas as gpd
    import pandas as pd

    print("▶ 1) 통·반 표 전개")
    recs, apt_rows, failed = expand_table(TABLE_CSV)
    tdf = pd.DataFrame(recs, columns=["통", "반", "법정동", "지번", "아파트"])
    print(f"   전개 지번행 {len(tdf)}, 고유필지 {tdf[['법정동','지번']].drop_duplicates().shape[0]}, "
          f"아파트반 {len(apt_rows)}, 전개실패 {len(failed)}")
    if failed:
        pd.DataFrame(failed, columns=["통","반","법정동","토큰"]).to_csv(
            f"{OUT_DIR}/report_parse_failed.csv", index=False, encoding="utf-8-sig")

    print("▶ 2) 연속지적도 로드")
    gdf = gpd.read_file(SHP_PATH, encoding=SHP_ENCODING)
    if gdf.crs is None:
        gdf.set_crs(SOURCE_CRS_FALLBACK, inplace=True)
    print("   행수:", len(gdf), " CRS:", gdf.crs)
    print("   컬럼:", list(gdf.columns))
    print(gdf.drop(columns="geometry").head(3).to_string())

    pnu_f   = pick(gdf.columns, PNU_FIELD_CANDIDATES)
    jib_f   = pick(gdf.columns, JIBUN_FIELD_CANDIDATES)
    name_f  = pick(gdf.columns, BJDNAME_FIELD_CANDIDATES)
    print(f"   탐지된 필드 → PNU={pnu_f}, 지번={jib_f}, 법정동명={name_f}")
    if not pnu_f and not (jib_f and name_f):
        sys.exit("⚠ 지번 키를 만들 필드를 못 찾음. CONFIG의 *_CANDIDATES에 실제 컬럼명을 추가하세요.")

    print("▶ 3) 거모동·군자동 필지만 추출 + 지번 키 생성")
    if pnu_f:
        canon = gdf[pnu_f].map(canon_from_pnu)
        gdf["_bjd"] = canon.map(lambda x: x[0])
        gdf["_jib"] = canon.map(lambda x: x[1])
        # 법정동코드→이름 결정: ①CONFIG 명시 매핑 → ②이름필드 자동추론 → ③분포 출력 후 종료
        if BJD_CODE_TO_NAME:
            target_codes = set(BJD_CODE_TO_NAME)
            gdf["_dong"] = gdf["_bjd"].map(BJD_CODE_TO_NAME)
            print(f"   법정동코드 매핑(CONFIG): {BJD_CODE_TO_NAME}")
        elif name_f:
            code_map = (gdf[[name_f, "_bjd"]].dropna()
                        .groupby(name_f)["_bjd"].agg(lambda s: s.mode().iloc[0]).to_dict())
            target_codes = {code_map[n] for n in TARGET_BEOPJEONG if n in code_map}
            gdf["_dong"] = gdf[name_f]
        else:
            print("   법정동명 필드 없음 → PNU코드 분포(상위 30):")
            print(gdf["_bjd"].value_counts().head(30).to_string())
            gdf["_bjd"].value_counts().to_csv(f"{OUT_DIR}/report_bjd_codes.csv",
                                              encoding="utf-8-sig")
            sys.exit("⚠ out/report_bjd_codes.csv 참고해 거모동·군자동 코드를 "
                     "CONFIG의 BJD_CODE_TO_NAME에 지정 후 재실행하세요.")
        sub = gdf[gdf["_bjd"].isin(target_codes)].copy()
    else:
        gdf["_jib"] = gdf[jib_f].map(canon_from_jibun)
        gdf["_dong"] = gdf[name_f].astype(str)
        sub = gdf[gdf["_dong"].isin(TARGET_BEOPJEONG)].copy()
    print("   대상 필지수:", len(sub))

    print("▶ 4) 통·반 조인")
    lut = defaultdict(list)
    for _, r in tdf.iterrows():
        lut[(r["법정동"], r["지번"])].append((r["통"], r["반"], r["아파트"]))

    # 본번 폴백용: 표가 '본번만'(부번 없음, 비아파트) 적은 항목 → (법정동,본번)→통/반
    def bonbun(j):
        return j.split("-")[0]          # '산79-3'->'산79', '491-2'->'491', '491'->'491'
    bon_tongs = defaultdict(set)        # (법정동,본번) -> {통...}  (충돌 판정)
    bon_rep   = {}                      # (법정동,본번) -> (통,반,아파트) 대표(최소통)
    if BONBUN_FALLBACK:
        for _, r in tdf.iterrows():
            jb = r["지번"]
            if r["아파트"] or "-" in jb:
                continue
            k = (r["법정동"], jb)       # jb가 곧 본번
            bon_tongs[k].add(r["통"])
        for _, r in tdf.iterrows():
            jb = r["지번"]
            if r["아파트"] or "-" in jb:
                continue
            k = (r["법정동"], jb)
            if len(bon_tongs[k]) == 1 and k not in bon_rep:
                bon_rep[k] = (r["통"], r["반"], r["아파트"])

    def assign(row):
        cand = lut.get((row["_dong"], row["_jib"]), [])
        if cand:
            tong = min(c[0] for c in cand) if CONFLICT_POLICY == "min_tong" else cand[0][0]
            sameban = [c for c in cand if c[0] == tong]
            return (tong, sameban[0][1], sameban[0][2], len({c[0] for c in cand}), "exact")
        if BONBUN_FALLBACK:
            bk = (row["_dong"], bonbun(row["_jib"]))
            if len(bon_tongs.get(bk, ())) == 1:
                tong, ban, apt = bon_rep[bk]
                return (tong, ban, apt, 1, "bonbun")
        return (None, None, False, 0, "none")
    res = sub.apply(assign, axis=1, result_type="expand")
    sub[["통", "반", "아파트", "통후보수", "_match"]] = res
    matched = sub[sub["통"].notna()].copy()
    n_exact = (matched["_match"] == "exact").sum()
    n_bon   = (matched["_match"] == "bonbun").sum()
    print(f"   매칭 필지 {len(matched)} / 대상 {len(sub)}  (정확 {n_exact} + 본번폴백 {n_bon}, "
          f"미배정 {len(sub)-len(matched)})")

    # 리포트: 미배정 필지 / 충돌 필지 / 표엔 있으나 지적도에 없는 지번
    sub[sub["통"].isna()][["_dong","_jib"]].to_csv(
        f"{OUT_DIR}/report_unassigned_parcels.csv", index=False, encoding="utf-8-sig")
    matched[matched["통후보수"] > 1][["_dong","_jib","통"]].to_csv(
        f"{OUT_DIR}/report_conflicts.csv", index=False, encoding="utf-8-sig")
    shp_keys = set(zip(sub["_dong"], sub["_jib"]))
    miss = tdf[~tdf.apply(lambda r: (r["법정동"], r["지번"]) in shp_keys, axis=1)]
    miss[["통","반","법정동","지번"]].drop_duplicates().to_csv(
        f"{OUT_DIR}/report_table_not_in_shp.csv", index=False, encoding="utf-8-sig")
    print(f"   표→지적도 미발견 지번 {miss[['법정동','지번']].drop_duplicates().shape[0]}건 (대부분 과생성 본번 → 정상)")

    # 통별 누락 점검: 표엔 있으나 지도에 0필지로 안 그려진 통 + 사유
    apt_tongs = {t for (t, *_rest) in apt_rows}
    drawn = set(matched["통"].astype(int)) if len(matched) else set()
    table_tongs = sorted(tdf["통"].unique())
    miss_rows = []
    for t in table_tongs:
        if t in drawn:
            continue
        keys = set(zip(tdf[tdf["통"]==t]["법정동"], tdf[tdf["통"]==t]["지번"]))
        in_shp = any(k in shp_keys for k in keys)
        if not in_shp:
            why = "표에 지번 없음/지적도에 없음(아파트 단지명 등)" if t in apt_tongs else "지적도에 해당 지번 없음"
        else:
            why = "지번은 지적도에 있으나 충돌(min_tong)로 다른 통에 흡수"
        miss_rows.append((t, "아파트" if t in apt_tongs else "일반", why))
    if miss_rows:
        pd.DataFrame(miss_rows, columns=["통","유형","사유"]).to_csv(
            f"{OUT_DIR}/report_missing_tong.csv", index=False, encoding="utf-8-sig")
        print("   미표시 통:", ", ".join(f"{t}통({why})" for t,_,why in miss_rows))

    print("▶ 5) 4326 변환 + 통 단위 병합 + 행정동 외곽선")
    matched = matched.to_crs("EPSG:4326")
    matched["통"] = matched["통"].astype(int)
    tong_gdf = matched.dissolve(by="통").reset_index()[["통", "geometry"]]
    tong_gdf["geometry"] = tong_gdf.buffer(0)   # 위상 정리
    # 통 번호 라벨 위치(폴리곤 내부 한 점)
    lp = tong_gdf.representative_point()
    tong_gdf["lon"] = lp.x.round(7)
    tong_gdf["lat"] = lp.y.round(7)

    # 행정동(군자동) 외곽 경계: 공식 행정동경계가 있으면 사용, 없으면 대상필지 병합
    admin_official = load_admin_outline()
    if admin_official is not None:
        admin_gdf = admin_official.dissolve().reset_index(drop=True)
        admin_gdf["geometry"] = admin_gdf.buffer(0)
        print("   행정동 외곽선: 공식 행정동경계 사용(ADM_CD", GUNJA_ADM_CD + ")")
        # 검증: 매칭 필지가 행정동 경계 안에 드는지(코드 매핑 오류 탐지)
        gp = admin_gdf.geometry.iloc[0]
        inside = matched.representative_point().within(gp).mean()
        print(f"   매칭 필지의 행정동 내부 비율 {inside*100:.1f}% (낮으면 법정동코드 매핑 오류)")
        bad = matched[~matched.representative_point().within(gp)]
        if len(bad):
            bad[["통","_dong","_jib"]].rename(columns={"_dong":"법정동","_jib":"지번"}).to_csv(
                f"{OUT_DIR}/report_outside_admin.csv", index=False, encoding="utf-8-sig")
            outside_tongs = sorted(bad["통"].astype(int).unique())
            print(f"   ⚠ 행정동 밖 필지 {len(bad)}개 (통 {outside_tongs}) → report_outside_admin.csv")
    else:
        admin = sub.to_crs("EPSG:4326")[["geometry"]].copy()
        admin["geometry"] = admin.buffer(0)
        admin_gdf = admin.dissolve().reset_index(drop=True)
        admin_gdf["geometry"] = admin_gdf.buffer(0)
        print("   행정동 외곽선: 대상필지 병합(행정동경계 파일 없음)")

    parcels_out = matched[["통","반","_dong","_jib","geometry"]].rename(
        columns={"_dong":"법정동","_jib":"지번"})
    tong_gdf["근사"] = 0
    parcels_out["근사"] = 0

    # 별표에 지번 없는 아파트 통(서희스타힐스): 실제 필지를 도로(근사 위도)로 남/북 분할
    from shapely.geometry import box
    code_of = {v: k for k, v in BJD_CODE_TO_NAME.items()}
    add_t, add_p = [], []
    for dong, bon, slat, s_tong, n_tong, desc in SPLIT_PARCEL_TONG:
        cell = gdf[(gdf["_bjd"] == code_of.get(dong)) & (gdf["_jib"].astype(str) == bon)]
        if cell.empty:
            print(f"   (분할대상 {dong} {bon} 없음 → 건너뜀)"); continue
        poly = cell.to_crs("EPSG:4326").geometry.union_all()
        x0, y0, x1, y1 = poly.bounds
        for geom, tong, half in [(poly.intersection(box(x0, y0, x1, slat)), s_tong, "남"),
                                 (poly.intersection(box(x0, slat, x1, y1)), n_tong, "북")]:
            if geom.is_empty:
                continue
            rp = geom.representative_point()
            add_t.append({"통": tong, "geometry": geom,
                          "lon": round(rp.x, 7), "lat": round(rp.y, 7), "근사": 1})
            add_p.append({"통": tong, "반": 0, "법정동": dong,
                          "지번": f"{bon}({half}·근사분할)", "geometry": geom, "근사": 1})
        print(f"   분할 추가: {dong} {bon} → {s_tong}통(남)/{n_tong}통(북)")
    if add_t:
        tong_gdf = pd.concat([tong_gdf, gpd.GeoDataFrame(add_t, crs="EPSG:4326")],
                             ignore_index=True)
        parcels_out = pd.concat([parcels_out, gpd.GeoDataFrame(add_p, crs="EPSG:4326")],
                                ignore_index=True)

    parcels_out.to_file(f"{OUT_DIR}/gunja_parcels.geojson", driver="GeoJSON")
    tong_gdf.to_file(f"{OUT_DIR}/gunja_tong.geojson", driver="GeoJSON")
    admin_gdf.to_file(f"{OUT_DIR}/gunja_admin.geojson", driver="GeoJSON")

    print("▶ 6) 인터랙티브 지도 생성")
    write_map(parcels_out.to_json(), tong_gdf.to_json(), admin_gdf.to_json(),
              f"{OUT_DIR}/gunja_map.html")
    print("✔ 완료 →", OUT_DIR, "(gunja_map.html 더블클릭)")

# ---------- 4. 단독 실행 Leaflet 지도 ----------
def write_map(parcels_geojson, tong_geojson, admin_geojson, path):
    html = """<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>군자동 통반경계도</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
 body{margin:0;font-family:-apple-system,"Apple SD Gothic Neo",sans-serif}
 #map{position:absolute;top:0;bottom:0;left:0;right:0}
 .panel{position:absolute;z-index:1000;top:10px;left:10px;background:#fff;padding:10px 12px;
   border-radius:10px;box-shadow:0 1px 6px rgba(0,0,0,.3);width:250px;font-size:13px}
 .panel input{width:100%;box-sizing:border-box;height:32px;padding:0 8px;margin:6px 0;
   border:1px solid #ccc;border-radius:6px}
 .panel button{height:28px;padding:0 9px;margin:2px 2px 0 0;border:1px solid #ccc;
   border-radius:6px;background:#fff;cursor:pointer;font-size:12px}
 .panel button.on{background:#1769aa;color:#fff;border-color:#1769aa}
 #res{margin-top:6px;color:#333}
 .note{margin-top:6px;color:#7a5b00;font-size:11px}
 .leaflet-popup-content{font-size:13px}
 /* 통 번호 라벨 */
 .tong-label{display:inline-block;min-width:16px;padding:0 5px;
   background:rgba(255,255,255,.93);border:2px solid #333;border-radius:11px;
   font-weight:700;font-size:12px;line-height:15px;color:#111;text-align:center;
   box-shadow:0 1px 2px rgba(0,0,0,.4)}
</style></head><body>
<div class="panel">
 <b>군자동 통반경계도</b>
 <input id="q" placeholder="지번 입력 (예: 491, 1769-1)"/>
 <div>
  <button id="go">조회</button>
  <button id="t-fill" class="on">면</button>
  <button id="t-line">경계선</button>
  <button id="t-label" class="on">번호</button>
  <button id="t-admin" class="on">동경계</button>
 </div>
 <div id="res">필지를 클릭하거나 지번을 입력하세요.</div>
 <div class="note">점선(31·32통): 별표에 지번이 없어 실제 필지를 도로 기준으로 분할한 추정치</div>
</div>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const PARCELS = __PARCELS__;
const TONG = __TONG__;
const ADMIN = __ADMIN__;
function color(t){const h=(t*47)%360;return `hsl(${h},65%,55%)`;}
const approx=f=>!!(f.properties&&f.properties.근사);
// +/- 줌버튼이 좌상단 패널과 겹치지 않게 우상단으로 이동
const map=L.map('map',{zoomControl:false});
L.control.zoom({position:'topright'}).addTo(map);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
 {attribution:'© OpenStreetMap',maxZoom:19}).addTo(map);

// 행정동(군자동) 외곽 경계 — 주변 타동/타시와 구분되게 굵은 검정선
const admin=L.geoJSON(ADMIN,{style:{color:'#111',weight:4,fill:false,opacity:0.85}}).addTo(map);

let mode='fill';
const pStyle=f=>({color:color(f.properties.통),weight:approx(f)?2:1,
  dashArray:approx(f)?'5 4':null,
  fillOpacity:mode==='fill'?(approx(f)?0.3:0.45):0,
  opacity:mode==='fill'?(approx(f)?0.95:0.6):0.9});
const parcels=L.geoJSON(PARCELS,{style:pStyle,onEachFeature:(f,l)=>{
  const p=f.properties;
  const txt = approx(f)
    ? `<b>${p.통}통 (근사 분할)</b><br>${p.법정동} ${p.지번}<br>`+
      `<small>별표에 지번이 없어 실제 필지를 도로 기준으로 분할한 추정치</small>`
    : `거모/군자 ${p.법정동} ${p.지번}<br><b>${p.통}통 ${p.반}반</b>`;
  l.bindPopup(txt);
  l.on('click',()=>{document.getElementById('res').innerHTML=txt;});
}}).addTo(map);
const tong=L.geoJSON(TONG,{style:f=>({color:color(f.properties.통),weight:3,
  dashArray:approx(f)?'5 4':null,fill:false,opacity:0.95})}).addTo(map);

// 통 번호 라벨(폴리곤 내부 점)
const labels=L.layerGroup();
TONG.features.forEach(f=>{
  const t=f.properties.통, lat=f.properties.lat, lon=f.properties.lon;
  if(lat==null||lon==null) return;
  const bs=approx(f)?'dashed':'solid';
  const icon=L.divIcon({className:'',iconSize:[26,19],iconAnchor:[13,10],
    html:`<div class="tong-label" style="border-color:${color(t)};border-style:${bs}">${t}</div>`});
  L.marker([lat,lon],{icon:icon,interactive:false,keyboard:false}).addTo(labels);
});
labels.addTo(map);

// 처음부터 군자동 행정동 영역만 보이게
map.fitBounds(admin.getBounds(),{padding:[12,12]});

function restyle(){parcels.setStyle(pStyle);}
function toggle(btn,on){btn.classList.toggle('on',on);}
document.getElementById('t-fill').onclick=e=>{mode='fill';restyle();
  toggle(e.target,true);toggle(document.getElementById('t-line'),false);};
document.getElementById('t-line').onclick=e=>{mode='line';restyle();
  toggle(e.target,true);toggle(document.getElementById('t-fill'),false);};
document.getElementById('t-label').onclick=e=>{
  if(map.hasLayer(labels)){map.removeLayer(labels);toggle(e.target,false);}
  else{labels.addTo(map);toggle(e.target,true);}};
document.getElementById('t-admin').onclick=e=>{
  if(map.hasLayer(admin)){map.removeLayer(admin);toggle(e.target,false);}
  else{admin.addTo(map);toggle(e.target,true);}};
document.getElementById('go').onclick=()=>{
  const v=document.getElementById('q').value.trim();let hit=null;
  parcels.eachLayer(l=>{const p=l.feature.properties;
    if(!hit && (p.지번===v||p.지번===('산'+v))){hit=l;}});
  const res=document.getElementById('res');
  if(hit){const p=hit.feature.properties;map.fitBounds(hit.getBounds(),{maxZoom:18});
    hit.openPopup();res.innerHTML=`<b>${p.법정동} ${p.지번}</b><br>${p.통}통 ${p.반}반`;}
  else res.innerHTML=`"${v}" 지번을 찾지 못했습니다.`;
};
document.getElementById('q').addEventListener('keydown',e=>{if(e.key==='Enter')document.getElementById('go').click();});
</script></body></html>"""
    html = (html.replace("__PARCELS__", parcels_geojson)
                .replace("__TONG__", tong_geojson)
                .replace("__ADMIN__", admin_geojson))
    open(path, "w", encoding="utf-8").write(html)

if __name__ == "__main__":
    main()
