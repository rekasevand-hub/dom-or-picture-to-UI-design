"""Reference-guided generated approximations for image enrichment."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image

GENERATOR = "reference-guided-image-edit/1.0"
PROMPT_VERSION = "grounding-image-enrichment/1.0"
REVIEW_STATUS = "candidate-unreviewed"
MIN_EDIT_AREA = 921_600
EDIT_SIZES = ((1024, 1024), (1536, 1024), (1024, 1536))


class _ImageEditError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _png_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _decode_bytes(value: Any) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if isinstance(value, Image.Image):
        return _png_bytes(value.convert("RGB"))
    if isinstance(value, Path):
        return value.read_bytes() if value.is_file() else None
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    try:
        return base64.b64decode(text, validate=True)
    except (ValueError, TypeError):
        return None


def _reference_bytes(request: Mapping[str, Any]) -> bytes | None:
    for key in (
        "reference_image",
        "reference_image_base64",
        "source_image",
        "input_reference",
    ):
        payload = _decode_bytes(request.get(key))
        if payload:
            try:
                with Image.open(io.BytesIO(payload)) as image:
                    return _png_bytes(image.convert("RGB"))
            except OSError:
                continue
    return None


def _mask_selection(request: Mapping[str, Any]) -> bytes | None:
    for key in ("mask_png", "mask", "selection_mask"):
        payload = _decode_bytes(request.get(key))
        if not payload:
            continue
        try:
            with Image.open(io.BytesIO(payload)) as image:
                return _png_bytes(image.convert("L"))
        except OSError:
            continue
    return None


def _prepare_edit_size(width: int, height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        return 1024, 1024
    ratio = width / height
    if ratio >= 1.2:
        size = 1536, 1024
    elif ratio <= 0.83:
        size = 1024, 1536
    else:
        size = 1024, 1024
    if size[0] * size[1] < MIN_EDIT_AREA:
        return 1024, 1024
    return size


def _resize_reference(reference: bytes, size: tuple[int, int]) -> bytes:
    with Image.open(io.BytesIO(reference)) as image:
        prepared = image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    return _png_bytes(prepared)


def _native_mask(mask: bytes, size: tuple[int, int]) -> bytes:
    with Image.open(io.BytesIO(mask)) as image:
        selection = image.convert("L").resize(size, Image.Resampling.NEAREST)
    alpha = selection.point(lambda value: 255 - value)
    native = Image.new("RGBA", size, (255, 255, 255, 255))
    native.putalpha(alpha)
    return _png_bytes(native)


def _client(cfg: Any) -> Any:
    configured = getattr(cfg, "image_generation_client", None)
    if configured is not None:
        return configured
    import requests

    return requests.Session()


def _post_edit(
    cfg: Any,
    *,
    prompt: str,
    prepared_reference: bytes,
    prepared_mask: bytes | None,
    size: tuple[int, int],
) -> bytes:
    base_url = str(getattr(cfg, "image_generation_base_url", "") or "").rstrip("/")
    api_key = str(getattr(cfg, "image_generation_api_key", "") or "")
    if not base_url or not api_key:
        raise _ImageEditError("image generation provider is not configured")
    files: dict[str, tuple[str, bytes, str]] = {
        "image[]": ("reference.png", prepared_reference, "image/png")
    }
    if prepared_mask is not None:
        files["mask"] = ("mask.png", prepared_mask, "image/png")
    data = {
        "model": str(
            getattr(cfg, "image_generation_model", "seedream-5.0-flash")
        ),
        "prompt": prompt,
        "size": f"{size[0]}x{size[1]}",
        "quality": "high",
        "output_format": "png",
        "background": "opaque",
        "n": "1",
    }
    response = _client(cfg).post(
        f"{base_url}/images/edits",
        headers={"Authorization": f"Bearer {api_key}"},
        data=data,
        files=files,
        timeout=float(getattr(cfg, "image_generation_timeout", 20)),
    )
    status = int(getattr(response, "status_code", 0) or 0)
    content = bytes(getattr(response, "content", b"") or b"")
    if status >= 400:
        text = str(getattr(response, "text", "") or content[:1000].decode(errors="replace"))
        raise _ImageEditError(text or f"HTTP {status}", status=status)
    try:
        value = json.loads(content)
        encoded = str(((value.get("data") or [{}])[0]).get("b64_json") or "")
        payload = base64.b64decode(encoded) if encoded else None
    except (ValueError, TypeError):
        payload = None
    if not payload and content.startswith(b"\x89PNG\r\n\x1a\n"):
        payload = content
    if not payload:
        raise _ImageEditError("image edit returned no image bytes", status=status)
    return payload


def _is_mask_rejection(error: _ImageEditError) -> bool:
    text = str(error).lower()
    return bool(
        error.status in {400, 422}
        and ("mask" in text or "unsupported" in text or "parameter" in text)
    )


def _result(
    *,
    request: Mapping[str, Any],
    cfg: Any,
    reference: bytes | None,
    payload: bytes | None,
    method: str,
    generated: bool,
    size: tuple[int, int],
    review_status: str = REVIEW_STATUS,
    degraded_reason: str = "",
) -> dict[str, Any]:
    digest = _sha256(payload) if payload else None
    return {
        "generator": GENERATOR,
        "model": str(
            getattr(cfg, "image_generation_model", "seedream-5.0-flash")
        ),
        "input_reference": (
            f"sha256:{_sha256(reference)}" if reference else None
        ),
        "prompt": str(request.get("prompt") or ""),
        "prompt_version": PROMPT_VERSION,
        "review_status": review_status,
        "payload_sha256": digest,
        "bytes_present": payload is not None,
        "payload": payload,
        "original": False,
        "generated": bool(generated and payload is not None),
        "method": method,
        "prepared_size": [size[0], size[1]],
        "degraded_reason": degraded_reason,
    }


def generate_asset_approximation(request: dict, cfg: Any) -> dict[str, Any]:
    """Generate one candidate only when a source reference is available."""

    if not isinstance(request, Mapping):
        raise ValueError("request must be an object")
    reference = _reference_bytes(request)
    width = int(request.get("width") or 0)
    height = int(request.get("height") or 0)
    if reference is None and width > 0 and height > 0:
        size = _prepare_edit_size(width, height)
    else:
        size = _prepare_edit_size(width, height)
    if reference is None:
        return _result(
            request=request,
            cfg=cfg,
            reference=None,
            payload=None,
            method="blocked-missing-reference",
            generated=False,
            size=size,
            review_status="blocked-missing-reference",
            degraded_reason="reference image bytes are required",
        )
    base_url = str(getattr(cfg, "image_generation_base_url", "") or "")
    api_key = str(getattr(cfg, "image_generation_api_key", "") or "")
    if not base_url or not api_key:
        return _result(
            request=request,
            cfg=cfg,
            reference=reference,
            payload=reference,
            method="local-reference-fallback",
            generated=False,
            size=size,
            review_status="candidate-local-fallback",
            degraded_reason="image generation provider is not configured",
        )

    prepared_reference = _resize_reference(reference, size)
    mask = _mask_selection(request)
    prepared_mask = _native_mask(mask, size) if mask else None
    degraded_reason = ""
    try:
        if prepared_mask is not None:
            try:
                payload = _post_edit(
                    cfg,
                    prompt=str(request.get("prompt") or ""),
                    prepared_reference=prepared_reference,
                    prepared_mask=prepared_mask,
                    size=size,
                )
                return _result(
                    request=request,
                    cfg=cfg,
                    reference=reference,
                    payload=payload,
                    method="reference-edit-native-mask",
                    generated=True,
                    size=size,
                )
            except _ImageEditError as error:
                if not _is_mask_rejection(error):
                    raise
                degraded_reason = f"native mask rejected: {error}"
        payload = _post_edit(
            cfg,
            prompt=str(request.get("prompt") or ""),
            prepared_reference=prepared_reference,
            prepared_mask=None,
            size=size,
        )
        return _result(
            request=request,
            cfg=cfg,
            reference=reference,
            payload=payload,
            method=(
                "reference-edit-degraded"
                if prepared_mask is not None
                else "reference-edit"
            ),
            generated=True,
            size=size,
            degraded_reason=degraded_reason,
        )
    except _ImageEditError as error:
        return _result(
            request=request,
            cfg=cfg,
            reference=reference,
            payload=prepared_reference,
            method="local-reference-fallback",
            generated=False,
            size=size,
            review_status="candidate-local-fallback",
            degraded_reason=str(error),
        )


def restore_background(
    image: Image.Image,
    mask_png: bytes,
    prompt: str,
    cfg: Any,
) -> dict[str, Any]:
    """Generate and composite a background only in selected mask regions."""

    if not isinstance(image, Image.Image):
        raise ValueError("image must be a PIL Image")
    source_bytes = _png_bytes(image.convert("RGB"))
    generated = generate_asset_approximation(
        {
            "prompt": prompt,
            "width": image.width,
            "height": image.height,
            "reference_image": source_bytes,
            "mask_png": mask_png,
        },
        cfg,
    )
    target = tuple(int(value) for value in generated["prepared_size"])
    with Image.open(io.BytesIO(source_bytes)) as source_image:
        observed = source_image.convert("RGB").resize(target, Image.Resampling.LANCZOS)
    with Image.open(io.BytesIO(mask_png)) as mask_image:
        selection = mask_image.convert("L").resize(target, Image.Resampling.NEAREST)
    observed_array = np.asarray(observed)
    if generated["bytes_present"]:
        with Image.open(io.BytesIO(generated["payload"])) as generated_image:
            candidate = generated_image.convert("RGB").resize(
                target, Image.Resampling.LANCZOS
            )
        candidate_array = np.asarray(candidate)
        selected = np.asarray(selection) > 127
        composite_array = np.where(
            selected[:, :, None],
            candidate_array,
            observed_array,
        )
        composite = Image.fromarray(composite_array.astype(np.uint8), mode="RGB")
        composite_bytes = _png_bytes(composite)
        composite_meta = {
            "payload_sha256": _sha256(composite_bytes),
            "method": (
                "native-mask-composite"
                if generated["generated"]
                else "masked-reference-composite"
            ),
            "original": False,
        }
    else:
        composite_bytes = None
        composite_meta = {
            "payload_sha256": None,
            "method": "missing",
            "original": False,
        }
    generated_summary = {
        key: value
        for key, value in generated.items()
        if key != "payload"
    }
    return {
        "observed": {
            "payload_sha256": _sha256(source_bytes),
            "original": False,
            "reference_only": True,
        },
        "generated": generated_summary,
        "composite": composite_meta,
        "composite_payload": composite_bytes,
    }
