# -*- coding: utf-8 -*-
"""人工框选“权威像素区”：在截图上拖框，把直出规则搞不定的区域交给像素底。

直出规则只能覆盖 DOM 能描述的东西：图标字体（私有区码位）、图表、canvas、
第三方控件、贴图背景等一律画不出来。这里让用户直接在截图上框选，把这些区域
按原图像素裁下来当“最终像素”（与浮层像素底同一条路：渲染端最后落笔，被它完全
盖住的图元丢弃，见 direct_design._shadowed_by_backdrop）。

产出 `manual_crops.json`：
    {"image": "<截图>", "size": [w, h], "crops": [[x, y, w, h], ...]}
之后每次运行只要该文件在输出目录里就会自动重放——无头、可复现、可提交进版本库。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from src.app.utils.path_utils import file_uri

logger = logging.getLogger(__name__)

_PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>框选像素底</title>
<style>
  html, body { margin: 0; background: #1e1e1e; }
  #stage { position: relative; display: inline-block; margin: 0; }
  #shot { display: block; }
  #ink { position: absolute; left: 0; top: 0; cursor: crosshair; }
  #ref { position: absolute; left: 0; top: 0; opacity: 0; pointer-events: none; }
  #hint { position: fixed; left: 10px; top: 10px; z-index: 9; color: #fff;
          font: 13px/1.6 "Microsoft YaHei", sans-serif; background: rgba(0,0,0,.72);
          padding: 8px 12px; border-radius: 6px; max-width: 620px; }
  #hint b { color: #7dd3fc; }
</style></head>
<body>
<div id="hint">
  <b>拖拽框选</b>要按原图像素还原的区域（图标字体/图表/任意直出画不出的块）　
  <b>u</b>=撤销　<b>c</b>=清空　<b>d</b>=叠加当前直出稿对照　<b>Enter</b>=保存　<b>Esc</b>=取消
  <div id="cnt">已框选 0 块</div>
</div>
<div id="stage">
  <img id="shot" src="__SHOT__">
  <img id="ref" src="__REF__">
  <canvas id="ink"></canvas>
</div>
<script>
  const shot = document.getElementById('shot');
  const ref = document.getElementById('ref');
  const ink = document.getElementById('ink');
  const cnt = document.getElementById('cnt');
  let boxes = [], drag = null, showRef = false;

  function fit() {
    const w = shot.naturalWidth, h = shot.naturalHeight;
    ink.width = w; ink.height = h;
    ink.style.width = w + 'px'; ink.style.height = h + 'px';
    ref.style.display = '__REF__' ? 'block' : 'none';
    draw();
  }
  function draw() {
    const g = ink.getContext('2d');
    g.clearRect(0, 0, ink.width, ink.height);
    for (const b of boxes) {
      g.fillStyle = 'rgba(255, 0, 0, 0.18)';
      g.fillRect(b[0], b[1], b[2], b[3]);
      g.strokeStyle = '#ff3b30'; g.lineWidth = 2;
      g.strokeRect(b[0] + 0.5, b[1] + 0.5, b[2] - 1, b[3] - 1);
    }
    if (drag) {
      g.strokeStyle = '#ffd60a'; g.lineWidth = 2;
      g.strokeRect(drag[0] + 0.5, drag[1] + 0.5, drag[2] - 1, drag[3] - 1);
    }
    cnt.textContent = '已框选 ' + boxes.length + ' 块'
      + (drag ? '（正在拖 ' + drag[2] + 'x' + drag[3] + '）' : '');
  }
  function pos(ev) {
    const r = ink.getBoundingClientRect();
    return [Math.round(ev.clientX - r.left), Math.round(ev.clientY - r.top)];
  }
  function norm(a, b) {
    const x = Math.min(a[0], b[0]), y = Math.min(a[1], b[1]);
    return [x, y, Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1])];
  }
  ink.addEventListener('mousedown', (ev) => {
    if (ev.button !== 0) return;
    ev.preventDefault();
    drag = norm(pos(ev), pos(ev));
  });
  ink.addEventListener('mousemove', (ev) => {
    if (!drag) return;
    drag = norm([drag[0], drag[1]], pos(ev));
    draw();
  });
  window.addEventListener('mouseup', (ev) => {
    if (!drag) return;
    const b = norm([drag[0], drag[1]], pos(ev));
    drag = null;
    if (b[2] >= 4 && b[3] >= 4) boxes.push(b);
    draw();
  });
  ink.addEventListener('contextmenu', (ev) => { ev.preventDefault(); boxes.pop(); draw(); });
  window.addEventListener('keydown', (ev) => {
    if (ev.key === 'u' || ev.key === 'Backspace') { boxes.pop(); draw(); }
    else if (ev.key === 'c') { boxes = []; draw(); }
    else if (ev.key === 'd') { showRef = !showRef; ref.style.opacity = showRef ? '0.45' : '0'; }
    else if (ev.key === 'Enter') { window.__crops = boxes; }
    else if (ev.key === 'Escape') { window.__crops = []; }
  });
  shot.addEventListener('load', fit);
  window.__crops = null;
</script>
</body></html>
"""


def load_manual_crops(path: str | Path) -> list[list[int]]:
    """读 manual_crops.json 里的矩形列表；缺失/损坏返回空列表（不打断管线）。"""
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 手工文件坏了不该让整次运行失败
        logger.warning("manual_crops.json 解析失败，忽略：%s", exc)
        return []
    crops: list[list[int]] = []
    for rect in (data.get("crops") or []):
        try:
            x, y, w, h = (int(round(float(v))) for v in rect)
        except (TypeError, ValueError):
            continue
        if w >= 2 and h >= 2:
            crops.append([x, y, w, h])
    return crops


def pick_crops(image_path: str | Path, out_json: str | Path,
               *, render_path: str | Path | None = None) -> list[list[int]]:
    """打开框选窗口（有头 Chromium），回车保存到 out_json 并返回矩形列表。

    render_path 存在时可按 d 把它叠在截图上（半透明）——直接看出当前直出稿缺了什么。
    """
    from playwright.sync_api import sync_playwright

    image_path = Path(image_path)
    ref = Path(render_path) if render_path and Path(render_path).exists() else None
    html = (_PAGE.replace("__SHOT__", file_uri(image_path))
                 .replace("__REF__", file_uri(ref) if ref else file_uri(image_path)))
    tmp = Path(out_json).with_suffix(".pick.html")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(html, encoding="utf-8")

    from PIL import Image
    with Image.open(image_path) as im:
        w, h = im.size
    viewport = {"width": min(w + 24, 1600), "height": min(h + 24, 1040)}
    logger.info("框选窗口已打开：拖拽框选后按 Enter 保存（Esc 取消）")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport=viewport)
        page.goto(file_uri(tmp))
        page.wait_for_timeout(600)
        try:
            page.wait_for_function("() => window.__crops !== null", timeout=30 * 60 * 1000)
        finally:
            boxes = page.evaluate("() => window.__crops || []")
            browser.close()

    crops: list[list[int]] = []
    for b in boxes or []:
        x, y, bw, bh = (int(round(float(v))) for v in b)
        x, y = max(0, x), max(0, y)
        bw, bh = min(bw, w - x), min(bh, h - y)
        if bw >= 2 and bh >= 2:
            crops.append([x, y, bw, bh])
    Path(out_json).write_text(json.dumps(
        {"image": str(image_path), "size": [w, h], "crops": crops},
        ensure_ascii=False, indent=1), encoding="utf-8")
    logger.info("框选像素底 %d 块已写入 %s", len(crops), out_json)
    return crops
