# -*- coding: utf-8 -*-
"""R5-EXP-03: DOM / screenshot field-authority matrix.

The experiment renders eight authored browser scenes, records DOM facts,
computed styles, real Chromium screenshots, pixel samples and a small OCR
surface, then builds a field-level authority matrix. It deliberately keeps
source text, visible text, CSS color and composited pixel color as separate
observations.

The contract validator is also exercised with targeted negative mutations. The
experiment does not modify production code, connect to Figma, or claim that the
matrix is production-verified.

Usage:
  C:/Users/lzq/.conda/envs/omni/python.exe scripts/r5_exp_03_authority_matrix.py
  ... --out output/_r5_experiments/r5_exp_03_authority_matrix
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import os
import re
import shutil
import sys
import threading
from collections import Counter
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Callable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pytesseract  # noqa: E402
from PIL import Image, ImageDraw, ImageFont, ImageOps  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JOB = "JOB-R5-EXP-03-20261019"
REVISION = "rev1"
PROFILE = "r5-exp-03-authority-matrix"
CAPTURED_AT = "2026-10-19T00:00:00+00:00"
VIEWPORT = {"width": 1280, "height": 900}
DPR = 1

DEFAULT_OUT = ROOT / "output" / "_r5_experiments" / "r5_exp_03_authority_matrix"

SCENES = (
    ("S01", "CSS text-transform + generated counter"),
    ("S02", "Canvas drawing + DOM overlay"),
    ("S03", "Accessible same-origin iframe"),
    ("S04", "Inaccessible sandboxed iframe"),
    ("S05", "Closed shadow root"),
    ("S06", "DOM-hidden legacy copy"),
    ("S07", "Hydration state switch"),
    ("S08", "Complex stacking context"),
)
SCENE_IDS = tuple(scene_id for scene_id, _title in SCENES)

FIELD_TYPES = (
    "raw-dom-text",
    "visible-dom-text",
    "screenshot-ocr-text",
    "text-content",
    "role",
    "editability",
    "css-declared-color",
    "composited-pixel-color",
    "asset-source",
    "visibility",
    "document-scope",
    "frame-access",
    "shadow-access",
    "state-signature",
    "local-occlusion",
    "global-z-order",
    "geometry",
)

DECISION_STATUSES = {
    "authoritative",
    "observed",
    "candidate",
    "external-conflict",
    "unknown",
    "unsupported",
    "not-applicable",
}

EXPECTED_TEXT = {
    "counter_raw": "sale item alpha",
    "counter_visible_dom": "SALE ITEM ALPHA",
    "counter_visible_with_pseudo": "01 / SALE ITEM ALPHA",
    "canvas_visible": "SHOT ONLY 42",
    "accessible_frame": "FRAME ACCESSIBLE 7",
    "blocked_frame": "FRAME OFFLINE 88",
    "closed_shadow": "CLOSED SHADOW 3",
    "hidden_legacy": "LEGACY PRICE 19",
    "current_price": "CURRENT PRICE 29",
    "hydration_old": "DRAFT COPY",
    "hydration_live": "LIVE COPY",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_hash(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "content_hash"}
    return sha256_text(canonical(payload))


def atomic_write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def check(name: str, description: str, passed: bool, detail: Any = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "passed": bool(passed),
        "detail": detail,
    }


def package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def normalize_ocr(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (text or "").upper())


def normalize_space(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def rgb_to_css(rgb: tuple[int, int, int] | list[int]) -> str:
    return f"rgb({int(rgb[0])}, {int(rgb[1])}, {int(rgb[2])})"


def rgb_to_hex(rgb: tuple[int, int, int] | list[int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(int(rgb[0]), int(rgb[1]), int(rgb[2]))


def safe_output_dir(path: Path) -> Path:
    resolved = path.resolve()
    expected_parent = (ROOT / "output" / "_r5_experiments").resolve()
    if resolved.parent != expected_parent:
        raise ValueError(f"Refusing to clean unexpected output directory: {resolved}")
    if not resolved.name.startswith("r5_exp_03"):
        raise ValueError(f"Refusing to clean unexpected experiment name: {resolved.name}")
    return resolved


ACCESSIBLE_FRAME_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>
  html,body { margin:0; background:#ffffff; font-family:Arial,sans-serif; }
  body { padding:16px 20px; color:#0f172a; }
  #frame-title { font-size:30px; line-height:1.15; font-weight:700; }
  p { margin:8px 0 0; font-size:14px; color:#475569; }
</style></head><body>
  <div id="frame-title" role="heading" aria-level="2">FRAME ACCESSIBLE 7</div>
  <p>STATIC FRAME COPY</p>
</body></html>"""

