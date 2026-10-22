# -*- coding: utf-8 -*-
"""把 Axure 8 发布的 HTML 目录用本地 HTTP 服务跑起来，再逐页整页截图。

用法：

    python scripts/axure_shoot_html.py --dir <发布目录> --out <输出目录> \
        --page 首页_home.html --page ___orders.html --page ___reports.html

为什么必须走 HTTP：Axure 8 的产物在 `file://` 下会被它自己的守卫页拦住
（细节见 `scripts/axure_serve_html.ps1` 的注释），所以截图前要先起一个静态服务。

页面名要用**发布出来的**文件名：中文页名会被 Axure 净化（`订单 Orders` ->
`___orders.html`，见 `归档文档 axure_rp8_format.md` §11.9）。

截图默认写成 `<out>/<前缀>_p<序号>.png`（前缀默认取发布目录名）。
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote


def serve(root: Path, port: int) -> socketserver.TCPServer:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(root))
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.5)
    return httpd


def shoot(root: Path, out: Path, pages, prefix, port, viewport, wait_ms) -> int:
    from playwright.sync_api import sync_playwright

    httpd = serve(root, port)
    shots = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for index, name in enumerate(pages, 1):
                page = browser.new_page(viewport=viewport)
                url = "http://127.0.0.1:%d/%s" % (port, quote(name))
                page.goto(url, wait_until="load")
                page.wait_for_timeout(wait_ms)
                path = out / ("%s_p%d.png" % (prefix, index))
                page.screenshot(path=str(path), full_page=True)
                print("shot %s  title=%r" % (path, page.title()))
                shots.append(path)
                page.close()
            browser.close()
    finally:
        httpd.shutdown()
    print("RESULT=OK shots=%d" % len(shots))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Axure 8 发布产物逐页截图（本地 HTTP + Playwright）")
    parser.add_argument("--dir", required=True, help="Axure 发布出来的 HTML 目录")
    parser.add_argument("--out", default="", help="截图输出目录（默认 = --dir 的父目录下 shots）")
    parser.add_argument("--page", action="append", default=[],
                        help="要截的页面文件名（发布出来的名字，可重复；默认 index.html）")
    parser.add_argument("--prefix", default="", help="截图文件前缀（默认取发布目录名）")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--width", type=int, default=1500)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--wait-ms", type=int, default=1500)
    args = parser.parse_args(argv)

    root = Path(args.dir).expanduser().resolve()
    if not root.is_dir():
        print("RESULT=NO_DIR dir=%s" % root)
        return 1
    pages = args.page or ["index.html"]
    missing = [name for name in pages if not (root / name).is_file()]
    if missing:
        print("RESULT=NO_PAGE %s" % missing)
        return 1
    out = Path(args.out).expanduser().resolve() if args.out else root.parent / "shots"
    out.mkdir(parents=True, exist_ok=True)
    return shoot(root, out, pages,
                 args.prefix or root.name, args.port,
                 {"width": args.width, "height": args.height}, args.wait_ms)


if __name__ == "__main__":
    sys.exit(main())
