from __future__ import annotations

from PIL import Image, ImageDraw

from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter
from src.app.services.evidence.dom_visual_quality import (
    evaluate_dom_visual_quality,
)


def _content_image(path, size, *, almost_blank=False, antialias=False):
    width, height = size
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    if not almost_blank:
        draw.rectangle(
            [10, 10, int(width * 0.7), int(height * 0.4)],
            fill=(18, 120, 190) if not antialias else (19, 121, 191),
        )
        draw.rectangle(
            [10, int(height * 0.55), int(width * 0.9), int(height * 0.85)],
            fill=(34, 34, 34),
        )
    image.save(path)


def _design(*, image=False):
    elements = []
    if image:
        elements.append(
            {
                "id": "hero",
                "type": "image",
                "x": 10,
                "y": 10,
                "width": 100,
                "height": 60,
                "style": {},
            }
        )
    return {
        "canvas": {"width": 160, "height": 120, "background": "#ffffff"},
        "elements": elements,
    }


def test_content_source_rendered_almost_blank_fails(tmp_path):
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    _content_image(reference, (160, 120))
    _content_image(rendered, (160, 120), almost_blank=True)

    result = evaluate_dom_visual_quality(
        reference,
        rendered,
        _design(),
        {"imageFillReport": {"total": 0}},
    )

    assert result["checks"]["blank_area"]["status"] == "fail"


def test_expected_images_with_zero_readback_fills_fail(tmp_path):
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    _content_image(reference, (160, 120))
    _content_image(rendered, (160, 120))

    result = evaluate_dom_visual_quality(
        reference,
        rendered,
        _design(image=True),
        {"imageFillReport": {"total": 0}},
    )

    assert result["metrics"]["image_fill_rate"] == 0.0
    assert result["checks"]["image_fill"]["status"] == "fail"


def test_figma_image_report_fill_count_is_counted(tmp_path):
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    _content_image(reference, (160, 120))
    _content_image(rendered, (160, 120))

    result = evaluate_dom_visual_quality(
        reference,
        rendered,
        _design(image=True),
        {"imageFillReport": {"fillCount": 1}},
    )

    assert result["checks"]["image_fill"]["observed"] == 1
    assert result["checks"]["image_fill"]["status"] == "pass"


def test_small_antialias_difference_passes_visual_diff(tmp_path):
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    _content_image(reference, (160, 120))
    _content_image(rendered, (160, 120), antialias=True)

    result = evaluate_dom_visual_quality(
        reference,
        rendered,
        _design(),
        {"imageFillReport": {"total": 0}},
    )

    assert result["checks"]["visual_diff"]["status"] == "pass"


def test_height_drift_over_five_percent_warns(tmp_path):
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    _content_image(reference, (160, 120))
    _content_image(rendered, (160, 132))

    result = evaluate_dom_visual_quality(
        reference,
        rendered,
        _design(),
        {"imageFillReport": {"total": 0}},
    )

    assert result["checks"]["height"]["status"] == "warn"


def test_figma_adapter_writes_quality_from_real_readback_actions(tmp_path):
    class RecordingAdapter(FigmaBridgeAdapter):
        def __init__(self):
            self.calls = []

        def _send(self, action, params=None, **kwargs):
            self.calls.append((action, params))
            if action == "get_node_tree":
                return {
                    "id": "45:67",
                    "type": "FRAME",
                    "children": [],
                }
            if action == "image_fill_report":
                return {"total": 0}
            raise AssertionError(action)

    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    _content_image(reference, (160, 120))
    _content_image(rendered, (160, 120), almost_blank=True)
    adapter = RecordingAdapter()

    result = adapter.capture_visual_quality(
        "45:67",
        reference_png=reference,
        rendered_png=rendered,
        design=_design(),
        output_dir=tmp_path,
    )

    assert result["checks"]["blank_area"]["status"] == "fail"
    assert [call[0] for call in adapter.calls] == [
        "get_node_tree",
        "image_fill_report",
    ]
    assert (tmp_path / "visual-quality.json").is_file()