BLOCKED_FRAME_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>
  html,body { margin:0; background:#ffffff; font-family:Arial,sans-serif; }
  body { padding:18px 20px; color:#0f172a; }
  #blocked-title { font-size:30px; line-height:1.15; font-weight:700; }
  p { margin:8px 0 0; font-size:14px; color:#475569; }
</style></head><body>
  <div id="blocked-title">FRAME OFFLINE 88</div>
  <p>OPAQUE SANDBOX DOCUMENT</p>
</body></html>"""


def fixture_html() -> str:
    accessible_doc = html.escape(ACCESSIBLE_FRAME_HTML, quote=True)
    blocked_doc = html.escape(BLOCKED_FRAME_HTML, quote=True)
    scene_markup = {
        "S01": """
        <div class="scene-title"><span>S01</span> CSS text-transform + generated counter</div>
        <div class="scene-note">Raw source text, innerText and generated counter text are intentionally different.</div>
        <div class="row">
          <div id="counter-line">sale item alpha</div>
          <div id="css-color-swatch" aria-label="CSS red at half opacity"></div>
        </div>
        """,
        "S02": """
        <div class="scene-title"><span>S02</span> Canvas drawing + DOM overlay</div>
        <div class="scene-note">The fallback is DOM text; the visible words are bitmap drawing plus a DOM overlay.</div>
        <div id="canvas-wrap">
          <canvas id="canvas-shot" width="420" height="112" role="img" aria-label="Canvas poster">CANVAS FALLBACK</canvas>
          <div id="canvas-overlay">DOM OVERLAY</div>
        </div>
        """,
        "S03": f"""
        <div class="scene-title"><span>S03</span> Accessible same-origin iframe</div>
        <div class="scene-note">The child document is separately scoped and page-readable.</div>
        <iframe id="accessible-frame" title="Accessible frame" srcdoc="{accessible_doc}"></iframe>
        """,
        "S04": f"""
        <div class="scene-title"><span>S04</span> Inaccessible sandboxed iframe</div>
        <div class="scene-note">The page can see pixels, but same-origin DOM access is blocked.</div>
        <iframe id="blocked-frame" title="Inaccessible frame" sandbox="allow-scripts" srcdoc="{blocked_doc}"></iframe>
        """,
        "S05": """
        <div class="scene-title"><span>S05</span> Closed shadow root</div>
        <div class="scene-note">The host is DOM-visible; its shadow tree is not exposed to page script.</div>
        <closed-card id="closed-host" role="article" aria-label="Closed shadow card"></closed-card>
        """,
        "S06": """
        <div class="scene-title"><span>S06</span> DOM-hidden legacy copy</div>
        <div class="scene-note">The hidden price remains in textContent and must not become a visible node.</div>
        <div id="hidden-copy-wrap">
          <div id="hidden-legacy" class="legacy">LEGACY PRICE 19</div>
          <div id="visible-current">CURRENT PRICE 29</div>
        </div>
        """,
        "S07": """
        <div class="scene-title"><span>S07</span> Hydration state switch</div>
        <div class="scene-note">M0 is captured before hydration; M1 replaces it. Stale pairs must not compare.</div>
        <div id="hydration-panel" data-state="M0">
          <div id="hydration-copy">DRAFT COPY</div>
        </div>
        """,
        "S08": """
        <div class="scene-title"><span>S08</span> Complex stacking context</div>
        <div class="scene-note">DOM order and z-index conflict; only a sampled local occlusion relation is claimed.</div>
        <div id="stack-zone">
          <div id="ctx-high" class="stack-context">
            <div id="stack-high">CTX HIGH</div>
          </div>
          <div id="ctx-low" class="stack-context">
            <div id="stack-low">CTX LOW</div>
          </div>
          <div id="composite-swatch" aria-label="CSS red with opacity"></div>
        </div>
        """,
    }
    panels = "\n".join(
        f'<section class="scene" id="scene-{scene_id}" data-scene-id="{scene_id}">{scene_markup[scene_id]}</section>'
        for scene_id in SCENE_IDS
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>R5 EXP-03 authority matrix fixture</title>
<style>
  * {{ box-sizing: border-box; animation: none !important; transition: none !important; }}
  html, body {{ margin: 0; padding: 0; background: #e8edf4; color: #0f172a; }}
  body {{ font-family: Arial, "Segoe UI", sans-serif; counter-reset: promo; }}
  #page {{ width: 1180px; margin: 0 auto; padding: 18px 0 26px; }}
  #masthead {{
    background: #0f172a; color: #f8fafc; border-radius: 8px; padding: 18px 22px;
  }}
  #masthead h1 {{ margin: 0; font-size: 24px; letter-spacing: 0; }}
  #masthead p {{ margin: 6px 0 0; color: #cbd5e1; font-size: 13px; }}
  .scene {{
    background: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px;
    margin-top: 14px; padding: 14px 16px 16px; min-height: 172px;
  }}
  .scene-title {{ font-size: 17px; line-height: 1.25; font-weight: 700; }}
  .scene-title span {{
    display: inline-block; background: #dbeafe; color: #1d4ed8; border-radius: 4px;
    padding: 2px 6px; margin-right: 8px; font-size: 12px;
  }}
  .scene-note {{ color: #475569; font-size: 12px; line-height: 1.4; margin: 4px 0 12px; }}
  .row {{ display: flex; gap: 24px; align-items: center; }}
  #counter-line {{
    flex: 1; background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px;
    color: #0f172a; font: 700 32px/1.35 Arial, sans-serif; padding: 14px 18px;
    text-transform: uppercase; white-space: nowrap;
  }}
  #counter-line::before {{
    counter-increment: promo;
    content: counter(promo, decimal-leading-zero) " / ";
    color: #b91c1c;
  }}
  #css-color-swatch {{
    width: 210px; height: 54px; background: rgb(220, 38, 38); opacity: 0.5;
    border: 1px solid #94a3b8; border-radius: 6px;
  }}
  #canvas-wrap {{ position: relative; width: 440px; height: 132px; }}
  #canvas-shot {{ display: block; background: #ffffff; border: 1px solid #94a3b8; border-radius: 6px; }}
  #canvas-overlay {{
    position: absolute; right: 8px; top: 68px; width: 150px; padding: 7px 9px;
    background: #0f766e; color: #ffffff; border: 2px solid #ffffff; border-radius: 4px;
    font: 700 15px/1.2 Arial, sans-serif; text-align: center;
  }}
  iframe {{ display: block; width: 560px; height: 112px; border: 2px solid #94a3b8; border-radius: 6px; background: #ffffff; }}
  #blocked-frame {{ border-color: #f59e0b; }}
  closed-card {{ display: block; width: 430px; min-height: 82px; }}
  #hidden-copy-wrap {{
    height: 80px; display: flex; align-items: center; justify-content: center;
    background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px;
    font: 700 30px/1.2 Arial, sans-serif; color: #0f172a;
  }}
  #visible-current {{ text-align: center; }}
  .legacy {{ display: none !important; }}
  #hydration-panel {{
    height: 80px; display: flex; align-items: center; justify-content: center;
    background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px;
    font: 700 30px/1.2 Arial, sans-serif; color: #0f172a;
  }}
  #hydration-panel[data-state="M1"] {{ background: #ecfdf5; border-color: #10b981; color: #065f46; }}
  #stack-zone {{
    position: relative; isolation: isolate; width: 640px; height: 160px;
    background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; overflow: hidden;
  }}
  .stack-context {{ position: absolute; transform: translateZ(0); }}
  #ctx-high {{ left: 36px; top: 28px; z-index: 2; width: 230px; height: 108px; }}
  #ctx-low {{ left: 172px; top: 48px; z-index: 1; width: 240px; height: 100px; }}
  #stack-high,
  #stack-low {{
    position: absolute; inset: 0; display: flex; align-items: flex-start; justify-content: flex-start;
    padding: 8px 10px; color: #ffffff; font: 700 13px/1.2 Arial, sans-serif;
  }}
  #stack-high {{ background: #f97316; }}
  #stack-low {{ background: #2563eb; }}
  #composite-swatch {{
    position: absolute; right: 18px; top: 26px; width: 172px; height: 106px;
    background: rgb(220, 38, 38); opacity: 0.5; border: 1px solid #94a3b8; border-radius: 6px;
  }}
</style>
</head>
<body>
<main id="page">
  <header id="masthead">
    <h1>R5-EXP-03 DOM / screenshot field-authority fixture</h1>
    <p>Authored Chromium scenes. Each field is observed separately; no node-level authority switch is allowed.</p>
  </header>
  {panels}
</main>
<script>
  class ClosedCard extends HTMLElement {{
    constructor() {{
      super();
      const root = this.attachShadow({{ mode: "closed" }});
      root.innerHTML = `
        <div style="height:82px;display:flex;align-items:center;justify-content:center;
                    background:#ffffff;border:1px solid #94a3b8;border-radius:6px;
                    color:#0f172a;font:700 30px/1.2 Arial,sans-serif;">CLOSED SHADOW 3</div>`;
    }}
  }}
  customElements.define("closed-card", ClosedCard);

  function drawCanvasFixture() {{
    const canvas = document.getElementById("canvas-shot");
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#0f172a";
    ctx.font = "700 34px Arial";
    ctx.fillText("SHOT ONLY 42", 22, 68);
  }}

  window.__hydration = {{ revision: 0, hydrated: false }};
  window.hydrateFixture = function () {{
    const copy = document.getElementById("hydration-copy");
    copy.textContent = "LIVE COPY";
    copy.dataset.revision = "1";
    document.getElementById("hydration-panel").dataset.state = "M1";
    window.__hydration = {{ revision: 1, hydrated: true }};
  }};

  function probeFrameAccess() {{
    const accessible = document.getElementById("accessible-frame");
    const blocked = document.getElementById("blocked-frame");
    const closed = document.getElementById("closed-host");
    const result = {{
      accessibleViaPage: false,
      accessibleText: null,
      accessibleError: null,
      blockedViaPage: false,
      blockedText: null,
      blockedError: null,
      closedShadowRoot: closed ? closed.shadowRoot : "missing-host"
    }};
    try {{
      const doc = accessible.contentDocument;
      result.accessibleViaPage = !!doc;
      result.accessibleText = doc ? doc.getElementById("frame-title").innerText : null;
    }} catch (error) {{
      result.accessibleError = error.name + ": " + error.message;
    }}
    try {{
      const doc = blocked.contentDocument;
      result.blockedViaPage = !!doc;
      result.blockedText = doc ? doc.body.innerText : null;
    }} catch (error) {{
      result.blockedError = error.name + ": " + error.message;
    }}
    result.closedShadowRoot = closed ? closed.shadowRoot : "missing-host";
    return result;
  }}

  window.addEventListener("load", () => {{
    drawCanvasFixture();
    window.__frameProbe = probeFrameAccess();
    window.__fixtureReady = true;
  }});
</script>
</body>
</html>
"""


def scene_path(out_dir: Path, scene_id: str, name: str) -> Path:
    return out_dir / "scenes" / scene_id / name


def capture_observation(page: Any, locator: Any, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    locator.screenshot(path=str(path))
    with Image.open(path) as image:
        width, height = image.size
    return {
        "path": str(path),
        "relative_path": path.relative_to(path.parents[2]).as_posix(),
        "sha256": sha256_file(path),
        "width": width,
        "height": height,
        "captured_at": CAPTURED_AT,
    }


def crop_left(src: Path, dst: Path, width: int | None = None) -> dict[str, Any]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as image:
        crop_width = min(image.width, width or int(image.width * 0.68))
        cropped = image.crop((0, 0, crop_width, image.height))
        cropped.save(dst)
        size = cropped.size
    return {
        "path": str(dst),
        "relative_path": dst.relative_to(dst.parents[2]).as_posix(),
        "sha256": sha256_file(dst),
        "width": size[0],
        "height": size[1],
        "source": str(src.relative_to(src.parents[2])).replace("\\", "/"),
    }


def crop_top(src: Path, dst: Path, height: int) -> dict[str, Any]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as image:
        crop_height = min(image.height, height)
        cropped = image.crop((0, 0, image.width, crop_height))
        cropped.save(dst)
        size = cropped.size
    return {
        "path": str(dst),
        "relative_path": dst.relative_to(dst.parents[2]).as_posix(),
        "sha256": sha256_file(dst),
        "width": size[0],
        "height": size[1],
        "source": str(src.relative_to(src.parents[2])).replace("\\", "/"),
    }


def collect_dom(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const byId = (id) => document.getElementById(id);
          const rect = (el) => {
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {
              x: r.x + window.scrollX,
              y: r.y + window.scrollY,
              width: r.width,
              height: r.height,
              right: r.right + window.scrollX,
              bottom: r.bottom + window.scrollY
            };
          };
          const style = (el, pseudo) => {
            if (!el) return null;
            const s = getComputedStyle(el, pseudo || null);
            return {
              display: s.display,
              visibility: s.visibility,
              opacity: s.opacity,
              color: s.color,
              backgroundColor: s.backgroundColor,
              textTransform: s.textTransform,
              content: pseudo ? s.content : null,
              position: s.position,
              zIndex: s.zIndex,
              transform: s.transform,
              isolation: s.isolation,
              contentEditable: el.isContentEditable
            };
          };
          const text = (el) => el ? (el.textContent || "").replace(/\\s+/g, " ").trim() : null;
          const inner = (el) => el ? (el.innerText || "").replace(/\\s+/g, " ").trim() : null;
          const attr = (el, name) => el ? el.getAttribute(name) : null;

          const counter = byId("counter-line");
          const canvas = byId("canvas-shot");
          const accessible = byId("accessible-frame");
          const blocked = byId("blocked-frame");
          const closed = byId("closed-host");
          const legacy = byId("hidden-legacy");
          const current = byId("visible-current");
          const hydrationPanel = byId("hydration-panel");
          const hydrationCopy = byId("hydration-copy");
          const high = byId("stack-high");
          const low = byId("stack-low");
          const highRect = rect(high);
          const lowRect = rect(low);
          let overlap = null;
          let sample = null;
          if (highRect && lowRect) {
            const left = Math.max(highRect.x, lowRect.x);
            const top = Math.max(highRect.y, lowRect.y);
            const right = Math.min(highRect.right, lowRect.right);
            const bottom = Math.min(highRect.bottom, lowRect.bottom);
            if (right > left && bottom > top) {
              overlap = { x: left, y: top, width: right - left, height: bottom - top };
              sample = { x: left + Math.min(24, (right - left) / 3), y: top + (bottom - top) / 2 };
            }
          }
          const composite = byId("composite-swatch");
          const compositeRect = rect(composite);

          return {
            url: location.href,
            viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio },
            documentHeight: document.documentElement.scrollHeight,
            fixtureReady: !!window.__fixtureReady,
            hydration: window.__hydration,
            frameProbe: window.__frameProbe,
            S01: {
              textContent: text(counter),
              innerText: inner(counter),
              computed: style(counter),
              pseudo: style(counter, "::before"),
              rect: rect(counter),
              cssSwatch: {
                computed: style(byId("css-color-swatch")),
                rect: rect(byId("css-color-swatch"))
              }
            },
            S02: {
              canvasFallbackText: text(canvas),
              canvasInnerText: inner(canvas),
              canvasRole: attr(canvas, "role"),
              canvasAriaLabel: attr(canvas, "aria-label"),
              canvasComputed: style(canvas),
              canvasRect: rect(canvas),
              overlayText: text(byId("canvas-overlay")),
              overlayInnerText: inner(byId("canvas-overlay")),
              overlayComputed: style(byId("canvas-overlay")),
              overlayRect: rect(byId("canvas-overlay"))
            },
            S03: {
              title: attr(accessible, "title"),
              pageAccess: window.__frameProbe ? window.__frameProbe.accessibleViaPage : null,
              pageText: window.__frameProbe ? window.__frameProbe.accessibleText : null,
              pageError: window.__frameProbe ? window.__frameProbe.accessibleError : null,
              rect: rect(accessible)
            },
            S04: {
              title: attr(blocked, "title"),
              sandbox: attr(blocked, "sandbox"),
              pageAccess: window.__frameProbe ? window.__frameProbe.blockedViaPage : null,
              pageText: window.__frameProbe ? window.__frameProbe.blockedText : null,
              pageError: window.__frameProbe ? window.__frameProbe.blockedError : null,
              rect: rect(blocked)
            },
            S05: {
              hostRole: attr(closed, "role"),
              hostAriaLabel: attr(closed, "aria-label"),
              shadowRoot: closed ? closed.shadowRoot : "missing-host",
              shadowAccess: window.__frameProbe ? window.__frameProbe.closedShadowRoot : null,
              rect: rect(closed)
            },
            S06: {
              rawText: text(byId("hidden-copy-wrap")),
              visibleText: inner(byId("hidden-copy-wrap")),
              legacyText: text(legacy),
              legacyInnerText: inner(legacy),
              legacyComputed: style(legacy),
              currentText: text(current),
              currentInnerText: inner(current),
              currentComputed: style(current),
              legacyRect: rect(legacy),
              currentRect: rect(current)
            },
            S07: {
              state: hydrationPanel ? hydrationPanel.dataset.state : null,
              rawText: text(hydrationCopy),
              innerText: inner(hydrationCopy),
              revision: hydrationCopy ? hydrationCopy.dataset.revision : null,
              hydrationSnapshot: window.__hydration,
              rect: rect(hydrationCopy)
            },
            S08: {
              highComputed: style(high),
              lowComputed: style(low),
              highRect,
              lowRect,
              overlap,
              sample,
              highContextComputed: style(byId("ctx-high")),
              lowContextComputed: style(byId("ctx-low")),
              domOrder: ["ctx-high", "ctx-low"],
              compositeComputed: style(composite),
              compositeRect,
              compositeSample: compositeRect ? {
                x: compositeRect.x + compositeRect.width / 2,
                y: compositeRect.y + compositeRect.height / 2
              } : null
            }
          };
        }
        """
    )


def capture_all(fixture_dir: Path, out_dir: Path) -> dict[str, Any]:
    fixture_dir.mkdir(parents=True, exist_ok=True)
    index_path = fixture_dir / "index.html"
    index_path.write_text(fixture_html(), encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=DPR,
            locale="en-US",
            timezone_id="UTC",
        )
        page = context.new_page()
        page.goto(index_path.as_uri(), wait_until="load")
        page.evaluate("document.fonts.ready.then(() => true)")
        page.wait_for_function("window.__fixtureReady === true")
        page.add_style_tag(
            content=(
                "* { animation: none !important; transition: none !important; "
                "caret-color: transparent !important; }"
            )
        )
        page.wait_for_timeout(80)

        scene_captures: dict[str, Any] = {}
        ocr_sources: dict[str, Any] = {}
        for scene_id, title in SCENES:
            target = scene_path(out_dir, scene_id, "capture.png")
            record = capture_observation(page, page.locator(f"#scene-{scene_id}"), target)
            record.update({"scene_id": scene_id, "title": title, "state": "M1" if scene_id == "S07" else "stable"})
            scene_captures[scene_id] = record

        ocr_sources["S01"] = capture_observation(
            page, page.locator("#counter-line"), scene_path(out_dir, "S01", "ocr_source.png")
        )
        ocr_sources["S02_raw"] = capture_observation(
            page, page.locator("#canvas-shot"), scene_path(out_dir, "S02", "ocr_source_canvas.png")
        )
        ocr_sources["S02"] = crop_left(
            scene_path(out_dir, "S02", "ocr_source_canvas.png"),
            scene_path(out_dir, "S02", "ocr_crop.png"),
            width=300,
        )
        accessible_title = page.frame_locator("#accessible-frame").locator("#frame-title")
        ocr_sources["S03"] = capture_observation(
            page, accessible_title, scene_path(out_dir, "S03", "ocr_source.png")
        )
        ocr_sources["S04_raw"] = capture_observation(
            page, page.locator("#blocked-frame"), scene_path(out_dir, "S04", "ocr_source.png")
        )
        ocr_sources["S04"] = crop_top(
            scene_path(out_dir, "S04", "ocr_source.png"),
            scene_path(out_dir, "S04", "ocr_crop.png"),
            height=58,
        )
        ocr_sources["S05"] = capture_observation(
            page, page.locator("#closed-host"), scene_path(out_dir, "S05", "ocr_source.png")
        )
        ocr_sources["S06"] = capture_observation(
            page, page.locator("#visible-current"), scene_path(out_dir, "S06", "ocr_source.png")
        )
        ocr_sources["S07_M0"] = capture_observation(
            page, page.locator("#hydration-copy"), scene_path(out_dir, "S07", "ocr_source_m0.png")
        )

        dom_m0 = collect_dom(page)
        full_m0 = out_dir / "full_page_m0.png"
        page.screenshot(path=str(full_m0), full_page=True)
        scene_m0 = page.locator("#scene-S07").screenshot(path=str(scene_path(out_dir, "S07", "capture_m0.png")))
        del scene_m0

        page.evaluate("window.hydrateFixture()")
        page.wait_for_timeout(40)
        ocr_sources["S07_M1"] = capture_observation(
            page, page.locator("#hydration-copy"), scene_path(out_dir, "S07", "ocr_source_m1.png")
        )
        capture_observation(page, page.locator("#scene-S07"), scene_path(out_dir, "S07", "capture.png"))
        dom_m1 = collect_dom(page)
        full_m1 = out_dir / "full_page_m1.png"
        page.screenshot(path=str(full_m1), full_page=True)

        accessible_frame = page.frame_locator("#accessible-frame")
        accessible_frame_dom = accessible_frame.locator("#frame-title").evaluate(
            """
            el => {
              const s = getComputedStyle(el);
              return {
                textContent: el.textContent,
                innerText: el.innerText,
                role: el.getAttribute("role"),
                contentEditable: el.isContentEditable,
                fontSize: s.fontSize,
                color: s.color
              };
            }
            """
        )
        browser_version = browser.version
        user_agent = page.evaluate("navigator.userAgent")
        context.close()
        browser.close()

    with Image.open(full_m0) as image:
        full_m0_size = image.size
    with Image.open(full_m1) as image:
        full_m1_size = image.size

    return {
        "fixture": str(index_path),
        "fixture_sha256": sha256_file(index_path),
        "scene_captures": scene_captures,
        "ocr_sources": ocr_sources,
        "dom_m0": dom_m0,
        "dom_m1": dom_m1,
        "accessible_frame_dom": accessible_frame_dom,
        "full_page": {
            "m0": {
                "path": str(full_m0),
                "sha256": sha256_file(full_m0),
                "width": full_m0_size[0],
                "height": full_m0_size[1],
            },
            "m1": {
                "path": str(full_m1),
                "sha256": sha256_file(full_m1),
                "width": full_m1_size[0],
                "height": full_m1_size[1],
            },
        },
        "browser": {
            "name": "chromium",
            "version": browser_version,
            "user_agent": user_agent,
            "viewport": VIEWPORT,
            "dpr": DPR,
            "locale": "en-US",
            "timezone": "UTC",
        },
    }


def ocr_image(path: Path) -> dict[str, Any]:
    with Image.open(path) as source:
        image = source.convert("RGB")
    gray = ImageOps.grayscale(image)
    extrema = gray.getextrema()
    if extrema and (sum(extrema) / 2.0) < 128:
        gray = ImageOps.invert(gray)
    scale = 2
    gray = gray.resize((gray.width * scale, gray.height * scale), Image.Resampling.LANCZOS)
    gray = ImageOps.autocontrast(gray)
    processed = gray.point(lambda value: 0 if value < 190 else 255)
    processed = ImageOps.expand(processed, border=20, fill=255)
    config = "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 /-"
    try:
        raw_text = pytesseract.image_to_string(processed, lang="eng", config=config).strip()
        error = None
    except Exception as exc:  # pragma: no cover - environment dependent
        raw_text = ""
        error = f"{type(exc).__name__}: {exc}"
    try:
        engine_version = str(pytesseract.get_tesseract_version())
    except Exception as exc:  # pragma: no cover - environment dependent
        engine_version = f"unknown: {type(exc).__name__}: {exc}"
    return {
        "raw_text": raw_text,
        "normalized": normalize_ocr(raw_text),
        "error": error,
        "engine": "tesseract",
        "engine_version": engine_version,
        "config": config,
    }


def run_ocr(ocr_sources: dict[str, Any], expectations: dict[str, str]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for key, expected in expectations.items():
        source = ocr_sources[key]
        path = Path(source["path"])
        record = ocr_image(path)
        record["expected_text"] = expected
        record["expected_normalized"] = normalize_ocr(expected or "")
        record["match"] = (
            record["error"] is None
            and record["normalized"] == record["expected_normalized"]
            and bool(record["normalized"])
        )
        record["source_path"] = str(path.relative_to(path.parents[2])).replace("\\", "/")
        results[key] = record
    return results


def sample_pixels(full_page_path: Path, samples: dict[str, dict[str, float]]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    with Image.open(full_page_path) as image:
        rgb_image = image.convert("RGB")
        for name, point in samples.items():
            x = max(0, min(rgb_image.width - 1, int(round(point["x"]))))
            y = max(0, min(rgb_image.height - 1, int(round(point["y"]))))
            rgb = rgb_image.getpixel((x, y))
            results[name] = {
                "requested": {"x": point["x"], "y": point["y"]},
                "sampled": {"x": x, "y": y},
                "rgb": list(rgb),
                "css": rgb_to_css(rgb),
                "hex": rgb_to_hex(rgb),
            }
    return results


def scene_observation(dom: dict[str, Any], scene_id: str, field: str) -> Any:
    return dom.get(scene_id, {}).get(field)


def make_row(
    row_id: str,
    scene_id: str,
    object_id: str,
    field_type: str,
    authority: str,
    decision_status: str,
    selected_value: Any,
    reason: str,
    evidence_refs: list[str],
    *,
    release_eligible: bool = False,
    cannot_promote: list[str] | None = None,
    observations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "row_id": row_id,
        "scene_id": scene_id,
        "object_id": object_id,
        "field_type": field_type,
        "authority": authority,
        "decision_status": decision_status,
        "selected_value": selected_value,
        "release_eligible": bool(release_eligible),
        "cannot_promote": list(cannot_promote or []),
        "reason": reason,
        "evidence_refs": list(evidence_refs),
        "observations": observations or {},
    }


def build_matrix(
    capture: dict[str, Any],
    ocr: dict[str, Any],
    pixels: dict[str, Any],
) -> dict[str, Any]:
    dom = capture["dom_m1"]
    dom_m0 = capture["dom_m0"]
    frame_dom = capture["accessible_frame_dom"]
    rows: list[dict[str, Any]] = []

    raw_counter = normalize_space(dom["S01"]["textContent"])
    visible_counter = normalize_space(dom["S01"]["innerText"])
    pseudo_content = dom["S01"]["pseudo"]["content"]
    counter_final = EXPECTED_TEXT["counter_visible_with_pseudo"]
    css_red = dom["S01"]["cssSwatch"]["computed"]["backgroundColor"]
    pixel_red = pixels["S01"]["css"]
    rows.extend(
        [
            make_row(
                "S01-raw-dom-text",
                "S01",
                "counter-line",
                "raw-dom-text",
                "dom",
                "observed",
                raw_counter,
                "textContent is the authored source string before text-transform or pseudo-element content.",
                ["dom:S01.textContent"],
                observations={"textContent": raw_counter},
            ),
            make_row(
                "S01-visible-dom-text",
                "S01",
                "counter-line",
                "visible-dom-text",
                "dom",
                "observed",
                visible_counter,
                "innerText includes CSS text-transform but excludes generated ::before content in Chromium.",
                ["dom:S01.innerText", "css:S01.text-transform"],
                observations={"innerText": visible_counter, "textTransform": dom["S01"]["computed"]["textTransform"]},
            ),
            make_row(
                "S01-screenshot-ocr-text",
                "S01",
                "counter-line",
                "screenshot-ocr-text",
                "screenshot",
                "candidate",
                counter_final if ocr["S01"]["match"] else None,
                "OCR observes the generated counter and transformed glyphs in the screenshot.",
                ["capture:S01.ocr_source", "ocr:S01"],
                cannot_promote=["role", "editability", "asset-source"],
                observations={
                    "raw": ocr["S01"]["raw_text"],
                    "normalized": ocr["S01"]["normalized"],
                    "match": ocr["S01"]["match"],
                },
            ),
            make_row(
                "S01-text-content",
                "S01",
                "counter-line",
                "text-content",
                "dom+screenshot",
                "authoritative" if ocr["S01"]["match"] else "unknown",
                counter_final if ocr["S01"]["match"] else None,
                "The source text is DOM-owned; the generated counter is visible only in rendered evidence.",
                ["dom:S01.textContent", "css:S01.pseudo", "ocr:S01"],
                release_eligible=ocr["S01"]["match"],
                cannot_promote=["role", "editability", "asset-source"],
                observations={"pseudoContent": pseudo_content, "ocrMatch": ocr["S01"]["match"]},
            ),
            make_row(
                "S01-role",
                "S01",
                "counter-line",
                "role",
                "dom",
                "authoritative",
                "text",
                "OCR text does not establish semantics; the ordinary DOM element remains text.",
                ["dom:S01.element"],
            ),
            make_row(
                "S01-editability",
                "S01",
                "counter-line",
                "editability",
                "dom",
                "authoritative",
                "static",
                "The generated counter does not make the line editable.",
                ["dom:S01.contentEditable"],
            ),
            make_row(
                "S01-css-declared-color",
                "S01",
                "css-color-swatch",
                "css-declared-color",
                "dom",
                "authoritative",
                css_red,
                "The CSS declaration records the authored red, before opacity compositing.",
                ["css:S01.css-color-swatch.backgroundColor"],
                observations={"opacity": dom["S01"]["cssSwatch"]["computed"]["opacity"]},
            ),
            make_row(
                "S01-composited-pixel-color",
                "S01",
                "css-color-swatch",
                "composited-pixel-color",
                "screenshot",
                "authoritative",
                pixel_red,
                "The screenshot records the composited pixel color after opacity.",
                ["pixel:S01.css-color-swatch"],
                observations={
                    "pixel": pixels["S01"],
                    "different_from_css": pixel_red != css_red,
                },
            ),
        ]
    )

    canvas_raw = normalize_space(dom["S02"]["canvasFallbackText"])
    overlay_rect = dom["S02"]["overlayRect"]
    rows.extend(
        [
            make_row(
                "S02-raw-dom-text",
                "S02",
                "canvas-shot",
                "raw-dom-text",
                "dom",
                "observed",
                canvas_raw,
                "Canvas fallback text is DOM source text, not the bitmap text the user sees.",
                ["dom:S02.canvasFallbackText"],
            ),
            make_row(
                "S02-text-content",
                "S02",
                "canvas-shot",
                "text-content",
                "screenshot",
                "candidate" if ocr["S02"]["match"] else "unknown",
                EXPECTED_TEXT["canvas_visible"] if ocr["S02"]["match"] else None,
                "Canvas glyphs are visible pixels; OCR can only propose text content.",
                ["capture:S02.ocr_crop", "ocr:S02"],
                cannot_promote=["role", "editability", "asset-source"],
                observations={
                    "fallbackText": canvas_raw,
                    "ocr": ocr["S02"]["raw_text"],
                    "ocrMatch": ocr["S02"]["match"],
                },
            ),
            make_row(
                "S02-role",
                "S02",
                "canvas-shot",
                "role",
                "dom",
                "authoritative",
                "img",
                "The canvas element has explicit image semantics.",
                ["dom:S02.canvasRole", "dom:S02.canvasAriaLabel"],
            ),
            make_row(
                "S02-editability",
                "S02",
                "canvas-shot",
                "editability",
                "dom",
                "authoritative",
                "none",
                "OCR does not turn painted glyphs into text objects.",
                ["dom:S02.element"],
            ),
            make_row(
                "S02-asset-source",
                "S02",
                "canvas-shot",
                "asset-source",
                "dom",
                "authoritative",
                "canvas-bitmap",
                "The element and drawing surface identify a generated bitmap source.",
                ["dom:S02.canvas"],
                cannot_promote=["original-vector", "font-source"],
            ),
            make_row(
                "S02-local-occlusion",
                "S02",
                "canvas-overlay",
                "local-occlusion",
                "dom+screenshot",
                "authoritative",
                "canvas-overlay-above-canvas-at-overlay-region",
                "The DOM overlay is positioned over the canvas; only this local relation is claimed.",
                ["dom:S02.overlayRect", "pixel:S02.overlay-background"],
                observations={
                    "overlayRect": overlay_rect,
                    "overlayPixel": pixels["S02"],
                },
            ),
        ]
    )

    rows.extend(
        [
            make_row(
                "S03-raw-dom-text",
                "S03",
                "accessible-frame#frame-title",
                "raw-dom-text",
                "dom",
                "authoritative",
                normalize_space(frame_dom["textContent"]),
                "The accessible iframe is a separately scoped child document.",
                ["dom:S03.frame-title.textContent"],
            ),
            make_row(
                "S03-text-content",
                "S03",
                "accessible-frame#frame-title",
                "text-content",
                "dom",
                "authoritative",
                EXPECTED_TEXT["accessible_frame"],
                "DOM text in the page-readable child document supplies text content; OCR only confirms rendering.",
                ["dom:S03.frame-title", "ocr:S03"],
                observations={"ocr": ocr["S03"]["raw_text"], "pageText": dom["S03"]["pageText"]},
            ),
            make_row(
                "S03-role",
                "S03",
                "accessible-frame#frame-title",
                "role",
                "dom",
                "authoritative",
                "heading",
                "ARIA role is read from the child document, not inferred from screenshot position.",
                ["dom:S03.frame-title.role"],
            ),
            make_row(
                "S03-editability",
                "S03",
                "accessible-frame#frame-title",
                "editability",
                "dom",
                "authoritative",
                "static",
                "The child element is not contenteditable.",
                ["dom:S03.frame-title.contentEditable"],
            ),
            make_row(
                "S03-frame-access",
                "S03",
                "accessible-frame",
                "frame-access",
                "dom",
                "authoritative",
                "page-readable-same-origin",
                "Both page script and automation can read the child DOM.",
                ["dom:S03.pageAccess", "dom:S03.pageText"],
            ),
            make_row(
                "S03-document-scope",
                "S03",
                "accessible-frame",
                "document-scope",
                "dom",
                "authoritative",
                "iframe:accessible-frame",
                "Frame fields remain scoped to the child document.",
                ["dom:S03.title"],
            ),
        ]
    )

    rows.extend(
        [
            make_row(
                "S04-text-content",
                "S04",
                "blocked-frame#blocked-title",
                "text-content",
                "screenshot",
                "candidate" if ocr["S04"]["match"] else "unknown",
                EXPECTED_TEXT["blocked_frame"] if ocr["S04"]["match"] else None,
                "Only screenshot pixels are available; OCR can propose text content only.",
                ["capture:S04.ocr_source", "ocr:S04"],
                cannot_promote=["role", "editability", "asset-source"],
                observations={"ocr": ocr["S04"]["raw_text"], "ocrMatch": ocr["S04"]["match"]},
            ),
            make_row(
                "S04-role",
                "S04",
                "blocked-frame#blocked-title",
                "role",
                "none",
                "unknown",
                None,
                "The sandboxed child DOM cannot be inspected from the page.",
                ["dom:S04.pageAccess", "dom:S04.pageError"],
            ),
            make_row(
                "S04-editability",
                "S04",
                "blocked-frame#blocked-title",
                "editability",
                "none",
                "unknown",
                None,
                "Visible glyphs do not establish editability in an inaccessible document.",
                ["dom:S04.pageAccess"],
            ),
            make_row(
                "S04-asset-source",
                "S04",
                "blocked-frame#blocked-title",
                "asset-source",
                "none",
                "unknown",
                None,
                "No source element or asset reference is readable.",
                ["dom:S04.pageAccess"],
            ),
            make_row(
                "S04-frame-access",
                "S04",
                "blocked-frame",
                "frame-access",
                "dom",
                "unsupported",
                None,
                "The requested child-document DOM access is blocked; this is distinct from an empty document.",
                ["dom:S04.sandbox", "dom:S04.pageAccess", "dom:S04.pageError"],
                observations={"sandbox": dom["S04"]["sandbox"], "pageError": dom["S04"]["pageError"]},
            ),
            make_row(
                "S04-document-scope",
                "S04",
                "blocked-frame",
                "document-scope",
                "dom",
                "authoritative",
                "iframe:blocked-frame",
                "The outer frame identity is known even though its document is inaccessible.",
                ["dom:S04.title"],
            ),
        ]
    )

    rows.extend(
        [
            make_row(
                "S05-text-content",
                "S05",
                "closed-host#shadow-title",
                "text-content",
                "screenshot",
                "candidate" if ocr["S05"]["match"] else "unknown",
                EXPECTED_TEXT["closed_shadow"] if ocr["S05"]["match"] else None,
                "Closed shadow content has screenshot evidence only; OCR can propose content.",
                ["capture:S05.ocr_source", "ocr:S05"],
                cannot_promote=["role", "editability", "asset-source"],
                observations={"ocr": ocr["S05"]["raw_text"], "ocrMatch": ocr["S05"]["match"]},
            ),
            make_row(
                "S05-role",
                "S05",
                "closed-host",
                "role",
                "dom",
                "authoritative",
                "article",
                "Only the host role is observable; the shadow descendant role remains unknown.",
                ["dom:S05.hostRole", "dom:S05.hostAriaLabel"],
            ),
            make_row(
                "S05-editability",
                "S05",
                "closed-host#shadow-title",
                "editability",
                "none",
                "unknown",
                None,
                "Closed shadow descendants cannot be inspected for contenteditable state.",
                ["dom:S05.shadowRoot"],
            ),
            make_row(
                "S05-asset-source",
                "S05",
                "closed-host#shadow-title",
                "asset-source",
                "none",
                "unknown",
                None,
                "OCR text does not identify an original asset or font source.",
                ["dom:S05.shadowRoot"],
            ),
            make_row(
                "S05-shadow-access",
                "S05",
                "closed-host",
                "shadow-access",
                "dom",
                "unsupported",
                None,
                "The shadow root is closed; page script cannot read its tree.",
                ["dom:S05.shadowRoot"],
            ),
        ]
    )

    raw_hidden = normalize_space(dom["S06"]["rawText"])
    visible_hidden = normalize_space(dom["S06"]["visibleText"])
    rows.extend(
        [
            make_row(
                "S06-raw-dom-text",
                "S06",
                "hidden-copy-wrap",
                "raw-dom-text",
                "dom",
                "observed",
                raw_hidden,
                "textContent still contains the display:none legacy copy.",
                ["dom:S06.rawText"],
            ),
            make_row(
                "S06-visible-dom-text",
                "S06",
                "hidden-copy-wrap",
                "visible-dom-text",
                "dom",
                "authoritative",
                visible_hidden,
                "innerText excludes the hidden legacy copy.",
                ["dom:S06.visibleText"],
            ),
            make_row(
                "S06-text-content",
                "S06",
                "hidden-copy-wrap",
                "text-content",
                "dom",
                "authoritative",
                EXPECTED_TEXT["current_price"],
                "Only the visible current price becomes text content.",
                ["dom:S06.currentText", "ocr:S06"],
                observations={"ocr": ocr["S06"]["raw_text"], "ocrMatch": ocr["S06"]["match"]},
            ),
            make_row(
                "S06-visibility",
                "S06",
                "hidden-legacy",
                "visibility",
                "dom",
                "authoritative",
                "hidden",
                "The legacy copy has display:none and no visible box.",
                ["css:S06.hidden-legacy.display", "dom:S06.legacyRect"],
            ),
            make_row(
                "S06-role",
                "S06",
                "visible-current",
                "role",
                "dom",
                "authoritative",
                "text",
                "The visible current price is ordinary text.",
                ["dom:S06.currentText"],
            ),
            make_row(
                "S06-editability",
                "S06",
                "visible-current",
                "editability",
                "dom",
                "authoritative",
                "static",
                "The visible current price is not contenteditable.",
                ["dom:S06.currentComputed"],
            ),
        ]
    )

    rows.extend(
        [
            make_row(
                "S07-state-signature",
                "S07",
                "hydration-panel",
                "state-signature",
                "dom",
                "external-conflict",
                None,
                "M0 and M1 are different hydration states; pairing them is a state mismatch.",
                ["dom:S07.M0", "dom:S07.M1"],
                observations={
                    "m0": dom_m0["S07"],
                    "m1": dom["S07"],
                },
            ),
            make_row(
                "S07-stale-raw-dom-text",
                "S07",
                "hydration-copy",
                "raw-dom-text",
                "dom",
                "external-conflict",
                None,
                "DRAFT COPY is stale evidence from M0 and cannot win against the current page.",
                ["dom:S07.M0.rawText"],
                observations={"observed": dom_m0["S07"]["rawText"]},
            ),
            make_row(
                "S07-stale-screenshot-ocr-text",
                "S07",
                "hydration-copy",
                "screenshot-ocr-text",
                "screenshot",
                "external-conflict",
                None,
                "The M0 screenshot is from a different state from the M1 DOM.",
                ["capture:S07.ocr_source_m0", "ocr:S07_M0"],
                cannot_promote=["role", "editability", "asset-source"],
                observations={"ocr": ocr["S07_M0"]["raw_text"]},
            ),
            make_row(
                "S07-text-content",
                "S07",
                "hydration-copy",
                "text-content",
                "dom",
                "authoritative",
                EXPECTED_TEXT["hydration_live"],
                "Only the current M1 DOM supplies text content; OCR confirms the same state.",
                ["dom:S07.M1.rawText", "ocr:S07_M1"],
                observations={"ocr": ocr["S07_M1"]["raw_text"], "ocrMatch": ocr["S07_M1"]["match"]},
            ),
            make_row(
                "S07-role",
                "S07",
                "hydration-copy",
                "role",
                "dom",
                "authoritative",
                "text",
                "Hydration does not change this ordinary text role.",
                ["dom:S07.M1.element"],
            ),
            make_row(
                "S07-editability",
                "S07",
                "hydration-copy",
                "editability",
                "dom",
                "authoritative",
                "static",
                "Hydration does not make the element editable.",
                ["dom:S07.M1.element"],
            ),
        ]
    )

    high_color = dom["S08"]["highComputed"]["backgroundColor"]
    low_color = dom["S08"]["lowComputed"]["backgroundColor"]
    stack_pixel = pixels["S08"]["stack-overlap"]["css"]
    composite_css = dom["S08"]["compositeComputed"]["backgroundColor"]
    composite_pixel = pixels["S08"]["composite"]["css"]
    rows.extend(
        [
            make_row(
                "S08-high-css-color",
                "S08",
                "stack-high",
                "css-declared-color",
                "dom",
                "authoritative",
                high_color,
                "The high stacking context child has an opaque CSS fill.",
                ["css:S08.stack-high.backgroundColor"],
            ),
            make_row(
                "S08-low-css-color",
                "S08",
                "stack-low",
                "css-declared-color",
                "dom",
                "authoritative",
                low_color,
                "The low stacking context child has an opaque CSS fill.",
                ["css:S08.stack-low.backgroundColor"],
            ),
            make_row(
                "S08-css-color-composite",
                "S08",
                "composite-swatch",
                "css-declared-color",
                "dom",
                "authoritative",
                composite_css,
                "The authored CSS color and opacity are kept separately from rendered pixels.",
                ["css:S08.composite-swatch.backgroundColor"],
                observations={"opacity": dom["S08"]["compositeComputed"]["opacity"]},
            ),
            make_row(
                "S08-composited-pixel-color",
                "S08",
                "composite-swatch",
                "composited-pixel-color",
                "screenshot",
                "authoritative",
                composite_pixel,
                "The pixel sample is the composited result, not a replacement CSS fill.",
                ["pixel:S08.composite"],
                observations={
                    "pixel": pixels["S08"]["composite"],
                    "different_from_css": composite_pixel != composite_css,
                },
            ),
            make_row(
                "S08-local-occlusion",
                "S08",
                "stack-zone",
                "local-occlusion",
                "dom+screenshot",
                "authoritative",
                "ctx-high-above-ctx-low-at-p1",
                "DOM stacking paths and the sampled overlap pixel agree; no global order is derived.",
                ["css:S08.ctx-high.z-index", "css:S08.ctx-low.z-index", "pixel:S08.stack-overlap"],
                observations={
                    "sample": dom["S08"]["sample"],
                    "pixel": pixels["S08"]["stack-overlap"],
                    "domOrder": dom["S08"]["domOrder"],
                    "highZ": dom["S08"]["highContextComputed"]["zIndex"],
                    "lowZ": dom["S08"]["lowContextComputed"]["zIndex"],
                },
            ),
            make_row(
                "S08-global-z-order",
                "S08",
                "scene",
                "global-z-order",
                "none",
                "unsupported",
                None,
                "A screenshot pair at one point does not recover a page-global z-order.",
                ["pixel:S08.stack-overlap"],
            ),
            make_row(
                "S08-geometry",
                "S08",
                "stack-high+stack-low",
                "geometry",
                "dom",
                "authoritative",
                "overlap-recorded",
                "DOM rectangles define the overlap region used for the local pixel sample.",
                ["dom:S08.highRect", "dom:S08.lowRect", "dom:S08.overlap"],
                observations={
                    "high": dom["S08"]["highRect"],
                    "low": dom["S08"]["lowRect"],
                    "overlap": dom["S08"]["overlap"],
                },
            ),
        ]
    )

    return {
        "job": JOB,
        "revision": REVISION,
        "profile": PROFILE,
        "status": "experimental",
        "scenes": [{"scene_id": scene_id, "title": title} for scene_id, title in SCENES],
        "field_types": list(FIELD_TYPES),
        "rows": rows,
        "node_authorities": {},
        "whole_node_switches": [],
        "observations": {
            "browser": capture["browser"],
            "fixture_sha256": capture["fixture_sha256"],
            "dom_m0": dom_m0,
            "dom_m1": dom,
            "accessible_frame_dom": frame_dom,
            "ocr": ocr,
            "pixels": pixels,
        },
    }


def freeze_contract(document: dict[str, Any]) -> dict[str, Any]:
    return {
        row["row_id"]: {
            "field_type": row["field_type"],
            "authority": row["authority"],
            "decision_status": row["decision_status"],
            "selected_value": copy.deepcopy(row["selected_value"]),
            "release_eligible": row["release_eligible"],
            "cannot_promote": list(row["cannot_promote"]),
        }
        for row in document["rows"]
    }


def validate_contract(document: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rows = document.get("rows", [])
    if not isinstance(rows, list):
        return ["rows must be a list"]

    row_ids = [row.get("row_id") for row in rows]
    duplicates = sorted(row_id for row_id, count in Counter(row_ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate row ids: {duplicates}")
    if set(row_ids) != set(baseline):
        errors.append(
            "row set changed: missing=%s extra=%s"
            % (sorted(set(baseline) - set(row_ids)), sorted(set(row_ids) - set(baseline)))
        )

    if document.get("node_authorities"):
        errors.append("node-level authority switch is forbidden")
    if document.get("whole_node_switches"):
        errors.append("whole-node source switching is forbidden")

    seen_scenes = {row.get("scene_id") for row in rows}
    if seen_scenes != set(SCENE_IDS):
        errors.append(f"scene coverage mismatch: {sorted(seen_scenes)}")

    for row in rows:
        row_id = row.get("row_id")
        expected = baseline.get(row_id)
        if expected is None:
            continue
        actual = {
            "field_type": row.get("field_type"),
            "authority": row.get("authority"),
            "decision_status": row.get("decision_status"),
            "selected_value": row.get("selected_value"),
            "release_eligible": row.get("release_eligible"),
            "cannot_promote": row.get("cannot_promote"),
        }
        for key, value in actual.items():
            if value != expected[key]:
                errors.append(f"{row_id}: {key} changed from {expected[key]!r} to {value!r}")

        if row.get("field_type") not in FIELD_TYPES:
            errors.append(f"{row_id}: unknown field_type {row.get('field_type')!r}")
        if row.get("decision_status") not in DECISION_STATUSES:
            errors.append(f"{row_id}: unknown decision_status {row.get('decision_status')!r}")
        if not row.get("evidence_refs"):
            errors.append(f"{row_id}: evidence_refs is empty")
        if row.get("decision_status") in {"external-conflict", "unknown", "unsupported"}:
            if row.get("selected_value") is not None:
                errors.append(f"{row_id}: unresolved status carries a selected value")
        if row.get("authority") == "screenshot" and row.get("field_type") in {
            "role",
            "editability",
            "asset-source",
        }:
            errors.append(f"{row_id}: screenshot authority cannot own semantic field")
        if row.get("authority") in {"screenshot", "dom+screenshot"} and row.get("field_type") in {
            "text-content",
            "screenshot-ocr-text",
        }:
            cannot_promote = set(row.get("cannot_promote") or [])
            required = {"role", "editability", "asset-source"}
            if not required.issubset(cannot_promote):
                errors.append(f"{row_id}: screenshot text does not explicitly keep semantics separate")
        if row.get("field_type") == "text-content" and row.get("decision_status") == "candidate":
            if row.get("release_eligible"):
                errors.append(f"{row_id}: OCR candidate is release eligible")
        if row.get("row_id") == "S08-global-z-order":
            if row.get("decision_status") != "unsupported" or row.get("selected_value") is not None:
                errors.append("global z-order must remain unsupported and unset")

    statuses = {row.get("decision_status") for row in rows}
    if not {"external-conflict", "unknown", "unsupported"}.issubset(statuses):
        errors.append("external-conflict, unknown and unsupported must remain distinct")

    css_rows = [row for row in rows if row.get("field_type") == "css-declared-color"]
    pixel_rows = [row for row in rows if row.get("field_type") == "composited-pixel-color"]
    if not css_rows or not pixel_rows:
        errors.append("CSS and composited pixel colors must both be present")
    else:
        paired_objects = {row.get("object_id") for row in css_rows} & {
            row.get("object_id") for row in pixel_rows
        }
        if not paired_objects:
            errors.append("no object carries both CSS color and pixel color evidence")
        else:
            if not any(
                next(row for row in css_rows if row["object_id"] == object_id)["selected_value"]
                != next(row for row in pixel_rows if row["object_id"] == object_id)["selected_value"]
                for object_id in paired_objects
            ):
                errors.append("CSS and composited pixel colors were collapsed into one value")

    frame_rows = {row["row_id"]: row for row in rows if row.get("field_type") == "frame-access"}
    if frame_rows.get("S03-frame-access", {}).get("decision_status") != "authoritative":
        errors.append("accessible iframe is not page-readable")
    if frame_rows.get("S04-frame-access", {}).get("decision_status") != "unsupported":
        errors.append("inaccessible iframe lost unsupported status")

    return errors


def get_row(document: dict[str, Any], row_id: str) -> dict[str, Any]:
    for row in document["rows"]:
        if row["row_id"] == row_id:
            return row
    raise KeyError(row_id)


def mutate(
    document: dict[str, Any],
    row_id: str,
    **changes: Any,
) -> None:
    row = get_row(document, row_id)
    row.update(changes)


MUTATION_SPECS: list[tuple[str, str, Callable[[dict[str, Any]], None]]] = [
    (
        "raw-text-as-visible",
        "Use textContent as if CSS text-transform and the counter were absent.",
        lambda doc: mutate(doc, "S01-raw-dom-text", selected_value="SALE ITEM ALPHA"),
    ),
    (
        "counter-dropped",
        "Drop generated counter content from final text.",
        lambda doc: mutate(doc, "S01-text-content", selected_value="SALE ITEM ALPHA"),
    ),
    (
        "css-color-used-as-pixel",
        "Collapse composited pixel color into the CSS declaration.",
        lambda doc: mutate(
            doc,
            "S01-composited-pixel-color",
            selected_value=get_row(doc, "S01-css-declared-color")["selected_value"],
        ),
    ),
    (
        "canvas-ocr-promotes-editability",
        "Promote canvas OCR to editable text.",
        lambda doc: mutate(doc, "S02-editability", selected_value="editable"),
    ),
    (
        "canvas-ocr-promotes-role",
        "Promote canvas OCR to a heading role.",
        lambda doc: mutate(doc, "S02-role", selected_value="heading"),
    ),
    (
        "canvas-ocr-promotes-asset-source",
        "Claim the canvas text has an original vector source.",
        lambda doc: mutate(doc, "S02-asset-source", selected_value="original-vector"),
    ),
    (
        "iframe-scope-merged",
        "Merge the accessible iframe into the parent document scope.",
        lambda doc: mutate(doc, "S03-document-scope", selected_value="parent-top-document"),
    ),
    (
        "blocked-iframe-marked-empty",
        "Treat inaccessible iframe contents as an observed empty document.",
        lambda doc: mutate(
            doc,
            "S04-text-content",
            authority="dom",
            decision_status="authoritative",
            selected_value="",
            release_eligible=True,
        ),
    ),
    (
        "blocked-iframe-marked-readable",
        "Claim page-readable access to the sandboxed document.",
        lambda doc: mutate(
            doc,
            "S04-frame-access",
            decision_status="authoritative",
            selected_value="page-readable-same-origin",
        ),
    ),
    (
        "closed-shadow-innertext-claimed",
        "Claim DOM authority for closed shadow text after OCR.",
        lambda doc: mutate(
            doc,
            "S05-text-content",
            authority="dom",
            decision_status="authoritative",
            selected_value=EXPECTED_TEXT["closed_shadow"],
        ),
    ),
    (
        "closed-shadow-role-guessed",
        "Guess the closed shadow descendant role from pixels.",
        lambda doc: mutate(doc, "S05-role", selected_value="heading"),
    ),
    (
        "hidden-legacy-visible",
        "Treat display:none legacy text as visible content.",
        lambda doc: mutate(
            doc,
            "S06-visibility",
            selected_value="visible",
        ),
    ),
    (
        "hidden-legacy-text-reintroduced",
        "Append hidden legacy text to current text content.",
        lambda doc: mutate(
            doc,
            "S06-text-content",
            selected_value="LEGACY PRICE 19 CURRENT PRICE 29",
        ),
    ),
    (
        "hydration-stale-selected",
        "Let the stale M0 text win.",
        lambda doc: mutate(
            doc,
            "S07-stale-raw-dom-text",
            decision_status="authoritative",
            selected_value=EXPECTED_TEXT["hydration_old"],
        ),
    ),
    (
        "state-conflict-collapsed-to-unknown",
        "Collapse an explicit state mismatch into unknown.",
        lambda doc: mutate(doc, "S07-state-signature", decision_status="unknown"),
    ),
    (
        "unsupported-collapsed-to-unknown",
        "Collapse unavailable DOM access into unknown evidence.",
        lambda doc: mutate(doc, "S04-frame-access", decision_status="unknown"),
    ),
    (
        "global-z-order-inferred",
        "Infer a page-global z-order from one screenshot pair.",
        lambda doc: mutate(
            doc,
            "S08-global-z-order",
            authority="screenshot",
            decision_status="authoritative",
            selected_value=["ctx-low", "ctx-high"],
        ),
    ),
    (
        "naive-dom-order-wins",
        "Use DOM order instead of the sampled local occlusion relation.",
        lambda doc: mutate(
            doc,
            "S08-local-occlusion",
            selected_value="ctx-low-above-ctx-high-at-p1",
        ),
    ),
    (
        "ocr-candidate-release",
        "Mark inaccessible iframe OCR as release eligible.",
        lambda doc: mutate(doc, "S04-text-content", release_eligible=True),
    ),
    (
        "semantic-promotion-guard-removed",
        "Remove the explicit semantic promotion guard from canvas text.",
        lambda doc: mutate(doc, "S02-text-content", cannot_promote=[]),
    ),
    (
        "whole-node-screenshot-authority",
        "Add a forbidden whole-node authority map.",
        lambda doc: doc.__setitem__("node_authorities", {"S02-canvas": "screenshot"}),
    ),
    (
        "pixel-color-replaces-css",
        "Replace declared CSS color with composited pixels.",
        lambda doc: mutate(
            doc,
            "S08-css-color-composite",
            selected_value=get_row(doc, "S08-composited-pixel-color")["selected_value"],
        ),
    ),
]


def run_mutations(document: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    base_errors = validate_contract(document, baseline)
    items: list[dict[str, Any]] = []
    for mutation_id, description, apply in MUTATION_SPECS:
        candidate = copy.deepcopy(document)
        apply(candidate)
        errors = validate_contract(candidate, baseline)
        items.append(
            {
                "mutation_id": mutation_id,
                "description": description,
                "rejected": bool(errors),
                "error_count": len(errors),
                "errors": errors[:12],
            }
        )
    rejected = sum(1 for item in items if item["rejected"])
    return {
        "base_valid": not base_errors,
        "base_errors": base_errors,
        "total": len(items),
        "rejected": rejected,
        "accepted": len(items) - rejected,
        "items": items,
    }


def base_pixels(capture: dict[str, Any]) -> dict[str, dict[str, float]]:
    dom = capture["dom_m1"]
    s01_rect = dom["S01"]["cssSwatch"]["rect"]
    overlay_rect = dom["S02"]["overlayRect"]
    stack_sample = dom["S08"]["sample"]
    composite_sample = dom["S08"]["compositeSample"]
    if not all([s01_rect, overlay_rect, stack_sample, composite_sample]):
        raise RuntimeError("Required pixel sample geometry is missing")
    return {
        "S01": {
            "x": s01_rect["x"] + s01_rect["width"] / 2,
            "y": s01_rect["y"] + s01_rect["height"] / 2,
        },
        "S02": {
            "x": overlay_rect["x"] + overlay_rect["width"] - 8,
            "y": overlay_rect["y"] + overlay_rect["height"] - 8,
        },
        "S08-stack": stack_sample,
        "S08-composite": composite_sample,
    }


def run_checks(
    capture: dict[str, Any],
    ocr: dict[str, Any],
    pixels: dict[str, Any],
    matrix: dict[str, Any],
    baseline: dict[str, Any],
    mutations: dict[str, Any],
    out_dir: Path,
) -> list[dict[str, Any]]:
    dom = capture["dom_m1"]
    dom_m0 = capture["dom_m0"]
    rows = {row["row_id"]: row for row in matrix["rows"]}
    scene_captures = capture["scene_captures"]
    checks: list[dict[str, Any]] = []

    checks.append(
        check(
            "scene-coverage",
            "All eight authored scenes have a real Chromium capture.",
            len(scene_captures) == 8
            and all(Path(item["path"]).exists() for item in scene_captures.values()),
            sorted(scene_captures),
        )
    )
    checks.append(
        check(
            "text-transform-separated",
            "Raw source text, innerText and the generated counter remain distinct.",
            dom["S01"]["textContent"] == EXPECTED_TEXT["counter_raw"]
            and dom["S01"]["innerText"] == EXPECTED_TEXT["counter_visible_dom"]
            and "counter(" in (dom["S01"]["pseudo"]["content"] or "")
            and dom["S01"]["computed"]["textTransform"] == "uppercase",
            dom["S01"],
        )
    )
    checks.append(
        check(
            "counter-visible-through-ocr",
            "Screenshot OCR recovers the generated counter prefix.",
            ocr["S01"]["match"],
            ocr["S01"],
        )
    )
    checks.append(
        check(
            "canvas-source-vs-visible",
            "Canvas fallback text differs from bitmap glyph OCR.",
            normalize_space(dom["S02"]["canvasFallbackText"]) != EXPECTED_TEXT["canvas_visible"]
            and ocr["S02"]["match"],
            {"fallback": dom["S02"]["canvasFallbackText"], "ocr": ocr["S02"]["raw_text"]},
        )
    )
    checks.append(
        check(
            "accessible-iframe-scope",
            "The accessible iframe is page-readable and keeps heading semantics.",
            dom["S03"]["pageAccess"] is True
            and dom["S03"]["pageText"] == EXPECTED_TEXT["accessible_frame"]
            and capture["accessible_frame_dom"]["role"] == "heading"
            and ocr["S03"]["match"],
            {
                "pageAccess": dom["S03"]["pageAccess"],
                "frame": capture["accessible_frame_dom"],
                "ocr": ocr["S03"],
            },
        )
    )
    checks.append(
        check(
            "inaccessible-iframe-is-unsupported",
            "The sandboxed iframe cannot be read as an empty DOM document.",
            dom["S04"]["pageAccess"] is False
            and "allow-same-origin" not in (dom["S04"]["sandbox"] or "")
            and rows["S04-frame-access"]["decision_status"] == "unsupported"
            and rows["S04-text-content"]["authority"] == "screenshot",
            dom["S04"],
        )
    )
    checks.append(
        check(
            "closed-shadow-not-claimed",
            "Closed shadow content remains screenshot evidence only.",
            dom["S05"]["shadowRoot"] is None
            and rows["S05-shadow-access"]["decision_status"] == "unsupported"
            and ocr["S05"]["match"],
            {"shadowRoot": dom["S05"]["shadowRoot"], "ocr": ocr["S05"]},
        )
    )
    checks.append(
        check(
            "hidden-legacy-not-written",
            "display:none legacy copy stays in raw text and out of visible text.",
            EXPECTED_TEXT["hidden_legacy"] in normalize_space(dom["S06"]["rawText"])
            and EXPECTED_TEXT["hidden_legacy"] not in normalize_space(dom["S06"]["visibleText"])
            and ocr["S06"]["match"],
            dom["S06"],
        )
    )
    checks.append(
        check(
            "hydration-state-gate",
            "M0 and M1 are separated; only M1 becomes current text.",
            dom_m0["S07"]["rawText"] == EXPECTED_TEXT["hydration_old"]
            and dom["S07"]["rawText"] == EXPECTED_TEXT["hydration_live"]
            and ocr["S07_M0"]["match"]
            and ocr["S07_M1"]["match"]
            and rows["S07-state-signature"]["decision_status"] == "external-conflict",
            {"m0": dom_m0["S07"], "m1": dom["S07"]},
        )
    )
    high_color = dom["S08"]["highComputed"]["backgroundColor"]
    low_color = dom["S08"]["lowComputed"]["backgroundColor"]
    stack_pixel = pixels["S08"]["stack-overlap"]["css"]
    checks.append(
        check(
            "local-stacking-sampled",
            "The overlap pixel selects the earlier DOM context, disproving naive last-in-DOM ordering.",
            stack_pixel == high_color
            and stack_pixel != low_color
            and dom["S08"]["domOrder"] == ["ctx-high", "ctx-low"],
            {
                "highColor": high_color,
                "lowColor": low_color,
                "pixel": pixels["S08"]["stack-overlap"],
                "domOrder": dom["S08"]["domOrder"],
            },
        )
    )
    checks.append(
        check(
            "css-vs-composited-color",
            "CSS declarations and composited pixels remain separate observations.",
            rows["S01-css-declared-color"]["selected_value"]
            != rows["S01-composited-pixel-color"]["selected_value"]
            and rows["S08-css-color-composite"]["selected_value"]
            != rows["S08-composited-pixel-color"]["selected_value"],
            {
                "S01Css": rows["S01-css-declared-color"]["selected_value"],
                "S01Pixel": rows["S01-composited-pixel-color"]["selected_value"],
                "S08Css": rows["S08-css-color-composite"]["selected_value"],
                "S08Pixel": rows["S08-composited-pixel-color"]["selected_value"],
            },
        )
    )
    checks.append(
        check(
            "four-observations-separated",
            "Raw text, visible text, CSS color and pixel color exist as separate field rows.",
            {"raw-dom-text", "visible-dom-text", "css-declared-color", "composited-pixel-color"}
            .issubset({row["field_type"] for row in matrix["rows"]}),
            sorted({row["field_type"] for row in matrix["rows"]}),
        )
    )
    checks.append(
        check(
            "three-unresolved-states",
            "external-conflict, unknown and unsupported all remain visible.",
            {"external-conflict", "unknown", "unsupported"}
            .issubset({row["decision_status"] for row in matrix["rows"]}),
            Counter(row["decision_status"] for row in matrix["rows"]),
        )
    )
    checks.append(
        check(
            "ocr-content-only",
            "Screenshot/OCR text never owns role, editability or asset-source.",
            not any(
                row["authority"] == "screenshot"
                and row["field_type"] in {"role", "editability", "asset-source"}
                for row in matrix["rows"]
            )
            and all(
                {"role", "editability", "asset-source"}.issubset(set(row["cannot_promote"]))
                for row in matrix["rows"]
                if row["field_type"] == "text-content" and "screenshot" in row["authority"]
            ),
            [
                {
                    "row": row["row_id"],
                    "authority": row["authority"],
                    "cannot_promote": row["cannot_promote"],
                }
                for row in matrix["rows"]
                if row["field_type"] == "text-content"
            ],
        )
    )
    checks.append(
        check(
            "no-global-z-order",
            "No page-global z-order is inferred from screenshot order.",
            rows["S08-global-z-order"]["decision_status"] == "unsupported"
            and rows["S08-global-z-order"]["selected_value"] is None,
            rows["S08-global-z-order"],
        )
    )
    checks.append(
        check(
            "base-contract-valid",
            "The base matrix passes the same validator used for mutations.",
            not validate_contract(matrix, baseline),
            validate_contract(matrix, baseline),
        )
    )
    checks.append(
        check(
            "negative-mutations-rejected",
            "Every targeted invalid authority or promotion mutation is rejected.",
            mutations["rejected"] == mutations["total"] and mutations["accepted"] == 0,
            {"rejected": mutations["rejected"], "total": mutations["total"]},
        )
    )
    checks.append(
        check(
            "capture-files-present",
            "All full-page, scene and OCR source artifacts exist.",
            all(Path(item["path"]).exists() for item in capture["ocr_sources"].values())
            and Path(capture["full_page"]["m0"]["path"]).exists()
            and Path(capture["full_page"]["m1"]["path"]).exists(),
            {
                "ocr_sources": len(capture["ocr_sources"]),
                "full_page": list(capture["full_page"]),
            },
        )
    )
    checks.append(
        check(
            "browser-observed",
            "The runs used real headless Chromium, not a fixed JSON fallback.",
            bool(capture["browser"].get("version"))
            and dom.get("fixtureReady") is True
            and dom["viewport"]["dpr"] == DPR,
            capture["browser"],
        )
    )
    return checks


def status_style(status: str) -> tuple[str, str]:
    return {
        "authoritative": ("#dcfce7", "#166534"),
        "observed": ("#dbeafe", "#1d4ed8"),
        "candidate": ("#fef3c7", "#92400e"),
        "external-conflict": ("#fee2e2", "#991b1b"),
        "unknown": ("#e5e7eb", "#374151"),
        "unsupported": ("#ede9fe", "#5b21b6"),
        "not-applicable": ("#ffffff", "#94a3b8"),
    }.get(status, ("#ffffff", "#334155"))


def authority_label(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "N/A"
    statuses = {row["decision_status"] for row in rows}
    if "external-conflict" in statuses:
        return "CONFLICT"
    if "unsupported" in statuses:
        return "UNSUPPORTED"
    if "unknown" in statuses:
        return "UNKNOWN"
    authorities = {row["authority"] for row in rows}
    if authorities == {"dom"}:
        label = "DOM"
    elif authorities == {"screenshot"}:
        label = "SHOT"
    elif authorities == {"dom+screenshot"} or authorities == {"dom", "screenshot"}:
        label = "DOM+SHOT"
    elif authorities == {"none"}:
        label = "NONE"
    else:
        label = "+".join(sorted(authority.upper() for authority in authorities))
    if "candidate" in statuses:
        label += " CAND"
    elif "observed" in statuses and "authoritative" not in statuses:
        label += " OBS"
    return label


def matrix_categories() -> dict[tuple[str, str], list[str]]:
    return {
        ("S01", "Text"): ["S01-text-content"],
        ("S01", "Raw/visible"): ["S01-raw-dom-text", "S01-visible-dom-text", "S01-screenshot-ocr-text"],
        ("S01", "Color"): ["S01-css-declared-color", "S01-composited-pixel-color"],
        ("S01", "Semantics"): ["S01-role", "S01-editability"],
        ("S02", "Text"): ["S02-text-content"],
        ("S02", "Raw/visible"): ["S02-raw-dom-text"],
        ("S02", "Semantics"): ["S02-role", "S02-editability"],
        ("S02", "Asset"): ["S02-asset-source"],
        ("S02", "Stack"): ["S02-local-occlusion"],
        ("S03", "Text"): ["S03-text-content"],
        ("S03", "Raw/visible"): ["S03-raw-dom-text"],
        ("S03", "Semantics"): ["S03-role", "S03-editability"],
        ("S03", "Scope/state"): ["S03-frame-access", "S03-document-scope"],
        ("S04", "Text"): ["S04-text-content"],
        ("S04", "Semantics"): ["S04-role", "S04-editability"],
        ("S04", "Asset"): ["S04-asset-source"],
        ("S04", "Scope/state"): ["S04-frame-access", "S04-document-scope"],
        ("S05", "Text"): ["S05-text-content"],
        ("S05", "Semantics"): ["S05-role", "S05-editability"],
        ("S05", "Asset"): ["S05-asset-source"],
        ("S05", "Scope/state"): ["S05-shadow-access"],
        ("S06", "Text"): ["S06-text-content"],
        ("S06", "Raw/visible"): ["S06-raw-dom-text", "S06-visible-dom-text"],
        ("S06", "Semantics"): ["S06-role", "S06-editability"],
        ("S06", "Scope/state"): ["S06-visibility"],
        ("S07", "Text"): ["S07-text-content"],
        ("S07", "Raw/visible"): ["S07-stale-raw-dom-text", "S07-stale-screenshot-ocr-text"],
        ("S07", "Semantics"): ["S07-role", "S07-editability"],
        ("S07", "Scope/state"): ["S07-state-signature"],
        ("S08", "Color"): ["S08-high-css-color", "S08-low-css-color", "S08-css-color-composite", "S08-composited-pixel-color"],
        ("S08", "Scope/state"): ["S08-geometry"],
        ("S08", "Stack"): ["S08-local-occlusion"],
        ("S08", "Global order"): ["S08-global-z-order"],
    }


def plot_authority_matrix(matrix: dict[str, Any], path: Path) -> None:
    rows = {row["row_id"]: row for row in matrix["rows"]}
    columns = ("Text", "Raw/visible", "Color", "Semantics", "Asset", "Scope/state", "Stack", "Global order")
    cells = matrix_categories()
    fig, ax = plt.subplots(figsize=(18, 8.2))
    ax.set_axis_off()
    fig.text(
        0.025,
        0.965,
        "R5-EXP-03 · Field authority matrix",
        fontsize=22,
        fontweight="bold",
        va="top",
        color="#0f172a",
    )
    fig.text(
        0.025,
        0.925,
        "DOM owns source/semantic facts; screenshots own rendered evidence. Cells show field-level decisions, never whole-node authority.",
        fontsize=10.5,
        va="top",
        color="#475569",
    )
    table_data: list[list[str]] = []
    cell_colors: list[list[str]] = []
    y = 0.89
    x_positions = [0.10] + [0.10 + 0.108 * index for index in range(len(columns))]
    for index, column in enumerate(columns):
        ax.text(
            x_positions[index + 1],
            0.90,
            column,
            ha="center",
            va="center",
            fontsize=10.5,
            fontweight="bold",
            color="#334155",
        )
    for scene_index, scene_id in enumerate(SCENE_IDS):
        y = 0.84 - scene_index * 0.092
        ax.text(0.04, y, scene_id, ha="left", va="center", fontsize=11, fontweight="bold", color="#0f172a")
        for column_index, column in enumerate(columns):
            ids = cells.get((scene_id, column), [])
            selected_rows = [rows[row_id] for row_id in ids if row_id in rows]
            label = authority_label(selected_rows)
            if selected_rows:
                priority = {
                    "external-conflict": 6,
                    "unsupported": 5,
                    "unknown": 4,
                    "candidate": 3,
                    "observed": 2,
                    "authoritative": 1,
                }
                dominant = max(selected_rows, key=lambda row: priority.get(row["decision_status"], 0))
                face, text_color = status_style(dominant["decision_status"])
            else:
                face, text_color = status_style("not-applicable")
            rect = plt.Rectangle(
                (x_positions[column_index + 1] - 0.050, y - 0.036),
                0.100,
                0.072,
                facecolor=face,
                edgecolor="#cbd5e1",
                linewidth=0.8,
            )
            ax.add_patch(rect)
            ax.text(
                x_positions[column_index + 1],
                y,
                label,
                ha="center",
                va="center",
                fontsize=8.4,
                fontweight="bold",
                color=text_color,
            )
    legend = (
        "Green authoritative · Blue observed · Yellow candidate · Red external-conflict · "
        "Gray unknown · Purple unsupported · White not applicable"
    )
    ax.text(0.04, 0.03, legend, fontsize=9, color="#475569", va="center")
    fig.subplots_adjust(left=0.02, right=0.995, top=0.96, bottom=0.02)
    fig.savefig(path, dpi=160, facecolor="#f8fafc")
    plt.close(fig)


def plot_report(
    matrix: dict[str, Any],
    checks: list[dict[str, Any]],
    mutations: dict[str, Any],
    pixels: dict[str, Any],
    path: Path,
) -> None:
    statuses = Counter(row["decision_status"] for row in matrix["rows"])
    fig = plt.figure(figsize=(17, 9.4), facecolor="#f8fafc")
    grid = fig.add_gridspec(2, 2, width_ratios=[1.0, 1.15], height_ratios=[1.0, 1.15])

    ax1 = fig.add_subplot(grid[0, 0])
    names = ["authoritative", "observed", "candidate", "external-conflict", "unknown", "unsupported"]
    values = [statuses.get(name, 0) for name in names]
    colors = [status_style(name)[0] for name in names]
    ax1.barh(names, values, color=colors, edgecolor="#94a3b8")
    ax1.set_title("Field decision status", loc="left", fontsize=14, fontweight="bold", color="#0f172a")
    ax1.tick_params(axis="both", labelsize=9, colors="#334155")
    ax1.grid(axis="x", color="#e2e8f0", linewidth=0.8)
    ax1.set_axisbelow(True)

    ax2 = fig.add_subplot(grid[0, 1])
    ax2.set_axis_off()
    passed = sum(1 for item in checks if item["passed"])
    lines = [
        f"Contract checks: {passed}/{len(checks)}",
        f"Negative mutations rejected: {mutations['rejected']}/{mutations['total']}",
        f"Field rows: {len(matrix['rows'])} across {len(SCENE_IDS)} scenes",
        f"Global z-order: {get_row(matrix, 'S08-global-z-order')['decision_status']}",
        "",
        f"Stack overlap pixel: {pixels['S08']['stack-overlap']['css']}",
        f"Composite CSS red + opacity: {pixels['S08']['composite']['css']}",
        "Canvas, closed shadow and sandboxed iframe remain screenshot candidates.",
        "OCR never owns role, editability or asset-source.",
    ]
    ax2.text(0.01, 0.94, "Run summary", fontsize=16, fontweight="bold", color="#0f172a", va="top")
    ax2.text(
        0.01,
        0.83,
        "\n".join(lines),
        fontsize=11,
        color="#334155",
        va="top",
        linespacing=1.45,
    )

    ax3 = fig.add_subplot(grid[1, :])
    ax3.set_axis_off()
    ax3.text(0.0, 1.0, "Key observations", fontsize=15, fontweight="bold", color="#0f172a", va="top")
    observations = [
        "S01: textContent='sale item alpha'; innerText='SALE ITEM ALPHA'; screenshot adds the CSS counter prefix.",
        "S02: the visible canvas glyphs are bitmap evidence; the DOM fallback is not the visible text.",
        "S03: the same-origin child document supplies text, heading role and static editability.",
        "S04: sandboxed DOM access is unsupported, not empty; OCR can only propose text content.",
        "S05: the host role is DOM-visible, while the closed shadow descendants remain unknown.",
        "S06: hidden legacy text stays in textContent and is excluded from visible text and output.",
        "S07: M0 and M1 are external-conflict; only the current M1 evidence is comparable.",
        "S08: the earlier DOM context remains visually on top; only a sampled local occlusion is claimed.",
    ]
    ax3.text(
        0.01,
        0.88,
        "\n".join(observations),
        fontsize=10.5,
        color="#334155",
        va="top",
        linespacing=1.6,
    )
    fig.suptitle(
        "R5-EXP-03 · Rendered evidence and field-level authority",
        x=0.03,
        y=0.985,
        ha="left",
        fontsize=20,
        fontweight="bold",
        color="#0f172a",
    )
    fig.subplots_adjust(left=0.08, right=0.97, top=0.91, bottom=0.06, hspace=0.35, wspace=0.25)
    fig.savefig(path, dpi=160, facecolor="#f8fafc")
    plt.close(fig)


def font_for(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def make_contact_sheet(capture: dict[str, Any], path: Path) -> None:
    thumb_width = 720
    label_height = 40
    gap = 18
    columns = 2
    items: list[tuple[str, str, Image.Image]] = []
    for scene_id, title in SCENES:
        image_path = Path(capture["scene_captures"][scene_id]["path"])
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        ratio = thumb_width / image.width
        thumb = image.resize((thumb_width, max(1, int(image.height * ratio))), Image.Resampling.LANCZOS)
        items.append((scene_id, title, thumb))
    row_heights = []
    for index in range(0, len(items), columns):
        row_heights.append(max(item[2].height for item in items[index : index + columns]) + label_height)
    canvas_width = columns * thumb_width + (columns + 1) * gap
    canvas_height = sum(row_heights) + (len(row_heights) + 1) * gap + 62
    canvas = Image.new("RGB", (canvas_width, canvas_height), "#e8edf4")
    draw = ImageDraw.Draw(canvas)
    draw.text((gap, 18), "R5-EXP-03 · Real Chromium scene captures", fill="#0f172a", font=font_for(25, True))
    y = 62 + gap
    for row_index in range(0, len(items), columns):
        row = items[row_index : row_index + columns]
        for column_index, (scene_id, title, image) in enumerate(row):
            x = gap + column_index * (thumb_width + gap)
            draw.rounded_rectangle(
                (x - 1, y - 1, x + thumb_width, y + image.height + label_height),
                radius=7,
                fill="#ffffff",
                outline="#cbd5e1",
            )
            canvas.paste(image, (x, y))
            draw.text(
                (x + 12, y + image.height + 9),
                f"{scene_id} · {title}",
                fill="#0f172a",
                font=font_for(15, True),
            )
        y += row_heights[row_index // columns] + gap
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def annotate_stack_sample(capture: dict[str, Any], pixels: dict[str, Any], path: Path) -> None:
    full_path = Path(capture["full_page"]["m1"]["path"])
    scene = capture["scene_captures"]["S08"]
    sample = capture["dom_m1"]["S08"]["sample"]
    with Image.open(full_path) as image:
        rgb = image.convert("RGB")
        x = int(round(sample["x"]))
        y = int(round(sample["y"]))
        left = max(0, x - 260)
        top = max(0, y - 120)
        right = min(rgb.width, x + 300)
        bottom = min(rgb.height, y + 130)
        crop = rgb.crop((left, top, right, bottom))
        draw = ImageDraw.Draw(crop)
        cx = x - left
        cy = y - top
        draw.ellipse((cx - 16, cy - 16, cx + 16, cy + 16), outline="#dc2626", width=4)
        draw.line((cx - 30, cy, cx + 30, cy), fill="#dc2626", width=2)
        draw.line((cx, cy - 30, cx, cy + 30), fill="#dc2626", width=2)
        draw.rectangle((10, 10, 390, 68), fill="#0f172a", outline="#f8fafc", width=2)
        draw.text(
            (22, 20),
            f"local sample {pixels['S08']['stack-overlap']['css']}",
            fill="#f8fafc",
            font=font_for(20, True),
        )
        crop.save(path)
    del scene


def input_digest(capture: dict[str, Any]) -> str:
    digest_input = {
        "fixture_sha256": capture["fixture_sha256"],
        "browser": capture["browser"],
        "scene_captures": {
            key: value["sha256"] for key, value in capture["scene_captures"].items()
        },
        "ocr_sources": {
            key: value["sha256"] for key, value in capture["ocr_sources"].items()
        },
        "full_page": {
            key: value["sha256"] for key, value in capture["full_page"].items()
        },
    }
    return sha256_text(canonical(digest_input))


BOUNDARY = {
    "browser": "Headless Chromium only; no Firefox, WebKit, mobile emulation or browser UI zoom.",
    "fixture": "Eight authored local scenes; not a sample of real sites or web applications.",
    "ocr": "Tesseract on authored high-contrast English text; not a general OCR accuracy benchmark.",
    "pixels": "Point samples at authored integer-aligned regions; not an automatic occlusion detector.",
    "runtime": "No Figma, bridge, production capture pipeline or write path is used.",
    "scope": "Current-scope contract evidence only; no production authority implementation is verified.",
}

LIMITATIONS = [
    "The matrix is derived from one authored page in one Chromium build at DPR 1.",
    "CSS generated content, canvas drawing and closed shadow content are isolated fixtures, not real application behavior.",
    "The sandboxed iframe tests page-script inaccessibility; Playwright can still control the browser and screenshot the region.",
    "Canvas and shadow OCR candidates are promoted only as text proposals and are not release eligible.",
    "The stacking scene records one local overlap sample; it cannot recover page-global z-order.",
    "Only two color examples are sampled; opacity, blend modes, filters and antialiasing are not exhaustively covered.",
    "The experiment does not run the production DOM collector, fusion engine or Figma writer.",
    "No accessibility-tree comparison, user comprehension study or cross-browser state calibration was performed.",
    "The negative mutations prove only that the listed invalid modifications are rejected by this validator.",
    "A passing run does not establish correctness for arbitrary sites, dynamic composition, or production data.",
]


def print_summary(result: dict[str, Any]) -> None:
    checks = result["checks"]
    passed = sum(1 for item in checks if item["passed"])
    print(f"status={result['status']}")
    print(f"checks={passed}/{len(checks)}")
    print(
        "mutations=%s/%s rejected"
        % (result["mutations"]["rejected"], result["mutations"]["total"])
    )
    print(f"rows={result['matrix_summary']['row_count']}")
    print(f"content_hash={result['content_hash']}")
    print(f"out={result['output_directory']}")
    for item in checks:
        if not item["passed"]:
            print(f"FAILED CHECK: {item['name']} :: {item['detail']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R5-EXP-03 field authority matrix.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    out_dir = safe_output_dir(args.out)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture_dir = out_dir / "fixtures"

    print("Capturing authored scenes with headless Chromium...")
    capture = capture_all(fixture_dir, out_dir)

    samples = base_pixels(capture)
    flat_pixels = sample_pixels(
        Path(capture["full_page"]["m1"]["path"]),
        {
            "S01": samples["S01"],
            "S02": samples["S02"],
            "S08-stack-overlap": samples["S08-stack"],
            "S08-composite": samples["S08-composite"],
        },
    )
    pixels = {
        "S01": flat_pixels["S01"],
        "S02": flat_pixels["S02"],
        "S08": {
            "stack-overlap": flat_pixels["S08-stack-overlap"],
            "composite": flat_pixels["S08-composite"],
        },
    }
    ocr = run_ocr(
        capture["ocr_sources"],
        {
            "S01": EXPECTED_TEXT["counter_visible_with_pseudo"],
            "S02": EXPECTED_TEXT["canvas_visible"],
            "S03": EXPECTED_TEXT["accessible_frame"],
            "S04": EXPECTED_TEXT["blocked_frame"],
            "S05": EXPECTED_TEXT["closed_shadow"],
            "S06": EXPECTED_TEXT["current_price"],
            "S07_M0": EXPECTED_TEXT["hydration_old"],
            "S07_M1": EXPECTED_TEXT["hydration_live"],
        },
    )

    print("Building field-level authority matrix...")
    matrix = build_matrix(capture, ocr, pixels)
    baseline = freeze_contract(matrix)
    mutations = run_mutations(matrix, baseline)
    checks = run_checks(capture, ocr, pixels, matrix, baseline, mutations, out_dir)

    matrix_visual = out_dir / "r5_exp_03_authority_matrix.png"
    report_visual = out_dir / "r5_exp_03_evidence_report.png"
    contact_sheet = out_dir / "r5_exp_03_contact_sheet.png"
    stack_visual = out_dir / "r5_exp_03_stack_sample.png"
    plot_authority_matrix(matrix, matrix_visual)
    plot_report(matrix, checks, mutations, pixels, report_visual)
    make_contact_sheet(capture, contact_sheet)
    annotate_stack_sample(capture, pixels, stack_visual)

    matrix["content_hash"] = content_hash(matrix)
    matrix_path = out_dir / "matrix.json"
    mutations_path = out_dir / "mutations.json"
    atomic_write_json(matrix_path, matrix)
    atomic_write_json(mutations_path, mutations)

    all_checks_passed = all(item["passed"] for item in checks)
    status = "completed-for-current-scope" if all_checks_passed and mutations["accepted"] == 0 else "failed"
    visual_files = {}
    for path in (matrix_visual, report_visual, contact_sheet, stack_visual):
        visual_files[path.name] = {
            "path": str(path),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }

    result: dict[str, Any] = {
        "job": JOB,
        "revision": REVISION,
        "profile": PROFILE,
        "status": status,
        "generated_at": CAPTURED_AT,
        "output_directory": str(out_dir),
        "environment": {
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "playwright": package_version("playwright"),
            "pytesseract": package_version("pytesseract"),
            "pillow": package_version("Pillow"),
            "matplotlib": package_version("matplotlib"),
            "tesseract": ocr["S01"]["engine_version"],
            "chromium": capture["browser"]["version"],
        },
        "inputs": {
            "fixture": str(Path(capture["fixture"])),
            "fixture_sha256": capture["fixture_sha256"],
            "scene_captures": capture["scene_captures"],
            "ocr_sources": capture["ocr_sources"],
            "full_page": capture["full_page"],
            "input_digest": input_digest(capture),
        },
        "observations": {
            "browser": capture["browser"],
            "dom_m0": capture["dom_m0"],
            "dom_m1": capture["dom_m1"],
            "accessible_frame_dom": capture["accessible_frame_dom"],
            "ocr": ocr,
            "pixels": pixels,
        },
        "matrix_summary": {
            "row_count": len(matrix["rows"]),
            "scene_count": len(SCENES),
            "field_count": len({row["field_type"] for row in matrix["rows"]}),
            "status_counts": dict(Counter(row["decision_status"] for row in matrix["rows"])),
            "authority_counts": dict(Counter(row["authority"] for row in matrix["rows"])),
            "matrix_path": str(matrix_path),
            "matrix_sha256": sha256_file(matrix_path),
        },
        "checks": checks,
        "mutations": mutations,
        "visuals": visual_files,
        "boundary": BOUNDARY,
        "limitations": LIMITATIONS,
        "release_claims": {
            "experiment_status": "completed-for-current-scope" if all_checks_passed else "failed",
            "verified": False,
            "production_ready": False,
            "figma_connected": False,
            "source_modified": False,
        },
    }
    result["content_hash"] = content_hash(result)
    atomic_write_json(out_dir / "result.json", result)
    print_summary(result)
    return 0 if all_checks_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
