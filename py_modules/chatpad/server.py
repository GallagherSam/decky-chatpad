"""Tiny stdlib HTTP server serving the phone page and the token-protected API."""

from __future__ import annotations

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlparse

from .core import ChatpadCore

MAX_BODY = 8 * 1024
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
TOKEN_HEADER = "X-Chatpad-Token"

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                               "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'",
}


def make_handler(core: ChatpadCore, log: logging.Logger, page_path: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Chatpad/1"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # route to plugin log, never log tokens
            log.debug("http %s %s", self.client_address[0], fmt % args)

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in SECURITY_HEADERS.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

        def _auth(self) -> bool:
            err = core.authorize(self.headers.get(TOKEN_HEADER), self.client_address[0])
            if err:
                self._json(*err)
                return False
            return True

        def _body(self) -> Optional[dict]:
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                self._json(413, {"ok": False, "error": "Request too large"})
                self.close_connection = True
                return None
            raw = self.rfile.read(n) if n else b""
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                self._json(400, {"ok": False, "error": "Invalid JSON"})
                return None
            if not isinstance(data, dict):
                self._json(400, {"ok": False, "error": "Expected a JSON object"})
                return None
            return data

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                try:
                    with open(page_path, "rb") as f:
                        page = f.read()
                except OSError:
                    self._json(500, {"ok": False, "error": "page missing"})
                    return
                self._send(200, page, "text/html; charset=utf-8")
            elif path == "/healthz":
                self._json(200, {"ok": True})
            elif path == "/api/state":
                if self._auth():
                    self._json(200, core.public_state())
            else:
                self._json(404, {"ok": False, "error": "Not found"})

        do_HEAD = do_GET

        def do_POST(self):
            path = urlparse(self.path).path
            if path not in ("/api/send", "/api/list"):
                self._json(404, {"ok": False, "error": "Not found"})
                return
            # Read the body first so keep-alive stays in sync, then authenticate.
            data = self._body()
            if data is None:
                return
            if not self._auth():
                return
            if path == "/api/send":
                code, obj = core.send(data.get("text"), data.get("enter", True))
                if code == 200:
                    log.info("typed %d chars (replaced %d)", len(obj["typed"]), obj["replaced"])
                elif code == 503:
                    log.error("send failed: %s", obj.get("error"))
                self._json(code, obj)
            else:
                self._json(*core.edit_list(data.get("kind"), data.get("action"), data.get("item")))

    return Handler


class ChatpadServer:
    def __init__(self, core: ChatpadCore, log: Optional[logging.Logger] = None,
                 page_path: str = os.path.join(WEB_DIR, "index.html")) -> None:
        self.core = core
        self.log = log or logging.getLogger("chatpad")
        self.page_path = page_path
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self.httpd is not None

    @property
    def port(self) -> Optional[int]:
        return self.httpd.server_address[1] if self.httpd else None

    def start(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        if self.httpd:
            return
        httpd = ThreadingHTTPServer((host, port), make_handler(self.core, self.log, self.page_path))
        httpd.daemon_threads = True
        self.httpd = httpd
        self.thread = threading.Thread(target=httpd.serve_forever, name="chatpad-http", daemon=True)
        self.thread.start()
        self.log.info("Chatpad HTTP server on %s:%d", host, self.port)

    def stop(self) -> None:
        httpd, self.httpd = self.httpd, None
        if not httpd:
            return
        httpd.shutdown()
        httpd.server_close()
        if self.thread:
            self.thread.join(timeout=2)
        self.thread = None
        self.log.info("Chatpad HTTP server stopped")
