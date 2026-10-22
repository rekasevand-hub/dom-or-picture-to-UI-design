# -*- coding: utf-8 -*-
"""Exercise image-fill replacement and restoration on one owned Figma node."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.figma_readback_smoke import solid_png  # noqa: E402
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402
from src.config.settings import load_config  # noqa: E402


ROOT_NAME = "P1 Asset Probe Root"
IMAGE_NAME = "P1 Asset Probe Image"


def build_asset_probe_report(
    initial_tree: dict[str, Any],
    replaced_tree: dict[str, Any],
    restored_tree: dict[str, Any],
    *,
    node_id: str,
) -> dict[str, Any]:
    initial = _find_node(initial_tree, node_id)
    replaced = _find_node(replaced_tree, node_id)
    restored = _find_node(restored_tree, node_id)
    if not initial or not replaced or not restored:
        return _failure_report("node-readback-missing")
    initial_fill = _image_fill(initial)
    replaced_fill = _image_fill(replaced)
    restored_fill = _image_fill(restored)
    if not initial_fill or not replaced_fill or not restored_fill:
        return _failure_report("image-fill-missing")
    checks = {
        "node_type_preserved": (
            initial.get("type") == replaced.get("type")
            and initial.get("type") == restored.get("type")
        ),
        "image_hash_changed": (
            bool(initial_fill.get("imageHash"))
            and bool(replaced_fill.get("imageHash"))
            and initial_fill.get("imageHash") != replaced_fill.get("imageHash")
        ),
        "scale_mode_preserved": (
            initial_fill.get("scaleMode") == replaced_fill.get("scaleMode")
            and initial_fill.get("scaleMode") == restored_fill.get("scaleMode")
        ),
        "restored": (
            restored_fill.get("imageHash") == initial_fill.get("imageHash")
            and restored_fill.get("type") == "IMAGE"
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "p1-figma-asset-probe/1.0",
        "node_id": node_id,
        **checks,
        "status": "pass" if not failed else "fail",
        "failed_checks": failed,
        "before_state": _image_snapshot(initial),
        "replaced_state": _image_snapshot(replaced),
        "restored_state": _image_snapshot(restored),
    }


def replace_with_restore(
    adapter: FigmaBridgeAdapter,
    *,
    root_id: str,
    node_id: str,
    source_base64: str,
    replacement_base64: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    replace_result = adapter.replace_image_fill(node_id, replacement_base64)
    events.append({"step": "replace_image_fill", "result": replace_result})
    replace_error = None
    try:
        replaced_tree = adapter._send(
            "get_node_tree",
            {"nodeId": root_id, "depth": 3},
        )
    except Exception as exc:  # noqa: BLE001
        replace_error = exc
    finally:
        restore_result = adapter.replace_image_fill(node_id, source_base64)
        events.append({"step": "restore_image_fill", "result": restore_result})
    if replace_error is not None:
        raise RuntimeError(
            f"image replaced but intermediate readback failed; restore sent: {replace_error}"
        ) from replace_error
    restored_tree = adapter._send(
        "get_node_tree",
        {"nodeId": root_id, "depth": 3},
    )
    return replaced_tree, restored_tree, events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="Probe output directory")
    parser.add_argument("--bridge-url", default=None)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    source_bytes = solid_png(16, 16, (225, 29, 72, 255))
    replacement_bytes = solid_png(16, 16, (37, 99, 235, 255))
    source_b64 = base64.b64encode(source_bytes).decode("ascii")
    replacement_b64 = base64.b64encode(replacement_bytes).decode("ascii")

    bridge_url = args.bridge_url or load_config().figma_bridge_url
    adapter = FigmaBridgeAdapter(bridge_url)
    try:
        adapter.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 连不上桥接服务器 {bridge_url}: {exc}")
        return 2

    events = []
    try:
        cleanup = adapter._send(
            "remove_nodes_by_name",
            {"name": ROOT_NAME, "prefix": False},
        )
        events.append({"step": "clean-owned-root", "result": cleanup})
        orphan_cleanup = adapter._send(
            "remove_nodes_by_name",
            {"name": IMAGE_NAME, "prefix": False},
        )
        events.append({"step": "clean-owned-orphan", "result": orphan_cleanup})
        root_id = adapter.create_frame(
            {
                "name": ROOT_NAME,
                "x": 0,
                "y": 0,
                "width": 220,
                "height": 120,
                "fillColor": "#ffffff",
            }
        )
        events.append({"step": "create_frame", "nodeId": root_id})
        image_id = adapter.create_image(
            {
                "name": IMAGE_NAME,
                "x": 20,
                "y": 20,
                "width": 80,
                "height": 80,
                "imageBase64": source_b64,
            },
            parent_id=root_id,
        )
        events.append({"step": "create_image", "nodeId": image_id})
        initial_tree = adapter._send(
            "get_node_tree",
            {"nodeId": root_id, "depth": 3},
        )
        replaced_tree, restored_tree, restore_events = replace_with_restore(
            adapter,
            root_id=root_id,
            node_id=image_id,
            source_base64=source_b64,
            replacement_base64=replacement_b64,
        )
        events.extend(restore_events)
    except Exception as exc:  # noqa: BLE001
        report = {
            "schema_version": "p1-figma-asset-probe/1.0",
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "events": events,
        }
        _write_report(out, report)
        print(f"[FAIL] {report['error']}")
        return 2
    finally:
        adapter.disconnect()

    report = build_asset_probe_report(
        initial_tree,
        replaced_tree,
        restored_tree,
        node_id=image_id,
    )
    report.update(
        {
            "experiment": "P1-FIGMA-ASSET-REPLACEMENT-PROBE",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "owned_root": {"name": ROOT_NAME, "node_id": root_id},
            "assets": {
                "source": {
                    "sha256": hashlib.sha256(source_bytes).hexdigest(),
                    "size_bytes": len(source_bytes),
                },
                "replacement": {
                    "sha256": hashlib.sha256(replacement_bytes).hexdigest(),
                    "size_bytes": len(replacement_bytes),
                },
            },
            "events": events,
            "boundary": {
                "real_figma_write": True,
                "owned_probe_node_only": True,
                "source_mutation": False,
            },
        }
    )
    _write_report(out, report)
    print(
        "[asset] %s node=%s failed=%s"
        % (report["status"], image_id, ",".join(report["failed_checks"]) or "-")
    )
    print("[out  ] %s" % (out / "figma_asset_probe.json"))
    return 0 if report["status"] == "pass" else 1


def _find_node(root: dict[str, Any] | None, node_id: str) -> dict[str, Any] | None:
    if not isinstance(root, dict):
        return None
    if root.get("id") == node_id:
        return root
    for child in root.get("children") or []:
        found = _find_node(child, node_id)
        if found:
            return found
    return None


def _image_fill(node: dict[str, Any]) -> dict[str, Any] | None:
    for fill in node.get("fills") or []:
        if isinstance(fill, dict) and fill.get("type") == "IMAGE":
            return fill
    return None


def _image_snapshot(node: dict[str, Any]) -> dict[str, Any]:
    fill = _image_fill(node) or {}
    return {
        "type": node.get("type"),
        "fill": {
            "type": fill.get("type"),
            "imageHash": fill.get("imageHash"),
            "scaleMode": fill.get("scaleMode"),
            "visible": fill.get("visible"),
        },
    }


def _failure_report(reason: str) -> dict[str, Any]:
    return {
        "schema_version": "p1-figma-asset-probe/1.0",
        "status": "fail",
        "reason": reason,
        "node_type_preserved": False,
        "image_hash_changed": False,
        "scale_mode_preserved": False,
        "restored": False,
        "failed_checks": [reason],
    }


def _write_report(out: Path, report: dict[str, Any]) -> None:
    payload = {key: value for key, value in report.items() if key != "content_hash"}
    report["content_hash"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    (out / "figma_asset_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
