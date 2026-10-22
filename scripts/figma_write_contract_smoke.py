# -*- coding: utf-8 -*-
"""Smoke C: replay R4-EXP-09's emitted write plan into a real Figma document.

The offline contract emits one artboard plus eight write commands. This script
creates the artboard, substitutes the real parent id and real asset bytes, sends
the commands through the bridge, then reads the tree back and compares it with
the command expectations.

Prerequisites:
  1) ``python -m src.app.services.bridge_server`` listens on ws://localhost:8765
  2) The Figma development plugin from ``figma_bridge/manifest.json`` is running

Usage:
  python scripts/figma_write_contract_smoke.py --out output/_figma_smoke_c
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402
from src.config.settings import load_config  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONTRACT_PATH = Path("output/_r4_experiments/r4_figma_write_contract.json")
COMMANDS_PATH = Path("output/_r4_experiments/r4_figma_write_artifacts/commands.json")
ASSETS_DIR = Path("output/_r4_experiments/r4_figma_write_artifacts/assets")
DEFERRED_NAMES = ["Occluded Card", "Unknown Occlusion", "Drawer"]


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "content_hash"}
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check(check_id: str, description: str, passed: bool, detail: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "description": description,
        "passed": bool(passed),
        "detail": detail,
    }


def close_enough(actual: Any, expected: Any, tolerance: float = 0.5) -> bool:
    return (
        isinstance(actual, (int, float))
        and isinstance(expected, (int, float))
        and abs(actual - expected) <= tolerance
    )


def hex_is(value: Any, expected: Any, tolerance: int = 1) -> bool:
    if not isinstance(value, str) or not isinstance(expected, str):
        return False
    if len(value) != 7 or len(expected) != 7 or not value.startswith("#") or not expected.startswith("#"):
        return False
    try:
        actual_rgb = [int(value[i : i + 2], 16) for i in (1, 3, 5)]
        expected_rgb = [int(expected[i : i + 2], 16) for i in (1, 3, 5)]
    except ValueError:
        return False
    return all(abs(a - b) <= tolerance for a, b in zip(actual_rgb, expected_rgb))


def font_matches(actual: Any, expected: Any) -> bool:
    """Figma may add variationSettings to variable fonts; compare the selected face."""
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return False
    return (
        actual.get("family") == expected.get("family")
        and actual.get("style") == expected.get("style")
    )


def child_by_name(tree: dict[str, Any], name: str) -> dict[str, Any]:
    for child in tree.get("children") or []:
        if child.get("name") == name:
            return child
    return {}


def build_asset_index() -> tuple[dict[str, bytes], dict[str, str]]:
    index: dict[str, bytes] = {}
    paths: dict[str, str] = {}
    for path in sorted(ASSETS_DIR.glob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        digest = sha256_bytes(data)
        index[digest] = data
        paths[digest] = str(path)
    return index, paths


def node_check(
    command: dict[str, Any],
    node: dict[str, Any],
    font_expect: dict[tuple[str, str], dict[str, str]],
) -> dict[str, Any]:
    params = command["params"]
    action = command["action"]
    node_id = command["node_id"]
    common = {
        "nodeId": node_id,
        "name": params.get("name"),
        "actualType": node.get("type"),
        "actualRect": [node.get("x"), node.get("y"), node.get("width"), node.get("height")],
    }

    if action == "create_text":
        fill = (node.get("fills") or [{}])[0]
        expected_font = font_expect.get((str(params.get("fontFamily")), str(params.get("fontWeight"))))
        center_actual = (node.get("y") or 0) + (node.get("height") or 0) / 2
        center_expected = params.get("y", 0) + params.get("height", 0) / 2
        passed = (
            node.get("type") == "TEXT"
            and node.get("characters") == params.get("text")
            and close_enough(node.get("fontSize"), params.get("fontSize"))
            and font_matches(node.get("fontName"), expected_font)
            and hex_is(fill.get("color"), params.get("textColor"))
            and close_enough(node.get("x"), params.get("x"))
            and close_enough(center_actual, center_expected, 1.0)
        )
        detail = {
            **common,
            "expected": {
                "type": "TEXT",
                "characters": params.get("text"),
                "fontSize": params.get("fontSize"),
                "fontName": expected_font,
                "textColor": params.get("textColor"),
                "x": params.get("x"),
                "centerY": center_expected,
            },
            "actual": {
                "type": node.get("type"),
                "characters": node.get("characters"),
                "fontSize": node.get("fontSize"),
                "fontName": node.get("fontName"),
                "fill": fill,
                "x": node.get("x"),
                "centerY": center_actual,
            },
        }
        return check(f"node-{node_id}", f"{node_id} text survives write+readback", passed, detail)

    if action == "create_rectangle":
        fill = (node.get("fills") or [{}])[0]
        passed = (
            node.get("type") == "RECTANGLE"
            and hex_is(fill.get("color"), params.get("fillColor"))
            and close_enough(node.get("x"), params.get("x"))
            and close_enough(node.get("y"), params.get("y"))
            and close_enough(node.get("width"), params.get("width"))
            and close_enough(node.get("height"), params.get("height"))
        )
        detail = {
            **common,
            "expected": {"type": "RECTANGLE", "fillColor": params.get("fillColor"), "rect": [params.get("x"), params.get("y"), params.get("width"), params.get("height")]},
            "actual": {"type": node.get("type"), "fill": fill},
        }
        return check(f"node-{node_id}", f"{node_id} rectangle survives write+readback", passed, detail)

    if action == "create_image":
        fill = (node.get("fills") or [{}])[0]
        passed = (
            node.get("type") == "RECTANGLE"
            and fill.get("type") == "IMAGE"
            and isinstance(fill.get("imageHash"), str)
            and bool(fill.get("imageHash"))
            and close_enough(node.get("x"), params.get("x"))
            and close_enough(node.get("y"), params.get("y"))
            and close_enough(node.get("width"), params.get("width"))
            and close_enough(node.get("height"), params.get("height"))
        )
        detail = {
            **common,
            "expected": {"type": "RECTANGLE", "fillType": "IMAGE", "rect": [params.get("x"), params.get("y"), params.get("width"), params.get("height")]},
            "actual": {"type": node.get("type"), "fill": fill},
        }
        return check(f"node-{node_id}", f"{node_id} image survives write+readback", passed, detail)

    return check(f"node-{node_id}", f"{node_id} uses a known write action", False, {"action": action})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="output/_figma_smoke_c", help="artifact directory")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    commands = json.loads(COMMANDS_PATH.read_text(encoding="utf-8"))
    asset_index, asset_paths = build_asset_index()

    cfg = load_config()
    adapter = FigmaBridgeAdapter(cfg.figma_bridge_url)
    try:
        adapter.connect()
    except Exception as exc:  # noqa: BLE001 - report the exact connection failure
        print(f"[FAIL] 连不上桥接服务器 {cfg.figma_bridge_url}: {type(exc).__name__}: {exc}")
        return 2

    print(f"[conn] {cfg.figma_bridge_url}")
    artboard = copy.deepcopy(contract["plan"]["artboard"]["params"])
    artboard_name = artboard.get("name") or "R4-EXP-09 Artboard"
    artboard["fillColor"] = artboard.pop("backgroundColor", artboard.get("fillColor", "#ffffff"))

    ids: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    resolved_assets: dict[str, Any] = {}
    tree: dict[str, Any] = {}
    render_bytes = b""
    font_expect: dict[tuple[str, str], dict[str, str]] = {}
    try:
        cleaned = adapter._send("remove_nodes_by_name", {"name": artboard_name, "prefix": False})
        events.append({"step": "clean", "result": cleaned})

        frame_id = adapter._send("create_frame", artboard)
        ids.append({"sequence": 0, "action": "create_frame", "case_id": None, "node_id": "artboard", "figma_id": frame_id})
        print(f"[art  ] {artboard_name} id={frame_id} size={artboard.get('width')}x{artboard.get('height')}")

        probes = []
        for command in commands:
            params = command["params"]
            if command["action"] == "create_text":
                probes.append({"fontFamily": params.get("fontFamily"), "fontWeight": params.get("fontWeight")})
        probe_result = adapter._send("font_probe", {"probes": probes})
        for item in probe_result.get("results") or []:
            request = item.get("request") or {}
            font_expect[(str(request.get("fontFamily")), str(request.get("fontWeight")))] = item.get("picked")

        for command in commands:
            params = copy.deepcopy(command["params"])
            params["parentId"] = frame_id
            payload = command.get("asset_payload")
            if command["action"] == "create_image" and payload:
                digest = payload.get("sha256")
                data = asset_index.get(digest)
                if data is None:
                    raise RuntimeError(f"缺少资产 {digest}")
                if len(data) != payload.get("bytes") or sha256_bytes(data) != digest:
                    raise RuntimeError(f"资产哈希/字节数不匹配 {digest}")
                params["imageBase64"] = base64.b64encode(data).decode("ascii")
                resolved_assets[digest] = {"path": asset_paths.get(digest), "bytes": len(data)}
            figma_id = adapter._send(command["action"], params)
            ids.append({
                "sequence": command["sequence"],
                "action": command["action"],
                "case_id": command["case_id"],
                "node_id": command["node_id"],
                "figma_id": figma_id,
            })
            events.append({"step": command["action"], "caseId": command["case_id"], "nodeId": command["node_id"], "figmaId": figma_id})

        tree = adapter._send("get_node_tree", {"nodeId": frame_id, "depth": 3})
        exported = adapter._send("export_frame", {"nodeId": frame_id, "scale": 1})
        render_bytes = base64.b64decode(exported["base64"])
        (out / "smoke_c_render.png").write_bytes(render_bytes)
        print(f"[write] {len(commands)} commands, {len(tree.get('children') or [])} children")
        print(f"[exp  ] {out / 'smoke_c_render.png'} ({len(render_bytes)} bytes)")
    except Exception as exc:  # noqa: BLE001 - bridge errors are the experiment result
        print(f"[FAIL] 写入/回读失败: {type(exc).__name__}: {exc}")
        failure = {
            "experiment": "SMOKE-C-WRITE-CONTRACT",
            "status": "failed",
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
            "events": events,
        }
        (out / "figma_write_contract_smoke.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        adapter.disconnect()
        return 1
    finally:
        adapter.disconnect()

    (out / "readback_tree.json").write_text(
        json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    expected_names = [command["params"]["name"] for command in commands]
    actual_names = [child.get("name") for child in tree.get("children") or []]
    children = tree.get("children") or []
    artboard_fill = (tree.get("fills") or [{}])[0]

    checks = [
        check(
            "artboard-created",
            "artboard frame matches the contract geometry and white fill",
            tree.get("type") == "FRAME"
            and close_enough(tree.get("width"), artboard.get("width"))
            and close_enough(tree.get("height"), artboard.get("height"))
            and hex_is(artboard_fill.get("color"), "#ffffff"),
            {"type": tree.get("type"), "width": tree.get("width"), "height": tree.get("height"), "fill": artboard_fill},
        ),
        check(
            "command-ids-returned",
            "every emitted command returns a Figma node id",
            len(ids) == len(commands) + 1 and all(isinstance(item["figma_id"], str) and item["figma_id"] for item in ids),
            ids,
        ),
        check(
            "child-count",
            "the artboard has exactly one child per write command",
            len(children) == len(commands),
            {"expected": len(commands), "actual": len(children), "names": actual_names},
        ),
        check(
            "child-order",
            "child order follows the emitted z-order/sequence",
            actual_names == expected_names,
            {"expected": expected_names, "actual": actual_names},
        ),
        check(
            "deferred-nodes-absent",
            "deferred and skipped contract nodes were not written",
            not any(name in actual_names for name in DEFERRED_NAMES),
            {"forbidden": DEFERRED_NAMES, "actual": actual_names},
        ),
        check(
            "asset-payload-hashes",
            "both image payloads resolve to files with the declared byte count and SHA-256",
            len(resolved_assets) == 2
            and all(
                asset_index[digest] and sha256_bytes(asset_index[digest]) == digest
                for digest in resolved_assets
            ),
            resolved_assets,
        ),
        check(
            "font-resolution",
            "text readback matches the plugin's own font probe for Inter 600/700",
            all(
                font_matches(
                    child_by_name(tree, command["params"]["name"]).get("fontName"),
                    font_expect.get((str(command["params"].get("fontFamily")), str(command["params"].get("fontWeight")))),
                )
                for command in commands
                if command["action"] == "create_text"
            ),
            {f"{key[0]}/{key[1]}": value for key, value in font_expect.items()},
        ),
    ]
    checks.extend(node_check(command, child_by_name(tree, command["params"]["name"]), font_expect) for command in commands)
    checks.append(
        check(
            "render-exported",
            "the artboard exports as a non-empty PNG",
            render_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(render_bytes) > 100,
            {"bytes": len(render_bytes), "sha256": sha256_bytes(render_bytes) if render_bytes else None},
        )
    )

    passed = sum(1 for item in checks if item["passed"])
    all_passed = passed == len(checks)
    result = {
        "experiment": "SMOKE-C-WRITE-CONTRACT",
        "title": "Replay of R4-EXP-09 emitted write plan in a real Figma document",
        "status": "completed-for-current-scope" if all_passed else "failed",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scope": "real Figma write plus node-tree readback for the 8 commands emitted by R4-EXP-09",
        "source": {
            "contract": {"path": str(CONTRACT_PATH), "content_hash": contract.get("content_hash")},
            "commands": {"path": str(COMMANDS_PATH), "sha256": sha256_bytes(COMMANDS_PATH.read_bytes())},
            "assets": resolved_assets,
        },
        "figma": {"artboard_id": ids[0]["figma_id"] if ids else None, "node_ids": ids},
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
        "summary": {"passed": passed, "total": len(checks), "commands": len(commands) + 1, "children": len(children)},
        "render": {
            "path": str(out / "smoke_c_render.png"),
            "bytes": len(render_bytes),
            "sha256": sha256_bytes(render_bytes) if render_bytes else None,
        },
        "limitations": [
            "Single local Figma document and one run; no cross-version, cross-platform or concurrent-write coverage.",
            "Only the eight commands emitted by R4-EXP-09 are replayed; the 19 field decisions and the 11 contract nodes include deferred/skipped cases not written here.",
            "Deferred/skipped absence is checked by node name only; occlusion and authority decisions remain as recorded in the offline contract.",
            "Readback reports current properties; undo, rollback, transaction boundaries and partial-write failure remain unverified.",
            "Image checks verify Figma IMAGE fills and geometry, not pixel equality or production asset pipelines.",
            "The smoke leaves an R4-EXP-09 Artboard frame in the active document; it is not a production write path.",
        ],
        "hash_note": "content_hash attests this result document and its check details.",
    }
    result["content_hash"] = content_hash(result)
    (out / "figma_write_contract_smoke.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"[check] {passed}/{len(checks)} passed")
    for item in checks:
        if not item["passed"]:
            print(f"   [FAIL] {item['id']}: {json.dumps(item['detail'], ensure_ascii=False)[:400]}")
    print(f"[out  ] {out / 'figma_write_contract_smoke.json'}")
    print(f"content_hash={result['content_hash']}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
