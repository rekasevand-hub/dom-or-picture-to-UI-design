"""Inject a real Figma runtime failure inside an edit transaction."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.figma_grid_complex_holdout_probe import (  # noqa: E402
    diff_grid_snapshots,
    project_grid_tree,
)
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402
from src.config.settings import load_config  # noqa: E402


ROOT_NAME = "P3 Runtime Fault Probe"
TRANSACTION_ID = "p3-runtime-fault-injection"


def build_runtime_fault_checks(
    before_tree: dict[str, Any],
    result: dict[str, Any],
    after_tree: dict[str, Any],
) -> dict[str, bool]:
    rollback = result.get("rollback") or {}
    failed = result.get("failed") or {}
    before_text = _first_text(before_tree)
    after_text = _first_text(after_tree)
    layout_differences = diff_grid_snapshots(
        project_grid_tree(before_tree),
        project_grid_tree(after_tree),
    )
    return {
        "runtime_failure_observed": (
            result.get("status") == "rolled-back"
            and failed.get("action") == "set_layout_flow"
            and failed.get("index") == 1
            and bool(failed.get("error"))
        ),
        "failed_action_rolled_back": (
            rollback.get("attempted") == 2
            and rollback.get("restored") == 2
            and not rollback.get("failed")
        ),
        "text_restored": (
            before_text.get("characters") is not None
            and before_text.get("characters") == after_text.get("characters")
        ),
        "layout_snapshot_restored": not layout_differences,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--bridge-url", default=None)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    adapter = FigmaBridgeAdapter(args.bridge_url or load_config().figma_bridge_url)
    adapter.connect()
    events: list[dict[str, Any]] = []
    root_id = ""
    try:
        adapter._send(
            "remove_nodes_by_name",
            {"name": ROOT_NAME, "prefix": True},
        )
        root_id = (
            adapter.create_frame(
                {
                    "name": ROOT_NAME,
                    "width": 420,
                    "height": 260,
                    "fillColor": "#ffffff",
                }
            )
            or ""
        )
        text_id = (
            adapter.create_text(
                {
                    "name": f"{ROOT_NAME} Text",
                    "parentId": root_id,
                    "width": 130,
                    "height": 50,
                    "text": "Before runtime fault",
                    "fontFamily": "Arial",
                    "fontWeightValue": 400,
                    "fontSize": 16,
                    "textColor": "#111827",
                }
            )
            or ""
        )
        child_ids = [
            adapter.create_rectangle(
                {
                    "name": f"{ROOT_NAME} Rectangle {index + 1}",
                    "parentId": root_id,
                    "width": 100,
                    "height": 70,
                    "fillColor": "#0f766e" if index == 0 else "#94a3b8",
                }
            )
            for index in range(3)
        ]
        events.append({"step": "allocate_children", "childIds": child_ids})
        adapter.set_layout_flow(
            root_id,
            {
                "mode": "GRID",
                "gridRowCount": 2,
                "gridColumnCount": 2,
                "gridRowGap": 10,
                "gridColumnGap": 10,
                "paddingTop": 10,
                "paddingRight": 10,
                "paddingBottom": 10,
                "paddingLeft": 10,
                "gridRowSizes": [
                    {"type": "FIXED", "value": 80},
                    {"type": "FIXED", "value": 80},
                ],
                "gridColumnSizes": [
                    {"type": "FIXED", "value": 100},
                    {"type": "FIXED", "value": 100},
                ],
                "gridItemsPositioning": "MANUAL",
                "gridAutoTracks": "NONE",
                "layoutSizingHorizontal": "FIXED",
                "layoutSizingVertical": "FIXED",
            },
            children=[
                {"index": 0, "rowAnchor": 0, "columnAnchor": 0},
                {"index": 1, "rowAnchor": 0, "columnAnchor": 1},
                {"index": 2, "rowAnchor": 1, "columnAnchor": 0},
                {"index": 3, "rowAnchor": 1, "columnAnchor": 1},
            ],
            width=420,
            height=260,
            depth=3,
        )
        before_tree = adapter._send(
            "get_node_tree",
            {"nodeId": root_id, "depth": 3},
        )
        events.append({"step": "initial_grid_ready", "tree": before_tree})

        result = adapter.apply_edit_batch(
            [
                {
                    "action": "set_text",
                    "params": {
                        "nodeId": text_id,
                        "text": "Temporary runtime edit",
                    },
                },
                {
                    "action": "set_layout_flow",
                    "params": {
                        "nodeId": root_id,
                        "layout": {
                            "mode": "GRID",
                            "gridRowCount": 2,
                            "gridColumnCount": 2,
                            "gridRowGap": 20,
                            "gridColumnGap": 20,
                            "paddingTop": 14,
                            "paddingRight": 14,
                            "paddingBottom": 14,
                            "paddingLeft": 14,
                            "gridRowSizes": [
                                {"type": "FIXED", "value": 70},
                                {"type": "FIXED", "value": 70},
                            ],
                            "gridColumnSizes": [
                                {"type": "FIXED", "value": 110},
                                {"type": "FIXED", "value": 110},
                            ],
                            "gridItemsPositioning": "MANUAL",
                            "gridAutoTracks": "NONE",
                        },
                        "children": [
                            {
                                "index": 0,
                                "rowAnchor": 0,
                                "columnAnchor": 0,
                                "columnSpan": 2,
                            }
                        ],
                    },
                },
            ],
            transaction_id=TRANSACTION_ID,
        )
        events.append({"step": "runtime_fault_transaction", "result": result})
        after_tree = adapter._send(
            "get_node_tree",
            {"nodeId": root_id, "depth": 3},
        )
        events.append({"step": "post_rollback_readback", "tree": after_tree})
    except Exception as exc:  # noqa: BLE001
        report = {
            "schema_version": "p3-figma-runtime-fault/1.0",
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "events": events,
        }
        _write(out, report)
        print(f"[FAIL] {report['error']}")
        return 2
    finally:
        try:
            adapter._send(
                "remove_nodes_by_name",
                {"name": ROOT_NAME, "prefix": True},
            )
        except Exception:  # noqa: BLE001
            pass
        adapter.disconnect()

    checks = build_runtime_fault_checks(before_tree, result, after_tree)
    failed_checks = [name for name, passed in checks.items() if not passed]
    report = {
        "schema_version": "p3-figma-runtime-fault/1.0",
        "experiment": "P3-FIGMA-RUNTIME-FAULT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **checks,
        "status": "pass" if not failed_checks else "fail",
        "failed_checks": failed_checks,
        "root_id": root_id,
        "transaction_id": TRANSACTION_ID,
        "events": events,
        "boundary": {
            "real_figma_write": True,
            "owned_probe_node_only": True,
            "source_mutation": False,
            "runtime_fault_injected_by_figma_constraint": True,
            "synthetic_plugin_patch": False,
            "preflight_passed_before_runtime_failure": True,
            "collaboration_conflict_exercised": False,
            "upload_interruption_exercised": False,
        },
    }
    _write(out, report)
    print(
        f"[runtime-fault] {report['status']} "
        f"failed={','.join(failed_checks) or '-'}"
    )
    print(f"[out ] {out / 'figma_runtime_fault_probe.json'}")
    return 0 if report["status"] == "pass" else 1


def _first_text(tree: dict[str, Any]) -> dict[str, Any]:
    for node in _walk(tree):
        if node.get("type") == "TEXT":
            return node
    return {}


def _walk(tree: dict[str, Any]):
    yield tree
    for child in tree.get("children") or []:
        if isinstance(child, dict):
            yield from _walk(child)


def _write(out: Path, report: dict[str, Any]) -> None:
    payload = {key: value for key, value in report.items() if key != "content_hash"}
    report["content_hash"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    (out / "figma_runtime_fault_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
