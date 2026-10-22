"""Create and verify a resumable real-Figma Grid combination holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402
from src.config.settings import load_config  # noqa: E402


SCHEMA_VERSION = "p3-figma-grid-complex-holdout/1.0"
MANUAL_ROOT_NAME = "P3 Grid Complex Holdout Manual"
AUTO_ROOT_NAME = "P3 Grid Complex Holdout Auto"
ROOT_NAME_PREFIX = "P3 Grid Complex Holdout"
NUMBER_TOLERANCE = 0.5
MIXED_TRACK_TYPES = {"FIXED", "FLEX", "HUG"}
ONE_PIXEL_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAusB9Y9Z6GQAAAAASUVORK5CYII="
)

PROJECTED_FIELDS = (
    "id",
    "name",
    "type",
    "x",
    "y",
    "width",
    "height",
    "visible",
    "layoutMode",
    "layoutWrap",
    "itemSpacing",
    "paddingTop",
    "paddingRight",
    "paddingBottom",
    "paddingLeft",
    "primaryAxisSizingMode",
    "counterAxisSizingMode",
    "primaryAxisAlignItems",
    "counterAxisAlignItems",
    "layoutSizingHorizontal",
    "layoutSizingVertical",
    "gridRowCount",
    "gridColumnCount",
    "gridRowGap",
    "gridColumnGap",
    "gridItemsPositioning",
    "gridAutoTracks",
    "gridRowSizes",
    "gridColumnSizes",
    "gridRowAnchorIndex",
    "gridColumnAnchorIndex",
    "gridRowSpan",
    "gridColumnSpan",
    "gridChildHorizontalAlign",
    "gridChildVerticalAlign",
    "characters",
    "fontName",
    "fontSize",
)


def project_grid_tree(tree: dict[str, Any]) -> dict[str, Any]:
    """Keep persistent Grid semantics while dropping viewport-dependent data."""
    projected = {
        key: _project_value(tree[key]) for key in PROJECTED_FIELDS if key in tree
    }
    if "fills" in tree:
        projected["fills"] = [
            {
                key: paint[key]
                for key in ("type", "imageHash", "scaleMode", "visible")
                if key in paint
            }
            for paint in tree.get("fills") or []
            if isinstance(paint, dict)
        ]
    if isinstance(tree.get("children"), list):
        projected["children"] = [
            project_grid_tree(child)
            for child in tree["children"]
            if isinstance(child, dict)
        ]
    return projected


def diff_grid_snapshots(
    expected: Any,
    actual: Any,
    *,
    path: str = "$",
    numeric_tolerance: float = NUMBER_TOLERANCE,
) -> list[dict[str, str]]:
    """Return path-specific differences, tolerating subpixel geometry drift."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        differences: list[dict[str, str]] = []
        for key in sorted(set(expected) | set(actual)):
            child_path = f"{path}.{key}"
            if key not in expected:
                differences.append(
                    _difference(child_path, "<missing>", _display(actual[key]))
                )
            elif key not in actual:
                differences.append(
                    _difference(child_path, _display(expected[key]), "<missing>")
                )
            else:
                differences.extend(
                    diff_grid_snapshots(
                        expected[key],
                        actual[key],
                        path=child_path,
                        numeric_tolerance=numeric_tolerance,
                    )
                )
        return differences
    if isinstance(expected, list) and isinstance(actual, list):
        differences = []
        if len(expected) != len(actual):
            differences.append(
                _difference(
                    f"{path}.length",
                    str(len(expected)),
                    str(len(actual)),
                )
            )
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            differences.extend(
                diff_grid_snapshots(
                    expected_item,
                    actual_item,
                    path=f"{path}[{index}]",
                    numeric_tolerance=numeric_tolerance,
                )
            )
        return differences
    if (
        isinstance(expected, (int, float))
        and not isinstance(expected, bool)
        and isinstance(actual, (int, float))
        and not isinstance(actual, bool)
    ):
        if math.isclose(
            float(expected),
            float(actual),
            abs_tol=numeric_tolerance,
            rel_tol=0,
        ):
            return []
        return [_difference(path, _display(expected), _display(actual))]
    if expected != actual:
        return [_difference(path, _display(expected), _display(actual))]
    return []


