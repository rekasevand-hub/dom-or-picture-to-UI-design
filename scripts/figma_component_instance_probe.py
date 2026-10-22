"""Probe native Figma component-instance text override isolation."""

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


ROOT_NAME = "P3 Component Instance Probe"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--bridge-url", default=None)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    adapter = FigmaBridgeAdapter(args.bridge_url or load_config().figma_bridge_url)
    adapter.connect()
    try:
        result = adapter._send(
            "component_instance_probe",
            {"rootName": ROOT_NAME},
        )
    finally:
        adapter.disconnect()
    report = {
        "schema_version": "p3-figma-component-instance/1.0",
        "experiment": "P3-FIGMA-COMPONENT-INSTANCE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **result,
        "boundary": {
            "real_figma_write": True,
            "owned_probe_node_only": True,
            "source_mutation": False,
            "component_instance_override_only": True,
        },
    }
    _write(out, report)
    print(f"[component] {report['status']} instance={report.get('instanceId')}")
    print(f"[out      ] {out / 'figma_component_instance_probe.json'}")
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
    (out / "figma_component_instance_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
