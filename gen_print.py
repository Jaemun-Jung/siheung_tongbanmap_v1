#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
7단계 고해상도 출력 — 보고/게시용 PDF(벡터)·PNG(300DPI).
화면(Leaflet)과 분리된 matplotlib 렌더링. 제목·범례·방위표·축척바·작성일 자동 포함.

사용:
  python gen_print.py --dong 31150680 [--palette pastel] [--paper A4] [--orient landscape]
                      [--boundary clean|parcel] [--select 3,5,12] [--dpi 300] [--date 2026-06-20]
  python gen_print.py --export print_settings.json   (셸 '출력 설정 내보내기' 파일)
출력: out/{code}/{동}_print.pdf, _print.png
"""
import argparse, colorsys, json, os, glob
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams
from matplotlib.patches import FancyArrow

# 한글 폰트(맑은 고딕)
for cand in ["Malgun Gothic", "맑은 고딕", "NanumGothic", "AppleGothic"]:
    if any(cand.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
        rcParams["font.family"] = cand; break
rcParams["axes.unicode_minus"] = False

PAPER = {"A4": (297, 210), "A3": (420, 297)}   # mm, 가로 기준
NCOL = 12                                            # 색 슬롯 수(인접 통은 다른 슬롯, assign_tong_colors.py)
PALETTES = {
    "default": lambda s: colorsys.hls_to_rgb(((s*360/NCOL) % 360)/360, 0.55, 0.65),
    "pastel":  lambda s: colorsys.hls_to_rgb(((s*360/NCOL) % 360)/360, 0.78, 0.48),
    "vivid":   lambda s: colorsys.hls_to_rgb(((s*360/NCOL) % 360)/360, 0.48, 0.85),
    "gray":    lambda s: colorsys.hls_to_rgb(0, (35 + (s*53) % 50)/100, 0),
}

def tong_color(slot, palette, overrides, code, t):
    o = overrides.get(f"{code}:{t}")
    if o:
        return o
    return PALETTES.get(palette, PALETTES["default"])(int(slot))

def find_dong(code):
    for cfgp in glob.glob("data/3*/config.json"):
        cfg = json.load(open(cfgp, encoding="utf-8"))
        if cfg["admin_code"] == code:
            return cfg["admin_dong"]
    return None

def scalebar(ax, x0, y0, length_m):
    ax.plot([x0, x0+length_m], [y0, y0], color="black", lw=2, solid_capstyle="butt")
    for x in (x0, x0+length_m):
        ax.plot([x, x], [y0, y0+length_m*0.05], color="black", lw=2)
    lab = f"{int(length_m)} m" if length_m < 1000 else f"{length_m/1000:g} km"
    ax.text(x0+length_m/2, y0+length_m*0.07, lab, ha="center", va="bottom", fontsize=9)

def render(code, dong, palette, paper, orient, boundary, select, dpi, date, overrides,
           line_w, fill_a):
    # 통 단위 dissolve 면(_tong.geojson) — 시행규칙 별표 통 그대로, 개별 필지선 없이 깔끔(상황판·대형 출력용)
    src = f"out/{code}/{dong}_tong.geojson"
    tong = gpd.read_file(src).to_crs("EPSG:5186")
    admin = gpd.read_file(f"out/{code}/{dong}_admin.geojson").to_crs("EPSG:5186")
    w_mm, h_mm = PAPER.get(paper, PAPER["A4"])
    if orient == "portrait":
        w_mm, h_mm = h_mm, w_mm
    fig = plt.figure(figsize=(w_mm/25.4, h_mm/25.4))
    ax = fig.add_axes([0.03, 0.03, 0.94, 0.88])
    ax.set_aspect("equal"); ax.axis("off")

    sel = set(int(s) for s in select) if select else set()
    for _, r in tong.iterrows():
        t = int(r["통"]); on = (not sel) or (t in sel); dim = bool(sel) and (t not in sel)
        slot = int(r["cidx"]) if "cidx" in tong.columns and r["cidx"] is not None else t
        gpd.GeoSeries([r.geometry]).plot(ax=ax, facecolor=tong_color(slot, palette, overrides, code, t),
            edgecolor="#333", linewidth=(line_w+1.2) if (sel and t in sel) else line_w,
            alpha=0.25 if dim else fill_a)
    admin.boundary.plot(ax=ax, color="black", linewidth=2.2)
    # 통 번호
    for _, r in tong.iterrows():
        t = int(r["통"]); dim = bool(sel) and (t not in sel)
        p = r.geometry.representative_point()
        ax.text(p.x, p.y, str(t), ha="center", va="center", fontsize=8, fontweight="bold",
                color="#111", alpha=0.3 if dim else 1,
                bbox=dict(boxstyle="circle,pad=0.18", fc="white", ec="#333", lw=0.8, alpha=0.85))

    # 제목 / 작성일
    fig.text(0.04, 0.955, f"시흥시 {dong} 통·반 경계도", fontsize=20, fontweight="bold")
    sub = "통 단위 경계(시행규칙 별표 기준)"
    fig.text(0.04, 0.925, sub, fontsize=11, color="#555")
    fig.text(0.97, 0.955, f"작성일 {date}", fontsize=10, color="#555", ha="right")
    fig.text(0.97, 0.935, "자료: 시행규칙 별표 + 연속지적도 + OSM", fontsize=8, color="#888", ha="right")

    # 방위표(N) + 축척바 — 지도 우하/좌하
    xmin, ymin, xmax, ymax = tong.total_bounds
    span = xmax - xmin
    nx, ny = xmax - span*0.05, ymin + (ymax-ymin)*0.13
    ax.add_patch(FancyArrow(nx, ny, 0, (ymax-ymin)*0.07, width=span*0.004,
                 head_width=span*0.016, head_length=(ymax-ymin)*0.02, color="black"))
    ax.text(nx, ny + (ymax-ymin)*0.10, "N", ha="center", va="bottom", fontsize=12, fontweight="bold")
    # 축척바 길이: 지도폭의 약 1/4를 깔끔한 값으로
    raw = span/4
    nice = min([50,100,200,300,500,1000,2000,3000,5000], key=lambda v: abs(v-raw))
    scalebar(ax, xmin + span*0.04, ymin + (ymax-ymin)*0.04, nice)
    if sel:
        fig.text(0.04, 0.90, f"강조: {', '.join(map(str, sorted(sel)))}통", fontsize=10, color="#1769aa")

    base = f"out/{code}/{dong}_print"
    fig.savefig(base + ".pdf", bbox_inches="tight")
    fig.savefig(base + ".png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"✔ {dong}: {base}.pdf / .png ({dpi}DPI, {paper} {orient}, 경계 {boundary}, 통 {len(tong)})")
    return base

def main():
    ap = argparse.ArgumentParser(description="고해상도 통반경계도 출력")
    ap.add_argument("--export", help="셸 출력설정 JSON")
    ap.add_argument("--dong", help="행정동코드(admin_code)")
    ap.add_argument("--palette", default="default", choices=list(PALETTES))
    ap.add_argument("--paper", default="A4", choices=list(PAPER))
    ap.add_argument("--orient", default="landscape", choices=["landscape", "portrait"])
    ap.add_argument("--boundary", default="clean", choices=["clean", "parcel"])
    ap.add_argument("--select", default="")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--date", default="")
    ap.add_argument("--open", action="store_true", help="생성 후 PDF 자동 열기")
    args = ap.parse_args()

    s = {}
    if args.export:
        s = json.load(open(args.export, encoding="utf-8"))
    code = s.get("code") or args.dong
    if not code:
        raise SystemExit("--dong 또는 --export 필요")
    dong = s.get("dong") or find_dong(code)
    select = s.get("select") or ([x for x in args.select.split(",") if x.strip()])
    date = args.date or s.get("date") or "____-__-__"
    base = render(code, dong,
           s.get("palette", args.palette), s.get("paper", args.paper),
           s.get("orient", args.orient), s.get("boundaryMode", args.boundary),
           select, args.dpi, date, s.get("tongColors", {}),
           float(s.get("lineWeight", 3)) * 0.4 if s else 1.2,   # 화면 두께→인쇄용 축소
           float(s.get("fillAlpha", 0.45)) if s else 0.55)
    if args.open:
        try:
            os.startfile(os.path.abspath(base + ".pdf"))   # Windows: 기본 PDF 뷰어로 열기
        except Exception as e:
            print("PDF 열기 실패(수동으로 여세요):", e)

if __name__ == "__main__":
    main()