def build_grid_holdout_checks(tree: dict[str, Any]) -> dict[str, bool]:
    """Check the manual mixed-track root and its nested Grid."""
    nested_grids = [
        child
        for child in tree.get("children") or []
        if child.get("type") == "FRAME" and child.get("layoutMode") == "GRID"
    ]
    track_types = _track_types(tree)
    text_nodes = _nodes_of_type(tree, "TEXT")
    image_nodes = [
        node
        for node in _walk_nodes(tree)
        if any(
            paint.get("type") == "IMAGE" and paint.get("imageHash")
            for paint in node.get("fills") or []
        )
    ]
    nested_children = nested_grids[0].get("children") or [] if nested_grids else []
    return {
        "outer_manual_grid": (
            tree.get("layoutMode") == "GRID"
            and tree.get("gridItemsPositioning") == "MANUAL"
        ),
        "outer_grid_dimensions": (
            tree.get("gridRowCount") == 2 and tree.get("gridColumnCount") == 3
        ),
        "mixed_track_types": MIXED_TRACK_TYPES.issubset(track_types),
        "nested_grid": bool(nested_grids),
        "nested_grid_children": len(nested_children) >= 2,
        "nested_grid_span": any(
            child.get("gridColumnSpan", 1) > 1 for child in nested_children
        ),
        "long_text": any(
            "\n" in str(node.get("characters") or "")
            or len(str(node.get("characters") or "")) > 30
            for node in text_nodes
        ),
        "image_fill": bool(image_nodes),
    }


def build_auto_flow_checks(tree: dict[str, Any]) -> dict[str, bool]:
    """Check the row-auto-flow root without assuming computed anchor values."""
    text_nodes = _nodes_of_type(tree, "TEXT")
    image_nodes = [
        node
        for node in _walk_nodes(tree)
        if any(
            paint.get("type") == "IMAGE" and paint.get("imageHash")
            for paint in node.get("fills") or []
        )
    ]
    children = tree.get("children") or []
    return {
        "auto_layout_grid": tree.get("layoutMode") == "GRID",
        "row_auto_flow": tree.get("gridItemsPositioning") == "ROW_AUTO_FLOW",
        "auto_tracks_rows": tree.get("gridAutoTracks") == "ROWS",
        "mixed_track_types": MIXED_TRACK_TYPES.issubset(_track_types(tree)),
        "children_preserved": len(children) == 5,
        "long_text": any(
            "\n" in str(node.get("characters") or "")
            or len(str(node.get("characters") or "")) > 30
            for node in text_nodes
        ),
        "image_fill": bool(image_nodes),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--phase", choices=("create", "verify", "cleanup"), default="create"
    )
    parser.add_argument(
        "--readback-context",
        choices=("unspecified", "plugin-reload", "document-reopen"),
        default="unspecified",
    )
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--bridge-url", default=None)
    args = parser.parse_args(argv)

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = (
        Path(args.manifest).resolve()
        if args.manifest
        else out / "complex_grid_manifest.json"
    )
    if args.phase == "create":
        return _create_phase(out, manifest_path, args.bridge_url)
    if args.phase == "verify":
        return _verify_phase(
            out,
            manifest_path,
            args.bridge_url,
            args.readback_context,
        )
    return _cleanup_phase(out, manifest_path, args.bridge_url)


