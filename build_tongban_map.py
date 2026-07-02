#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
시흥시 통반경계도 빌드 파이프라인  (군자동 행정동부터)
------------------------------------------------------------
입력 : 1) 통·반 표 CSV   data/{행정동코드}/관할구역.csv      (config.table_csv)
       2) 연속지적도 SHP (시흥시, 도시 단위 1개)            -- 사용자 다운로드 (--shp)
       3) 동별 설정      data/{행정동코드}/config.json        (--config)
출력 : out/{행정동코드}/{동명}_parcels.geojson, {동명}_tong.geojson, {동명}_admin.geojson,
       리포트 CSV(미매칭/충돌), {동명}_map.html (단독 실행 인터랙티브 지도)

실행 환경 : geopandas / shapely / pyproj 필요 (이 채팅 샌드박스 아님 → Claude Code/로컬)
사용법 : 1) pip install -r requirements.txt
        2) python build_tongban_map.py --config data/31150680/config.json --shp <연속지적도.shp>
        3) 처음엔 SHP 컬럼 스키마가 출력됨 → 필드명이 자동탐지와 다르면 *_FIELD_CANDIDATES 수정 후 재실행
"""

import os, re, sys, json
from collections import defaultdict

# ===================== 설정(공유 기본값) =====================
# 동별 값은 config.json 에서 로드(--config). 아래는 출처가 같은 '도시 단위' 기본값만 남긴다.
DEFAULT_SHP_PATH = "LSMD_CONT_LDREG_41390_202606.shp"   # 시흥시(41390) 연속지적도 2026.06

# 연속지적도 필드명 (출처마다 다름). 자동탐지하되 필요시 직접 지정.
PNU_FIELD_CANDIDATES   = ["PNU", "pnu", "A1", "ADDR_PNU", "pnu_cd"]
JIBUN_FIELD_CANDIDATES = ["JIBUN", "jibun", "지번", "A5", "BONBUN", "ADDR"]
BJDNAME_FIELD_CANDIDATES = ["EMD_NM", "EMD_KOR_NM", "LDONG_NM", "법정동명", "DONG_NM", "ADM_NM"]

# 행정동경계 파일(도시 단위 1개). 동별로는 ADM_CD(=config.admin_code)만 달라진다.
ADMIN_SHP_GLOB = "shp_admin/*.shp"
ADMIN_ZIP_GLOB = "*행정동경계*.zip"

# ↓↓ 아래 전역값은 apply_config()가 config.json 으로 런타임에 채운다. ↓↓
TABLE_CSV = SHP_PATH = OUT_DIR = None
ADMIN_DONG = ADMIN_CODE = None
TARGET_BEOPJEONG = []          # 행정동이 관할하는 법정동 목록
BJD_CODE_TO_NAME = {}          # 법정동코드10 → 법정동명 (공간검증으로 확정)
SHP_ENCODING = "cp949"         # 한글 깨지면 config에서 'utf-8'/'euc-kr'
SOURCE_CRS_FALLBACK = "EPSG:5186"   # .prj 없을 때 가정 (중부원점 GRS80)
CONFLICT_POLICY = "min_tong"   # 충돌 시 낮은 통 번호 우선
BONBUN_FALLBACK = True         # 본번만 적힌 표 항목 → 해당 본번 전체 부번을 같은 통으로
CLIP_TO_ADMIN = True           # 매칭 필지를 공식 행정동경계로 클립(공유 법정동 본번폴백 과대확장 방지). 군자동(골든)은 config에서 false
SPLIT_PARCEL_TONG = []         # (법정동, 본번, 분할위도, 남통, 북통, 설명) — 지번없는 아파트통 도로분할
# --- 2단계: 도로 경계 보정 ---
ROAD_FILL = False              # 도로(지목 도) 필지를 인접 통에 배분할지
ROAD_JIMOK = ["도"]            # 도로로 간주할 지목(연속지적도 JIBUN 끝 한글)
ROAD_SLIVER_M2 = 5.0           # 분할 조각 최소 면적(미만 슬리버는 버림)
ADJ_BUF_M = 0.5               # 인접 판정 버퍼(미터, source CRS 기준)
BOUND_STEP_M = 3.0            # 분할 시 도로 경계 점 샘플 간격(미터)
# ==========================================================

REQUIRED_CONFIG_KEYS = ["admin_dong", "admin_code", "legal_dongs",
                        "target_beopjeong", "table_csv"]

def load_config(path):
    """config.json 로드 → 필수키 검증 → table_csv를 config 폴더 기준 절대경로로 해석."""
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    missing = [k for k in REQUIRED_CONFIG_KEYS if k not in cfg]
    if missing:
        sys.exit(f"⚠ config 필수 항목 누락: {missing}  ({path})")
    cfg_dir = os.path.dirname(os.path.abspath(path))
    cfg["table_csv"] = os.path.join(cfg_dir, cfg["table_csv"])
    return cfg

def apply_config(cfg, shp_path, out_root):
    """config 값을 모듈 전역으로 주입하고 출력 폴더 out/{admin_code}/ 를 만든다."""
    global TABLE_CSV, SHP_PATH, OUT_DIR, ADMIN_DONG, ADMIN_CODE
    global TARGET_BEOPJEONG, BJD_CODE_TO_NAME, SHP_ENCODING, SOURCE_CRS_FALLBACK
    global CONFLICT_POLICY, BONBUN_FALLBACK, SPLIT_PARCEL_TONG, CLIP_TO_ADMIN
    global ROAD_FILL, ROAD_JIMOK, ROAD_SLIVER_M2
    ADMIN_DONG = cfg["admin_dong"]
    ADMIN_CODE = str(cfg["admin_code"])
    TABLE_CSV  = cfg["table_csv"]
    SHP_PATH   = shp_path
    TARGET_BEOPJEONG = list(cfg["target_beopjeong"])
    BJD_CODE_TO_NAME = {str(k): v for k, v in cfg["legal_dongs"].items()}
    SHP_ENCODING        = cfg.get("shp_encoding", "cp949")
    SOURCE_CRS_FALLBACK = cfg.get("source_crs_fallback", "EPSG:5186")
    CONFLICT_POLICY     = cfg.get("conflict_policy", "min_tong")
    BONBUN_FALLBACK     = cfg.get("bonbun_fallback", True)
    CLIP_TO_ADMIN       = cfg.get("clip_to_admin", True)
    SPLIT_PARCEL_TONG = [
        (s["dong"], str(s["bonbun"]), float(s["split_lat"]),
         int(s["south_tong"]), int(s["north_tong"]), s.get("desc", ""))
        for s in cfg.get("split_parcel_tong", [])
    ]
    ROAD_FILL      = bool(cfg.get("road_fill", False))
    ROAD_JIMOK     = list(cfg.get("road_jimok", ["도"]))
    ROAD_SLIVER_M2 = float(cfg.get("road_split_sliver_m2", 5.0))
    OUT_DIR = os.path.join(out_root, ADMIN_CODE)
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"config loaded: {ADMIN_DONG}/{ADMIN_CODE}  "
          f"(CSV={os.path.basename(TABLE_CSV)}, SHP={SHP_PATH}, OUT={OUT_DIR})")

# ---------- 1. 지번 전개 로직 (별표 표기 다양성 대응) ----------
# 별표 관할구역 표기가 동마다 조금씩 다름: 범위(491~537, 공백 295 ~ 340), 가운뎃점 나열
# (256-1ㆍ2ㆍ3), 부번 범위(169-35~40), 아파트명 혼합(243-6(선경그린빌라트)), 다(多)법정동,
# 공백 구분(225~229 225-1). 모두 빠짐없이 전개한다.
APT_WORD = re.compile(r'아파트|빌라|연립|상가|단지|타운|마을|푸르지오|레이크|클래스|호반|어울림|센트럴|'
                      r'스타힐스|그린빌|건영|세원|삼호|혜성|건안|더존|중흥|호수|써밋|Ⓐ|\d+호|\d+동')
BEOP_RE = re.compile(r'^([가-힣]{1,4}[동리])\s*(.*)$')   # 2글자 법정동(포동 등)도 인식
SPEC_FULL = re.compile(r'^산?\d[\d~\-ㆍ]*$')

def normalize(s):
    s = (str(s).replace('～', '~').replace('〜', '~').replace('∼', '~')
         .replace('·', 'ㆍ').replace('，', ',').replace('​', '').replace('　', ' '))
    s = re.sub(r'\s*~\s*', '~', s)          # 틸드 주변 공백 제거(295 ~ 340 → 295~340)
    s = re.sub(r'\s*ㆍ\s*', 'ㆍ', s)         # 가운뎃점 주변 공백 제거
    return s

def parse_spec(spec, san):
    """깨끗한 지번 스펙(169-35~40, 256-1ㆍ2ㆍ3, 491~537, 49~55 ...) → 지번 리스트('산' 포함)."""
    core = spec
    if not core:
        return []
    if 'ㆍ' in core:
        parts = [p for p in core.split('ㆍ') if p]
        if '-' in parts[0]:
            base = parts[0].split('-')[0]
            seq = [parts[0]] + [p if '-' in p else f"{base}-{p}" for p in parts[1:]]
        else:
            seq = parts
        out = []
        for p in seq:
            r = parse_spec(p, False)
            if r is None:
                return None
            out += r
        return ['산' + x for x in out] if san else out
    if '~' in core:
        a, b = [x.strip() for x in core.split('~', 1)]
        try:
            if '-' in a and '-' not in b:                       # 169-35~40
                base, sub = a.split('-', 1)
                out = [f"{base}-{n}" for n in range(int(sub), int(b) + 1)]
            elif '-' not in a and '-' not in b:                 # 491~537 / 1008~3(=1008-3 오타)
                if int(a) > int(b):                             # 내림차순=틸드 오타 → 'a-b'(부번), 지적도가 검증
                    out = [f"{a}-{b}"]
                else:
                    out = [str(n) for n in range(int(a), int(b) + 1)]
            elif '-' not in a and '-' in b:                     # 491~537-2
                bm = b.split('-')[0]
                out = [str(n) for n in range(int(a), int(bm) + 1)] + [b]
            else:                                               # 169-3~169-7 / 1882-1~1885-9
                am, asub = a.split('-'); bm, bsub = b.split('-')
                if am == bm:                                    # 같은 본번 → 부번 범위
                    out = [f"{am}-{n}" for n in range(int(asub), int(bsub) + 1)]
                else:                                           # 본번 넘나듦 A-asub~B-bsub
                    out = []
                    # 시작 본번 A: 부번 1부터면 A 전체(bare→본번폴백), 아니면 A-asub..상한(지적도가 필터)
                    if int(asub) <= 1:
                        out.append(am)
                    else:
                        out += [f"{am}-{n}" for n in range(int(asub), 200)]
                    out += [str(n) for n in range(int(am) + 1, int(bm))]   # 중간 본번 전체(bare→폴백)
                    out += [f"{bm}-{n}" for n in range(1, int(bsub) + 1)]  # 끝 본번 B: 1..bsub
        except ValueError:
            return None
        if len(out) > 2000:                                     # 비정상 범위(파싱 오류) 안전장치
            return None
    else:
        out = [core]
    return ['산' + x for x in out] if san else out

def expand_table(csv_path, valid_beop):
    """별표 CSV → [(통,반,법정동,지번,아파트bool)], 아파트행, 실패. valid_beop=관할 법정동 집합."""
    import csv
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    recs, apt_rows, failed = [], [], []
    for r in rows:
        try:
            tong, ban = int(r['통']), int(r['반'])
        except (ValueError, KeyError, TypeError):
            continue
        raw = normalize(r['관할구역'])
        # '(부번지 포함)'은 아파트가 아니라 '본번의 모든 부번을 같은 통'이라는 뜻 → 괄호를 Ⓐ로
        # 바꾸기 전에 먼저 제거(안 그러면 Ⓐ로 아파트 오인되어 본번폴백에서 빠져 부번이 미배정됨).
        raw = re.sub(r'\(\s*부번지?\s*포함\s*\)', ' ', raw)
        # 나머지 괄호(아파트명·호수, 내부에 콤마 포함: '1740-3(아주5차 101호~1701호, 102호~1702호)')를
        # 콤마 분리 전에 ' Ⓐ ' 표시로 치환 → 지번이 안 깨지고, 아파트 여부는 세그먼트 단위로 유지
        # (아파트와 같은 행의 정상 지번을 아파트로 오인하지 않도록).
        raw = re.sub(r'\([^)]*\)', ' Ⓐ ', raw)
        cur = None
        cur_bon = None                                          # 직전 본번(부번 연속 해석용): '764-3, 9~12, 16' → 764-9~12, 764-16
        for seg in raw.split(','):                              # 콤마/법정동 단위 세그먼트
            seg = seg.strip()
            if not seg:
                continue
            had_apt = bool(APT_WORD.search(seg))               # 세그먼트 단위 아파트 여부
            m = BEOP_RE.match(seg)
            if m and m.group(1) in valid_beop:                  # 알려진 법정동만 전환
                cur = m.group(1); body = m.group(2).strip(); cur_bon = None
            else:
                body = seg
            if cur is None:
                failed.append((tong, ban, '', seg)); continue
            got = False
            for word in body.split():                          # 지번은 공백으로도 구분됨
                word = word.split('(')[0].strip(',.')          # 미닫힌 괄호 잔여 제거
                word = re.sub(r'번지$', '', word)              # 'N번지' → 'N'(지번 접미사 제거)
                if not word:
                    continue
                # 지번은 세그먼트 앞쪽에 먼저 온다. '산'이 아닌 한글이 든 단어(아파트명·N동)가
                # 나오면 그 뒤(연성쉐르빌 501~920, 241동 101~806)는 호수/동 표기 → 지번 아님 → 멈춤.
                if re.search(r'[가-힣]', word) and not re.fullmatch(r'산?\d[\d~\-ㆍ산]*', word):
                    break
                # 오른쪽 끝점에 산이 붙은 범위('산74-1~산87', '산100-4~산104', '13-1~산13-7' 등):
                # SPEC_FULL이 산 2회를 못 받아 통째 드롭되던 버그를 수정. 오른쪽 산은 그 끝점이
                # '본번'이라는 신호 → 다른 본번이면 본번 범위(부번은 본번폴백이 채움), 같은 본번이면
                # 부번 범위로 전개. (왼쪽만 산인 범위 '산68~74'는 기존 경로가 이미 정상 처리.)
                if '~산' in word:
                    cur_bon = None                              # 산은 별도 네임스페이스 → 부번 연속 끊음
                    try:
                        a, b = word.replace('산', '').strip('-~ㆍ').split('~', 1)
                        abon, bbon = int(a.split('-')[0]), int(b.split('-')[0])
                        if abon == bbon:                        # 같은 본번 → 부번 범위
                            asub = int(a.split('-')[1]) if '-' in a else 0
                            bsub = int(b.split('-')[1]) if '-' in b else 0
                            res = ['산'+str(abon)+(f'-{n}' if n else '') for n in range(asub, bsub+1)]
                        elif 0 < bbon - abon < 2000:            # 다른 본번 → 본번 범위 + 끝점 부번
                            res = ['산'+str(n) for n in range(abon, bbon+1)]
                            if '-' in a: res.append('산'+a)
                            if '-' in b: res.append('산'+b)
                        else:
                            res = []
                    except (ValueError, IndexError):
                        res = []
                    if res:
                        for j in res:
                            recs.append((tong, ban, cur, j, had_apt))
                        got = True
                    else:
                        failed.append((tong, ban, cur, word))
                    continue
                if not SPEC_FULL.match(word):                   # 아파트명 등 비지번 단어 → 스킵
                    continue
                san = word.startswith('산')
                core = (word[1:] if san else word).strip('-~ㆍ')
                res = parse_spec(core, san)
                if res is None or not res:
                    failed.append((tong, ban, cur, word)); continue
                for j in res:
                    recs.append((tong, ban, cur, j, had_apt))
                got = True
                # 부번 연속 해석: 직전 본번-부번('764-3') 뒤의 bare 숫자('9~12','16')는 그 본번의
                # 부번일 수 있음 → cur_bon-X도 함께 생성(지적도에 실재하는 쪽만 매칭됨). 본번 해석은
                # 그대로 두므로(대야동 '496-1~12, 491'의 491=본번) 회귀 없음.
                if san:
                    cur_bon = None
                elif '-' in core:                               # 본번-부번 → 본번 기억
                    try: cur_bon = int(core.split('-')[0])
                    except ValueError: cur_bon = None
                elif cur_bon is not None:                       # bare 숫자 → 직전 본번의 부번 해석 추가
                    for x in res:
                        recs.append((tong, ban, cur, f"{cur_bon}-{x}", had_apt))
            if not got and body:                               # 지번 없는 아파트명 행
                apt_rows.append((tong, ban, cur, body, r['관할구역']))
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
    a = a[a["ADM_CD"].astype(str) == ADMIN_CODE]
    return a.to_crs("EPSG:4326")[["geometry"]] if len(a) else None

# ---------- 2.5 도로 경계 보정 (2단계) ----------
def jimok(jibun):
    """연속지적도 JIBUN 끝의 지목 한글 추출. 예: '1-183 대'→'대', '39-18전'→'전'."""
    m = re.search(r'([가-힣]+)\s*$', str(jibun).strip())
    return m.group(1) if m else ""

def _polys_only(geom):
    """교집합 결과에서 폴리곤 성분만 남긴다(라인/점 제거)."""
    from shapely.geometry.base import BaseMultipartGeometry
    from shapely.geometry import Polygon, MultiPolygon
    from shapely.ops import unary_union
    if geom.is_empty:
        return None
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    if isinstance(geom, BaseMultipartGeometry):
        parts = [g for g in geom.geoms if isinstance(g, (Polygon, MultiPolygon))]
        return unary_union(parts) if parts else None
    return None

def _split_road_by_nearest(road, near_geoms, near_tongs, sliver):
    """도로 폴리곤을 '인접 배정필지까지의 거리(최근접)' 기준으로 통별 분할.
    near_geoms/near_tongs: 인접 주거필지 geometry/통(같은 길이). 반환 [(통,geometry)...] 또는 None."""
    from shapely.ops import voronoi_diagram, unary_union
    from shapely.geometry import MultiPoint
    from shapely import STRtree
    boundary = road.boundary
    n = int(boundary.length // BOUND_STEP_M)
    n = max(min(n, 1200), 12)                       # 샘플 점 개수 상·하한
    ftree = STRtree(near_geoms)
    pts, labs = [], []
    for i in range(n):
        p = boundary.interpolate(i / n, normalized=True)
        labs.append(near_tongs[int(ftree.nearest(p))])  # 최근접 인접필지의 통
        pts.append(p)
    if len(set(labs)) == 1:                          # 사실상 한 통만 인접
        return [(labs[0], road)]
    try:
        cells = voronoi_diagram(MultiPoint(pts), envelope=road)
    except Exception:
        return None
    stree = STRtree(pts)
    from collections import defaultdict
    byt = defaultdict(list)
    for cell in cells.geoms:
        hit = stree.query(cell, predicate="contains")
        lab = labs[int(hit[0])] if len(hit) else labs[int(stree.nearest(cell.representative_point()))]
        piece = _polys_only(cell.intersection(road))
        if piece is not None:
            byt[lab].append(piece)
    out = []
    for t, gs in byt.items():
        g = unary_union(gs)
        if not g.is_empty and g.area >= sliver:
            out.append((t, g))
    return out or None

def assign_roads(sub, matched):
    """미배정 도로(지목 도) 필지를 인접 배정 통에 배분.
    sub/matched: source CRS(미터). 반환: (도로 GeoDataFrame[통,반,_dong,_jib,_fill,geometry] | None, 통계 dict)."""
    import geopandas as gpd
    from shapely import STRtree
    roads = sub[sub["통"].isna()].copy()
    if "JIBUN" in roads.columns:
        roads = roads[roads["JIBUN"].map(jimok).isin(ROAD_JIMOK)].copy()
    else:
        roads = roads.iloc[0:0]
    stats = {"roads": int(len(roads)), "simple": 0, "split": 0, "hold": 0}
    if roads.empty:
        return None, stats
    res = matched[["통", "geometry"]].copy()
    res["통"] = res["통"].astype(int)
    res = res.reset_index(drop=True)
    res_geoms, res_tongs = list(res.geometry), list(res["통"])
    res_tree = STRtree(res_geoms)

    roads = roads.reset_index(drop=True)
    roads["rid"] = range(len(roads))
    rb = roads[["rid", "geometry"]].copy()
    rb["geometry"] = rb.buffer(ADJ_BUF_M)
    j = gpd.sjoin(rb, res[["통", "geometry"]], predicate="intersects", how="inner")
    adj = j.groupby("rid")["통"].agg(lambda s: sorted({int(x) for x in s}))

    rows = []
    for rid, dong, jib, geom in zip(roads["rid"], roads["_dong"], roads["_jib"], roads.geometry):
        tongs = adj.get(rid)
        if not tongs:
            stats["hold"] += 1
            continue
        if len(tongs) == 1:
            rows.append((tongs[0], 0, dong, jib, "road_match", geom))
            stats["simple"] += 1
            continue
        idx = res_tree.query(geom.buffer(ADJ_BUF_M), predicate="intersects")
        ng = [res_geoms[i] for i in idx if res_tongs[i] in tongs]
        nt = [res_tongs[i] for i in idx if res_tongs[i] in tongs]
        pieces = _split_road_by_nearest(geom, ng, nt, ROAD_SLIVER_M2) if ng else None
        if pieces is None:
            rows.append((tongs[0], 0, dong, jib, "manual_pending", geom))
        else:
            for t, g in pieces:
                rows.append((t, 0, dong, jib, "road_split", g))
            stats["split"] += 1

    if not rows:
        return None, stats
    rgdf = gpd.GeoDataFrame(
        [{"통": t, "반": b, "_dong": d, "_jib": jb, "_fill": fm, "geometry": g}
         for (t, b, d, jb, fm, g) in rows],
        geometry="geometry", crs=matched.crs)
    return rgdf, stats

# ---------- 3. 메인 ----------
def main():
    import geopandas as gpd
    import pandas as pd

    print("▶ 1) 통·반 표 전개")
    recs, apt_rows, failed = expand_table(TABLE_CSV, set(TARGET_BEOPJEONG))
    # 별표에 '아파트 이름만' 있어 지번 없던 통 → 외부 검증(juso 주소DB + 지적도 실재)으로 확인한
    # 지번을 보강(data/apt_jibun_overrides.csv). 추측 아님: 검증된 지번만 등재.
    ovp = "data/apt_jibun_overrides.csv"
    if os.path.exists(ovp):
        import csv as _csv
        n0 = len(recs)
        for o in _csv.DictReader(open(ovp, encoding="utf-8-sig")):
            if str(o.get("code", "")).strip() != ADMIN_CODE:
                continue
            try:
                ot = int(o["통"]); ob = int(o.get("반") or 0)
            except (ValueError, KeyError):
                continue
            recs.append((ot, ob, o["법정동"].strip(), o["지번"].strip(), True))  # 아파트로 등재 → 범위 항목 이김
        if len(recs) > n0:
            print(f"   + 아파트 지번 보강(override) {len(recs)-n0}건")
    tdf = pd.DataFrame(recs, columns=["통", "반", "법정동", "지번", "아파트"])
    print(f"   전개 지번행 {len(tdf)}, 고유필지 {tdf[['법정동','지번']].drop_duplicates().shape[0]}, "
          f"아파트반 {len(apt_rows)}, 전개실패 {len(failed)}")
    if failed:
        pd.DataFrame(failed, columns=["통","반","법정동","토큰"]).to_csv(
            f"{OUT_DIR}/report_parse_failed.csv", index=False, encoding="utf-8-sig")

    print("▶ 2) 연속지적도 로드")
    if not os.path.exists(SHP_PATH):
        sys.exit(f"⚠ 연속지적도 SHP 없음: {SHP_PATH}\n"
                 f"  README '준비물' 참고 → 시흥시(41390) 연속지적도(.shp/.shx/.dbf/.prj)를 받아 "
                 f"--shp 로 지정하세요. (위 1단계 표 전개는 정상 동작 확인됨)")
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
        jb = r["지번"]
        # 부번 '0'은 실재하지 않는 표기 → 본번지로 정규화(별표 'N-0'='2635-0', 지적도는 'N'='2635').
        # 지적도(canon_from_*)는 부번0을 이미 'N'으로 두므로 별표도 맞춰야 정확매칭됨(거북섬동 매립지 '2603-0~5' 등 다수).
        # 정확매칭 키에서만 정규화 → 본번폴백 분류(아래 '-' 검사)는 원본대로라 과대배정 없음.
        if jb.endswith("-0"):
            jb = jb[:-2]
        lut[(r["법정동"], jb)].append((r["통"], r["반"], r["아파트"]))

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
            # 충돌 시 '구체적 아파트' 항목이 '범위' 항목을 이긴다.
            # (예: 824가 통1 '818~827' 범위와 통12 '824 대우3차'에 둘 다 있으면 → 대우3차 통12)
            pool = [c for c in cand if c[2]] or cand
            tong = min(c[0] for c in pool) if CONFLICT_POLICY == "min_tong" else pool[0][0]
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

    # 법적근거(별표 지번) 구간 표시. 도로 보정 조각은 assign_roads가 별도 _fill 부여.
    matched["_fill"] = "parcel_match"
    if ROAD_FILL:
        print("▶ 4.5) 도로 경계 보정")
        road_gdf, rstats = assign_roads(sub, matched)
        print(f"   도로필지 {rstats['roads']} → 단순배정 {rstats['simple']}, "
              f"분할 {rstats['split']}, 보류(미접) {rstats['hold']}")
        if road_gdf is not None and len(road_gdf):
            src_crs = matched.crs
            matched = gpd.GeoDataFrame(
                pd.concat([matched, road_gdf], ignore_index=True),
                geometry="geometry", crs=src_crs)
            road_gdf.drop(columns="geometry").to_csv(
                f"{OUT_DIR}/report_roads.csv", index=False, encoding="utf-8-sig")

    print("▶ 5) 4326 변환 + (선택)행정동 클립 + 통 단위 병합 + 행정동 외곽선")
    matched = matched.to_crs("EPSG:4326")
    matched["통"] = matched["통"].astype(int)
    admin_poly = None                            # 공식 행정동경계 폴리곤(통 기하 클립용)

    # 행정동 외곽 경계 먼저 로드(클립·검증에 사용): 공식 경계 있으면 사용, 없으면 대상필지 병합
    admin_official = load_admin_outline()
    if admin_official is not None:
        admin_gdf = admin_official.dissolve().reset_index(drop=True)
        admin_gdf["geometry"] = admin_gdf.buffer(0)
        print("   행정동 외곽선: 공식 행정동경계 사용(ADM_CD", ADMIN_CODE + ")")
        # 검증/클립: 매칭 필지가 행정동 경계 안에 드는지
        gp = admin_gdf.geometry.iloc[0]; admin_poly = gp
        inside_mask = matched.representative_point().within(gp)
        print(f"   매칭 필지의 행정동 내부 비율 {inside_mask.mean()*100:.1f}% (낮으면 법정동코드 매핑 오류)")
        bad = matched[~inside_mask]
        if len(bad):
            bad[["통","_dong","_jib"]].rename(columns={"_dong":"법정동","_jib":"지번"}).to_csv(
                f"{OUT_DIR}/report_outside_admin.csv", index=False, encoding="utf-8-sig")
            outside_tongs = sorted(int(t) for t in bad["통"].unique())
            print(f"   ⚠ 행정동 밖 필지 {len(bad)}개 (통 {outside_tongs}) → report_outside_admin.csv")
            if CLIP_TO_ADMIN:                       # 공유 법정동 본번폴백 과대확장 제거
                matched = matched[inside_mask].copy()
                print(f"   ✂ clip_to_admin: 행정동 밖 {len(bad)}필지 제외 → 통 경계 동 안으로")
    else:
        admin = sub.to_crs("EPSG:4326")[["geometry"]].copy()
        admin["geometry"] = admin.buffer(0)
        admin_gdf = admin.dissolve().reset_index(drop=True)
        admin_gdf["geometry"] = admin_gdf.buffer(0)
        print("   행정동 외곽선: 대상필지 병합(행정동경계 파일 없음)")

    # (클립된) matched로 통 단위 병합
    tong_gdf = matched.dissolve(by="통").reset_index()[["통", "geometry"]]
    tong_gdf["geometry"] = tong_gdf.buffer(0)   # 위상 정리
    # 통 폴리곤을 행정동 경계로 기하 클립 → 경계 가로지르는 잔여(straddle)까지 제거
    if CLIP_TO_ADMIN and admin_poly is not None:
        tong_gdf["geometry"] = tong_gdf.geometry.intersection(admin_poly).buffer(0)
        tong_gdf = tong_gdf[~tong_gdf.geometry.is_empty].reset_index(drop=True)
    # 통 번호 라벨 위치(폴리곤 내부 한 점)
    lp = tong_gdf.representative_point()
    tong_gdf["lon"] = lp.x.round(7)
    tong_gdf["lat"] = lp.y.round(7)

    parcels_out = matched[["통","반","_dong","_jib","_fill","geometry"]].rename(
        columns={"_dong":"법정동","_jib":"지번","_fill":"fill_method"})
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
                          "지번": f"{bon}({half}·근사분할)", "fill_method": "road_split",
                          "geometry": geom, "근사": 1})
        print(f"   분할 추가: {dong} {bon} → {s_tong}통(남)/{n_tong}통(북)")
    if add_t:
        tong_gdf = pd.concat([tong_gdf, gpd.GeoDataFrame(add_t, crs="EPSG:4326")],
                             ignore_index=True)
        parcels_out = pd.concat([parcels_out, gpd.GeoDataFrame(add_p, crs="EPSG:4326")],
                                ignore_index=True)

    parcels_out.to_file(f"{OUT_DIR}/{ADMIN_DONG}_parcels.geojson", driver="GeoJSON")
    tong_gdf.to_file(f"{OUT_DIR}/{ADMIN_DONG}_tong.geojson", driver="GeoJSON")
    admin_gdf.to_file(f"{OUT_DIR}/{ADMIN_DONG}_admin.geojson", driver="GeoJSON")

    print("▶ 6) 인터랙티브 지도 생성")
    write_map(parcels_out.to_json(), tong_gdf.to_json(), admin_gdf.to_json(),
              f"{OUT_DIR}/{ADMIN_DONG}_map.html", f"{ADMIN_DONG} 통반경계도")
    print("✔ 완료 →", OUT_DIR, f"({ADMIN_DONG}_map.html 더블클릭)")

# ---------- 4. 단독 실행 Leaflet 지도 ----------
def write_map(parcels_geojson, tong_geojson, admin_geojson, path, title="통반경계도"):
    html = """<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>__TITLE__</title>
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
 <b>__TITLE__</b>
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
const road=f=>{const m=f.properties&&f.properties.fill_method;
  return m==='road_match'||m==='road_split'||m==='manual_pending';};
