from __future__ import annotations

import base64
import io
import json
from types import SimpleNamespace

from PIL import Image

from src.app.services.structure.image_enrichment.generation import (
    generate_asset_approximation,
    restore_background,
)


def _png_bytes(
    size: tuple[int, int],
    color: tuple[int, int, int] = (40, 80, 120),
) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def _mask_bytes(size: tuple[int, int], box: tuple[int, int, int, int]) -> bytes:
    image = Image.new("L", size, 0)
    image.paste(255, box)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class _Response:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: bytes | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self.content = payload or b""
        self.text = text or self.content.decode("utf-8", errors="replace")


class _Client:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url, *, headers, data, files, timeout):
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "data": dict(data),
                "files": dict(files),
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)


def _success(image_bytes: bytes) -> _Response:
    return _Response(
        payload=json.dumps(
            {"data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}]}
        ).encode("utf-8")
    )


def _cfg(client: _Client) -> SimpleNamespace:
    return SimpleNamespace(
        image_generation_base_url="https://generation.test/v1",
        image_generation_api_key="test-key",
        image_generation_model="seedream-5.0-flash",
        image_generation_timeout=18,
        image_generation_client=client,
    )


def test_reference_edit_prepares_native_mask_and_sends_both_images():
    reference = Image.new("RGB", (200, 120), "#224466")
    mask = _mask_bytes((200, 120), (60, 30, 140, 90))
    generated = _png_bytes((1536, 1024), (10, 180, 30))
    client = _Client([_success(generated)])

    result = generate_asset_approximation(
        {
            "name": "hero",
            "prompt": "Restore the occluded product using the visible reference.",
            "width": 200,
            "height": 120,
            "reference_image": reference,
            "mask_png": mask,
        },
        _cfg(client),
    )

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"] == "https://generation.test/v1/images/edits"
    assert call["data"]["model"] == "seedream-5.0-flash"
    assert call["data"]["size"] == "1536x1024"
    assert "image[]" in call["files"]
    assert "mask" in call["files"]
    sent_reference = Image.open(io.BytesIO(call["files"]["image[]"][1])).convert("RGB")
    assert sent_reference.size == (1536, 1024)
    assert sent_reference.getpixel((750, 500)) == pytest_approx((34, 68, 102))
    sent_mask = Image.open(io.BytesIO(call["files"]["mask"][1])).convert("RGBA")
    assert sent_mask.getpixel((512, 512))[3] == 0
    assert sent_mask.getpixel((10, 10))[3] == 255

    assert result["method"] == "reference-edit-native-mask"
    assert result["bytes_present"] is True
    assert result["original"] is False
    assert result["generated"] is True
    assert result["payload"] == generated
    assert len(result["payload_sha256"]) == 64


def test_unsupported_native_mask_degrades_to_reference_edit_without_mask():
    reference = _png_bytes((320, 180), (80, 90, 100))
    mask = _mask_bytes((320, 180), (100, 40, 220, 150))
    generated = _png_bytes((1536, 1024), (20, 180, 90))
    client = _Client(
        [
            _Response(status_code=400, text="unsupported mask parameter"),
            _success(generated),
        ]
    )

    result = generate_asset_approximation(
        {
            "prompt": "Restore the hidden region from the reference.",
            "width": 320,
            "height": 180,
            "reference_image": reference,
            "mask_png": mask,
        },
        _cfg(client),
    )

    assert len(client.calls) == 2
    assert "mask" in client.calls[0]["files"]
    assert "mask" not in client.calls[1]["files"]
    assert result["method"] == "reference-edit-degraded"
    assert result["generated"] is True
    assert result["original"] is False
    assert "mask" in result["degraded_reason"].lower()


def test_missing_reference_never_falls_back_to_text_only_generation():
    generated = _png_bytes((1024, 1024), "green")
    client = _Client([_success(generated)])

    result = generate_asset_approximation(
        {"prompt": "Generate an unrelated product image."},
        _cfg(client),
    )

    assert client.calls == []
    assert result["bytes_present"] is False
    assert result["generated"] is False
    assert result["original"] is False
    assert result["review_status"] == "blocked-missing-reference"


def test_background_restore_composites_only_white_mask_regions():
    source = Image.new("RGB", (100, 100), (20, 40, 160))
    mask = _mask_bytes((100, 100), (30, 30, 70, 70))
    generated = _png_bytes((1024, 1024), (20, 180, 60))
    client = _Client([_success(generated)])

    result = restore_background(
        source,
        mask,
        "Restore only the selected occlusion.",
        _cfg(client),
    )
    composite = Image.open(io.BytesIO(result["composite_payload"])).convert("RGB")

    assert composite.size == (1024, 1024)
    assert composite.getpixel((5, 5)) == (20, 40, 160)
    assert composite.getpixel((512, 512)) == (20, 180, 60)
    assert result["generated"]["original"] is False
    assert result["composite"]["original"] is False
    assert result["composite"]["method"] == "native-mask-composite"
    assert result["observed"]["payload_sha256"] != result["generated"]["payload_sha256"]


def pytest_approx(value: tuple[int, int, int]):
    import pytest

    return pytest.approx(value, abs=2)