def _create_phase(
    out: Path,
    manifest_path: Path,
    bridge_url: str | None,
) -> int:
    adapter = FigmaBridgeAdapter(bridge_url or load_config().figma_bridge_url)
    adapter.connect()
    events: list[dict[str, Any]] = []
    created = False
    try:
        cleanup = adapter._send(
            "remove_nodes_by_name",
            {"name": ROOT_NAME_PREFIX, "prefix": True},
        )
        events.append({"step": "remove_previous_owned_roots", "result": cleanup})
        try:
            manual_id = _create_manual_grid(adapter, events)
        except Exception as exc:
            raise RuntimeError(f"manual Grid creation failed: {exc}") from exc
        created = True
        try:
            auto_id = _create_auto_flow_grid(adapter, events)
        except Exception as exc:
            raise RuntimeError(f"auto-flow Grid creation failed: {exc}") from exc

        manual_tree = adapter._send(
            "get_node_tree",
            {"nodeId": manual_id, "depth": 6},
        )
        auto_tree = adapter._send(
            "get_node_tree",
            {"nodeId": auto_id, "depth": 4},
        )
        events.append(
            {
                "step": "read_created_trees",
                "manualRootId": manual_id,
                "autoRootId": auto_id,
            }
        )
    except Exception as exc:  # noqa: BLE001
        if created:
            try:
                adapter._send(
                    "remove_nodes_by_name",
                    {"name": ROOT_NAME_PREFIX, "prefix": True},
                )
            except Exception:  # noqa: BLE001
                pass
        report = _report(
            "create",
            "failed",
            error=f"{type(exc).__name__}: {exc}",
            events=events,
        )
        _write_report(out / "figma_grid_complex_create.json", report)
        print(f"[FAIL] {report['error']}")
        return 2
    finally:
        adapter.disconnect()

    manual_checks = build_grid_holdout_checks(manual_tree)
    auto_checks = build_auto_flow_checks(auto_tree)
    failed_checks = [
        f"manual.{name}" for name, passed in manual_checks.items() if not passed
    ] + [f"auto.{name}" for name, passed in auto_checks.items() if not passed]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "root_prefix": ROOT_NAME_PREFIX,
        "numeric_tolerance": NUMBER_TOLERANCE,
        "targets": [
            {
                "kind": "manual_nested_mixed_grid",
                "name": MANUAL_ROOT_NAME,
                "root_id": manual_id,
                "snapshot": project_grid_tree(manual_tree),
            },
            {
                "kind": "row_auto_flow_grid",
                "name": AUTO_ROOT_NAME,
                "root_id": auto_id,
                "snapshot": project_grid_tree(auto_tree),
            },
        ],
    }
    _write_json(manifest_path, manifest)
    report = _report(
        "create",
        "pass" if not failed_checks else "fail",
        failed_checks=failed_checks,
        manual_checks=manual_checks,
        auto_checks=auto_checks,
        manual_root_id=manual_id,
        auto_root_id=auto_id,
        manifest_path=str(manifest_path),
        reopen_status="pending",
        cleanup_required=True,
        events=events,
        boundary={
            "real_figma_write": True,
            "owned_probe_nodes_only": True,
            "source_mutation": False,
            "nested_grid": True,
            "long_text": True,
            "image_fill": True,
            "fixed_flex_hug_tracks": True,
            "row_auto_flow_and_auto_tracks": True,
            "save_reopen_readback_complete": False,
        },
    )
    _write_report(out / "figma_grid_complex_create.json", report)
    print(
        f"[grid-complex:create] {report['status']} "
        f"failed={','.join(failed_checks) or '-'}"
    )
    print(f"[manifest] {manifest_path}")
    return 0 if report["status"] == "pass" else 1


