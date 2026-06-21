#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
별표 파서 개선 분석 — 현행 vs 신규 파서를 전 20개 행정동에 적용해
'지적도에 있는데 매칭 못 한 별표 지번(미배정)'이 얼마나 회복되는지 측정한다.
빌드를 건드리지 않고 검증만. (build 적용 전 사전 검증용)
"""
import csv, glob, json, re
import geopandas as gpd

SHP_PATH = "LSMD_CONT_LDREG_41390_202606.shp"


def normalize(s):
    s = (str(s).replace('～', '~').replace('〜', '~').replace('∼', '~')
         .replace('·', 'ㆍ').replace('，', ',').replace('​', '').replace('　', ' '))
    s = re.sub(r'\s*~\s*', '~', s)      # 틸드 주변 공백 제거(295 ~ 340 → 295~340)
    s = re.sub(r'\s*ㆍ\s*', 'ㆍ', s)     # 가운뎃점 주변 공백 제거
    return s


# ---------- 신규 파서 ----------
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
            elif '-' not in a and '-' not in b:                 # 491~537
                out = [str(n) for n in range(int(a), int(b) + 1)]
            elif '-' not in a and '-' in b:                     # 491~537-2
                bm = b.split('-')[0]
                out = [str(n) for n in range(int(a), int(bm) + 1)] + [b]
            else:                                               # 169-3~169-7 / 169-3~170-2
                am, asub = a.split('-'); bm, bsub = b.split('-')
                if am == bm:
                    out = [f"{am}-{n}" for n in range(int(asub), int(bsub) + 1)]
                else:
                    out = [a, b] + [str(n) for n in range(int(am) + 1, int(bm))]
        except ValueError:
            return None
        if len(out) > 2000:                                     # 비정상 범위(파싱 오류) 안전장치
            return None
    else:
        out = [core]
    return ['산' + x for x in out] if san else out


SPEC_FULL = re.compile(r'^산?\d[\d~\-ㆍ]*$')


APT_WORD = re.compile(r'아파트|빌라|연립|상가|단지|타운|마을|푸르지오|레이크|클래스|호반|어울림|센트럴|'
                      r'스타힐스|그린빌|건영|세원|삼호|혜성|건안|더존|중흥|호수|써밋|Ⓐ|\d+호|\d+동')
BEOP = re.compile(r'^([가-힣]{2,5}[동리])\s*(.*)$')
LEAD_JIBUN = re.compile(r'^(\d[\d\sㆍ~\-]*)')


def expand_new(csv_path, valid_beop):
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    addr = list(rows[0].keys())[-1]
    recs, apt, failed = [], [], []
    for r in rows:
        tong, ban = r['통'], r['반']
        raw = normalize(r[addr])
        cur = None
        for seg in raw.split(','):
            seg = seg.strip()
            if not seg:
                continue
            had_apt = bool(re.search(r'\(', seg)) or bool(APT_WORD.search(seg))
            seg = re.sub(r'\([^)]*\)', '', seg).strip()         # 아파트명 괄호 제거
            m = BEOP.match(seg)
            if m and m.group(1) in valid_beop:                  # 알려진 법정동만 전환
                cur = m.group(1); body = m.group(2).strip()
            else:
                body = seg
            if cur is None:
                failed.append((tong, ban, seg)); continue
            got = False
            for word in body.split():                            # 지번은 공백으로도 구분됨
                word = word.strip(',.')
                if not SPEC_FULL.match(word):                    # 아파트명 등 비지번 단어 → 스킵
                    continue
                san = word.startswith('산')
                core = (word[1:] if san else word).strip('-~ㆍ')
                res = parse_spec(core, san)
                if res is None or not res:
                    failed.append((tong, ban, cur, word)); continue
                for j in res:
                    recs.append((tong, ban, cur, j, had_apt))
                got = True
            if not got and body:
                apt.append((tong, ban, cur, body))
    return recs, apt, failed


# ---------- 현행 파서(비교용, build와 동일 로직 발췌) ----------
def normalize_old(s):
    return str(s).replace('～', '~').replace('〜', '~').replace('∼', '~').replace('·', 'ㆍ')


def parse_token_old(tok):
    tok = tok.strip().strip(',')
    if not tok:
        return []
    san = tok.startswith('산'); core = tok[1:].strip() if san else tok
    if 'ㆍ' in core:
        parts = core.split('ㆍ'); res = []
        if '-' in parts[0]:
            base = parts[0].split('-')[0]
            seq = [parts[0]] + [p if '-' in p else f"{base}-{p}" for p in parts[1:]]
        else:
            seq = parts
        for p in seq:
            r = parse_token_old(('산' if san else '') + p)
            if r is None:
                return None
            res += r
        return res
    if '~' in core:
        a, b = [x.strip() for x in core.split('~', 1)]
        try:
            if '-' in a and '-' not in b:
                base, sub = a.split('-', 1); out = [f"{base}-{n}" for n in range(int(sub), int(b) + 1)]
            elif '-' not in a and '-' not in b:
                out = [str(n) for n in range(int(a), int(b) + 1)]
            elif '-' not in a and '-' in b:
                bm = b.split('-')[0]; out = [str(n) for n in range(int(a), int(bm) + 1)] + [b]
            else:
                return None
        except ValueError:
            return None
    else:
        out = [core]
    return ['산' + x for x in out] if san else out


APT_OLD = re.compile(r'아파트|Ⓐ|상가|\d+호|\(')


def expand_old(csv_path):
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    addr = list(rows[0].keys())[-1]
    recs = []
    for r in rows:
        raw = normalize_old(r[addr]); dong = raw.split()[0]; rest = raw[len(dong):].strip()
        if APT_OLD.search(rest):
            mm = re.match(r'([\d]+(?:-[\d]+)?)', rest)
            if mm:
                recs.append((dong, mm.group(1)))
            continue
        for tok in rest.split(','):
            res = parse_token_old(tok.strip())
            if res:
                for j in res:
                    recs.append((dong, j))
    return recs


def canon_pnu(pnu):
    pnu = str(pnu).strip()
    if len(pnu) < 19 or not pnu[:19].isdigit():
        return None, None
    san = pnu[10] == '2'; bon = int(pnu[11:15]); bu = int(pnu[15:19])
    return pnu[:10], ('산' if san else '') + str(bon) + (f"-{bu}" if bu else '')


def main():
    shp = gpd.read_file(SHP_PATH)
    shp["_bjd"], shp["_jib"] = zip(*shp["PNU"].map(canon_pnu))
    grand_old = grand_new = grand_recover = grand_notshp = 0
    print(f"{'행정동':<8} {'별표지번(구→신)':>14} {'SHP존재(구→신)':>14} {'신규회복':>8} {'SHP에없음':>9}")
    for cfgp in sorted(glob.glob("data/3*/config.json")):
        cfg = json.load(open(cfgp, encoding="utf-8"))
        code, dong = cfg["admin_code"], cfg["admin_dong"]
        leg = cfg.get("legal_dongs", {})
        name_by_code = leg
        valid = set(leg.values())
        csvp = f"data/{code}/관할구역.csv"
        try:
            rows = list(csv.DictReader(open(csvp, encoding="utf-8-sig")))
        except FileNotFoundError:
            continue
        # SHP 키: (법정동명, 지번)
        sub = shp[shp["_bjd"].isin(leg.keys())]
        shp_keys = set((name_by_code[b], j) for b, j in zip(sub["_bjd"], sub["_jib"]) if b in name_by_code)
        # 구
        old = set(expand_old(csvp))
        old_in = old & shp_keys
        # 신
        recs, apt, failed = expand_new(csvp, valid)
        new = set((b, j) for _, _, b, j, _ in recs)
        new_in = new & shp_keys
        recover = new_in - old_in
        notshp = new - shp_keys
        grand_old += len(old_in); grand_new += len(new_in)
        grand_recover += len(recover); grand_notshp += len(notshp)
        print(f"{dong:<8} {len(old):>6}→{len(new):<6} {len(old_in):>6}→{len(new_in):<6} "
              f"{len(recover):>8} {len(notshp):>9}   실패{len(failed)}")
    print(f"\n합계: SHP매칭 별표지번 {grand_old}→{grand_new} (신규 회복 {grand_recover}), "
          f"신파서 SHP에없음 {grand_notshp}")


if __name__ == "__main__":
    main()
