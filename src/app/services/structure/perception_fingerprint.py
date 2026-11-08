"""Reproducibility contract for Grounding perception artefacts.

Two full reruns of the same image must produce the same perception output.
That requires three things that the legacy pipeline did not have:

1. a deterministic VLM request (temperature / seed / output bound),
2. a content-addressed cache that survives across processes, and
3. a manifest fingerprint that records the request contract and the hashes of
   every perception artefact actually used by the run.

The cache key deliberately includes the request contract and the coordinate
contract version, so a change to the parsing logic invalidates old cached
perception results instead of silently replaying them.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.app.services.structure.coordinate_space import (
    COORDINATE_CONTRACT_VERSION,
    canonical,
)

PERCEPTION_FINGERPRINT_VERSION = "grounding-perception-fingerprint/1.0"
VISION_REQUEST_CONTRACT_VERSION = "vision-request-contract/1.0"

# 09_evidence_bundle.json is an execution report (cache_status, latency,
# attempts) and is intentionally excluded: hashing it would make a cache hit
# and a cache miss look like different perception artefacts.
ARTIFACTS = (
    "10_content_inventory.json",
    "10_geometry_manifest.json",
    "11_scene_plan.json",
    "11_som.json",
    "image_ir.json",
    "image_enrichment.json",
    "image_reference.json",
    "ocr_supplement.json",
)

# The original ARTIFACTS tuple (and therefore ``fingerprint_sha256``) is kept
# byte-for-byte stable so historical runs remain comparable.  It mixed two
# different layers, however: a change to the scene planner changed the
# fingerprint even when the VLM/OCR perception input was identical.
#
# ``perception_core_sha256`` identifies only what the perception subsystem
# produced.  ``pipeline_derived_sha256`` identifies what the planner/compiler
# built from it.  A same-perception A/B experiment must compare the former.
PERCEPTION_CORE_ARTIFACTS = (
    "image_reference.json",
    "image_enrichment.json",
    "ocr_supplement.json",
    "10_content_inventory.json",
    "10_geometry_manifest.json",
)
PIPELINE_DERIVED_ARTIFACTS = (
    "11_scene_plan.json",
    "11_som.json",
    "image_ir.json",
)


def vision_request_contract(cfg: Any) -> dict[str, Any]:
    """The exact request parameters that must be part of the cache identity."""
    return {
        "schema_version": VISION_REQUEST_CONTRACT_VERSION,
        "model": str(getattr(cfg, "vision_model", "") or ""),
        "temperature": float(getattr(cfg, "vision_temperature", 0.0)),
        "seed": int(getattr(cfg, "vision_seed", 20261108)),
        "send_seed": bool(getattr(cfg, "vision_send_seed", False)),
        # The historical request did not bound max_tokens; keep that behaviour
        # so fixing reproducibility does not change the VLM output distribution.
        "max_tokens": "server-default",
        "max_tokens_sent": False,
        "response_format": "json_object",
        "coordinate_contract": COORDINATE_CONTRACT_VERSION,
    }


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


_EXECUTION_KEYS = frozenset(
    {
        "observability",
        "cache_status",
        "attempt_count",
        "retry_count",
        "latency_ms",
        "fallback_latency_ms",
        "token_usage",
        "usage",
        "seconds",
        "attempts",
        "breaker_probe",
        "error_category",
        "http_status",
        "final_endpoint_index",
    }
)
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/|\\\\)")


def _normalize_artifact(value: Any, key: str | None = None) -> Any:
    """Strip run-local paths and execution state from a perception artefact."""
    if key in _EXECUTION_KEYS:
        return None
    if isinstance(value, str):
        if _ABSOLUTE_PATH.match(value):
            return re.split(r"[\\/]", value)[-1]
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for child_key, child_value in value.items():
            result = _normalize_artifact(child_value, str(child_key))
            if result is not None:
                normalized[str(child_key)] = result
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize_artifact(item, key) for item in value]
    return value


def _artifact_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        canonical_value = canonical(_normalize_artifact(parsed))
        return _sha256_bytes(canonical_value.encode("utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def build_perception_fingerprint(
    cfg: Any,
    out_dir: str | Path,
) -> dict[str, Any]:
    """Record the perception identity of one pipeline run and persist it."""
    out = Path(out_dir)
    contract = vision_request_contract(cfg)
    evidence = _read_json(out / "09_evidence_bundle.json")
    reliability = (evidence.get("provenance") or {}).get(
        "grounding_reliability"
    ) or {}
    reference = _read_json(out / "image_reference.json")
    input_meta = reference.get("input") or {}

    artifacts = {
        name: digest
        for name in ARTIFACTS
        if (digest := _artifact_digest(out / name)) is not None
    }
    coordinate_spaces: dict[str, int] = {}
    som = _read_json(out / "11_som.json")
    for node in som.get("nodes") or []:
        if not isinstance(node, Mapping):
            continue
        label = str(node.get("coordinateSpace") or "unspecified")
        coordinate_spaces[label] = coordinate_spaces.get(label, 0) + 1

    coordinate_decision = reliability.get("coordinate_space") or {}
    # Execution state (hit/miss, attempts) is deliberately excluded: the
    # fingerprint identifies perception artefacts, not how they were obtained.
    material = {
        "version": PERCEPTION_FINGERPRINT_VERSION,
        "request_contract": contract,
        "input_sha256": str(input_meta.get("sha256") or ""),
        "input_size": input_meta.get("size"),
        "cache_key_prefix": reliability.get("cache_key_prefix"),
        "coordinate_space_decision": coordinate_decision,
        "artifacts": artifacts,
        "coordinate_spaces": coordinate_spaces,
    }
    core_material = {
        "version": PERCEPTION_FINGERPRINT_VERSION,
        "layer": "perception-core",
        "request_contract": contract,
        "input_sha256": str(input_meta.get("sha256") or ""),
        "input_size": input_meta.get("size"),
        "coordinate_space_decision": _normalize_artifact(coordinate_decision),
        "artifacts": {
            name: artifacts[name]
            for name in PERCEPTION_CORE_ARTIFACTS
            if name in artifacts
        },
    }
    derived_material = {
        "version": PERCEPTION_FINGERPRINT_VERSION,
        "layer": "pipeline-derived",
        "artifacts": {
            name: artifacts[name]
            for name in PIPELINE_DERIVED_ARTIFACTS
            if name in artifacts
        },
        "coordinate_spaces": coordinate_spaces,
    }
    fingerprint = {
        **material,
        "schema_version": PERCEPTION_FINGERPRINT_VERSION,
        # Do not bump PERCEPTION_FINGERPRINT_VERSION here: it is part of
        # ``material`` and would invalidate every historical
        # ``fingerprint_sha256``.  These are additive fields only.
        "perception_core_sha256": _sha256_bytes(
            canonical(core_material).encode("utf-8")
        ),
        "pipeline_derived_sha256": _sha256_bytes(
            canonical(derived_material).encode("utf-8")
        ),
        "artifact_layers": {
            "perceptionCore": list(PERCEPTION_CORE_ARTIFACTS),
            "pipelineDerived": list(PIPELINE_DERIVED_ARTIFACTS),
        },
        "status": "computed" if artifacts else "partial",
        "grounding": {
            "model": reliability.get("model"),
            "strategy_id": reliability.get("strategy_id"),
            "strategy_version": reliability.get("strategy_version"),
            "cache_key_prefix": reliability.get("cache_key_prefix"),
            "cache_status": reliability.get("cache_status"),
            "attempt_count": reliability.get("attempt_count"),
            "coordinate_space": coordinate_decision,
        },
        "persistent_cache_enabled": bool(
            getattr(cfg, "vision_persistent_cache", True)
        ),
        "fingerprint_sha256": _sha256_bytes(
            canonical(material).encode("utf-8")
        ),
        "limitations": [
            "Fingerprint covers perception artefacts, not the Figma export.",
            "A persistent cache hit replays parsed perception output; changing "
            "the request or coordinate contract produces a new cache key.",
            "fingerprint_sha256 is kept for historical comparability but mixes "
            "perception and planning artefacts. Use perception_core_sha256 to "
            "decide whether two runs saw the same perception input.",
            "image_ir.json is derived from the SoM/plan, not from the VLM "
            "response; its variation across planner versions is expected.",
        ],
    }
    try:
        (out / "perception_fingerprint.json").write_text(
            json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        fingerprint["status"] = "partial"
    return fingerprint
