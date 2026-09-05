# -*- coding: utf-8 -*-
"""capture 模块离线测试（integration 需要网络/Chromium，默认跳过）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.app.services.structure.capture import DOM_JS


def test_dom_js_present():
    assert "getBoundingClientRect" in DOM_JS
    assert "position: cs.position" in DOM_JS
    assert "zIndex: parseInt(cs.zIndex" in DOM_JS

def test_storage_state_missing_file_raises(tmp_path):
    """storage_state 指向不存在文件时必须在启动浏览器前报错。"""
    from dataclasses import replace
    from src.config import load_config
    from src.app.services.structure.capture import capture_page

    cfg = replace(load_config(), playwright_storage_state=str(tmp_path / "no_such_state.json"))
    with pytest.raises(ValueError, match="storage_state"):
        capture_page("https://example.invalid", cfg, str(tmp_path))


@pytest.mark.integration
def test_capture_live(tmp_path):
    from src.config import load_config
    from src.app.services.structure.capture import capture_page
    r = capture_page("https://example.com", load_config(), str(tmp_path))
    assert r["image"] and r["dom"]


@pytest.mark.integration
def test_capture_full_page_tall_page(tmp_path):
    """整页截图：超视口高度的文档，折叠线下方的 DOM bbox 必须落在画布内。"""
    from dataclasses import replace
    from PIL import Image
    from src.config import load_config
    from src.app.services.structure.capture import capture_page

    cfg = replace(load_config(), playwright_viewport_width=800,
                  playwright_viewport_height=600, device_scale_factor=1)
    html = tmp_path / "tall.html"
    html.write_text(
        "<!doctype html><html><head><style>html,body{margin:0;padding:0}"
        "body{background:#ffffff}</style></head><body>"
        "<div style=\"height:2000px\"></div>"
        "<div style=\"width:80px;height:80px;background:#cc0000;margin:100px 0 0 0\">"
        "BELOWFOLD</div></body></html>",
        encoding="utf-8")
    r = capture_page(html.as_uri(), cfg, str(tmp_path))

    with Image.open(r["image"]) as im:
        png_w, png_h = im.size
    assert r["height"] == png_h
    assert r["height"] > cfg.playwright_viewport_height
    assert png_h > cfg.playwright_viewport_height

    dom = json.loads(Path(r["dom"]).read_text(encoding="utf-8"))
    markers = [n for n in dom if n.get("text", "").strip() == "BELOWFOLD"]
    assert len(markers) == 1
    y = markers[0]["y"]
    assert cfg.playwright_viewport_height < y < r["height"]


@pytest.mark.integration
def test_login_state_export_then_capture_reuse(tmp_path):
    """登录态导出 -> 复用：本地 HTTP 页面按 cookie 渲染标记，验证 storage_state 生效。"""
    import threading
    from dataclasses import replace
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from src.config import load_config
    from src.app.services.structure.capture import capture_page, export_login_state

    html = (
        "<!doctype html><html><body style='margin:0'><script>"
        "const m=document.createElement('div');m.id='marker';"
        "m.style.cssText='font-size:16px;width:300px;height:20px;';"
        "const c=(document.cookie.match(/pw=([^;]+)/)||[])[1];"
        "m.textContent='COOKIE='+(c||'none')+' LS='+(localStorage.getItem('auth')||'none');"
        "document.body.appendChild(m);"
        "</script></body></html>"
    ).encode("utf-8")

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Set-Cookie", "pw=ok123; Path=/")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        cfg = replace(load_config(), playwright_headless=True)
        state_file = tmp_path / "login_state.json"

        exported = export_login_state(url, str(state_file), cfg, headless=True, ask=lambda prompt: "")
        assert exported == str(state_file)
        assert state_file.is_file()
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert any(c.get("name") == "pw" for c in state.get("cookies", []))

        out_dir = tmp_path / "out"
        cfg2 = replace(cfg, playwright_storage_state=str(state_file))
        r = capture_page(url, cfg2, str(out_dir))
        dom = json.loads(Path(r["dom"]).read_text(encoding="utf-8"))
        markers = [n for n in dom if n.get("text", "").startswith("COOKIE=")]
        assert markers and markers[0]["text"] == "COOKIE=ok123 LS=none"
    finally:
        server.shutdown()
        server.server_close()
