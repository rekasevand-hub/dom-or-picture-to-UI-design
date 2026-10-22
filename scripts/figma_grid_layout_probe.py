"""Probe real Figma Grid layout, track sizing, spans, and alignment."""

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


ROOT_NAME = "P3 Grid Layout Probe"
CELL_WIDTH = 80
CELL_HEIGHT = 60
COLUMNS = 3
ROWS = 2
COLUMN_GAP = 10
ROW_GAP = 10
PADDING = 8


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
    child_ids: list[str | None] = []
    try:
        adapter._send(
            "remove_nodes_by_name",
            {"name": ROOT_NAME, "prefix": False},
        )
        width = COLUMNS * CELL_WIDTH + (COLUMNS - 1) * COLUMN_GAP + PADDING * 2
        height = ROWS * CELL_HEIGHT + (ROWS - 1) * ROW_GAP + PADDING * 2
        root_id = (
            adapter.create_frame(
                {
                    "name": ROOT_NAME,
                    "width": width,
                    "height": height,
                    "fillColor": "#ffffff",
                }
            )
            or ""
        )
        for index in range(ROWS * COLUMNS - 1):
            child_ids.append(
                adapter.create_rectangle(
                    {
                        "name": f"{ROOT_NAME} Cell {index + 1}",
                        "parentId": root_id,
                        "width": CELL_WIDTH,
                        "height": CELL_HEIGHT,
                        "fillColor": "#0f766e",
                    }
                )
            )

        positions = [(0, 0), (0, 2), (1, 0), (1, 1), (1, 2)]
        children = [
            {
                "index": index,
                "rowAnchor": row,
                "columnAnchor": column,
                "rowSpan": 1,
                "columnSpan": 2 if index == 0 else 1,
                "layoutSizingHorizontal": "FILL" if index == 0 else "FIXED",
                "layoutSizingVertical": "FIXED",
                "gridChildHorizontalAlign": "CENTER" if index == 1 else "MIN",
                "gridChildVerticalAlign": "MAX" if index == 1 else "MIN",
            }
            for index, (row, column) in enumerate(positions)
        ]
        tree = adapter.set_layout_flow(
            root_id,
            {
                "mode": "GRID",
                "gridRowCount": ROWS,
                "gridColumnCount": COLUMNS,
                "gridRowGap": ROW_GAP,
                "gridColumnGap": COLUMN_GAP,
                "paddingTop": PADDING,
                "paddingRight": PADDING,
                "paddingBottom": PADDING,
                "paddingLeft": PADDING,
                "gridRowSizes": [
                    {"type": "FIXED", "value": CELL_HEIGHT} for _ in range(ROWS)
                ],
                "gridColumnSizes": [
                    {"type": "FIXED", "value": CELL_WIDTH} for _ in range(COLUMNS)
                ],
                "gridItemsPositioning": "MANUAL",
                "gridAutoTracks": "NONE",
                "layoutSizingHorizontal": "FIXED",
                "layoutSizingVertical": "FIXED",
            },
            children=children,
            width=width,
            height=height,
            depth=3,
        )
        events.append({"step": "apply_grid", "result": tree})
    except Exception as exc:  # noqa: BLE001
        report = {
            "schema_version": "p3-figma-grid-layout/1.0",
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

    tree_children = tree.get("children") or []
    checks = {
        "layout_mode_grid": tree.get("layoutMode") == "GRID",
        "row_count": tree.get("gridRowCount") == ROWS,
        "column_count": tree.get("gridColumnCount") == COLUMNS,
        "row_gap": float(tree.get("gridRowGap") or 0) == ROW_GAP,
        "column_gap": float(tree.get("gridColumnGap") or 0) == COLUMN_GAP,
        "all_children_present": len(tree_children) == ROWS * COLUMNS - 1,
        "anchors_applied": (
            len(tree_children) == len(positions)
            and all(
                child.get("gridRowAnchorIndex") == row
                and child.get("gridColumnAnchorIndex") == column
                for child, (row, column) in zip(tree_children, positions)
            )
        ),
        "column_span_applied": (
            bool(tree_children) and tree_children[0].get("gridColumnSpan") == 2
        ),
        "fill_span_expanded": (
            bool(tree_children)
            and float(tree_children[0].get("width") or 0) == COLUMN_GAP + CELL_WIDTH * 2
        ),
        "alignment_applied": (
            len(tree_children) >= 2
            and tree_children[1].get("gridChildHorizontalAlign") == "CENTER"
            and tree_children[1].get("gridChildVerticalAlign") == "MAX"
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "schema_version": "p3-figma-grid-layout/1.0",
        "experiment": "P3-FIGMA-GRID-LAYOUT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **checks,
        "status": "pass" if not failed else "fail",
        "failed_checks": failed,
        "root_id": root_id,
        "child_ids": child_ids,
        "events": events,
        "boundary": {
            "real_figma_write": True,
            "owned_probe_node_only": True,
            "source_mutation": False,
            "fixed_tracks_manual_positioning": True,
            "flex_hug_and_save_reopen_not_covered": True,
        },
    }
    _write(out, report)
    print(f"[grid] {report['status']} failed={','.join(failed) or '-'}")
    print(f"[out ] {out / 'figma_grid_layout_probe.json'}")
    return 0 if report["status"] == "pass" else 1


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
    (out / "figma_grid_layout_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
