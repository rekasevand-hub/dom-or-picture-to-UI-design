# -*- coding: utf-8 -*-
"""Smoke D: real Figma Auto Layout, strict font failure and partial occlusion.

Prerequisites:
  1) ``python -m src.app.services.bridge_server`` listens on ws://localhost:8765
  2) The Figma development plugin from ``figma_bridge/manifest.json`` is running
  3) The plugin has loaded the experimental actions ``set_layout_flow`` and
     ``font_strict_probe`` from ``figma_bridge/code.js``

Usage:
  python scripts/figma_smoke_d.py --out output/_figma_smoke_d
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402
from src.config.settings import load_config  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT_NAME = "SmokeD Root"
MISSING_FONT = "DefinitelyMissingFont_9f3a"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "content_hash"}
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def check(check_id: str, description: str, passed: bool, detail: Any) -> dict[str, Any]:
    return {"id": check_id, "description": description, "passed": bool(passed), "detail": detail}


def find_node(node: dict[str, Any], name: str) -> dict[str, Any] | None:
    if node.get("name") == name:
        return node
    for child in node.get("children") or []:
        found = find_node(child, name)
        if found is not None:
            return found
    return None


def close_enough(actual: Any, expected: Any, tol: float = 0.5) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= tol
    except (TypeError, ValueError):
        return False


def rect_of(node: dict[str, Any]) -> list[Any]:
    return [node.get("x"), node.get("y"), node.get("width"), node.get("height")]


def rect_matches(node: dict[str, Any], expected: list[float], tol: float = 0.5) -> bool:
    return all(close_enough(a, e, tol) for a, e in zip(rect_of(node), expected))


def pixel_matches(image: Image.Image, xy: tuple[int, int], hex_color: str, tol: int = 4) -> bool:
    if not (0 <= xy[0] < image.width and 0 <= xy[1] < image.height):
        return False
    actual = image.getpixel(xy)[:3]
    expected = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return all(abs(a - e) <= tol for a, e in zip(actual, expected))


def export_png(adapter: FigmaBridgeAdapter, node_id: str, path: Path) -> dict[str, Any]:
    exported = adapter._send("export_frame", {"nodeId": node_id, "scale": 1})
    raw = base64.b64decode(exported["base64"])
    path.write_bytes(raw)
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    return {
        "path": str(path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "width": image.width,
        "height": image.height,
        "image": image,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="output/_figma_smoke_d", help="artifact directory")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    adapter = FigmaBridgeAdapter(cfg.figma_bridge_url)
    try:
        adapter.connect()
    except Exception as exc:  # noqa: BLE001 - report the exact connection failure
        print(f"[FAIL] 连不上桥接服务器 {cfg.figma_bridge_url}: {type(exc).__name__}: {exc}")
        return 2

    print(f"[conn] {cfg.figma_bridge_url}")
    events: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    renders: dict[str, Any] = {}
    root_tree: dict[str, Any] = {}
    page_before_strict: dict[str, Any] = {}
    page_after_strict: dict[str, Any] = {}
    strict_error = ""
    font_probe: dict[str, Any] = {}
    strict_probe: dict[str, Any] = {}

    try:
        cleaned = adapter._send("remove_nodes_by_name", {"name": ROOT_NAME, "prefix": False})
        events.append({"step": "clean", "result": cleaned})

        root_id = adapter._send("create_frame", {
            "name": ROOT_NAME,
            "x": 0,
            "y": 0,
            "width": 1000,
            "height": 640,
            "fillColor": "#ffffff",
        })
        events.append({"step": "create_frame", "name": ROOT_NAME, "nodeId": root_id})

        al_col_id = adapter._send("create_frame", {
            "name": "AL Column",
            "parentId": root_id,
            "x": 40,
            "y": 40,
            "width": 320,
            "height": 200,
            "fillColor": "#f8fafc",
            "clipsContent": True,
        })
        for name, width, height, color in [
            ("AL Item 0", 100, 40, "#2563eb"),
            ("AL Item 1", 120, 40, "#16a34a"),
            ("AL Item 2", 80, 40, "#dc2626"),
        ]:
            adapter._send("create_rectangle", {
                "name": name,
                "parentId": al_col_id,
                "x": 0,
                "y": 0,
                "width": width,
                "height": height,
                "fillColor": color,
            })

        al_col = adapter._send("set_layout_flow", {
            "nodeId": al_col_id,
            "layout": {
                "mode": "VERTICAL",
                "itemSpacing": 12,
                "paddingTop": 16,
                "paddingRight": 16,
                "paddingBottom": 16,
                "paddingLeft": 16,
                "primaryAxisSizingMode": "AUTO",
                "counterAxisSizingMode": "FIXED",
            },
            "children": [{"index": 0, "layoutAlign": "STRETCH"}],
            "width": 320,
            "depth": 2,
        })
        col_items = al_col.get("children") or []
        checks.extend([
            check(
                "al-column-layout",
                "vertical Auto Layout applies mode, spacing, padding and fixed width",
                al_col.get("layoutMode") == "VERTICAL"
                and close_enough(al_col.get("itemSpacing"), 12)
                and all(close_enough(al_col.get(k), 16) for k in
                        ("paddingTop", "paddingRight", "paddingBottom", "paddingLeft"))
                and close_enough(al_col.get("width"), 320)
                and al_col.get("counterAxisSizingMode") == "FIXED",
                {k: al_col.get(k) for k in (
                    "width", "height", "layoutMode", "itemSpacing",
                    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
                    "primaryAxisSizingMode", "counterAxisSizingMode")},
            ),
            check(
                "al-column-hug-height",
                "vertical Auto Layout hugs its content height",
                close_enough(al_col.get("height"), 176),
                {"expected": 176, "actual": al_col.get("height")},
            ),
            check(
                "al-column-stretch",
                "layoutAlign=STRETCH fills the counter axis",
                len(col_items) == 3
                and rect_matches(col_items[0], [16, 16, 288, 40])
                and col_items[0].get("layoutAlign") == "STRETCH"
                and col_items[0].get("layoutSizingHorizontal") == "FILL",
                {"item0": rect_of(col_items[0]) if col_items else None,
                 "layoutAlign": col_items[0].get("layoutAlign") if col_items else None},
            ),
            check(
                "al-column-item-positions",
                "spacing and padding place the three items at the expected coordinates",
                len(col_items) == 3
                and rect_matches(col_items[0], [16, 16, 288, 40])
                and rect_matches(col_items[1], [16, 68, 120, 40])
                and rect_matches(col_items[2], [16, 120, 80, 40]),
                [{"name": c.get("name"), "rect": rect_of(c)} for c in col_items],
            ),
        ])

        adapter._send("create_rectangle", {
            "name": "AL Item 3",
            "parentId": al_col_id,
            "x": 0,
            "y": 0,
            "width": 90,
            "height": 40,
            "fillColor": "#f59e0b",
        })
        al_col_append = adapter._send("get_node_tree", {"nodeId": al_col_id, "depth": 2})
        append_items = al_col_append.get("children") or []
        checks.append(check(
            "al-column-append-reflow",
            "appending a child reflows the hugging Auto Layout frame",
            close_enough(al_col_append.get("height"), 228)
            and len(append_items) == 4
            and rect_matches(append_items[3], [16, 172, 90, 40]),
            {"height": al_col_append.get("height"),
             "items": [{"name": c.get("name"), "rect": rect_of(c)} for c in append_items]},
        ))

        al_col_resize = adapter._send("set_layout_flow", {
            "nodeId": al_col_id,
            "layout": {
                "mode": "VERTICAL",
                "itemSpacing": 12,
                "paddingTop": 16,
                "paddingRight": 16,
                "paddingBottom": 16,
                "paddingLeft": 16,
                "primaryAxisSizingMode": "AUTO",
                "counterAxisSizingMode": "FIXED",
            },
            "width": 360,
            "depth": 2,
        })
        resize_items = al_col_resize.get("children") or []
        checks.append(check(
            "al-column-resize-reflow",
            "resizing the frame reflows the stretched child without changing hug height",
            close_enough(al_col_resize.get("width"), 360)
            and close_enough(al_col_resize.get("height"), 228)
            and len(resize_items) == 4
            and rect_matches(resize_items[0], [16, 16, 328, 40]),
            {"width": al_col_resize.get("width"), "height": al_col_resize.get("height"),
             "item0": rect_of(resize_items[0]) if resize_items else None},
        ))

        al_row_id = adapter._send("create_frame", {
            "name": "AL Row",
            "parentId": root_id,
            "x": 440,
            "y": 40,
            "width": 400,
            "height": 80,
            "fillColor": "#f8fafc",
            "clipsContent": True,
        })
        for name, color in [("Row Item 0", "#2563eb"), ("Row Item 1", "#16a34a"), ("Row Item 2", "#dc2626")]:
            adapter._send("create_rectangle", {
                "name": name,
                "parentId": al_row_id,
                "x": 0,
                "y": 0,
                "width": 60,
                "height": 40,
                "fillColor": color,
            })
        al_row = adapter._send("set_layout_flow", {
            "nodeId": al_row_id,
            "layout": {
                "mode": "HORIZONTAL",
                "itemSpacing": 10,
                "paddingTop": 10,
                "paddingRight": 10,
                "paddingBottom": 10,
                "paddingLeft": 10,
                "primaryAxisSizingMode": "FIXED",
                "counterAxisSizingMode": "FIXED",
            },
            "children": [{"index": 1, "layoutGrow": 1, "layoutAlign": "STRETCH"}],
            "width": 400,
            "height": 80,
            "depth": 2,
        })
        row_items = al_row.get("children") or []
        checks.extend([
            check(
                "al-row-layout",
                "horizontal Auto Layout applies fixed size, spacing and padding",
                al_row.get("layoutMode") == "HORIZONTAL"
                and close_enough(al_row.get("width"), 400)
                and close_enough(al_row.get("height"), 80)
                and close_enough(al_row.get("itemSpacing"), 10)
                and all(close_enough(al_row.get(k), 10) for k in
                        ("paddingTop", "paddingRight", "paddingBottom", "paddingLeft")),
                {k: al_row.get(k) for k in (
                    "width", "height", "layoutMode", "itemSpacing",
                    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft")},
            ),
            check(
                "al-row-grow",
                "layoutGrow=1 consumes the remaining primary-axis width",
                len(row_items) == 3
                and rect_matches(row_items[1], [80, 10, 240, 60])
                and row_items[1].get("layoutGrow") == 1
                and row_items[1].get("layoutAlign") == "STRETCH",
                {"item1": rect_of(row_items[1]) if len(row_items) > 1 else None,
                 "layoutGrow": row_items[1].get("layoutGrow") if len(row_items) > 1 else None},
            ),
            check(
                "al-row-fixed-siblings",
                "fixed siblings keep their width on both sides of the growing child",
                len(row_items) == 3
                and rect_matches(row_items[0], [10, 10, 60, 40])
                and rect_matches(row_items[2], [330, 10, 60, 40]),
                [{"name": c.get("name"), "rect": rect_of(c)} for c in row_items],
            ),
        ])

        font_probe = adapter._send("font_probe", {"probes": [
            {"fontFamily": "Inter", "fontWeight": 700},
            {"fontFamily": MISSING_FONT, "fontWeight": 700},
        ]})
        strict_probe = adapter._send("font_strict_probe", {"probes": [
            {"fontFamily": MISSING_FONT, "fontWeight": 700},
            {"fontFamily": f"{MISSING_FONT}, Inter", "fontWeight": 700},
        ]})
        probe_results = font_probe.get("results") or []
        strict_results = strict_probe.get("results") or []
        checks.extend([
            check(
                "font-probe-inter",
                "Inter 700 resolves to Inter Bold without fallback",
                len(probe_results) >= 1
                and probe_results[0].get("picked", {}).get("family") == "Inter"
                and probe_results[0].get("picked", {}).get("style") == "Bold"
                and probe_results[0].get("fallback") is False,
                probe_results[0] if probe_results else None,
            ),
            check(
                "font-probe-missing-fallback",
                "current default probe silently falls back to Inter Regular (recorded policy gap)",
                len(probe_results) >= 2
                and probe_results[1].get("picked", {}).get("family") == "Inter"
                and probe_results[1].get("picked", {}).get("style") == "Regular"
                and probe_results[1].get("fallback") is True,
                probe_results[1] if len(probe_results) > 1 else None,
            ),
            check(
                "font-strict-missing-blocked",
                "strict probe reports the missing family as unavailable",
                len(strict_results) >= 1
                and strict_results[0].get("available") is False
                and "FONT_NOT_AVAILABLE" in str(strict_results[0].get("error", "")),
                strict_results[0] if strict_results else None,
            ),
            check(
                "font-strict-stack-resolves",
                "a requested stack containing Inter resolves inside that stack",
                len(strict_results) >= 2
                and strict_results[1].get("available") is True
                and strict_results[1].get("picked", {}).get("family") == "Inter"
                and strict_results[1].get("picked", {}).get("style") == "Bold",
                strict_results[1] if len(strict_results) > 1 else None,
            ),
        ])

        default_text_id = adapter._send("create_text", {
            "name": "Default Missing Font Text",
            "parentId": root_id,
            "x": 40,
            "y": 300,
            "width": 360,
            "height": 28,
            "text": "Default missing-font text",
            "fontFamily": MISSING_FONT,
            "fontWeight": 700,
            "fontSize": 20,
            "textColor": "#0f172a",
        })
        events.append({"step": "create_text", "name": "Default Missing Font Text",
                       "nodeId": default_text_id, "fontPolicy": "fallback"})

        page_before_strict = adapter._send("get_node_tree", {"depth": 1})
        try:
            adapter._send("create_text", {
                "name": "Strict Missing Font Text",
                "parentId": root_id,
                "x": 40,
                "y": 340,
                "width": 360,
                "height": 28,
                "text": "Strict missing-font text",
                "fontFamily": MISSING_FONT,
                "fontWeight": 700,
                "fontSize": 20,
                "textColor": "#0f172a",
                "fontPolicy": "strict",
            })
        except Exception as exc:  # noqa: BLE001 - expected strict failure
            raw_error = f"{type(exc).__name__}: {exc}"
            marker = "FONT_NOT_AVAILABLE:"
            if marker in raw_error:
                strict_error = f"{type(exc).__name__}: {marker} {raw_error.split(marker, 1)[1].strip()}"
            else:
                strict_error = raw_error
        page_after_strict = adapter._send("get_node_tree", {"depth": 1})

        strict_inter_id = adapter._send("create_text", {
            "name": "Strict Inter Text",
            "parentId": root_id,
            "x": 40,
            "y": 380,
            "width": 360,
            "height": 28,
            "text": "Strict Inter text",
            "fontFamily": "Inter",
            "fontWeight": 700,
            "fontSize": 20,
            "textColor": "#0f172a",
            "fontPolicy": "strict",
        })
        strict_stack_id = adapter._send("create_text", {
            "name": "Strict Stack Text",
            "parentId": root_id,
            "x": 40,
            "y": 420,
            "width": 360,
            "height": 28,
            "text": "Strict stack text",
            "fontFamily": f"{MISSING_FONT}, Inter",
            "fontWeight": 700,
            "fontSize": 20,
            "textColor": "#0f172a",
            "fontPolicy": "strict",
        })
        events.extend([
            {"step": "create_text", "name": "Strict Inter Text", "nodeId": strict_inter_id},
            {"step": "create_text", "name": "Strict Stack Text", "nodeId": strict_stack_id},
        ])
        page_before_count = len(page_before_strict.get("children") or [])
        page_after_count = len(page_after_strict.get("children") or [])

        occl_id = adapter._send("create_frame", {
            "name": "Occlusion Frame",
            "parentId": root_id,
            "x": 40,
            "y": 480,
            "width": 240,
            "height": 160,
            "fillColor": "#ffffff",
            "clipsContent": True,
        })
        adapter._send("create_rectangle", {
            "name": "Base", "parentId": occl_id, "x": 20, "y": 20,
            "width": 200, "height": 100, "fillColor": "#2563eb",
        })
        adapter._send("create_text", {
            "name": "Occluded Label",
            "parentId": occl_id,
            "x": 30,
            "y": 30,
            "width": 120,
            "height": 20,
            "text": "PARTIAL",
            "fontFamily": "Inter",
            "fontWeight": 700,
            "fontSize": 16,
            "textColor": "#ffffff",
            "fontPolicy": "strict",
        })
        for name, x, y, width, height, color in [
            ("Occluder", 70, 20, 100, 100, "#dc2626"),
            ("Clip Left", -40, 120, 80, 40, "#f59e0b"),
            ("Clip Bottom", 20, 140, 100, 40, "#16a34a"),
        ]:
            adapter._send("create_rectangle", {
                "name": name, "parentId": occl_id, "x": x, "y": y,
                "width": width, "height": height, "fillColor": color,
            })

        noclip_id = adapter._send("create_frame", {
            "name": "NoClip Frame",
            "parentId": root_id,
            "x": 320,
            "y": 480,
            "width": 240,
            "height": 160,
            "fillColor": "#ffffff",
            "clipsContent": False,
        })
        adapter._send("create_rectangle", {
            "name": "NoClip Overflow",
            "parentId": noclip_id,
            "x": -40,
            "y": 120,
            "width": 80,
            "height": 40,
            "fillColor": "#f59e0b",
        })

        occl_tree = adapter._send("get_node_tree", {"nodeId": occl_id, "depth": 2})
        root_tree = adapter._send("get_node_tree", {"nodeId": root_id, "depth": 4})
        occl_children = occl_tree.get("children") or []
        occl_names = [child.get("name") for child in occl_children]
        expected_order = ["Base", "Occluded Label", "Occluder", "Clip Left", "Clip Bottom"]

        renders["autolayout_column"] = export_png(adapter, al_col_id, out / "smoke_d_autolayout_column.png")
        renders["autolayout_row"] = export_png(adapter, al_row_id, out / "smoke_d_autolayout_row.png")
        renders["occlusion"] = export_png(adapter, occl_id, out / "smoke_d_occlusion.png")
        renders["noclip"] = export_png(adapter, noclip_id, out / "smoke_d_noclip.png")
        renders["root"] = export_png(adapter, root_id, out / "smoke_d_render.png")

        occl_image = renders["occlusion"]["image"]
        noclip_image = renders["noclip"]["image"]
        occl_label = find_node(occl_tree, "Occluded Label")

        checks.extend([
            check(
                "font-default-missing-writes",
                "default create_text writes the text with Inter Regular instead of failing",
                find_node(root_tree, "Default Missing Font Text") is not None
                and find_node(root_tree, "Default Missing Font Text").get("fontName", {}).get("family") == "Inter",
                (find_node(root_tree, "Default Missing Font Text") or {}).get("fontName"),
            ),
            check(
                "font-strict-missing-blocks-write",
                "strict create_text fails closed and leaves no page-level node",
                "FONT_NOT_AVAILABLE" in strict_error
                and page_after_count == page_before_count
                and find_node(root_tree, "Strict Missing Font Text") is None,
                {"error": strict_error, "pageChildrenBefore": page_before_count,
                 "pageChildrenAfter": page_after_count},
            ),
            check(
                "font-strict-inter-writes",
                "strict create_text writes a real Inter Bold node",
                find_node(root_tree, "Strict Inter Text") is not None
                and find_node(root_tree, "Strict Inter Text").get("fontName", {}).get("family") == "Inter"
                and find_node(root_tree, "Strict Inter Text").get("fontName", {}).get("style") == "Bold",
                (find_node(root_tree, "Strict Inter Text") or {}).get("fontName"),
            ),
            check(
                "font-strict-stack-writes",
                "strict create_text resolves Inter inside a requested fallback stack",
                find_node(root_tree, "Strict Stack Text") is not None
                and find_node(root_tree, "Strict Stack Text").get("fontName", {}).get("family") == "Inter"
                and find_node(root_tree, "Strict Stack Text").get("fontName", {}).get("style") == "Bold",
                (find_node(root_tree, "Strict Stack Text") or {}).get("fontName"),
            ),
            check(
                "occlusion-child-order",
                "Figma child order preserves the intended stacking order",
                occl_names == expected_order,
                {"expected": expected_order, "actual": occl_names},
            ),
            check(
                "occlusion-text-preserved",
                "partially covered text remains a real editable text node",
                occl_label is not None
                and occl_label.get("type") == "TEXT"
                and occl_label.get("characters") == "PARTIAL",
                {"type": occl_label.get("type") if occl_label else None,
                 "characters": occl_label.get("characters") if occl_label else None},
            ),
            check(
                "occlusion-base-visible",
                "base remains visible outside the occluder",
                pixel_matches(occl_image, (40, 100), "#2563eb"),
                {"xy": [40, 100], "pixel": list(occl_image.getpixel((40, 100)))},
            ),
            check(
                "occlusion-top-covers",
                "later sibling covers the overlap region",
                pixel_matches(occl_image, (100, 40), "#dc2626"),
                {"xy": [100, 40], "pixel": list(occl_image.getpixel((100, 40)))},
            ),
            check(
                "occlusion-clip-left",
                "clipsContent clips a child extending past the left edge",
                pixel_matches(occl_image, (5, 130), "#f59e0b"),
                {"xy": [5, 130], "pixel": list(occl_image.getpixel((5, 130)))},
            ),
            check(
                "occlusion-clip-bottom",
                "clipsContent clips a child extending past the bottom edge",
                pixel_matches(occl_image, (50, 150), "#16a34a"),
                {"xy": [50, 150], "pixel": list(occl_image.getpixel((50, 150)))},
            ),
            check(
                "occlusion-clipped-export-size",
                "clipsContent export stays at the frame size",
                occl_image.width == 240 and occl_image.height == 160,
                {"width": occl_image.width, "height": occl_image.height},
            ),
            check(
                "noclip-export-expands",
                "clipsContent=false export expands to include overflow",
                noclip_image.width == 280 and noclip_image.height == 160
                and pixel_matches(noclip_image, (5, 130), "#f59e0b"),
                {"width": noclip_image.width, "height": noclip_image.height,
                 "xy": [5, 130], "pixel": list(noclip_image.getpixel((5, 130)))},
            ),
            check(
                "root-render-exported",
                "the root frame exports as a non-empty PNG",
                renders["root"]["bytes"] > 0,
                {k: renders["root"][k] for k in ("path", "bytes", "sha256", "width", "height")},
            ),
        ])

        for key, render in renders.items():
            render.pop("image", None)
        events.append({"step": "export", "renders": {k: v["sha256"] for k, v in renders.items()}})
    except Exception as exc:  # noqa: BLE001 - bridge errors are the experiment result
        print(f"[FAIL] Smoke D 写入/回读失败: {type(exc).__name__}: {exc}")
        failure = {
            "experiment": "SMOKE-D-AUTOLAYOUT-FONT-OCCLUSION",
            "status": "failed",
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
            "events": events,
            "checks": checks,
        }
        (out / "figma_smoke_d.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        adapter.disconnect()
        return 1
    finally:
        adapter.disconnect()

    (out / "readback_tree.json").write_text(
        json.dumps(root_tree, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    passed = sum(1 for item in checks if item["passed"])
    total = len(checks)
    findings = [
        {
            "id": "default-font-silent-fallback",
            "severity": "high",
            "observed": "create_text without fontPolicy fell back from a missing family to Inter Regular",
            "policy": "缺字体不自动替换",
            "recommendation": "pass fontPolicy=strict from the production IR boundary, or change the default after regression",
        },
        {
            "id": "autolayout-flow-separate-from-production",
            "severity": "info",
            "observed": "real reflow works through the experimental set_layout_flow action",
            "policy": "not-applicable",
            "recommendation": "production set_autolayout still pins children ABSOLUTE by design; keep the two paths separate",
        },
        {
            "id": "noclip-export-expands",
            "severity": "info",
            "observed": "a frame with clipsContent=false exported 280x160 for 40px left overflow",
            "policy": "partial delivery must state its range",
            "recommendation": "record clipsContent and export bounds in the delivery manifest",
        },
    ]
    document = {
        "experiment": "SMOKE-D-AUTOLAYOUT-FONT-OCCLUSION",
        "title": "Real Figma Auto Layout reflow, strict font failure and partial occlusion",
        "status": "completed-for-current-scope" if passed == total else "failed-checks",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scope": "single local Figma document and one run; experimental set_layout_flow and fontPolicy=strict",
        "boundary": {
            "read_only": False,
            "source_mutation": False,
            "figma_write": True,
            "real_figma_connected": True,
            "src_modified": False,
            "figma_bridge_modified": True,
            "external_network": False,
        },
        "inputs": {
            "rootName": ROOT_NAME,
            "missingFont": MISSING_FONT,
            "fontProbe": font_probe,
            "strictFontProbe": strict_probe,
            "strictError": strict_error,
        },
        "checks": checks,
        "summary": {
            "passed": passed,
            "total": total,
            "autolayoutChecks": sum(1 for c in checks if c["id"].startswith("al-")),
            "fontChecks": sum(1 for c in checks if c["id"].startswith("font-")),
            "occlusionChecks": sum(1 for c in checks if c["id"].startswith("occlusion-")
                                   or c["id"].startswith("noclip-")),
        },
        "findings": findings,
        "renders": renders,
        "limitations": [
            "Single local Figma document and one run; no cross-version, cross-platform or concurrent-write coverage.",
            "Auto Layout is exercised through the experimental set_layout_flow action; production set_autolayout still pins children ABSOLUTE and is not reflow-tested here.",
            "Only vertical/horizontal layout with spacing, padding, fixed sizes, STRETCH, FILL and layoutGrow are covered; grid, wrap, min/max constraints and baseline alignment are not.",
            "Font tests use one deliberately missing family and Inter; CJK fonts, variable fonts, font-loading errors and cross-platform font libraries are not covered.",
            "Occlusion uses solid rectangles and one text node; transparency, masks, effects, blend modes, rotation, image occlusion and anti-aliasing thresholds are not covered.",
            "Pixel checks are small exact samples, not whole-image perceptual comparisons.",
            "No partial-write failure injection; the strict font failure is a single pre-write, node-level failure.",
            "The smoke leaves a SmokeD Root frame in the active document; it is not a production write path.",
        ],
        "hash_note": "content_hash attests this result document and its check details.",
    }
    document["content_hash"] = content_hash(document)

    result_path = out / "figma_smoke_d.json"
    result_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] {passed}/{total} checks passed")
    print(f"[out ] {result_path}")
    for key, render in renders.items():
        print(f"[png ] {key}: {render['width']}x{render['height']} {render['bytes']} bytes")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
