#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
정적 파일 서버 — 항상 최신 확인(no-cache).

배포(빌드 갱신) 후 사용자가 강력 새로고침(Ctrl+Shift+R) 없이도 최신을 받게,
모든 응답에 'Cache-Control: no-cache'를 붙인다.
  - no-cache = 브라우저가 캐시는 두되 '매번 최신인지 서버에 확인'.
  - 안 바뀐 파일은 표준 조건부 요청으로 304(본문 없음) → 5MB 필지도 재다운로드 안 함.
멀티스레드 + 0.0.0.0 바인딩(클라우드 호환).

사용:
  로컬:   python server.py 8000        →  http://localhost:8000/
  Render: Start Command = python server.py $PORT   (Build Command = echo skip)
"""
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # 매번 최신인지 확인하게 함(배포 즉시 반영). 304 응답에도 그대로 붙음.
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):   # 접근 로그 소음 최소화
        pass


def main():
    # 포트: Start Command 인자(예: $PORT) → 환경변수 PORT → 8000 순
    port = 8000
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    elif os.environ.get("PORT", "").isdigit():
        port = int(os.environ["PORT"])
    # server.py 가 있는 폴더(=index.html 위치)를 항상 서빙(실행 위치 무관)
    root = os.path.dirname(os.path.abspath(__file__))
    handler = partial(NoCacheHandler, directory=root)
    httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"Serving (no-cache) {root} on 0.0.0.0:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