def _verify_phase(
    out: Path,
    manifest_path: Path,
    bridge_url: str | None,
    readback_context: str,
) -> int:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        report = _report(
            "verify",
            "failed",
            error=f"{type(exc).__name__}: {exc}",
            manifest_path=str(manifest_path),
            readback_context=readback_context,
        )
        _write_report(out / "figma_grid_complex_verify.json", report)
        print(f"[FAIL] {report['error']}")
        return 2

    adapter = FigmaBridgeAdapter(bridge_url or load_config().figma_bridge_url)
    adapter.connect()
    events: list[dict[str, Any]] = []
    target_results: list[dict[str, Any]] = []
    try:
        for target in manifest.get("targets") or []:
            root_id = str(target.get("root_id") or "")
            actual_tree = adapter._send(
                "get_node_tree",
                {"nodeId": root_id, "depth": 6},
            )
            actual_snapshot = project_grid_tree(actual_tree)
            differences = diff_grid_snapshots(
                target.get("snapshot") or {},
                actual_snapshot,
                numeric_tolerance=float(
                    manifest.get("numeric_tolerance") or NUMBER_TOLERANCE
                ),
            )
            checks = (
                build_grid_holdout_checks(actual_tree)
                if target.get("kind") == "manual_nested_mixed_grid"
                else build_auto_flow_checks(actual_tree)
            )
            target_results.append(
                {
                    "kind": target.get("kind"),
                    "name": target.get("name"),
                    "root_id": root_id,
                    "checks": checks,
                    "differences": differences,
                    "status": (
                        "pass" if not differences and all(checks.values()) else "fail"
                    ),
                }
            )
            events.append(
                {
                    "step": "verify_target",
                    "rootId": root_id,
                    "differenceCount": len(differences),
                }
            )
    except Exception as exc:  # noqa: BLE001
        report = _report(
            "verify",
            "failed",
            error=f"{type(exc).__name__}: {exc}",
            manifest_path=str(manifest_path),
            readback_context=readback_context,
            events=events,
            targets=target_results,
        )
        _write_report(out / "figma_grid_complex_verify.json", report)
        print(f"[FAIL] {report['error']}")
        return 2
    finally:
        adapter.disconnect()

    status = (
        "pass"
        if target_results
        and all(target["status"] == "pass" for target in target_results)
        else "fail"
    )
    report = _report(
        "verify",
        status,
        manifest_path=str(manifest_path),
        readback_context=readback_context,
        targets=target_results,
        reopen_status="verified" if status == "pass" else "failed",
        cleanup_required=True,
        events=events,
        boundary={
            "readback_context": readback_context,
            "numeric_tolerance": manifest.get("numeric_tolerance"),
            "owned_probe_nodes_only": True,
            "source_mutation": False,
        },
    )
    _write_report(out / "figma_grid_complex_verify.json", report)
    print(f"[grid-complex:verify] {status}")
    return 0 if status == "pass" else 1


def _cleanup_phase(
    out: Path,
    manifest_path: Path,
    bridge_url: str | None,
) -> int:
    adapter = FigmaBridgeAdapter(bridge_url or load_config().figma_bridge_url)
    adapter.connect()
    try:
        result = adapter._send(
            "remove_nodes_by_name",
            {"name": ROOT_NAME_PREFIX, "prefix": True},
        )
    except Exception as exc:  # noqa: BLE001
        report = _report(
            "cleanup",
            "failed",
            error=f"{type(exc).__name__}: {exc}",
            manifest_path=str(manifest_path),
        )
        _write_report(out / "figma_grid_complex_cleanup.json", report)
        print(f"[FAIL] {report['error']}")
        return 2
    finally:
        adapter.disconnect()
    report = _report(
        "cleanup",
        "pass",
        manifest_path=str(manifest_path),
        result=result,
        cleanup_required=False,
    )
    _write_report(out / "figma_grid_complex_cleanup.json", report)
    print("[grid-complex:cleanup] pass")
    return 0


