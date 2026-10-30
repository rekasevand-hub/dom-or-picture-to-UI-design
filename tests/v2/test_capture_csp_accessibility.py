from __future__ import annotations

import http.server
import threading
from dataclasses import replace
from pathlib import Path

from src.app.services.structure.capture import capture_page
from src.config.settings import Config


class _CspHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        paragraphs = "".join(
            f"<p>Visible CSP content paragraph {index}</p>"
            for index in range(30)
        )
        body = (
            "<!doctype html><html><body><main>"
            f"{paragraphs}</main></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'",
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def test_csp_style_injection_failure_does_not_block_capture(tmp_path: Path):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CspHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        config = replace(
            Config(),
            playwright_headless=True,
            playwright_headed_fallback=False,
            playwright_viewport_width=800,
            playwright_viewport_height=600,
        )
        result = capture_page(
            url,
            config,
            str(tmp_path / "capture"),
            capture_attempts=1,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result["page_state"]["kind"] == "content"
    assert result["error"] is None
    assert (tmp_path / "capture" / "00_dom.json").is_file()
