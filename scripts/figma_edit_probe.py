# -*- coding: utf-8 -*-
"""Exercise native text editing, local geometry propagation and restoration."""

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


def build_edit_probe_report(
    before_tree: dict[str, Any],
    updated_tree: dict[str, Any],
    restored_tree: dict[str, Any],
    *,
    node_id: str,
    probe_text: str,
) -> dict[str, Any]:
    before = _find_node(before_tree, node_id)
    updated = _find_node(updated_tree, node_id)
    restored = _find_node(restored_tree, node_id)
    if not before or not updated or not restored:
        return _failure_report("node-readback-missing")
    before_font = _font_name(before)
    updated_font = _font_name(updated)
    restored_font = _font_name(restored)
    geometry_changed = any(
        abs(_number(updated.get(key)) - _number(before.get(key))) > 0.1
        for key in ("x", "y", "width", "height")
    )
    restored_geometry = all(
        abs(_number(restored.get(key)) - _number(before.get(key))) <= 0.5
        for key in ("x", "y", "width", "height")
    )
    checks = {
        "node_type_preserved": (
            before.get("type") == "TEXT"
            and updated.get("type") == "TEXT"
            and restored.get("type") == "TEXT"
        ),
        "characters_updated": updated.get("characters") == probe_text,
        "font_preserved": (
            bool(before_font)
            and before_font == updated_font
            and before_font == restored_font
        ),
        "geometry_updated": geometry_changed,
        "restored": (
            restored.get("characters") == before.get("characters")
            and restored_font == before_font
            and restored_geometry
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "p1-figma-edit-probe/1.0",
        "node_id": node_id,
        "probe_text": probe_text,
        **checks,
        "status": "pass" if not failed else "fail",
        "failed_checks": failed,
        "parent_layout_propagation": {
            "status": "not-evaluated",
            "reason": "probe-verifies-native-text-and-local-bbox-only",
        },
        "before_state": _node_snapshot(before),
        "updated_state": _node_snapshot(updated),
        "restored_state": _node_snapshot(restored),
    }


def edit_with_restore(
    adapter: FigmaBridgeAdapter,
    *,
    root_id: str,
    node_id: str,
    original_text: str,
    probe_text: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    update_result = adapter.set_text(node_id, probe_text)
    events.append({"step": "set_text", "result": update_result})
    update_error = None
    try:
        updated_tree = adapter._send(
            "get_node_tree",
            {"nodeId": root_id, "depth": 8},
        )
    except Exception as exc:  # noqa: BLE001
        update_error = exc
    finally:
        restore_result = adapter.set_text(node_id, original_text)
        events.append({"step": "restore_text", "result": restore_result})
    if update_error is not None:
        raise RuntimeError(
            f"text updated but intermediate readback failed; restore sent: {update_error}"
        ) from update_error
    restored_tree = adapter._send(
        "get_node_tree",
        {"nodeId": root_id, "depth": 8},
    )
    return updated_tree, restored_tree, events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--readback", required=True, help="Real canonical readback tree"
    )
    parser.add_argument("--out", required=True, help="Probe output directory")
    parser.add_argument("--node-id", default=None, help="Optional native text node id")
    parser.add_argument("--bridge-url", default=None)
    args = parser.parse_args(argv)

    readback_path = Path(args.readback).resolve()
    before_tree = json.loads(readback_path.read_text(encoding="utf-8"))
    root_id = str(before_tree.get("id") or "")
    if not root_id:
        print("[FAIL] readback tree has no root id")
        return 1
    target = (
        _find_node(before_tree, args.node_id)
        if args.node_id
        else _first_text_node(before_tree)
    )
    if not target or target.get("type") != "TEXT":
        print("[FAIL] no native text node found")
        return 1
    node_id = str(target["id"])
    original = str(target.get("characters") or "")
    probe_text = "Native edit probe: " + original
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    bridge_url = args.bridge_url or load_config().figma_bridge_url
    adapter = FigmaBridgeAdapter(bridge_url)
    try:
        adapter.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 连不上桥接服务器 {bridge_url}: {exc}")
        return 2

    events = []
    try:
        updated_tree, restored_tree, events = edit_with_restore(
            adapter,
            root_id=root_id,
            node_id=node_id,
            original_text=original,
            probe_text=probe_text,
        )
    except Exception as exc:  # noqa: BLE001
        report = {
            "schema_version": "p1-figma-edit-probe/1.0",
            "status": "failed",
            "node_id": node_id,
            "error": f"{type(exc).__name__}: {exc}",
            "events": events,
        }
        _write_report(out, report)
        print(f"[FAIL] {report['error']}")
        return 2
    finally:
        adapter.disconnect()

    report = build_edit_probe_report(
        before_tree,
        updated_tree,
        restored_tree,
        node_id=node_id,
        probe_text=probe_text,
    )
    report.update(
        {
            "experiment": "P1-FIGMA-NATIVE-TEXT-EDIT-PROBE",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "input": {
                "path": str(readback_path),
                "sha256": hashlib.sha256(readback_path.read_bytes()).hexdigest(),
            },
            "events": events,
            "boundary": {
                "real_figma_write": True,
                "node_restored": report.get("restored", False),
                "source_mutation": False,
                "destructive_cleanup": False,
            },
        }
    )
    _write_report(out, report)
    print(
        "[edit ] %s node=%s failed=%s"
        % (report["status"], node_id, ",".join(report["failed_checks"]) or "-")
    )
    print("[out  ] %s" % (out / "figma_edit_probe.json"))
    return 0 if report["status"] == "pass" else 1


def _find_node(
    root: dict[str, Any] | None, node_id: str | None
) -> dict[str, Any] | None:
    if not isinstance(root, dict):
        return None
    if root.get("id") == node_id:
        return root
    for child in root.get("children") or []:
        found = _find_node(child, node_id)
        if found:
            return found
    return None


def _first_text_node(root: dict[str, Any]) -> dict[str, Any] | None:
    if root.get("type") == "TEXT":
        return root
    for child in root.get("children") or []:
        found = _first_text_node(child)
        if found:
            return found
    return None


def _font_name(node: dict[str, Any]) -> dict[str, Any] | None:
    value = node.get("fontName")
    if not isinstance(value, dict):
        return None
    return {
        "family": value.get("family"),
        "style": value.get("style"),
    }


def _node_snapshot(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "characters": node.get("characters"),
        "fontName": _font_name(node),
        "fontSize": node.get("fontSize"),
        "x": node.get("x"),
        "y": node.get("y"),
        "width": node.get("width"),
        "height": node.get("height"),
    }


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _failure_report(reason: str) -> dict[str, Any]:
    return {
        "schema_version": "p1-figma-edit-probe/1.0",
        "status": "fail",
        "reason": reason,
        "node_type_preserved": False,
        "characters_updated": False,
        "font_preserved": False,
        "geometry_updated": False,
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
    (out / "figma_edit_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