def _create_manual_grid(
    adapter: FigmaBridgeAdapter,
    events: list[dict[str, Any]],
) -> str:
    root_id = adapter.create_frame(
        {
            "name": MANUAL_ROOT_NAME,
            "x": 0,
            "y": 0,
            "width": 640,
            "height": 420,
            "fillColor": "#f8fafc",
        }
    )
    if not root_id:
        raise RuntimeError("manual Grid root did not return a node id")
    events.append({"step": "create_manual_root", "nodeId": root_id})

    nested_id = adapter.create_frame(
        {
            "name": f"{MANUAL_ROOT_NAME} Nested",
            "parentId": root_id,
            "width": 300,
            "height": 180,
            "fillColor": "#ffffff",
        }
    )
    if not nested_id:
        raise RuntimeError("nested Grid did not return a node id")
    events.append({"step": "create_nested_grid", "nodeId": nested_id})

    nested_text_id = adapter.create_text(
        {
            "name": f"{MANUAL_ROOT_NAME} Nested Copy",
            "parentId": nested_id,
            "width": 220,
            "height": 70,
            "text": "Nested Grid copy wraps\ninside a spanned track.",
            "lines": ["Nested Grid copy wraps", "inside a spanned track."],
            "fontFamily": "Inter",
            "fontSize": 16,
            "textColor": "#0f172a",
        }
    )
    nested_image_id = adapter.create_image(
        {
            "name": f"{MANUAL_ROOT_NAME} Nested Image",
            "parentId": nested_id,
            "width": 90,
            "height": 70,
            "imageBase64": ONE_PIXEL_PNG,
        }
    )
    events.append(
        {
            "step": "create_nested_children",
            "textNodeId": nested_text_id,
            "imageNodeId": nested_image_id,
        }
    )
    adapter.set_layout_flow(
        nested_id,
        {
            "mode": "GRID",
            "gridRowCount": 2,
            "gridColumnCount": 2,
            "gridRowGap": 6,
            "gridColumnGap": 8,
            "paddingTop": 6,
            "paddingRight": 6,
            "paddingBottom": 6,
            "paddingLeft": 6,
            "gridRowSizes": [
                {"type": "FIXED", "value": 80},
                {"type": "HUG"},
            ],
            "gridColumnSizes": [
                {"type": "FIXED", "value": 90},
                {"type": "FLEX", "value": 1},
            ],
            "gridItemsPositioning": "MANUAL",
            "gridAutoTracks": "NONE",
            "layoutSizingHorizontal": "FIXED",
            "layoutSizingVertical": "FIXED",
        },
        children=[
            {
                "index": 1,
                "rowAnchor": 1,
                "columnAnchor": 0,
                "rowSpan": 1,
                "columnSpan": 1,
                "layoutSizingHorizontal": "FILL",
                "gridChildHorizontalAlign": "CENTER",
            },
            {
                "index": 0,
                "rowAnchor": 0,
                "columnAnchor": 0,
                "rowSpan": 1,
                "columnSpan": 2,
                "layoutSizingHorizontal": "FILL",
                "gridChildHorizontalAlign": "MIN",
            },
        ],
        width=300,
        height=180,
        depth=2,
    )
    events.append({"step": "apply_nested_grid"})

    outer_text_id = adapter.create_text(
        {
            "name": f"{MANUAL_ROOT_NAME} Long Copy",
            "parentId": root_id,
            "width": 190,
            "height": 110,
            "text": "Outer holdout copy is intentionally long\nand spans two Grid rows.",
            "lines": [
                "Outer holdout copy is intentionally long",
                "and spans two Grid rows.",
            ],
            "fontFamily": "Inter",
            "fontSize": 16,
            "textColor": "#0f172a",
        }
    )
    outer_image_id = adapter.create_image(
        {
            "name": f"{MANUAL_ROOT_NAME} Outer Image",
            "parentId": root_id,
            "width": 150,
            "height": 80,
            "imageBase64": ONE_PIXEL_PNG,
        }
    )
    fill_id = adapter.create_rectangle(
        {
            "name": f"{MANUAL_ROOT_NAME} Color Block",
            "parentId": root_id,
            "width": 150,
            "height": 70,
            "fillColor": "#0f766e",
        }
    )
    events.append(
        {
            "step": "create_outer_children",
            "textNodeId": outer_text_id,
            "imageNodeId": outer_image_id,
            "rectangleNodeId": fill_id,
        }
    )
    outer_layout = {
        "mode": "GRID",
        "gridRowCount": 2,
        "gridColumnCount": 3,
        "gridRowGap": 10,
        "gridColumnGap": 12,
        "paddingTop": 12,
        "paddingRight": 12,
        "paddingBottom": 12,
        "paddingLeft": 12,
        "gridRowSizes": [
            {"type": "FIXED", "value": 120},
            {"type": "FLEX", "value": 1},
        ],
        "gridColumnSizes": [
            {"type": "FIXED", "value": 180},
            {"type": "FLEX", "value": 1},
            {"type": "HUG"},
        ],
        "gridItemsPositioning": "MANUAL",
        "gridAutoTracks": "NONE",
        "layoutSizingHorizontal": "FIXED",
        "layoutSizingVertical": "FIXED",
    }
    adapter.set_layout_flow(
        root_id,
        outer_layout,
        children=[
            {
                "index": 3,
                "rowAnchor": 1,
                "columnAnchor": 1,
                "rowSpan": 1,
                "columnSpan": 1,
                "layoutSizingHorizontal": "FILL",
                "gridChildHorizontalAlign": "CENTER",
            },
            {
                "index": 2,
                "rowAnchor": 1,
                "columnAnchor": 0,
                "rowSpan": 1,
                "columnSpan": 1,
                "layoutSizingHorizontal": "FILL",
                "gridChildHorizontalAlign": "CENTER",
            },
            {
                "index": 1,
                "rowAnchor": 0,
                "columnAnchor": 2,
                "rowSpan": 1,
                "columnSpan": 1,
                "layoutSizingHorizontal": "FIXED",
                "layoutSizingVertical": "FIXED",
                "gridChildHorizontalAlign": "MIN",
            },
            {
                "index": 0,
                "rowAnchor": 0,
                "columnAnchor": 0,
                "rowSpan": 1,
                "columnSpan": 1,
                "layoutSizingHorizontal": "FILL",
                "layoutSizingVertical": "FIXED",
                "gridChildHorizontalAlign": "MIN",
            },
        ],
        width=640,
        height=420,
        depth=2,
    )
    first_pass = adapter._send(
        "get_node_tree",
        {"nodeId": root_id, "depth": 1},
    )
    events.append(
        {
            "step": "manual_grid_first_pass",
            "gridRowCount": first_pass.get("gridRowCount"),
            "gridColumnCount": first_pass.get("gridColumnCount"),
            "children": [
                {
                    "name": child.get("name"),
                    "row": child.get("gridRowAnchorIndex"),
                    "column": child.get("gridColumnAnchorIndex"),
                }
                for child in first_pass.get("children") or []
            ],
        }
    )
    events.append({"step": "begin_manual_grid_spans"})
    adapter.set_grid_child_overrides(
        root_id,
        [
            {
                "index": 1,
                "rowAnchor": 0,
                "columnAnchor": 2,
                "rowSpan": 2,
                "columnSpan": 1,
                "layoutSizingHorizontal": "FIXED",
                "layoutSizingVertical": "FIXED",
                "gridChildHorizontalAlign": "MIN",
            },
            {
                "index": 0,
                "rowAnchor": 0,
                "columnAnchor": 0,
                "rowSpan": 1,
                "columnSpan": 2,
                "layoutSizingHorizontal": "FILL",
                "layoutSizingVertical": "FIXED",
                "gridChildHorizontalAlign": "MIN",
            },
        ],
        depth=2,
    )
    events.append({"step": "position_manual_grid_children"})
    events.append({"step": "apply_manual_grid"})
    return root_id


