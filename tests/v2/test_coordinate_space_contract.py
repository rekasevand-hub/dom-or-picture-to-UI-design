"""Regression tests for the coordinate-space and reproducibility contracts."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.structure.backends.grounding_reliability import (
    GroundingReliability,
)
from src.app.services.structure.backends.grounding_vlm import parse_vlm_json
from src.app.services.structure.coordinate_space import (
    COORDINATE_CONTRACT_VERSION,
    build_ink_scorer,
    infer_coordinate_space,
    legacy_axis_scales,
    resolve_bbox,
)
from src.app.services.structure.perception_fingerprint import (
    build_perception_fingerprint,
    vision_request_contract,
)

W, H = 1600, 1200
SX, SY = W / 1000.0, H / 1000.0
TEXT_BOXES = [
    (120, 600, 180, 30),
    (420, 700, 150, 28),
    (760, 820, 170, 30),
    (1080, 940, 160, 28),
]


def _make_reference(path: Path) -> None:
    image = Image.new("RGB", (W, H), (26, 25, 23))
    draw = ImageDraw.Draw(image)
    for index, (x, y, _w, _h) in enumerate(TEXT_BOXES):
        draw.text((x + 4, y + 6), f"ROW-{index}", fill=(235, 232, 225))
    image.save(path)


def _normalized_items() -> list[dict]:
    return [
        {
            "type": "text",
            "text": f"ROW-{index}",
            "bbox": {
                "x": x / SX,
                "y": y / SY,
                "width": box_w / SX,
                "height": box_h / SY,
            },
        }
        for index, (x, y, box_w, box_h) in enumerate(TEXT_BOXES)
    ]


def test_infer_selects_normalized_transform_from_pixel_evidence(tmp_path) -> None:
    path = tmp_path / "reference.png"
    _make_reference(path)
    scorer = build_ink_scorer(path)
    assert scorer is not None

    decision = infer_coordinate_space(_normalized_items(), W, H, scorer)

    assert decision.provenance == "xywh-1000"
    assert decision.x_scale == SX
    assert decision.y_scale == SY
    assert decision.evidence["supportedBoxes"] >= 3
    assert decision.evidence["identitySupportedBoxes"] == 0


def test_resolve_bbox_restores_normalized_y_and_protects_pixel_container(
    tmp_path,
) -> None:
    path = tmp_path / "reference.png"
    _make_reference(path)
    scorer = build_ink_scorer(path)
    decision = infer_coordinate_space(_normalized_items(), W, H, scorer)

    raw = _normalized_items()[0]["bbox"]
    restored, provenance = resolve_bbox(raw, decision, W, H, scorer)
    assert restored is not None
    assert abs(restored[1] - TEXT_BOXES[0][1]) <= 2
    assert provenance == "xywh-1000"

    # A container already expressed in source pixels must not be inflated.
    pixel_container = {"x": 0, "y": 0, "width": W, "height": H}
    kept, container_provenance = resolve_bbox(
        pixel_container, decision, W, H, scorer
    )
    assert kept == [0, 0, W, H]
    assert container_provenance == "identity-override-bounds"


def test_legacy_axis_scales_keeps_historical_y_behaviour() -> None:
    x_scale, y_scale, label = legacy_axis_scales([220.0, 340.0], 1920)
    assert x_scale == 1.92
    assert y_scale == 1.0
    assert label == "legacy-heuristic"


def test_parse_without_reference_pixels_uses_legacy_contract() -> None:
    raw = json.dumps(
        {
            "containers": [],
            "elements": [
                {
                    "type": "text",
                    "text": "auto_backup",
                    "bbox": {"x": 220, "y": 172, "width": 340, "height": 32},
                }
            ],
            "assets": [],
            "backgrounds": [],
        }
    )
    parsed = parse_vlm_json(raw, 1920, 826, bbox_format="source-px-xywh")
    assert parsed["elements"][0]["bbox"] == [422, 172, 653, 32]
    assert parsed["coordinateSpace"]["provenance"] == "legacy-heuristic"
    assert parsed["elements"][0]["coordinateSpace"] == "legacy-heuristic"


def test_parse_with_reference_pixels_restores_y_axis(tmp_path) -> None:
    path = tmp_path / "reference.png"
    _make_reference(path)
    items = _normalized_items()
    raw = json.dumps(
        {
            "containers": [
                {"role": "banner", "bbox": {"x": 0, "y": 0, "width": W, "height": 80}}
            ],
            "elements": items,
            "assets": [],
            "backgrounds": [],
        }
    )
    parsed = parse_vlm_json(
        raw,
        W,
        H,
        bbox_format="source-px-xywh",
        image_path=path,
    )
    assert parsed["coordinateSpace"]["provenance"] == "xywh-1000"
    assert parsed["coordinateSpace"]["schema_version"] == (
        COORDINATE_CONTRACT_VERSION
    )
    for element, expected in zip(parsed["elements"], TEXT_BOXES):
        assert abs(element["bbox"][1] - expected[1]) <= 2
        assert element["coordinateSpace"] == "xywh-1000"
    assert parsed["containers"][0]["coordinateSpace"] == (
        "identity-override-bounds"
    )


class _Cfg:
    vision_model = "qwen3-vl-plus"
    vision_temperature = 0.1
    vision_seed = 20261108
    vision_send_seed = False
    vision_max_tokens = 16000
    vision_persistent_cache = True


def _runtime(**kwargs) -> GroundingReliability:
    options = {
        "endpoints": ("https://example.invalid/v1",),
        "model": "qwen3-vl-plus",
        "cache_namespace": "test",
    }
    options.update(kwargs)
    return GroundingReliability(**options)


def test_request_contract_is_part_of_cache_identity() -> None:
    base = _runtime()
    with_contract = _runtime(request_contract={"temperature": 0.0, "seed": 7})
    other_contract = _runtime(request_contract={"temperature": 0.2, "seed": 7})

    assert base.cache_key(b"image", "prompt") != with_contract.cache_key(
        b"image", "prompt"
    )
    assert with_contract.cache_key(b"image", "prompt") != other_contract.cache_key(
        b"image", "prompt"
    )


def test_persistent_cache_survives_a_new_runtime_instance(tmp_path) -> None:
    cache_dir = tmp_path / "vision-cache"
    first = _runtime(persistent_cache_dir=cache_dir)
    key = first.cache_key(b"image-bytes", "prompt-text")
    first._cache_put(key, {"elements": [{"bbox": [1, 2, 3, 4]}]}, {"total_tokens": 9})

    second = _runtime(persistent_cache_dir=cache_dir)
    cached = second._cache_get(key)

    assert cached is not None
    assert cached[0] == {"elements": [{"bbox": [1, 2, 3, 4]}]}
    assert cached[1] == {"total_tokens": 9}


def test_vision_request_contract_records_coordinate_version() -> None:
    contract = vision_request_contract(_Cfg())

    assert contract["temperature"] == 0.1
    assert contract["seed"] == 20261108
    assert contract["send_seed"] is False
    assert contract["max_tokens"] == "server-default"
    assert contract["max_tokens_sent"] is False
    assert contract["coordinate_contract"] == COORDINATE_CONTRACT_VERSION


def test_fingerprint_records_artifacts_and_is_persisted(tmp_path) -> None:
    out = tmp_path / "pipeline"
    out.mkdir()
    (out / "image_reference.json").write_text(
        json.dumps({"input": {"sha256": "abc", "size": [W, H]}}),
        encoding="utf-8",
    )
    (out / "11_som.json").write_text(
        json.dumps({"nodes": [{"coordinateSpace": "xywh-1000"}]}),
        encoding="utf-8",
    )
    (out / "09_evidence_bundle.json").write_text(
        json.dumps(
            {
                "provenance": {
                    "grounding_reliability": {
                        "model": "qwen3-vl-plus",
                        "cache_key_prefix": "deadbeef",
                        "cache_status": "hit",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = build_perception_fingerprint(_Cfg(), out)

    assert result["status"] == "computed"
    assert result["fingerprint_sha256"]
    assert "11_som.json" in result["artifacts"]
    assert result["grounding"]["cache_status"] == "hit"
    assert result["coordinate_spaces"] == {"xywh-1000": 1}
    assert (out / "perception_fingerprint.json").is_file()


def test_fingerprint_ignores_cache_hit_or_miss(tmp_path) -> None:
    """A cache hit must not change the identity of the perception artefacts."""
    digests = []
    for status in ("miss", "hit"):
        out = tmp_path / status
        out.mkdir()
        (out / "image_reference.json").write_text(
            json.dumps({"input": {"sha256": "abc", "size": [W, H]}}),
            encoding="utf-8",
        )
        (out / "11_som.json").write_text(
            json.dumps({"nodes": []}), encoding="utf-8"
        )
        (out / "09_evidence_bundle.json").write_text(
            json.dumps(
                {
                    "provenance": {
                        "grounding_reliability": {
                            "cache_key_prefix": "deadbeef",
                            "cache_status": status,
                            "coordinate_space": {
                                "provenance": "xywh-1000",
                                "schema_version": COORDINATE_CONTRACT_VERSION,
                            },
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        result = build_perception_fingerprint(_Cfg(), out)
        digests.append(result["fingerprint_sha256"])
        assert result["grounding"]["coordinate_space"]["provenance"] == (
            "xywh-1000"
        )
    assert digests[0] == digests[1]
