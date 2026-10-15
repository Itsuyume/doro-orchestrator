from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import socket
from socketserver import BaseServer
import time
from urllib.parse import urlsplit

from doro.application.status import status_view
from doro.domain.models import Config, DoroError
from doro.infrastructure.storage import LocalStore

ASSETS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
          "/style.css": ("style.css", "text/css")}
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'"


class ProgressHandler(BaseHTTPRequestHandler):
    def __init__(self, request: socket.socket, client_address: tuple[str, int], server: BaseServer, *,
                 config: Config, store: LocalStore, session_id: str,
                 token: str, assets: Path, touched: list[float]) -> None:
        if not isinstance(server, HTTPServer):
            raise DoroError("Progress view requires the loopback HTTP server")
        self.http_server = server
        self.config = config
        self.store = store
        self.session_id = session_id
        self.token = token
        self.assets = assets
        self.touched = touched
        request.settimeout(5)
        super().__init__(request, client_address, server)

    def log_message(self, format: str, *args: object) -> None:
        return  # The UI token and user text must never be written to access logs.

    def send_body(self, data: bytes, mime: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        expected = f"127.0.0.1:{self.http_server.server_port}"
        if self.headers.get("Host") != expected:
            self.send_body(b"Invalid host", "text/plain", 403)
            return
        origin = self.headers.get("Origin")
        if origin is not None and origin != "http://" + expected:
            self.send_body(b"Cross-origin access refused", "text/plain", 403)
            return
        self.touched[0] = time.monotonic()
        path = urlsplit(self.path).path
        if path in ASSETS:
            filename, mime = ASSETS[path]
            self.send_body((self.assets / filename).read_bytes(), mime)
            return
        if path != "/api/status":
            self.send_body(b"Not found", "text/plain", 404)
            return
        if not secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + self.token):
            self.send_body(b"Unauthorized", "text/plain", 401)
            return
        state = status_view(self.config, self.store.load(self.session_id))
        self.send_body(json.dumps(state, ensure_ascii=False).encode(), "application/json")


def serve_progress(config: Config, store: LocalStore, session_id: str, assets: Path) -> None:
    store.load(session_id)  # Validate the exact selected session before binding any socket.
    token = secrets.token_urlsafe(24)
    touched = [time.monotonic()]
    handler = partial(ProgressHandler, config=config, store=store, session_id=session_id,
                      token=token, assets=assets, touched=touched)
    with HTTPServer(("127.0.0.1", 0), handler) as server:
        server.timeout = 1
        print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/#{token}",
                          "session_id": session_id, "read_only": True}), flush=True)
        while time.monotonic() - touched[0] < 180:
            server.handle_request()
