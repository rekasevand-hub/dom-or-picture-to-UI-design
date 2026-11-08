# -*- coding: utf-8 -*-
"""Emit the pre-write fallback observation contract for a controlled run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.contracts import canonical_hash  # noqa: E402
from src.app.services.observability.fallback_metrics import (  # noqa: E402
    build_fallback_observation,
)


def run_probe(output: str | Path) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    observation = build_fallback_observation(
        requested_route="auto",
        selected_route="cv",
        attempts=[
            {
                "strategy": "grounding",
                "status": "unavailable",
                "reason": "grounding-service-unavailable",
            },
            {"strategy": "cv", "status": "selected"},
        ],
        grounding_report={
            "attempt_count": 3,
            "retry_count": 2,
            "latency_ms": 812.5,
            "cache_status": "miss",
            "usage": {
                "prompt_tokens": 1450,
                "completion_tokens": 0,
                "total_tokens": 1450,
            },
        },
    )
    result = {
        "schema_version": "fallback-observability-probe/1.0",
        "status": (
            "pass-current-scope"
            if observation["fallback_triggered"]
            and observation["fallback_selection_accepted"]
            and not observation["write_before_decision"]
            else "blocked"
        ),
        "scope": "controlled pre-write fallback observation",
        "code_revision": _code_revision(),
        "source_hashes": {
            "contract": _sha(
                ROOT / "src/app/services/observability/fallback_metrics.py"
            ),
            "agent": _sha(ROOT / "src/app/agents/precise_agent.py"),
        },
        "observation_hash": canonical_hash(observation),
        "boundary": {
            "real_grounding_service": False,
            "real_figma": False,
            "quality_acceptance": "not-evaluated",
            "cost_table": "not-configured",
        },
        "non_claims": [
            "real-grounding-availability",
            "cv-fallback-quality",
            "real-figma-fallback-write",
            "production-cost",
            "production-admission",
        ],
        "limitations": [
            "The observation uses a controlled unavailable Grounding report.",
            "Selection acceptance is not visual or content acceptance.",
            "No production pricing table is configured.",
        ],
    }
    result["content_hash"] = canonical_hash(result)
    _write_json(destination / "fallback_observability.json", observation)
    _write_json(destination / "result.json", result)
    return result


def _code_revision() -> str:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return revision + ("+dirty" if dirty else "")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    staging = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    staging.write_text(payload, encoding="utf-8")
    os.replace(staging, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    result = run_probe(args.out)
    print("status=" + result["status"])
    print("content_hash=" + result["content_hash"])
    return 0 if result["status"] == "pass-current-scope" else 1


if __name__ == "__main__":
    raise SystemExit(main())
