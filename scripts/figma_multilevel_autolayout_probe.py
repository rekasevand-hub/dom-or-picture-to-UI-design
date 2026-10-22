"""Verify text growth propagates through two nested Figma Auto Layout frames."""

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


ROOT_NAME = "P3 Multi-Level Auto Layout Probe"
INITIAL_TEXT = "Short first line\nShort second line"
EDIT_TEXT = (
    "This edited native text is intentionally long enough to wrap into "
    "several additional lines and force two parent Auto Layout frames to grow."
)


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
    try:
        events.append(
            {
                "step": "clean-owned-root",
                "result": adapter._send(
                    "remove_nodes_by_name",
                    {"name": ROOT_NAME, "prefix": False},
                ),
            }
        )
        outer_id = adapter.create_frame(
            {
                "name": ROOT_NAME,
                "width": 360,
                "height": 260,
                "fillColor": "#ffffff",
            }
        )
        inner_id = adapter.create_frame(
            {
                "name": f"{ROOT_NAME} Inner",
                "parentId": outer_id,
                "width": 328,
                "height": 100,
                "fillColor": "#f8fafc",
            }
        )
        text_id = adapter.create_text(
            {
                "name": f"{ROOT_NAME} Text",
                "parentId": inner_id,
                "width": 304,
                "height": 36,
                "text": INITIAL_TEXT,
                "lines": INITIAL_TEXT.split("\n"),
                "fontFamily": "Arial",
                "fontWeight": "normal",
                "fontSize": 16,
                "textColor": "#17212b",
            }
        )
        inner_sibling_id = adapter.create_rectangle(
            {
                "name": f"{ROOT_NAME} Inner Sibling",
                "parentId": inner_id,
                "width": 80,
                "height": 24,
                "fillColor": "#2563eb",
            }
        )
        outer_sibling_id = adapter.create_rectangle(
            {
                "name": f"{ROOT_NAME} Outer Sibling",
                "parentId": outer_id,
                "width": 120,
                "height": 40,
                "fillColor": "#0f766e",
            }
        )
        events.append(
            {
                "step": "create_nodes",
                "outer_id": outer_id,
                "inner_id": inner_id,
                "text_id": text_id,
                "inner_sibling_id": inner_sibling_id,
                "outer_sibling_id": outer_sibling_id,
            }
        )

        adapter._send(
            "set_layout_flow",
            {
                "nodeId": inner_id,
                "layout": {
                    "mode": "VERTICAL",
                    "itemSpacing": 8,
                    "paddingTop": 12,
                    "paddingRight": 12,
                    "paddingBottom": 12,
                    "paddingLeft": 12,
                    "primaryAxisSizingMode": "AUTO",
                    "counterAxisSizingMode": "FIXED",
                },
                "children": [{"index": 0, "layoutAlign": "STRETCH"}],
                "width": 328,
                "depth": 4,
            },
        )
        adapter._send(
            "set_layout_flow",
            {
                "nodeId": outer_id,
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
                "width": 360,
                "depth": 8,
            },
        )
        before = adapter._send("get_node_tree", {"nodeId": outer_id, "depth": 8})
        adapter.set_text(text_id, EDIT_TEXT)
        updated = adapter._send("get_node_tree", {"nodeId": outer_id, "depth": 8})
        adapter.set_text(text_id, INITIAL_TEXT)
        restored = adapter._send("get_node_tree", {"nodeId": outer_id, "depth": 8})
        events.append({"step": "edit_and_restore", "text_id": text_id})
    except Exception as exc:  # noqa: BLE001
        report = {
            "schema_version": "p3-figma-multilevel-autolayout/1.0",
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "events": events,
        }
        _write(out, report)
        print(f"[FAIL] {report['error']}")
        return 2
    finally:
        adapter.disconnect()

    report = _build_report(
        before,
        updated,
        restored,
        outer_id=outer_id,
        inner_id=inner_id,
        text_id=text_id,
        inner_sibling_id=inner_sibling_id,
        outer_sibling_id=outer_sibling_id,
    )
    report.update(
        {
            "experiment": "P3-FIGMA-MULTILEVEL-AUTOLAYOUT",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "events": events,
            "boundary": {
                "real_figma_write": True,
                "owned_probe_node_only": True,
                "source_mutation": False,
                "uses_experimental_layout_flow": True,
            },
        }
    )
    _write(out, report)
    print(
        f"[layout] {report['status']} failed={','.join(report['failed_checks']) or '-'}"
    )
    print(f"[out   ] {out / 'figma_multilevel_autolayout_probe.json'}")
    return 0 if report["status"] == "pass" else 1


def _build_report(
    before: dict[str, Any],
    updated: dict[str, Any],
    restored: dict[str, Any],
    *,
    outer_id: str,
    inner_id: str,
    text_id: str,
    inner_sibling_id: str,
    outer_sibling_id: str,
) -> dict[str, Any]:
    ids = {
        "outer": outer_id,
        "inner": inner_id,
        "text": text_id,
        "inner_sibling": inner_sibling_id,
        "outer_sibling": outer_sibling_id,
    }
    states = [
        {name: _find(tree, node_id) for name, node_id in ids.items()}
        for tree in (before, updated, restored)
    ]
    if any(value is None for state in states for value in state.values()):
        return {
            "schema_version": "p3-figma-multilevel-autolayout/1.0",
            "status": "fail",
            "failed_checks": ["node-readback-missing"],
        }
    before_state, updated_state, restored_state = states
    checks = {
        "inner_height_changed": _grew(updated_state["inner"], before_state["inner"]),
        "outer_height_changed": _grew(updated_state["outer"], before_state["outer"]),
        "inner_sibling_y_changed": _moved(
            updated_state["inner_sibling"], before_state["inner_sibling"]
        ),
        "outer_sibling_y_changed": _moved(
            updated_state["outer_sibling"], before_state["outer_sibling"]
        ),
        "restored": all(
            _close(restored_state[name].get(key), before_state[name].get(key))
            for name, key in (
                ("inner", "height"),
                ("outer", "height"),
                ("inner_sibling", "y"),
                ("outer_sibling", "y"),
            )
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "p3-figma-multilevel-autolayout/1.0",
        **checks,
        "status": "pass" if not failed else "fail",
        "failed_checks": failed,
        "before_state": _snapshot(before_state),
        "updated_state": _snapshot(updated_state),
        "restored_state": _snapshot(restored_state),
    }


def _snapshot(state: dict[str, Any]) -> dict[str, Any]:
    return {
        name: {
            "layoutMode": node.get("layoutMode"),
            "height": node.get("height"),
            "y": node.get("y"),
        }
        for name, node in state.items()
    }


def _find(root: dict[str, Any] | None, node_id: str) -> dict[str, Any] | None:
    if not isinstance(root, dict):
        return None
    if root.get("id") == node_id:
        return root
    for child in root.get("children") or []:
        found = _find(child, node_id)
        if found is not None:
            return found
    return None


def _grew(updated: dict[str, Any], before: dict[str, Any]) -> bool:
    return _number(updated.get("height")) > _number(before.get("height")) + 0.5


def _moved(updated: dict[str, Any], before: dict[str, Any]) -> bool:
    return _number(updated.get("y")) > _number(before.get("y")) + 0.5


def _close(actual: Any, expected: Any) -> bool:
    return abs(_number(actual) - _number(expected)) <= 0.5


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


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
    (out / "figma_multilevel_autolayout_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