def _create_auto_flow_grid(
    adapter: FigmaBridgeAdapter,
    events: list[dict[str, Any]],
) -> str:
    root_id = adapter.create_frame(
        {
            "name": AUTO_ROOT_NAME,
            "x": 0,
            "y": 460,
            "width": 560,
            "height": 320,
            "fillColor": "#fff7ed",
        }
    )
    if not root_id:
        raise RuntimeError("auto-flow Grid root did not return a node id")
    events.append({"step": "create_auto_root", "nodeId": root_id})

    text_one_id = adapter.create_text(
        {
            "name": f"{AUTO_ROOT_NAME} Text One",
            "parentId": root_id,
            "width": 220,
            "height": 70,
            "text": "Auto-flow text shares a spanned\nrow with image and blocks.",
            "lines": ["Auto-flow text shares a spanned", "row with image and blocks."],
            "fontFamily": "Inter",
            "fontSize": 15,
            "textColor": "#7c2d12",
        }
    )
    image_id = adapter.create_image(
        {
            "name": f"{AUTO_ROOT_NAME} Image",
            "parentId": root_id,
            "width": 120,
            "height": 70,
            "imageBase64": ONE_PIXEL_PNG,
        }
    )
    block_one_id = adapter.create_rectangle(
        {
            "name": f"{AUTO_ROOT_NAME} Block One",
            "parentId": root_id,
            "width": 120,
            "height": 60,
            "fillColor": "#c2410c",
        }
    )
    text_two_id = adapter.create_text(
        {
            "name": f"{AUTO_ROOT_NAME} Text Two",
            "parentId": root_id,
            "width": 140,
            "height": 56,
            "text": "Second flow item",
            "fontFamily": "Inter",
            "fontSize": 15,
            "textColor": "#7c2d12",
        }
    )
    block_two_id = adapter.create_rectangle(
        {
            "name": f"{AUTO_ROOT_NAME} Block Two",
            "parentId": root_id,
            "width": 110,
            "height": 60,
            "fillColor": "#ea580c",
        }
    )
    events.append(
        {
            "step": "create_auto_children",
            "nodeIds": [
                text_one_id,
                image_id,
                block_one_id,
                text_two_id,
                block_two_id,
            ],
        }
    )
    adapter.set_layout_flow(
        root_id,
        {
            "mode": "GRID",
            "gridRowCount": 2,
            "gridColumnCount": 3,
            "gridRowGap": 8,
            "gridColumnGap": 8,
            "paddingTop": 10,
            "paddingRight": 10,
            "paddingBottom": 10,
            "paddingLeft": 10,
            "gridRowSizes": [
                {"type": "FIXED", "value": 100},
                {"type": "FLEX", "value": 1},
            ],
            "gridColumnSizes": [
                {"type": "FIXED", "value": 120},
                {"type": "FLEX", "value": 1},
                {"type": "HUG"},
            ],
            "gridItemsPositioning": "ROW_AUTO_FLOW",
            "gridAutoTracks": "ROWS",
            "layoutSizingHorizontal": "FIXED",
            "layoutSizingVertical": "FIXED",
        },
        children=[
            {
                "index": 0,
                "rowSpan": 1,
                "columnSpan": 1,
                "layoutSizingHorizontal": "FILL",
                "gridChildHorizontalAlign": "MIN",
            },
            {
                "index": 1,
                "rowSpan": 1,
                "columnSpan": 1,
                "layoutSizingHorizontal": "FILL",
                "gridChildHorizontalAlign": "CENTER",
            },
            {
                "index": 2,
                "layoutSizingHorizontal": "FILL",
                "gridChildHorizontalAlign": "CENTER",
            },
            {
                "index": 3,
                "layoutSizingHorizontal": "FILL",
                "gridChildHorizontalAlign": "MIN",
            },
            {
                "index": 4,
                "layoutSizingHorizontal": "FILL",
                "gridChildHorizontalAlign": "CENTER",
            },
        ],
        width=560,
        height=320,
        depth=2,
    )
    events.append({"step": "apply_auto_flow_grid"})
    return root_id


def _walk_nodes(tree: dict[str, Any]):
    yield tree
    for child in tree.get("children") or []:
        if isinstance(child, dict):
            yield from _walk_nodes(child)


def _nodes_of_type(tree: dict[str, Any], node_type: str) -> list[dict[str, Any]]:
    return [node for node in _walk_nodes(tree) if node.get("type") == node_type]


def _track_types(tree: dict[str, Any]) -> set[str]:
    types: set[str] = set()
    for name in ("gridRowSizes", "gridColumnSizes"):
        for track in tree.get(name) or []:
            if isinstance(track, dict) and track.get("type"):
                types.add(str(track["type"]))
    return types


def _project_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_project_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _project_value(item) for key, item in value.items()}
    return value


def _difference(path: str, expected: str, actual: str) -> dict[str, str]:
    return {"path": path, "expected": expected, "actual": actual}


def _display(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    return repr(value)


def _report(phase: str, status: str, **payload: Any) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment": "P3-FIGMA-GRID-COMPLEX-HOLDOUT",
        "phase": phase,
        "status": status,
        "generated_at": _utc_now(),
        **payload,
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    _write_json(path, report)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {key: value for key, value in payload.items() if key != "content_hash"}
    data["content_hash"] = hashlib.sha256(
        json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
