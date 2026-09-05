# -*- coding: utf-8 -*-
"""Playwright 抓取：同一次会话产出截图 + DOM JSON，dsf=1 保证坐标对齐。"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.config import Config

logger = logging.getLogger(__name__)

LOGIN_PROMPT = (
    "\n请在已打开的浏览器窗口里完成登录，进入目标页面后回到这里按回车，"
    "我会把登录态（cookie / localStorage）保存到 JSON 文件。\n> "
)

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
      title: el.getAttribute('title') || '',
      text: hasText ? (el.textContent || '').trim().slice(0, 200) : '',
      x: Math.round(r.x), y: Math.round(r.y),
      w: Math.round(r.width), h: Math.round(r.height),
      bg: cs.backgroundColor, pageBg: pageBg,
      color: cs.color, fontSize: cs.fontSize, fontWeight: cs.fontWeight,
      borderRadius: cs.borderRadius,
      borderColor: cs.borderColor, borderWidth: cs.borderWidth,
      position: cs.position, zIndex: parseInt(cs.zIndex, 10) || 0,
      interactive: /^(A|BUTTON|INPUT|SELECT|TEXTAREA)$/.test(el.tagName)
    });
  }
  return out;
}
"""

def _resolve_storage_state(path_value: str | None) -> str | None:
    """校验 Playwright storageState JSON；文件缺失时提前报错，避免启动浏览器后才发现。"""
    if not path_value:
        return None
    p = Path(path_value)
    if not p.is_file():
        raise ValueError(
            f"storage_state 文件不存在: {p}（请先运行 --login-state 导出登录态，"
            "或用 PLAYWRIGHT_STORAGE_STATE 指向已导出的 JSON）"
        )
    return str(p)


def _page_has_password_input(page) -> bool:
    try:
        return bool(page.evaluate("document.querySelectorAll('input[type=password]').length"))
    except Exception:
        return False


def export_login_state(url: str, output_path: str, cfg: "Config",
                       *, headless: bool = False, ask=None) -> str:
    """打开（默认有头）浏览器让用户登录，回车后把登录态导出为 Playwright storageState JSON。"""
    if ask is None:
        ask = input
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page(
                viewport={"width": cfg.playwright_viewport_width,
                          "height": cfg.playwright_viewport_height},
                device_scale_factor=cfg.device_scale_factor)
            page.goto(url, wait_until="domcontentloaded",
                      timeout=cfg.wait_networkidle_timeout)
            page.wait_for_timeout(1000)  # 给 SPA 首屏/跳转一点时间
            ask(LOGIN_PROMPT)
            page.wait_for_timeout(500)
            page.context.storage_state(path=str(out))
        finally:
            browser.close()
    state = json.loads(out.read_text(encoding="utf-8"))
    cookies = state.get("cookies") or []
    origins = state.get("origins") or []
    domains = sorted({c.get("domain", "") for c in cookies if c.get("domain")})
    logger.info("已保存登录态 %s：cookies=%d, localStorage origins=%d",
                out, len(cookies), len(origins))
    if domains:
        logger.info("cookie 域：%s", ", ".join(domains))
    if not cookies and not origins:
        logger.warning("导出内容为空：可能尚未真正登录成功，请重跑 --login-state 并在登录后再回车")
    return str(out)


def capture_page(url: str, cfg: "Config", output_dir: str) -> dict:
    from playwright.sync_api import sync_playwright
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    image_p = out / "00_screenshot.png"
    dom_p = out / "00_dom.json"
    storage_state = _resolve_storage_state(cfg.playwright_storage_state)
    context_opts = {}
    if storage_state:
        context_opts["storage_state"] = storage_state
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=cfg.playwright_headless)
        try:
            page = browser.new_page(viewport={"width": cfg.playwright_viewport_width,
                                              "height": cfg.playwright_viewport_height},
                                    device_scale_factor=cfg.device_scale_factor,
                                    **context_opts)
            page.goto(url, wait_until="networkidle", timeout=cfg.wait_networkidle_timeout)
            page.add_style_tag(content="*,*::before,*::after{transition:none!important;animation:none!important}")
            page.wait_for_timeout(500)
            if _page_has_password_input(page):
                logger.warning("检测到密码输入框：当前页面疑似仍停在登录页，storage_state 可能无效或已过期")
            # 整页截图：DOM_JS 坐标为整文档几何，画布必须覆盖整页
            # （否则视口以下区域的 bbox 会落在截图画布之外，SoM 框在图上消失）。
            page.screenshot(path=str(image_p), full_page=True)
            nodes = page.evaluate(DOM_JS)
            dom_p.write_text(json.dumps(nodes, ensure_ascii=False), encoding="utf-8")
        finally:
            browser.close()
    from PIL import Image
    with Image.open(image_p) as im:
        w, h = im.size
    return {"image": str(image_p), "width": w, "height": h, "dom": str(dom_p)}
