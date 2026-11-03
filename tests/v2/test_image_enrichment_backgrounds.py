from __future__ import annotations

import hashlib
import io
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from src.app.services.structure.image_enrichment.backgrounds import (
    build_background_mask,
    create_background_candidates,
)


def test_background_mask_is_white_only_inside_selected_overlays():
    background = {
        "id": "hero",
        "name": "hero_background",
        "bbox": [10, 10, 80, 60],
    }
    overlays = [
        {
            "id": "card",
            "kind": "code-overlay",
            "bbox": [0, 15, 30, 20],
        },
        {
            "id": "button",
            "kind": "raster-overlay",
            "bbox": [50, 40, 60, 30],
        },
    ]

    raw = build_background_mask(background, overlays, (100, 80))
    mask = Image.open(io.BytesIO(raw)).convert("L")

    assert mask.size == (100, 80)
    assert mask.getpixel((0, 0)) == 0
    assert mask.getpixel((10, 15)) == 255
    assert mask.getpixel((50, 40)) == 255
    assert mask.getpixel((89, 69)) == 255
    assert mask.histogram()[255] == 20 * 20 + 40 * 30
    assert len(hashlib.sha256(raw).hexdigest()) == 64


def test_background_candidates_keep_unmasked_source_and_write_hashed_assets():
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        image = Image.new("RGB", (120, 90), "#dce8f4")
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 109, 79), fill="#88aacc")
        draw.rectangle((30, 20, 69, 49), fill="#ffffff")
        draw.rectangle((40, 55, 59, 69), fill="#2f6fed")
        background = {
            "id": "hero",
            "name": "hero_background",
            "bbox": [10, 10, 100, 70],
        }
        overlays = [
            {
                "id": "card",
                "kind": "code-overlay",
                "bbox": [30, 20, 40, 30],
            },
            {
                "id": "button",
                "kind": "code-overlay",
                "bbox": [40, 55, 20, 15],
            },
        ]

        candidate = create_background_candidates(
            image,
            background,
            overlays,
            root / "work",
        )
        source_crop = Image.open(candidate["sourceCrop"]["path"]).convert("RGB")
        expected_crop = image.crop((10, 10, 110, 80))
        mask = Image.open(candidate["mask"]["path"]).convert("L")
        clean = Image.open(candidate["cleanCandidate"]["path"]).convert("RGB")
        source_bytes = Path(candidate["sourceCrop"]["path"]).read_bytes()
        mask_bytes = Path(candidate["mask"]["path"]).read_bytes()
        clean_bytes = Path(candidate["cleanCandidate"]["path"]).read_bytes()

        assert ImageChops.difference(source_crop, expected_crop).getbbox() is None
        assert source_crop.size == (100, 70)
        assert mask.size == (120, 90)
        assert clean.size == (100, 70)
        assert mask.histogram()[255] == 40 * 30 + 20 * 15
        assert candidate["sourceCrop"]["payload_sha256"] == hashlib.sha256(
            source_bytes
        ).hexdigest()
        assert candidate["mask"]["payload_sha256"] == hashlib.sha256(
            mask_bytes
        ).hexdigest()
        assert candidate["cleanCandidate"]["payload_sha256"] == hashlib.sha256(
            clean_bytes
        ).hexdigest()
        assert candidate["sourceCrop"]["observed_source"] is True
        assert candidate["cleanCandidate"]["generated"] is False
        assert candidate["cleanCandidate"]["method"] == "edge-blend"


def test_background_candidate_ignores_overlay_outside_background():
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        image = Image.new("RGB", (100, 80), "white")
        candidate = create_background_candidates(
            image,
            {"id": "bg", "bbox": [20, 20, 40, 30]},
            [{"id": "outside", "kind": "code-overlay", "bbox": [0, 0, 10, 10]}],
            root / "work",
        )
        mask = Image.open(candidate["mask"]["path"]).convert("L")

    assert mask.histogram()[255] == 0
    assert candidate["overlayCount"] == 0
