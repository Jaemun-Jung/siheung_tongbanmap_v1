@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 시흥시 통반경계도 출력

set "JSON=print_settings.json"

rem 다운로드 폴더에 새 설정이 있으면 가져오기(최신 우선)
if exist "%USERPROFILE%\Downloads\print_settings.json" (
  copy /Y "%USERPROFILE%\Downloads\print_settings.json" "%JSON%" >nul
)

if not exist "%JSON%" (
  echo.
  echo  [!] print_settings.json 을 찾을 수 없습니다.
  echo      지도 화면에서 "출력 설정 내보내기"를 먼저 누른 뒤 다시 실행하세요.
  echo.
  pause
  exit /b 1
)

echo.
echo  출력 생성 중... (잠시만 기다리세요)
echo.
".venv\Scripts\python.exe" gen_print.py --export "%JSON%" --open

if errorlevel 1 (
  echo.
  echo  [!] 출력에 실패했습니다. 위 메시지를 확인하세요.
  pause
  exit /b 1
)

echo.
echo  완료! PDF가 열립니다. (out 폴더에 PDF/PNG 저장됨)
timeout /t 3 >nul
