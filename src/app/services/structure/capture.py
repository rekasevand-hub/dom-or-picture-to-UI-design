# -*- coding: utf-8 -*-
"""Playwright 抓取：同一次会话产出截图 + DOM JSON（+ CDP AX JSON），dsf=1 保证坐标对齐。"""
from __future__ import annotations
import json
from pathlib import Path
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.config import Config

DOM_JS = r"""
() => {
  const out = [];
  const pageBg = getComputedStyle(document.body).backgroundColor;
  for (const el of document.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const hasText = el.childElementCount === 0 && (el.textContent || '').trim().length > 0;
    out.push({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      ariaLabel: el.getAttribute('aria-label') || '',
      text: hasText ? (el.textContent || '').trim().slice(0, 200) : '',
      x: Math.round(r.x), y: Math.round(r.y),
      w: Math.round(r.width), h: Math.round(r.height),
      bg: cs.backgroundColor, pageBg: pageBg,
      color: cs.color, fontSize: cs.fontSize, fontWeight: cs.fontWeight,
      borderRadius: cs.borderRadius,
      interactive: /^(A|BUTTON|INPUT|SELECT|TEXTAREA)$/.test(el.tagName)
    });
  }
  return out;
}
"""

def _ax_bounds(props: list) -> list[int] | None:
    for p in props:
        if p.get("name") == "bounds":
            v = p.get("value", {}).get("value")
            if isinstance(v, dict):
                try:
                    return [round(v["x"]), round(v["y"]), round(v["width"]), round(v["height"])]
                except (KeyError, TypeError):
                    return None
    return None

def _inject_ax_bounds(client, nodes: list) -> None:
    """通过 DOM.getBoxModel 为可见 AX 节点补充 bounds 属性（无几何信息的节点保持原样）。"""
    for node in nodes:
        if node.get("ignored"):
            continue
        backend_id = node.get("backendDOMNodeId")
        if backend_id is None:
            continue
        try:
            box = client.send("DOM.getBoxModel", {"backendNodeId": backend_id})
        except Exception:
            continue
        model = (box or {}).get("model", {})
        content = model.get("content")
        if not isinstance(content, list) or len(content) < 8:
            continue
        xs = [float(v) for v in content[0::2]]
        ys = [float(v) for v in content[1::2]]
        try:
            if model.get("width") is not None:
                width = float(model["width"])
            else:
                width = max(xs) - min(xs)
            if model.get("height") is not None:
                height = float(model["height"])
            else:
                height = max(ys) - min(ys)
        except (TypeError, ValueError):
            continue
        x, y = round(min(xs)), round(min(ys))
        w, h = round(width), round(height)
        if w < 1 or h < 1:
            continue
        props = node.setdefault("properties", [])
        if not isinstance(props, list):
            props = node["properties"] = []
        props.append({"name": "bounds",
                      "value": {"value": {"x": x, "y": y, "width": w, "height": h}}})

def capture_page(url: str, cfg: "Config", output_dir: str) -> dict:
    from playwright.sync_api import sync_playwright
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    image_p = out / "00_screenshot.png"
    dom_p = out / "00_dom.json"
    ax_p = out / "00_ax.json"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=cfg.playwright_headless)
        try:
            page = browser.new_page(viewport={"width": cfg.playwright_viewport_width,
                                              "height": cfg.playwright_viewport_height},
                                    device_scale_factor=cfg.device_scale_factor)
            page.goto(url, wait_until="networkidle", timeout=cfg.wait_networkidle_timeout)
            page.add_style_tag(content="*,*::before,*::after{transition:none!important;animation:none!important}")
            page.wait_for_timeout(500)
            page.screenshot(path=str(image_p))
            nodes = page.evaluate(DOM_JS)
            dom_p.write_text(json.dumps(nodes, ensure_ascii=False), encoding="utf-8")
            client = page.context.new_cdp_session(page)
            tree = client.send("Accessibility.getFullAXTree")
            ax_nodes = tree.get("nodes", [])
            _inject_ax_bounds(client, ax_nodes)
            ax_p.write_text(json.dumps(ax_nodes, ensure_ascii=False), encoding="utf-8")
        finally:
            browser.close()
    from PIL import Image
    with Image.open(image_p) as im:
        w, h = im.size
    return {"image": str(image_p), "width": w, "height": h,
            "dom": str(dom_p), "ax": str(ax_p)}
