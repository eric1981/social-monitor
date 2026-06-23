#!/usr/bin/env python3
"""
Social Monitor — modular API service.
Serves API on localhost:5408 + static frontend files.
Refactored from monolith server.py (~1250 lines).
"""
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

import config
from db import migrate, MONITOR_DIR, FRONTEND_DIR

# Import all handler modules (side-effect: registers them in HANDLERS)
from api import accounts, groups, keywords, config as cfg_handler
from api import collect, relogin, health, data

HANDLER_MODULES = [accounts, groups, keywords, cfg_handler, collect, relogin, health, data]


# ── Proxy image helper ──
from utils import is_safe_image_url


def serve_proxy_image(handler, parsed):
    """Handle /proxy/image — proxy external images through the server."""
    if not parsed.path.startswith("/proxy/image"):
        return False
    from urllib.parse import parse_qs

    qs = parse_qs(parsed.query)
    url = qs.get("url", [""])[0]
    if not url:
        handler.send_error(400, "Missing url")
        return True
    if not is_safe_image_url(url):
        handler.send_error(403, "Blocked: domain not allowed")
        return True
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Referer": config.image_proxy_referer(),
                "User-Agent": config.image_proxy_user_agent(),
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Sec-Fetch-Dest": "image",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Site": "cross-site",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            ct = resp.headers.get("Content-Type", "image/jpeg")
        handler.send_response(200)
        handler.send_header("Content-Type", ct)
        handler.send_header(
            "Cache-Control", f"public, max-age={config.image_proxy_cache_max_age()}"
        )
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        handler.wfile.write(data)
    except Exception:
        placeholder = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n\xe2\xe2\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        handler.send_response(200)
        handler.send_header("Content-Type", "image/png")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        handler.wfile.write(placeholder)
    return True


def serve_static(handler, parsed):
    """Serve static files from frontend/ directory."""
    filepath = FRONTEND_DIR / parsed.path.lstrip("/")
    if not filepath.exists() or not filepath.is_file():
        filepath = FRONTEND_DIR / "index.html"

    ct_map = {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript",
        ".css": "text/css",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".svg": "image/svg+xml",
    }
    ct = ct_map.get(filepath.suffix, "application/octet-stream")
    handler.send_response(200)
    handler.send_header("Content-Type", ct)
    handler.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    with open(str(filepath), "rb") as f:
        handler.wfile.write(f.read())
    return True


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        # Attach parsed for reuse in handlers that need query params
        self.parsed_path = parsed

        # Try proxy/image first (not an API endpoint)
        try:
            if serve_proxy_image(self, parsed):
                return
        except Exception as e:
            self._error_response(str(e))
            return

        # Try each API handler module
        for mod in HANDLER_MODULES:
            try:
                if mod.handle(self, "GET", parsed.path):
                    return
            except Exception as e:
                self._error_response(str(e))
                return

        # Fallback: static files
        try:
            serve_static(self, parsed)
        except Exception as e:
            self._error_response(str(e))

    def do_POST(self):
        parsed = urlparse(self.path)
        self.parsed_path = parsed

        for mod in HANDLER_MODULES:
            try:
                if mod.handle(self, "POST", parsed.path):
                    return
            except Exception as e:
                self._error_response(str(e))
                return

        # Not handled
        self._json_response({"error": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass

    def _json_response(self, data, status=200):
        import json

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _error_response(self, message):
        self._json_response({"error": message}, 500)


if __name__ == "__main__":
    migrate()
    port = config.server_port()
    print(f"📡 Social Monitor API — http://localhost:{port}")
    print(f"   前端页面: http://localhost:{port}")
    print(f"   API接口:  http://localhost:{port}/api/data")
    print(f"   新增账号: POST http://localhost:{port}/api/login")
    print()

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已停止")
        server.server_close()
