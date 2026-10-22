# -*- coding: utf-8 -*-
"""Verify native text edits propagate through a real Figma Auto Layout frame."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402
from src.config.settings import load_config  # noqa: E402


ROOT_NAME = "P1 Auto Layout Edit Probe"
TEXT_NAME = "Auto Layout Probe Text"
SIBLING_NAME = "Auto Layout Probe Sibling"
INITIAL_TEXT = "Short first line\nShort second line"
EDIT_TEXT = (
    "This edited native text is intentionally much longer so that it wraps "
    "into additional lines inside the fixed-width Auto Layout column."
)


def build_autolayout_probe_report(
    before_tree: dict[str, Any],
    updated_tree: dict[str, Any],
    restored_tree: dict[str, Any],
    *,
    frame_id: str,
    text_id: str,
    sibling_id: str,
) -> dict[str, Any]:
    before = _find_node(before_tree, frame_id)
    updated = _find_node(updated_tree, frame_id)
    restored = _find_node(restored_tree, frame_id)
    if not before or not updated or not restored:
        return _failure_report("frame-readback-missing")
    before_text = _find_node(before, text_id)
    updated_text = _find_node(updated, text_id)
    restored_text = _find_node(restored, text_id)
    before_sibling = _find_node(before, sibling_id)
    updated_sibling = _find_node(updated, sibling_id)
    restored_sibling = _find_node(restored, sibling_id)
    if not all(
        (
            before_text,
            updated_text,
            restored_text,
            before_sibling,
            updated_sibling,
            restored_sibling,
        )
    ):
        return _failure_report("child-readback-missing")

    text_height_changed = (
        _number(updated_text.get("height")) - _number(before_text.get("height")) > 0.5
    )
    sibling_y_changed = (
        _number(updated_sibling.get("y")) - _number(before_sibling.get("y")) > 0.5
    )
    parent_height_changed = (
        _number(updated.get("height")) - _number(before.get("height")) > 0.5
    )
    restored_match = all(
        (
            _close(restored_text.get("height"), before_text.get("height")),
            _close(restored_sibling.get("y"), before_sibling.get("y")),
            _close(restored.get("height"), before.get("height")),
        )
    )
    checks = {
        "layout_mode_vertical": (
            before.get("layoutMode") == "VERTICAL"
            and updated.get("layoutMode") == "VERTICAL"
            and restored.get("layoutMode") == "VERTICAL"
        ),
        "text_height_changed": text_height_changed,
        "sibling_y_changed": sibling_y_changed,
        "parent_height_changed": parent_height_changed,
        "restored": restored_match,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "p1-figma-autolayout-edit-probe/1.0",
        "frame_id": frame_id,
        "text_id": text_id,
        "sibling_id": sibling_id,
        **checks,
        "status": "pass" if not failed else "fail",
        "failed_checks": failed,
        "before_state": _layout_snapshot(
            before,
            before_text,
            before_sibling,
        ),
        "updated_state": _layout_snapshot(
            updated,
            updated_text,
            updated_sibling,
        ),
        "restored_state": _layout_snapshot(
            restored,
            restored_text,
            restored_sibling,
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--bridge-url", default=None)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    bridge_url = args.bridge_url or load_config().figma_bridge_url
    adapter = FigmaBridgeAdapter(bridge_url)
    try:
        adapter.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 连不上桥接服务器 {bridge_url}: {exc}")
        return 2

    events: list[dict[str, Any]] = []
    try:
        cleanup = adapter._send(
            "remove_nodes_by_name",
            {"name": ROOT_NAME, "prefix": False},
        )
        events.append({"step": "clean-owned-root", "result": cleanup})
        frame_id = adapter.create_frame(
            {
                "name": ROOT_NAME,
                "x": 0,
                "y": 0,
                "width": 320,
                "height": 200,
                "fillColor": "#ffffff",
            }
        )
        events.append({"step": "create_frame", "nodeId": frame_id})
        text_id = adapter.create_text(
            {
                "name": TEXT_NAME,
                "x": 0,
                "y": 0,
                "width": 288,
                "height": 40,
                "text": INITIAL_TEXT,
                "lines": INITIAL_TEXT.split("\n"),
                "fontFamily": "Arial",
                "fontWeight": "normal",
                "fontSize": 16,
                "textColor": "#17212b",
            },
            parent_id=frame_id,
        )
        sibling_id = adapter.create_rectangle(
            {
                "name": SIBLING_NAME,
                "x": 0,
                "y": 70,
                "width": 120,
                "height": 40,
                "fillColor": "#2563eb",
            },
            parent_id=frame_id,
        )
        events.extend(
            [
                {"step": "create_text", "nodeId": text_id},
                {"step": "create_sibling", "nodeId": sibling_id},
            ]
        )
        before_tree = adapter._send(
            "set_layout_flow",
            {
                "nodeId": frame_id,
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
                "depth": 4,
            },
        )
        events.append({"step": "set_layout_flow", "result": before_tree})
        adapter.set_text(text_id, EDIT_TEXT)
        updated_tree = adapter._send(
            "get_node_tree",
            {"nodeId": frame_id, "depth": 4},
        )
        events.append({"step": "edit_text", "nodeId": text_id})
        adapter.set_text(text_id, INITIAL_TEXT)
        restored_tree = adapter._send(
            "get_node_tree",
            {"nodeId": frame_id, "depth": 4},
        )
        events.append({"step": "restore_text", "nodeId": text_id})
    except Exception as exc:  # noqa: BLE001
        report = {
            "schema_version": "p1-figma-autolayout-edit-probe/1.0",
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "events": events,
        }
        _write_report(out, report)
        print(f"[FAIL] {report['error']}")
        return 2
    finally:
        adapter.disconnect()

    report = build_autolayout_probe_report(
        before_tree,
        updated_tree,
        restored_tree,
        frame_id=frame_id,
        text_id=text_id,
        sibling_id=sibling_id,
    )
    report.update(
        {
            "experiment": "P1-FIGMA-AUTOLAYOUT-EDIT-PROBE",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "owned_root": {"name": ROOT_NAME, "node_id": frame_id},
            "events": events,
            "boundary": {
                "real_figma_write": True,
                "owned_probe_node_only": True,
                "node_restored": report.get("restored") is True,
                "uses_experimental_layout_flow": True,
                "source_mutation": False,
            },
        }
    )
    _write_report(out, report)
    print(
        "[layout] %s frame=%s failed=%s"
        % (report["status"], frame_id, ",".join(report["failed_checks"]) or "-")
    )
    print("[out   ] %s" % (out / "figma_autolayout_edit_probe.json"))
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


def _layout_snapshot(
    frame: dict[str, Any],
    text: dict[str, Any],
    sibling: dict[str, Any],
) -> dict[str, Any]:
    return {
        "frame": {
            "layoutMode": frame.get("layoutMode"),
            "width": frame.get("width"),
            "height": frame.get("height"),
        },
        "text": {
            "width": text.get("width"),
            "height": text.get("height"),
            "y": text.get("y"),
        },
        "sibling": {
            "width": sibling.get("width"),
            "height": sibling.get("height"),
            "y": sibling.get("y"),
        },
    }


def _close(actual: Any, expected: Any) -> bool:
    return abs(_number(actual) - _number(expected)) <= 0.5


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _failure_report(reason: str) -> dict[str, Any]:
    return {
        "schema_version": "p1-figma-autolayout-edit-probe/1.0",
        "status": "fail",
        "reason": reason,
        "layout_mode_vertical": False,
        "text_height_changed": False,
        "sibling_y_changed": False,
        "parent_height_changed": False,
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
    (out / "figma_autolayout_edit_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