const fmKor=m=>({road_match:'도로(통째 보정)',road_split:'도로(분할 보정)',
  manual_pending:'도로(수동 검토 대상)',parcel_match:'별표 지번(법적 근거)'}[m]||'');
// +/- 줌버튼이 좌상단 패널과 겹치지 않게 우상단으로 이동
const map=L.map('map',{zoomControl:false});
L.control.zoom({position:'topright'}).addTo(map);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
 {attribution:'© OpenStreetMap',maxZoom:19}).addTo(map);

// 행정동(군자동) 외곽 경계 — 주변 타동/타시와 구분되게 굵은 검정선
const admin=L.geoJSON(ADMIN,{style:{color:'#111',weight:4,fill:false,opacity:0.85}}).addTo(map);

let mode='fill';
const pStyle=f=>{const a=approx(f),rd=road(f);return{
  color:color(f.properties.통),weight:a?2:(rd?0.6:1),
  dashArray:a?'5 4':null,
  fillOpacity:mode==='fill'?(a?0.3:(rd?0.28:0.45)):0,
  opacity:mode==='fill'?(a?0.95:(rd?0.5:0.6)):0.9};};
const parcels=L.geoJSON(PARCELS,{style:pStyle,onEachFeature:(f,l)=>{
  const p=f.properties;
  const txt = approx(f)
    ? `<b>${p.통}통 (근사 분할)</b><br>${p.법정동} ${p.지번}<br>`+
      `<small>별표에 지번이 없어 실제 필지를 도로 기준으로 분할한 추정치</small>`
    : road(f)
    ? `${p.법정동} ${p.지번} <small>(도로)</small><br><b>${p.통}통</b><br>`+
      `<small>${fmKor(p.fill_method)}</small>`
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
    html = (html.replace("__TITLE__", title)
                .replace("__PARCELS__", parcels_geojson)
                .replace("__TONG__", tong_geojson)
                .replace("__ADMIN__", admin_geojson))
    open(path, "w", encoding="utf-8").write(html)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description="시흥시 통반경계도 빌드 (동별 config.json 기반)")
    ap.add_argument("--config", required=True,
                    help="동별 config.json 경로 (예: data/31150680/config.json)")
    ap.add_argument("--shp", default=DEFAULT_SHP_PATH,
                    help=f"연속지적도 SHP 경로 (기본 {DEFAULT_SHP_PATH})")
    ap.add_argument("--out-dir", default="out",
                    help="출력 루트 (실제 출력은 {out-dir}/{admin_code}/ 아래)")
    ap.add_argument("--no-road-fill", action="store_true",
                    help="도로 경계 보정(2단계)을 끄고 빌드 — 1단계 동일 재현 회귀 검증용")
    args = ap.parse_args()
    apply_config(load_config(args.config), args.shp, args.out_dir)
    if args.no_road_fill:
        ROAD_FILL = False
    main()
