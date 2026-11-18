"""Ollama 앞의 공유 토큰 검사 프록시(2026-11-18, 문제 기록 69번: Vercel 데모 → Mac mini Ollama).

외부(Tailscale Funnel) → 이 프록시(127.0.0.1) → Ollama(127.0.0.1). 표준 라이브러리만 쓴다.
- `Authorization: Bearer <토큰>`이 맞을 때만 넘긴다(상수 시간 비교). 틀리면 401.
- 앱이 쓰는 길만 연다: POST /api/chat, POST /api/embed, GET /api/tags. 나머지(모델 받기·지우기 등)는 403.
- 요청 본문은 2MB까지.

환경 변수: OLLAMA_TOKEN 또는 JEJU_GATE_TOKEN_FILE(토큰 파일 경로), JEJU_GATE_PORT(기본 11500), JEJU_GATE_UPSTREAM(기본 http://127.0.0.1:11436).
"""
import hmac
import http.client
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ALLOW = {("POST", "/api/chat"), ("POST", "/api/embed"), ("GET", "/api/tags")}
MAX_BODY = 2 * 1024 * 1024


def _token():
    t = os.environ.get("OLLAMA_TOKEN", "")
    f = os.environ.get("JEJU_GATE_TOKEN_FILE")
    if not t and f:
        with open(os.path.expanduser(f), encoding="utf-8") as fh:
            t = fh.read().strip()
    if len(t) < 24:
        sys.exit("토큰이 없거나 24자보다 짧습니다(OLLAMA_TOKEN 또는 JEJU_GATE_TOKEN_FILE).")
    return t


TOKEN = None
UP = urlsplit(os.environ.get("JEJU_GATE_UPSTREAM", "http://127.0.0.1:11436"))


class Gate(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _deny(self, code, msg):
        body = msg.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")  # 읽지 않은 요청 본문이 다음 요청으로 읽히지 않게 연결을 닫는다
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _handle(self):
        path = self.path.split("?", 1)[0]
        got = self.headers.get("Authorization", "")
        if not hmac.compare_digest(got.encode(), ("Bearer " + TOKEN).encode()):
            return self._deny(401, "unauthorized")
        if (self.command, path) not in ALLOW:
            return self._deny(403, "forbidden")
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self._deny(413, "too large")
        body = self.rfile.read(n) if n else None
        conn = http.client.HTTPConnection(UP.hostname, UP.port, timeout=300)
        try:
            conn.request(self.command, path, body, {"Content-Type": "application/json"})
            r = conn.getresponse()
            data = r.read()
        except OSError:
            return self._deny(502, "upstream unavailable")
        finally:
            conn.close()
        self.send_response(r.status)
        self.send_header("Content-Type", r.getheader("Content-Type", "application/json"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = _handle

    def do_PUT(self):
        self._deny(403, "forbidden")

    do_DELETE = do_PATCH = do_HEAD = do_PUT

    def log_message(self, fmt, *args):  # 본문·머리글(토큰)은 남기지 않는다
        sys.stderr.write("%s %s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), self.address_string(), fmt % args))


def main():
    global TOKEN
    TOKEN = _token()
    port = int(os.environ.get("JEJU_GATE_PORT", "11500"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Gate)
    sys.stderr.write(f"ollama_gate 127.0.0.1:{port} → {UP.geturl()}\n")
    srv.serve_forever()


if __name__ == "__main__":
    main()
