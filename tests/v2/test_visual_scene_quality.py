from __future__ import annotations

from PIL import Image

from src.app.services.evidence.visual_scene_quality import (
    evaluate_visual_scene,
)


def _design() -> dict:
    return {
        "canvas": {"width": 400, "height": 200},
        "elements": [
            {
                "id": "1",
                "type": "text",
                "x": 20,
                "y": 20,
                "width": 100,
                "height": 24,
                "text": "Title",
                "style": {
                    "fontFamily": "Arimo, Arial, sans-serif",
                    "fontSize": 16,
                    "lineHeight": 24,
                },
            },
            {
                "id": "2",
                "type": "image",
                "x": 150,
                "y": 20,
                "width": 24,
                "height": 24,
                "vectorSvg": "<svg width='24' height='24'/>",
            },
        ],
    }


def test_visual_scene_gate_rejects_duplicate_overlap(tmp_path):
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    Image.new("RGB", (400, 200), "white").save(reference)
    Image.new("RGB", (400, 200), "white").save(rendered)
    design = _design()
    design["elements"].append(
        {
            **design["elements"][0],
            "id": "duplicate",
            "x": 21,
        }
    )

    report = evaluate_visual_scene(design, rendered, reference)

    assert report["status"] == "fail"
    assert "duplicate-text-overlap" in report["blockers"]


def test_visual_scene_gate_accepts_clean_scene(tmp_path):
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    Image.new("RGB", (400, 200), "white").save(reference)
    Image.new("RGB", (400, 200), "white").save(rendered)

    report = evaluate_visual_scene(_design(), rendered, reference)

    assert report["status"] == "pass"
    assert report["metrics"]["duplicate_text_overlap_count"] == 0
    assert report["metrics"]["explicit_font_ratio"] == 1.0
