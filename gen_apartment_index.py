#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
아파트 동(棟) → 통·반 검색 인덱스 — out/apartment_index.json.

지도에 못 그리는(한 지번을 동·호로 나눈) 아파트도 '아파트 이름 + 동번호'로
몇 통 몇 반인지 검색할 수 있게, 별표 관할구역 텍스트에서
(아파트명, 동번호, 통, 반, 호범위)를 뽑는다.

같은 동이 호수 범위로 여러 반에 걸치면 각각 별도 항목(검색 시 모두 표시).
사용: python gen_apartment_index.py   (data/{code}/관할구역.csv 필요)
"""
import csv, glob, json, os, re

DONG_TOK = re.compile(r'(\d+)\s*동')                       # 숫자 동 "101동"
DONG_RANGE = re.compile(r'(\d+)\s*동?\s*[~～\-]\s*(\d+)\s*동')  # "101~103동", "101동~103동"
# 한글 동(가·나·다…) — 건물 동 글자만, 토큰 경계로(법정동 '미산동'의 '산동' 오인 방지)
DONG_KOR = re.compile(r'(?:^|[\s(（])([가나다라마바사아자차카타파하])동')
DONG_ALPHA = re.compile(r'(?:^|[\s(（])([A-Za-z])동')         # 알파벳 동 "A동"
JIBUN = re.compile(r'산?\d[\d\-]*')                          # 지번
JIBUN_ISH = re.compile(r'산?\d[\d\-～~ㆍ·,]*(?:외)?|\d+필지|외')  # 지번·"869-1～7"·"289-9ㆍ56"·"…외"·"N필지"(이름 추출 멈춤)
# 동 뒤 호범위/메모(전체 등) 추출 — 동번호 다음부터 콤마/다음 동/끝까지
HO_AFTER = re.compile(r'(\d+)\s*동\s*([^,，()]*?)(?=(?:\d+\s*동)|[,，()]|$)')


def apt_name(head, beops):
    """동번호 앞부분(head)에서 아파트명을 뒤 토큰부터 모은다.
    법정동/순수 지번 토큰을 만나면 멈춰 이름의 'N차'(예: 풍림1차)는 보존한다."""
    s = head.replace('Ⓐ', ' ')
    s = re.sub(r'[()（）\[\],，]', ' ', s)
    toks = s.split()
    out = []
    for t in reversed(toks):
        if t in beops:                       # 법정동이면 멈춤
            break
        if JIBUN_ISH.fullmatch(t):           # 지번·"…외"·"N필지" 토큰이면 멈춤(이름 속 'N차'는 통과)
            break
        out.insert(0, t)
    name = ' '.join(out).strip(' ·～~-')
    # 마무리: 이름 맨 앞에 붙은 지번("599-1대우4차", "994번지 풍림4차") 한 번 더 제거
    name = re.sub(r'^산?\d[\d\-～~ㆍ·]*(?:외)?\s*(?:\d+\s*필지)?\s*(?:번지)?\s*', '', name)
    return name.strip(' ·～~-')


def norm(s):
    """검색 매칭용 정규화: 공백·'아파트'·Ⓐ 제거."""
    return re.sub(r'\s+', '', (s or '')).replace('아파트', '').replace('Ⓐ', '')


def main():
    legmap = {}
    for cfgp in sorted(glob.glob("data/3*/config.json")):
        cfg = json.load(open(cfgp, encoding="utf-8"))
        legmap[cfg["admin_code"]] = (cfg["admin_dong"], list(cfg["legal_dongs"].values()))

    items = []
    for cfgp in sorted(glob.glob("data/3*/config.json")):
        cfg = json.load(open(cfgp, encoding="utf-8"))
        code = cfg["admin_code"]
        dong, beops = legmap[code]
        csvp = f"data/{code}/관할구역.csv"
        if not os.path.exists(csvp):
            continue
        for r in csv.DictReader(open(csvp, encoding="utf-8-sig")):
            txt = str(r.get("관할구역", "")).strip()
            firsts = [mm.start() for rx in (DONG_TOK, DONG_KOR, DONG_ALPHA)
                      for mm in [rx.search(txt)] if mm]   # 첫 동(숫자/한글/알파벳) 위치 = 이름 경계
            if not firsts:
                continue
            try:
                tong = int(r["통"]); ban = int(float(r["반"])) if r.get("반") not in (None, "") else 0
            except (ValueError, KeyError):
                continue
            name = apt_name(txt[:min(firsts)], beops)
            if not name:                                   # 아파트명 못 뽑으면 스킵
                continue
            # 이 행의 동(숫자 범위/단일 + 한글 + 알파벳) — 전부 문자열로
            dongs = set()
            for a, b in DONG_RANGE.findall(txt):
                a, b = int(a), int(b)
                if 0 < b - a < 40:
                    dongs.update(str(x) for x in range(a, b + 1))
            dongs.update(DONG_TOK.findall(txt))
            dongs.update(DONG_KOR.findall(txt))
            dongs.update(DONG_ALPHA.findall(txt))
            # 호범위/메모는 숫자 동만(한글·알파벳 동은 호 표기 거의 없음)
            ho = {d: (h or "").strip(" ·~-") for d, h in HO_AFTER.findall(txt)}
            for d in sorted(dongs):
                items.append({"apt": name, "n": norm(name), "동": d,
                              "code": code, "dong": dong, "통": tong, "반": ban,
                              "호": ho.get(d, "")})

    # 같은 (동명코드,아파트,동,통,반) 중복 정리
    seen, uniq = set(), []
    for it in items:
        k = (it["code"], it["n"], it["동"], it["통"], it["반"], it["호"])
        if k in seen:
            continue
        seen.add(k); uniq.append(it)
    json.dump({"list": uniq}, open("out/apartment_index.json", "w", encoding="utf-8"),
              ensure_ascii=False)
    names = {it["n"] for it in uniq}
    size = os.path.getsize("out/apartment_index.json")
    print(f"아파트 동 인덱스 {len(uniq)}건 · 아파트명 {len(names)}종 → out/apartment_index.json ({size//1024}KB)")


if __name__ == "__main__":
    main()
