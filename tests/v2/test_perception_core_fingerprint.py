"""The perception fingerprint must not change when only planning changes.

Regression for the A/B diagnosis in chapter 11: two runs can share exactly the
same VLM/OCR perception input yet produce different scene plans (the emission
criterion), SoMs and image IRs.  ``fingerprint_sha256`` mixes both layers, so
it cannot answer "did these two runs see the same perception?".  These fields
are additive; the historical digest is deliberately left untouched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.app.services.structure.perception_fingerprint import (
    ARTIFACTS,
    PERCEPTION_CORE_ARTIFACTS,
    PIPELINE_DERIVED_ARTIFACTS,
    build_perception_fingerprint,
)


class _Cfg:
    vision_model = "qwen3-vl-plus"
    vision_temperature = 0.1
    vision_seed = 20261108
    vision_send_seed = False
    vision_persistent_cache = True


CORE = {
    "image_reference.json": {"input": {"sha256": "abc123", "size": [2544, 1336]}},
    "image_enrichment.json": {"status": "applied", "assets": []},
    "ocr_supplement.json": {"status": "applied", "observations": []},
    "10_content_inventory.json": {"items": [{"id": "text:a", "text": "数据看板"}]},
    "10_geometry_manifest.json": {"items": []},
}
DERIVED = {
    "11_scene_plan.json": {"nodes": [{"content_ref": "text:a"}], "suppressed": []},
    "11_som.json": {"nodes": [{"coordinateSpace": "xywh-1000"}]},
    "image_ir.json": {"nodes": [], "counts": {"nodes": 0}},
}


def _write(out: Path, payload: dict[str, dict[str, Any]]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, value in payload.items():
        (out / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _run(out: Path) -> dict[str, Any]:
    return build_perception_fingerprint(_Cfg(), out)


def test_artifact_layers_are_a_disjoint_partition():
    assert set(PERCEPTION_CORE_ARTIFACTS) | set(PIPELINE_DERIVED_ARTIFACTS) == set(
        ARTIFACTS
    )
    assert not set(PERCEPTION_CORE_ARTIFACTS) & set(PIPELINE_DERIVED_ARTIFACTS)


def test_planning_changes_do_not_change_perception_core(tmp_path):
    left, right = tmp_path / "legacy", tmp_path / "strict"
    _write(left, {**CORE, **DERIVED})
    changed = dict(DERIVED)
    changed["11_scene_plan.json"] = {
        "nodes": [
            {"content_ref": "text:a"},
            {"content_ref": "text:b"},
        ],
        "suppressed": [],
    }
    changed["image_ir.json"] = {"nodes": [{"node_id": "1"}], "counts": {"nodes": 1}}
    _write(right, {**CORE, **changed})

    a, b = _run(left), _run(right)
    assert a["perception_core_sha256"] == b["perception_core_sha256"]
    assert a["pipeline_derived_sha256"] != b["pipeline_derived_sha256"]
    # Historical behaviour is intentionally preserved.
    assert a["fingerprint_sha256"] != b["fingerprint_sha256"]


def test_perception_input_change_does_change_core(tmp_path):
    left, right = tmp_path / "a", tmp_path / "b"
    _write(left, {**CORE, **DERIVED})
    changed = dict(CORE)
    changed["10_content_inventory.json"] = {
        "items": [{"id": "text:a", "text": "完全不同的文字"}]
    }
    _write(right, {**changed, **DERIVED})
    assert _run(left)["perception_core_sha256"] != _run(right)[
        "perception_core_sha256"
    ]


def test_execution_state_does_not_change_core(tmp_path):
    left, right = tmp_path / "hit", tmp_path / "miss"
    _write(left, {**CORE, **DERIVED})
    _write(right, {**CORE, **DERIVED})
    evidence = {
        "provenance": {
            "grounding_reliability": {
                "model": "qwen3-vl-plus",
                "cache_status": "hit",
                "attempt_count": 0,
                "latency_ms": 0.0,
                "coordinate_space": {"provenance": "xywh-1000"},
            }
        }
    }
    (left / "09_evidence_bundle.json").write_text(
        json.dumps(evidence, ensure_ascii=False), encoding="utf-8"
    )
    missed = json.loads(json.dumps(evidence))
    missed["provenance"]["grounding_reliability"].update(
        {"cache_status": "miss", "attempt_count": 1, "latency_ms": 1234.0}
    )
    (right / "09_evidence_bundle.json").write_text(
        json.dumps(missed, ensure_ascii=False), encoding="utf-8"
    )
    assert _run(left)["perception_core_sha256"] == _run(right)[
        "perception_core_sha256"
    ]


def test_fingerprint_is_deterministic_and_persisted(tmp_path):
    out = tmp_path / "run"
    _write(out, {**CORE, **DERIVED})
    first, second = _run(out), _run(out)
    assert first["fingerprint_sha256"] == second["fingerprint_sha256"]
    assert first["perception_core_sha256"] == second["perception_core_sha256"]
    persisted = json.loads(
        (out / "perception_fingerprint.json").read_text(encoding="utf-8")
    )
    assert persisted["perception_core_sha256"] == first["perception_core_sha256"]
    assert persisted["artifact_layers"]["perceptionCore"] == list(
        PERCEPTION_CORE_ARTIFACTS
    )
