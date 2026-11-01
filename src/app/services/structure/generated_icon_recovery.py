"""LLM-authored similar icons for unresolved iconfont crops."""

from __future__ import annotations

import base64
import hashlib
import io
import re
import statistics
from collections.abc import Callable
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw

from src.app.services.structure.asset_fusion import fuse_asset_record


GENERATOR = "codex-pillow-icon-v1"
MODEL = "gpt-5-codex"
PROMPT_VERSION = "d012.1"
REVIEW_STATUS = "accepted-product-policy"
IMAGE_GENERATOR = "vlm-similar-image-v1"


def generate_icon_approximations(
    design: Mapping[str, Any],
    *,
    output_dir: str | Path,
    include_icons: bool = True,
    include_missing_images: bool = False,
    image_generator: Callable[[dict[str, Any]], bytes] | None = None,
    svg_generator: Callable[[dict[str, Any]], str] | None = None,
    cfg: Any | None = None,
) -> dict[str, Any]:
    """Attach explicit generated candidates to unresolved icon/display uses."""
    import copy

    updated = copy.deepcopy(dict(design))
    output = Path(output_dir)
    icons_dir = output / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for element in updated.get("elements") or []:
        if not isinstance(element, dict):
            continue
        is_icon = include_icons and _is_icon_crop(element)
        is_missing_image = include_missing_images and _is_missing_image(element)
        if not is_icon and not is_missing_image:
            continue
        semantic = (
            _semantic_name(str(element.get("name") or ""))
            if is_icon
            else "generic-image"
        )
        width = max(1, int(round(float(element.get("width") or 1))))
        height = max(1, int(round(float(element.get("height") or 1))))
        color = _ink_color(element.get("imageBase64"))
        generation_mode = "deterministic-fallback"
        generated_request = None
        if is_missing_image:
            generated_request = _missing_image_request(
                element,
                width=width,
                height=height,
            )
            payload = (
                image_generator(generated_request)
                if image_generator is not None
                else _generate_image_provider(generated_request, cfg)
            )
            if payload:
                payload = _normalize_image_payload(payload, width, height)
                generation_mode = "provider-generated"
            else:
                svg_source = (
                    svg_generator(generated_request)
                    if svg_generator is not None
                    else _generate_vlm_svg(generated_request, cfg)
                )
                payload = _rasterize_generated_svg(
                    svg_source,
                    output / "generated-svg",
                    width=width,
                    height=height,
                )
                if payload:
                    generation_mode = "vlm-svg"
                else:
                    payload = _render_missing_image(
                        width=width,
                        height=height,
                        color=color,
                    )
        else:
            payload = _render_icon(
                semantic,
                width=width,
                height=height,
                color=color,
            )
        digest = hashlib.sha256(payload).hexdigest()
        target = icons_dir / f"{digest}.png"
        target.write_bytes(payload)
        display = _display_payload(element)
        prompt = (
            f"Generate a minimal transparent-background line icon semantically "
            f"matching the browser iconfont '{semantic}', preserving its "
            f"{width}x{height} display box and approximate ink color."
            if is_icon
            else _missing_image_prompt(element, width, height)
        )
        candidate = {
            "generator": IMAGE_GENERATOR if is_missing_image else GENERATOR,
            "model": (
                str(getattr(cfg, "image_generation_model", "") or MODEL)
                if is_missing_image
                else MODEL
            ),
            "input_reference": (
                f"{element.get('id')}:{element.get('name')}:"
                f"{display.get('payload_sha256')}"
            ),
            "prompt": prompt,
            "prompt_version": PROMPT_VERSION,
            "review_status": REVIEW_STATUS,
            "payload_sha256": digest,
            "bytes_present": True,
            "use_class": "icon-crop" if is_icon else (
                "image-generated"
                if generation_mode in {"provider-generated", "vlm-svg"}
                else "image-placeholder"
            ),
            "generation_mode": generation_mode,
            "semantic": semantic,
            "locator": f"icons/{target.name}",
        }
        element["generatedAssetCandidates"] = [candidate]
        element.pop("generatedImageRequired", None)
        element.pop("generationReferenceImageBase64", None)
        if is_icon:
            element["generatedIcon"] = dict(candidate)
        else:
            element["generatedImageApproximation"] = dict(candidate)
        element["imageBase64"] = base64.b64encode(payload).decode("ascii")
        record = (element.get("assetIdentity") or {}).get("asset_record") or {}
        element["sourceResolution"] = fuse_asset_record(
            record,
            generated_candidates=[candidate],
            prefer_generated_for_icon_crop=is_icon,
        )
        rows.append(
            {
                "element_id": element.get("id"),
                "semantic": semantic,
                "payload_sha256": digest,
                "locator": candidate["locator"],
            }
        )
    result = {
        "schema_version": "dom-generated-icon-recovery/1.0",
        "generator": GENERATOR,
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "generated_count": len(rows),
        "rows": rows,
        "design": updated,
    }
    (output / "generated_icons.json").write_text(
        __import__("json").dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _is_icon_crop(element: Mapping[str, Any]) -> bool:
    record = (element.get("assetIdentity") or {}).get("asset_record") or {}
    use = record.get("use") or {}
    return str(use.get("source_kind") or "") == "icon-crop"


def _is_missing_image(element: Mapping[str, Any]) -> bool:
    if str(element.get("type") or "").lower() not in {"image", "avatar"}:
        return False
    if element.get("generatedImageRequired"):
        return not bool(element.get("generatedImageApproximation"))
    record = (element.get("assetIdentity") or {}).get("asset_record") or {}
    display = record.get("display_payload") or {}
    source = record.get("source_identity") or {}
    source_status = str(source.get("status") or "").lower()
    name = str(element.get("name") or "").strip().lower()
    image_tag = (
        name.startswith(("img", "image", "photo", "picture"))
        or bool(str(element.get("alt") or "").strip())
        or (
            str(display.get("status") or "") == "missing"
            and not str(source.get("source_url") or "").strip()
        )
    )
    return (
        (
            str(display.get("status") or "") == "missing"
            or source_status
            in {"missing", "unavailable", "blocked-incomplete-identity"}
        )
        and image_tag
        and not bool(element.get("generatedImageApproximation"))
    )


def _missing_image_prompt(
    element: Mapping[str, Any],
    width: int,
    height: int,
) -> str:
    identity = str(
        element.get("imagePrompt")
        or element.get("alt")
        or element.get("name")
        or "website image"
    ).strip()
    return (
        "Generate a clean, realistic website image matching the semantic subject "
        f"'{identity}'. Preserve a {width}x{height} composition suitable for the "
        "captured UI. Do not include text, logos, borders, or browser chrome. "
        "This is a similar replacement, not the original asset."
    )


def _missing_image_request(
    element: Mapping[str, Any],
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    return {
        "element_id": element.get("id"),
        "name": element.get("name"),
        "alt": element.get("alt"),
        "width": width,
        "height": height,
        "reference_image_base64": (
            element.get("generationReferenceImageBase64")
            or element.get("imageBase64")
        ),
        "prompt": _missing_image_prompt(element, width, height),
    }


def _generate_image_provider(
    request: Mapping[str, Any],
    cfg: Any | None,
) -> bytes | None:
    if cfg is None:
        return None
    api_key = getattr(cfg, "image_generation_api_key", None)
    if not api_key:
        return None
    try:
        import openai

        client = openai.OpenAI(
            base_url=(
                getattr(cfg, "image_generation_base_url", None)
                or getattr(cfg, "vision_base_url", None)
            ),
            api_key=api_key,
            timeout=float(getattr(cfg, "image_generation_timeout", 20)),
        )
        response = client.images.generate(
            model=getattr(cfg, "image_generation_model", "gpt-image-1"),
            prompt=str(request["prompt"]),
            size="1024x1024",
            response_format="b64_json",
        )
        encoded = response.data[0].b64_json
        return base64.b64decode(encoded) if encoded else None
    except Exception:
        return None


def _generate_vlm_svg(
    request: Mapping[str, Any],
    cfg: Any | None,
) -> str:
    if cfg is None or not getattr(cfg, "vision_api_key", None):
        return ""
    try:
        from src.app.services.llm.llm_service import call_vlm

        content = [
            {
                "type": "text",
                "text": (
                    "Create one sanitized SVG illustration for the missing website "
                    f"image described as: {request['prompt']}\n"
                    f"Use a {request['width']}x{request['height']} viewBox. "
                    "Return only an <svg>...</svg> element. Do not include scripts, "
                    "external URLs, text, logos, or claim original identity."
                ),
            }
        ]
        reference = str(request.get("reference_image_base64") or "")
        if reference:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64," + reference},
                }
            )
        raw = call_vlm([{"role": "user", "content": content}], cfg)
        match = re.search(r"<svg\b[\s\S]*?</svg>", raw, re.IGNORECASE)
        return match.group(0) if match else ""
    except Exception:
        return ""


