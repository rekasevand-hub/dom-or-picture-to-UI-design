"""Probe real Figma horizontal wrap and fail-closed invalid layout mode."""

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


ROOT_NAME = "P3 Wrap Layout Probe"


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
        root_id = adapter.create_frame(
            {
                "name": ROOT_NAME,
                "width": 300,
                "height": 260,
                "fillColor": "#ffffff",
            }
        )
        child_ids = []
        for index, color in enumerate(("#2563eb", "#0f766e", "#d97706", "#7c3aed")):
            child_ids.append(
                adapter.create_rectangle(
                    {
                        "name": f"{ROOT_NAME} Item {index + 1}",
                        "parentId": root_id,
                        "width": 110,
                        "height": 40,
                        "fillColor": color,
                    }
                )
            )
        wrap_tree = adapter._send(
            "set_layout_flow",
            {
                "nodeId": root_id,
                "layout": {
                    "mode": "HORIZONTAL",
                    "wrap": "WRAP",
                    "itemSpacing": 10,
                    "paddingTop": 12,
                    "paddingRight": 12,
                    "paddingBottom": 12,
                    "paddingLeft": 12,
                    "primaryAxisSizingMode": "FIXED",
                    "counterAxisSizingMode": "AUTO",
                },
                "width": 300,
                "depth": 3,
            },
        )
        events.append({"step": "set_wrap", "result": wrap_tree})
        invalid_mode_error = None
        try:
            adapter._send(
                "set_layout_flow",
                {
                    "nodeId": root_id,
                    "layout": {"mode": "MASONRY"},
                    "depth": 2,
                },
            )
        except Exception as exc:  # noqa: BLE001
            invalid_mode_error = f"{type(exc).__name__}: {exc}"
        after_invalid = adapter._send(
            "get_node_tree",
            {"nodeId": root_id, "depth": 2},
        )
        events.append({"step": "invalid_mode_reject", "error": invalid_mode_error})
        cleanup = adapter._send(
            "remove_nodes_by_name",
            {"name": ROOT_NAME, "prefix": False},
        )
        events.append({"step": "cleanup", "result": cleanup})
    except Exception as exc:  # noqa: BLE001
        report = {
            "schema_version": "p3-figma-wrap-layout/1.0",
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "events": events,
        }
        _write(out, report)
        print(f"[FAIL] {report['error']}")
        return 2
    finally:
        adapter.disconnect()

    children = wrap_tree.get("children") or []
    rows = sorted(
        {
            round(float(child.get("absolute", {}).get("y") or child.get("y") or 0), 1)
            for child in children
        }
    )
    checks = {
        "layout_mode_horizontal": wrap_tree.get("layoutMode") == "HORIZONTAL",
        "layout_wrap": wrap_tree.get("layoutWrap") == "WRAP",
        "multiple_rows": len(rows) >= 2,
        "invalid_mode_rejected": bool(
            invalid_mode_error
            and "UNSUPPORTED_LAYOUT_MODE: MASONRY" in invalid_mode_error
        ),
        "invalid_mode_did_not_mutate_layout": (
            after_invalid.get("layoutMode") == "HORIZONTAL"
            and after_invalid.get("layoutWrap") == "WRAP"
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "schema_version": "p3-figma-wrap-layout/1.0",
        "experiment": "P3-FIGMA-WRAP-LAYOUT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **checks,
        "status": "pass" if not failed else "fail",
        "failed_checks": failed,
        "row_count": len(rows),
        "row_y": rows,
        "root_id": root_id,
        "child_ids": child_ids,
        "invalid_mode_error": invalid_mode_error,
        "events": events,
        "boundary": {
            "real_figma_write": True,
            "owned_probe_node_only": True,
            "source_mutation": False,
            "grid_covered_by_separate_probe": True,
        },
    }
    _write(out, report)
    print(
        f"[layout] {report['status']} rows={len(rows)} failed={','.join(failed) or '-'}"
    )
    print(f"[out   ] {out / 'figma_wrap_layout_probe.json'}")
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
    (out / "figma_wrap_layout_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
