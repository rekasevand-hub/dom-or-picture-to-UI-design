from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.evidence.native_text_quality import (
    build_native_text_quality,
)


def test_native_text_quality_is_diagnostic_and_splits_chrome(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path in (reference, rendered):
        image = Image.new("RGB", (200, 100), "white")
        ImageDraw.Draw(image).rectangle((20, 20, 60, 28), fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "type": "text",
                "contentRef": "text:label",
                "text": "Label",
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 40, 8],
                    }
                },
            }
        ]
    }
    readback = {
        "type": "FRAME",
        "children": [
            {
                "type": "TEXT",
                "characters": "Label",
                "bounds": {"x": 20, "y": 20, "width": 40, "height": 8},
            }
        ],
    }

    report = build_native_text_quality(
        design,
        readback,
        str(reference),
        str(rendered),
        [{"id": "page", "role": "page", "bbox": [0, 0, 200, 100]}],
    )

    assert report["acceptance_effect"] == "none"
    assert report["summary"]["nativeTextCount"] == 1
    assert report["owners"][0]["status"] == "pass"
    assert report["owners"][0]["baseline"] == "unknown"
    assert report["chromeRegions"][0]["chromeBadPixelCount"] == 0
    assert report["chromeRegions"][0]["status"] == "pass"