def _rasterize_generated_svg(
    source: str,
    output_dir: Path,
    *,
    width: int,
    height: int,
) -> bytes | None:
    if not source:
        return None
    try:
        from src.app.services.structure.svg_materialization import (
            materialize_svg_assets,
        )

        manifest = materialize_svg_assets(
            [{"svgSource": source, "w": width, "h": height}],
            output_dir,
            page_url="",
        )
        row = (manifest.get("assets") or [{}])[0]
        display_path = str(row.get("displayPayloadPath") or "")
        if not display_path:
            return None
        path = output_dir / display_path
        return path.read_bytes() if path.is_file() else None
    except Exception:
        return None


def _normalize_image_payload(payload: bytes, width: int, height: int) -> bytes:
    image = Image.open(io.BytesIO(payload)).convert("RGB")
    image = image.resize((width, height), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _semantic_name(name: str) -> str:
    lowered = name.lower()
    if "icon-search" in lowered:
        return "search"
    if "icon-user" in lowered:
        return "user"
    if "icon-shujia" in lowered:
        return "bookshelf"
    if "icon-jiantou-right" in lowered or "icon-arrow-right" in lowered:
        return "chevron-right"
    return "generic"


def _display_payload(element: Mapping[str, Any]) -> dict[str, Any]:
    display = element.get("displayPayload")
    if isinstance(display, Mapping):
        return dict(display)
    record = (element.get("assetIdentity") or {}).get("asset_record") or {}
    value = record.get("display_payload")
    return dict(value) if isinstance(value, Mapping) else {}


def _ink_color(encoded: Any) -> tuple[int, int, int]:
    text = str(encoded or "")
    if not text:
        return (102, 102, 102)
    try:
        image = Image.open(io.BytesIO(base64.b64decode(text))).convert("RGBA")
    except (ValueError, TypeError, OSError):
        return (102, 102, 102)
    candidates = []
    for red, green, blue, alpha in image.get_flattened_data():
        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        if alpha >= 32 and luminance < 220:
            candidates.append((red, green, blue))
    if not candidates:
        return (102, 102, 102)
    return tuple(int(statistics.median(channel)) for channel in zip(*candidates))


def _render_icon(
    semantic: str,
    *,
    width: int,
    height: int,
    color: tuple[int, int, int],
) -> bytes:
    scale = 8
    image = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    stroke = max(1, int(round(min(width, height) * 0.10 * scale)))
    rgba = (*color, 255)

    def point(x: float, y: float) -> tuple[int, int]:
        return int(round(x * scale)), int(round(y * scale))

    if semantic == "search":
        draw.ellipse(
            (*point(width * 0.20, height * 0.20), *point(width * 0.72, height * 0.72)),
            outline=rgba,
            width=stroke,
        )
        draw.line(
            [point(width * 0.66, height * 0.66), point(width * 0.84, height * 0.84)],
            fill=rgba,
            width=stroke,
        )
    elif semantic == "user":
        draw.ellipse(
            (*point(width * 0.34, height * 0.18), *point(width * 0.66, height * 0.50)),
            outline=rgba,
            width=stroke,
        )
        draw.arc(
            (*point(width * 0.18, height * 0.48), *point(width * 0.82, height * 0.92)),
            start=190,
            end=350,
            fill=rgba,
            width=stroke,
        )
    elif semantic == "bookshelf":
        book_width = max(stroke, int(width * 0.16 * scale))
        for fraction in (0.20, 0.43, 0.66):
            left = int(width * fraction * scale)
            draw.rounded_rectangle(
                (
                    left,
                    int(height * 0.20 * scale),
                    left + book_width,
                    int(height * 0.80 * scale),
                ),
                radius=max(1, stroke // 2),
                outline=rgba,
                width=max(1, stroke // 2),
            )
    elif semantic == "chevron-right":
        draw.line(
            [
                point(width * 0.36, height * 0.22),
                point(width * 0.64, height * 0.50),
                point(width * 0.36, height * 0.78),
            ],
            fill=rgba,
            width=stroke,
            joint="curve",
        )
    else:
        draw.rounded_rectangle(
            (*point(width * 0.22, height * 0.22), *point(width * 0.78, height * 0.78)),
            radius=max(1, stroke),
            outline=rgba,
            width=stroke,
        )
    image = image.resize((width, height), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _render_missing_image(
    *,
    width: int,
    height: int,
    color: tuple[int, int, int],
) -> bytes:
    scale = 4
    image = Image.new("RGBA", (width * scale, height * scale), (242, 244, 247, 255))
    draw = ImageDraw.Draw(image)
    stroke = max(1, scale)
    line = (*color, 190)
    draw.rectangle(
        (0, 0, width * scale - 1, height * scale - 1),
        outline=line,
        width=stroke,
    )
    draw.line(
        [(0, height * scale), (width * scale, 0)],
        fill=line,
        width=stroke,
    )
    draw.line(
        [(0, 0), (width * scale, height * scale)],
        fill=line,
        width=stroke,
    )
    image = image.resize((width, height), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
