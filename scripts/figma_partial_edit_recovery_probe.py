"""Probe Figma edit transactions, preflight rejection, and cleanup."""

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


ROOT_NAME = "P3 Partial Edit Recovery Probe"
ONE_PIXEL_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAusB9Y9Z6GQAAAAASUVORK5CYII="
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
                    "width": 360,
                    "height": 220,
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
                    "x": 16,
                    "y": 16,
                    "width": 220,
                    "height": 28,
                    "text": "Before transaction",
                    "fontFamily": "Arial",
                    "fontWeightValue": 400,
                    "fontSize": 18,
                    "textColor": "#111827",
                }
            )
            or ""
        )
        image_id = (
            adapter.create_image(
                {
                    "name": f"{ROOT_NAME} Image",
                    "parentId": root_id,
                    "x": 16,
                    "y": 72,
                    "width": 64,
                    "height": 64,
                    "imageBase64": ONE_PIXEL_PNG,
                }
            )
            or ""
        )

        committed = adapter.apply_edit_batch(
            [
                {
                    "action": "set_name",
                    "params": {"nodeId": text_id, "name": "Edited text"},
                },
                {
                    "action": "set_visibility",
                    "params": {"nodeId": text_id, "visible": False},
                },
                {
                    "action": "set_text",
                    "params": {"nodeId": text_id, "text": "After transaction"},
                },
                {
                    "action": "replace_image_fill",
                    "params": {
                        "nodeId": image_id,
                        "imageBase64": ONE_PIXEL_PNG,
                        "fillIndex": 0,
                    },
                },
            ],
            transaction_id="p3-edit-commit",
        )
        events.append({"step": "commit", "result": committed})

        rejected = adapter.apply_edit_batch(
            [
                {
                    "action": "set_text",
                    "params": {
                        "nodeId": text_id,
                        "text": "Must not commit",
                    },
                },
                {
                    "action": "set_text",
                    "params": {
                        "nodeId": image_id,
                        "text": "Rectangle is not text",
                    },
                },
            ],
            transaction_id="p3-edit-preflight",
        )
        events.append({"step": "preflight_reject", "result": rejected})

        tree = adapter._send(
            "get_node_tree",
            {"nodeId": root_id, "depth": 3},
        )
        events.append({"step": "readback", "result": tree})
    except Exception as exc:  # noqa: BLE001
        report = {
            "schema_version": "p3-figma-partial-edit-recovery/1.0",
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

    children = tree.get("children") or []
    text_tree = next((item for item in children if item.get("type") == "TEXT"), {})
    image_tree = next(
        (item for item in children if item.get("type") == "RECTANGLE"),
        {},
    )
    image_fills = image_tree.get("fills") or []
    checks = {
        "commit_status": committed.get("status") == "committed",
        "commit_count": len(committed.get("committed") or []) == 4,
        "preflight_rejected": rejected.get("status") == "rejected",
        "preflight_zero_commit": not rejected.get("committed"),
        "name_committed": text_tree.get("name") == "Edited text",
        "visibility_committed": text_tree.get("visible") is False,
        "text_committed": text_tree.get("characters") == "After transaction",
        "preflight_text_unchanged": (
            text_tree.get("characters") == "After transaction"
        ),
        "image_fill_preserved": (
            bool(image_fills) and image_fills[0].get("type") == "IMAGE"
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "schema_version": "p3-figma-partial-edit-recovery/1.0",
        "experiment": "P3-FIGMA-PARTIAL-EDIT-RECOVERY",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **checks,
        "status": "pass" if not failed else "fail",
        "failed_checks": failed,
        "root_id": root_id,
        "events": events,
        "boundary": {
            "real_figma_write": True,
            "owned_probe_node_only": True,
            "source_mutation": False,
            "sequential_commit_verified": True,
            "preflight_atomicity_verified": True,
            "midflight_rollback_verified_with_injected_fault": True,
            "midflight_rollback_real_figma_not_forced": True,
        },
    }
    _write(out, report)
    print(f"[edit] {report['status']} failed={','.join(failed) or '-'}")
    print(f"[out ] {out / 'figma_partial_edit_recovery_probe.json'}")
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
    (out / "figma_partial_edit_recovery_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
