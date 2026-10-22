# -*- coding: utf-8 -*-
"""Smoke B: write three core node kinds into Figma and read the tree back.

Prerequisites:
  1) ``python -m src.app.services.bridge_server`` listens on ws://localhost:8765
  2) The Figma development plugin from ``figma_bridge/manifest.json`` is running

Usage:
  python scripts/figma_readback_smoke.py --out output/_figma_smoke_b

Exit codes:
  0 = every check passed
  1 = write/readback ran but at least one check failed
  2 = bridge or plugin connection failed
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402
from src.config.settings import load_config  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT_NAME = "SmokeB Root"
TEXT_NAME = "SmokeB Text"
RECT_NAME = "SmokeB Rect"
IMAGE_NAME = "SmokeB Image"
TEXT_CONTENT = "Smoke B Readback"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "content_hash"}
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def solid_png(width: int, height: int, rgba: tuple[int, int, int, int]) -> bytes:
    """Build a tiny solid PNG without third-party dependencies."""
    raw = b"".join(b"\x00" + bytes(rgba) * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def check(check_id: str, description: str, passed: bool, detail: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "description": description,
        "passed": bool(passed),
        "detail": detail,
    }


def child_by_name(tree: dict[str, Any], name: str) -> dict[str, Any] | None:
    for child in tree.get("children") or []:
        if child.get("name") == name:
            return child
    return None


def hex_is(value: Any, expected: str, tolerance: int = 1) -> bool:
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        return False
    try:
        actual_rgb = [int(value[i : i + 2], 16) for i in (1, 3, 5)]
        expected_rgb = [int(expected[i : i + 2], 16) for i in (1, 3, 5)]
    except ValueError:
        return False
    return all(abs(a - b) <= tolerance for a, b in zip(actual_rgb, expected_rgb))


def close_enough(actual: Any, expected: float, tolerance: float = 0.5) -> bool:
    return isinstance(actual, (int, float)) and abs(actual - expected) <= tolerance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="output/_figma_smoke_b", help="artifact directory")
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
    png_b64 = base64.b64encode(solid_png(8, 8, (225, 29, 72, 255))).decode("ascii")
    events: list[dict[str, Any]] = []
    ids: dict[str, Any] = {}
    tree: dict[str, Any] = {}
    render_bytes = b""
    try:
        cleaned = adapter._send("remove_nodes_by_name", {"name": "SmokeB", "prefix": True})
        events.append({"step": "clean", "result": cleaned})

        ids["frame"] = adapter._send(
            "create_frame",
            {
                "name": ROOT_NAME,
                "x": 0,
                "y": 0,
                "width": 480,
                "height": 320,
                "fillColor": "#ffffff",
            },
        )
        events.append({"step": "create_frame", "frameId": ids["frame"]})

        ids["text"] = adapter._send(
            "create_text",
            {
                "name": TEXT_NAME,
                "parentId": ids["frame"],
                "x": 24,
                "y": 24,
                "width": 240,
                "height": 40,
                "text": TEXT_CONTENT,
                "fontFamily": "Arial",
                "fontWeight": "bold",
                "fontSize": 24,
                "textColor": "#0f172a",
                "textAnchor": "start",
            },
        )
        events.append({"step": "create_text", "nodeId": ids["text"]})

        ids["rect"] = adapter._send(
            "create_rectangle",
            {
                "name": RECT_NAME,
                "parentId": ids["frame"],
                "x": 24,
                "y": 96,
                "width": 120,
                "height": 72,
                "fillColor": "#1d4ed8",
                "borderRadius": 8,
            },
        )
        events.append({"step": "create_rectangle", "nodeId": ids["rect"]})

        ids["image"] = adapter._send(
            "create_image",
            {
                "name": IMAGE_NAME,
                "parentId": ids["frame"],
                "x": 168,
                "y": 96,
                "width": 120,
                "height": 72,
                "imageBase64": png_b64,
            },
        )
        events.append({"step": "create_image", "nodeId": ids["image"]})

        tree = adapter._send("get_node_tree", {"nodeId": ids["frame"], "depth": 3})
        print(f"[write] frame={ids['frame']} text={ids['text']} rect={ids['rect']} image={ids['image']}")
        print(f"[read ] children={len(tree.get('children') or [])}")

        exported = adapter._send("export_frame", {"nodeId": ids["frame"], "scale": 1})
        render_bytes = base64.b64decode(exported["base64"])
        (out / "smoke_b_render.png").write_bytes(render_bytes)
        print(f"[exp  ] {out / 'smoke_b_render.png'} ({len(render_bytes)} bytes)")
    except Exception as exc:  # noqa: BLE001 - bridge errors are the experiment result
        print(f"[FAIL] 写入/回读失败: {type(exc).__name__}: {exc}")
        failure = {
            "experiment": "SMOKE-B-READBACK",
            "status": "failed",
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
            "events": events,
        }
        (out / "figma_readback_smoke.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        adapter.disconnect()
        return 1
    finally:
        adapter.disconnect()

    (out / "readback_tree.json").write_text(
        json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    text = child_by_name(tree, TEXT_NAME) or {}
    rect = child_by_name(tree, RECT_NAME) or {}
    image = child_by_name(tree, IMAGE_NAME) or {}
    order = [child.get("name") for child in tree.get("children") or []]

    text_fill = (text.get("fills") or [{}])[0]
    rect_fill = (rect.get("fills") or [{}])[0]
    image_fill = (image.get("fills") or [{}])[0]
    corners = rect.get("cornerRadius") or {}

    checks = [
        check(
            "write-ids-returned",
            "create_frame/create_text/create_rectangle/create_image return node ids",
            all(isinstance(value, str) and value for value in ids.values()),
            ids,
        ),
        check(
            "frame-type-size",
            "frame is a FRAME with the requested 480x320 size",
            tree.get("type") == "FRAME" and close_enough(tree.get("width"), 480) and close_enough(tree.get("height"), 320),
            {"type": tree.get("type"), "width": tree.get("width"), "height": tree.get("height")},
        ),
        check(
            "child-order",
            "frame children preserve creation order",
            order == [TEXT_NAME, RECT_NAME, IMAGE_NAME],
            order,
        ),
        check(
            "text-content-font",
            "text content, size and resolved face survive readback",
            text.get("characters") == TEXT_CONTENT
            and close_enough(text.get("fontSize"), 24)
            and (text.get("fontName") or {}).get("family") == "Arial"
            and "bold" in str((text.get("fontName") or {}).get("style", "")).lower(),
            {"characters": text.get("characters"), "fontSize": text.get("fontSize"), "fontName": text.get("fontName")},
        ),
        check(
            "text-position",
            "text x and box center y match the requested geometry",
            close_enough(text.get("x"), 24)
            and close_enough((text.get("y") or 0) + (text.get("height") or 0) / 2, 44, 1.0),
            {"x": text.get("x"), "y": text.get("y"), "height": text.get("height")},
        ),
        check(
            "text-fill",
            "text fill matches #0f172a",
            hex_is(text_fill.get("color"), "#0f172a"),
            text_fill,
        ),
        check(
            "rect-geometry",
            "rectangle keeps 120x72 at (24,96)",
            close_enough(rect.get("x"), 24)
            and close_enough(rect.get("y"), 96)
            and close_enough(rect.get("width"), 120)
            and close_enough(rect.get("height"), 72),
            {"x": rect.get("x"), "y": rect.get("y"), "width": rect.get("width"), "height": rect.get("height")},
        ),
        check(
            "rect-fill",
            "rectangle fill matches #1d4ed8",
            hex_is(rect_fill.get("color"), "#1d4ed8"),
            rect_fill,
        ),
        check(
            "rect-radius",
            "rectangle keeps the requested 8px corner radius",
            all(close_enough(corners.get(key), 8) for key in ("topLeft", "topRight", "bottomRight", "bottomLeft")),
            corners,
        ),
        check(
            "image-geometry",
            "image rectangle keeps 120x72 at (168,96)",
            close_enough(image.get("x"), 168)
            and close_enough(image.get("y"), 96)
            and close_enough(image.get("width"), 120)
            and close_enough(image.get("height"), 72),
            {"x": image.get("x"), "y": image.get("y"), "width": image.get("width"), "height": image.get("height")},
        ),
        check(
            "image-fill",
            "image node keeps an IMAGE fill with a non-empty image hash",
            image_fill.get("type") == "IMAGE" and isinstance(image_fill.get("imageHash"), str) and bool(image_fill.get("imageHash")),
            image_fill,
        ),
        check(
            "render-exported",
            "the frame exports as a non-empty PNG",
            render_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(render_bytes) > 100,
            {"bytes": len(render_bytes), "sha256": hashlib.sha256(render_bytes).hexdigest() if render_bytes else None},
        ),
    ]

    passed = sum(1 for item in checks if item["passed"])
    all_passed = passed == len(checks)
    result = {
        "experiment": "SMOKE-B-READBACK",
        "title": "Real Figma write plus node-tree readback for frame/text/rectangle/image",
        "status": "completed-for-current-scope" if all_passed else "failed",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scope": "single local Figma document, one frame, three child node kinds",
        "figma": {"frame_id": ids.get("frame"), "text_id": ids.get("text"), "rect_id": ids.get("rect"), "image_id": ids.get("image")},
        "render": {
            "path": str(out / "smoke_b_render.png"),
            "bytes": len(render_bytes),
            "sha256": hashlib.sha256(render_bytes).hexdigest() if render_bytes else None,
        },
        "events": events,
        "boundary": {
            "read_only": False,
            "source_mutation": False,
            "figma_write": True,
            "real_figma_connected": True,
            "src_modified": False,
            "figma_bridge_modified": True,
            "external_network": False,
        },
        "checks": checks,
        "summary": {"passed": passed, "total": len(checks)},
        "limitations": [
            "Single local Figma document and one run; no cross-version, cross-platform or concurrent-write coverage.",
            "Only frame, text, rectangle and image are covered; auto layout, components, masks, effects and rich fonts are not.",
            "Readback reports current node properties only; rollback, undo and transaction semantics remain unverified.",
            "The smoke leaves a SmokeB Root frame in the active document for inspection; it is not a production write path.",
        ],
        "hash_note": "content_hash attests this result document, including the raw readback values summarised by the checks.",
    }
    result["content_hash"] = content_hash(result)
    (out / "figma_readback_smoke.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"[check] {passed}/{len(checks)} passed")
    for item in checks:
        if not item["passed"]:
            print(f"   [FAIL] {item['id']}: {item['detail']}")
    print(f"[out  ] {out / 'figma_readback_smoke.json'}")
    print(f"content_hash={result['content_hash']}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
