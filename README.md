# 시흥시 통·반 조회 지도 (v1)

시흥시 **20개 행정동 전체**의 통·반 경계를 한 곳에서 조회하는 인터랙티브 웹 지도입니다.
시행규칙 [별표]의 통·반 관할구역(지번)과 연속지적도를 합쳐, **같은 통에 속한 필지를 병합**해
통 경계를 자동으로 그립니다. 사람이 선을 긋는 게 아니라 데이터로 경계가 만들어집니다.

> 한 장짜리 셸(`index.html`)이 `out/`의 동별 GeoJSON을 그때그때 불러오는 구조라,
> 20개 동을 가볍게 오가며 볼 수 있습니다.

**▶ 일반 사용자(직원)용 사용법은 [`사용안내.md`](사용안내.md)에 따로 정리했습니다.** (이 README는 개발·데이터 재생성용)

## 주요 기능

- **행정동 선택 / 전체지도** — 시 전체 통 경계 + 동 라벨에서 동을 클릭해 상세로 진입
- **검색 3종** — 지번(`신천동 771-5`), 도로명(`신천로 82`, juso 변환), 아파트 이름+동(`동보아파트 104동`)
  - 검색 결과 위치에 **빨간 핀 + 통·반 팝업** 표시
- **통·반 조회** — 통 선택, 다중 통 강조, 통 번호 라벨, 인접 통 자동 색 구분(지도 4색)
- **통 경계 직접 그리기** — 시행규칙엔 있으나 지적도로 자동 분할이 안 되는 통(아파트 동별 분할 등)을
  지도에서 직접 그려 이 브라우저에 저장(검토용)
- **영역 인쇄** — 지도에서 사각형을 드래그해 **선택한 영역 그대로** **A4 / B4 / A3 / A1(전지)** 로 인쇄·PDF 저장
  (사각형은 용지 비율로 고정 → 화면=출력 일치). 제목 표시 on/off(회의실 상황판은 off). 통 경계·번호는 벡터라 확대해도 선명
- **배경지도 전환** — 일반(OpenStreetMap, 기본) / 위성(브이월드 항공영상 + 한글 지명).
  위성은 배포 도메인에서 표시되며, 위성 배경에선 시 경계선이 자동으로 밝은 색(황색)으로 바뀜
- **담당자 검토 모드** — `?admin=1` 로 접속 시 미배정·검증 경고 표시

## 로컬에서 실행

`file://` 직접 열기는 브라우저 보안(CORS)으로 GeoJSON을 못 불러옵니다. **반드시 로컬 서버**로 여세요.

```bash
# 저장소 루트에서
python -m http.server 8000
# 브라우저에서 http://localhost:8000/ 접속
```

도로명 검색을 쓰려면 `index.html` 상단의 `JUSO_KEY`(juso.go.kr 개발키)가 필요합니다.
클라이언트(브라우저)에서 동작하는 도로명주소 검색용 무료 개발키입니다.

## 데이터 파이프라인 (재생성)

원본이 바뀌었을 때(시행규칙 별표 개정, 연속지적도 갱신)만 다시 돌리면 됩니다.

```bash
pip install -r requirements.txt        # geopandas/shapely/pyogrio/pyproj 등 (GDAL 포함)

python build_tongban_map.py            # 별표 전개 → 지적도 조인 → 통 병합 → 동별 산출
python clean_tong.py                   # 통 폴리곤 내부 구멍·잔선 정리
python split_apartments.py             # 한 지번을 아파트 동별로 나눈 통 분할(예: 군자동 동보 23/24통)
python assign_tong_colors.py           # 인접 통이 다른 색이 되도록 색 슬롯 배정(_tong.geojson에 cidx)
python gen_manifest.py                 # out/manifest.json (동 목록·중심·범위)
python gen_overview.py                 # 전체지도용 통합 GeoJSON(all_tong/all_admin/city_boundary)
python gen_address_index.py            # 지번 → 통·반 검색 인덱스
python gen_apartment_index.py          # 아파트 이름+동 → 통·반 검색 인덱스
python gen_issues.py                   # 검증 경고(통과 떨어진 필지 등)
python gen_unassigned.py               # 미배정 대지 데이터
python verify_tongban.py               # 별표 ↔ 산출물 정합성 검증
```

> Windows 콘솔에서 한글이 깨지면 `PYTHONUTF8=1 PYTHONIOENCODING=utf-8` 를 함께 주세요.
> 고해상도 벡터 PDF(제목·범례·축척바·방위표)가 필요하면 `python gen_print.py --dong <행정동코드>`.

## 디렉터리 구조

```
index.html                 # 웹 지도 셸(메인 진입점)
requirements.txt
build_tongban_map.py       # 핵심 파이프라인 (별표 파서 + 지적도 조인 + 통 병합)
clean_tong.py / split_apartments.py / assign_tong_colors.py
gen_manifest.py / gen_overview.py / gen_address_index.py / gen_apartment_index.py
gen_issues.py / gen_unassigned.py / gen_print.py / verify_tongban.py
scan_unassigned_anomalies.py        # "별표엔 있는데 미배정" 이상치 점검

data/{행정동코드}/
  config.json              # 동별 설정(행정동·법정동 코드, 도로보정 옵션 등)
  관할구역.csv             # 시행규칙 별표에서 추출한 통·반 표(입력)

out/{행정동코드}/
  {동}_tong.geojson        # 통 단위 경계(통별 색·번호)
  {동}_parcels.geojson     # 필지 단위(지번 검색용)
  {동}_admin.geojson       # 행정동 경계
out/overview/              # 전체지도용 통합본
out/manifest.json, out/address_index.json, out/apartment_index.json
```

## 데이터 출처

- **시흥시 통·반 설치 조례 시행규칙 [별표] — 통·반의 명칭 및 관할구역** (규칙 제1069호, 2026. 2. 26.) — 통·반 관할구역(지번). 상위 근거는 **시흥시 통·반 설치 조례**(제2135호, 2022. 5. 3.). `data/{코드}/관할구역.csv`로 추출 (자세한 근거는 `근거법규.md`)
- **연속지적도(SHP)** — 공공데이터포털(data.go.kr) / 국가공간정보포털 오픈마켓(market.nsdi.go.kr).
  용량이 커 저장소에는 포함하지 않습니다(`.gitignore`). 필지 경계의 원본
- **OpenStreetMap** — 배경지도 및 도로·건물 보조 데이터
- **행정안전부 행정동 경계** — 동 경계 폴리곤

## 참고·주의

- **추정 경계 표시** — 별표에 지번이 없거나 본번 범위로만 적혀 지적도와 안 맞는 구간은
  본번 폴백·도로 분할 등으로 보완한 **추정치**이며, 별표가 바뀌지 않는 한 임의로 통 배정을 고치지 않습니다
- **연속지적도 SHP는 추적되지 않습니다** — 위 출처에서 직접 받아 파이프라인을 돌리세요
- **JUSO_KEY는 클라이언트용 개발키**입니다. 배포 웹페이지에서도 보이는 키 종류이며, 운영 시 정식 키로 교체 권장
- `*_print.pdf/.png`, `print_settings.json`, `.venv/` 등 재생성 가능한 산출물은 `.gitignore` 처리
