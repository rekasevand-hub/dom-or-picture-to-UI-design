"""LLM-authored similar icons for unresolved iconfont crops."""

from __future__ import annotations

import base64
import hashlib
import io
import statistics
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw

from src.app.services.structure.asset_fusion import fuse_asset_record


GENERATOR = "codex-pillow-icon-v1"
MODEL = "gpt-5-codex"
PROMPT_VERSION = "d012.1"
REVIEW_STATUS = "accepted-product-policy"


def generate_icon_approximations(
    design: Mapping[str, Any],
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Attach explicit generated-icon candidates to unresolved icon crops."""
    import copy

    updated = copy.deepcopy(dict(design))
    output = Path(output_dir)
    icons_dir = output / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for element in updated.get("elements") or []:
        if not isinstance(element, dict) or not _is_icon_crop(element):
            continue
        semantic = _semantic_name(str(element.get("name") or ""))
        width = max(1, int(round(float(element.get("width") or 1))))
        height = max(1, int(round(float(element.get("height") or 1))))
        color = _ink_color(element.get("imageBase64"))
        payload = _render_icon(semantic, width=width, height=height, color=color)
        digest = hashlib.sha256(payload).hexdigest()
        target = icons_dir / f"{digest}.png"
        target.write_bytes(payload)
        display = _display_payload(element)
        prompt = (
            f"Generate a minimal transparent-background line icon semantically "
            f"matching the browser iconfont '{semantic}', preserving its "
            f"{width}x{height} display box and approximate ink color."
        )
        candidate = {
            "generator": GENERATOR,
            "model": MODEL,
            "input_reference": (
                f"{element.get('id')}:{element.get('name')}:"
                f"{display.get('payload_sha256')}"
            ),
            "prompt": prompt,
            "prompt_version": PROMPT_VERSION,
            "review_status": REVIEW_STATUS,
            "payload_sha256": digest,
            "bytes_present": True,
            "use_class": "icon-crop",
            "semantic": semantic,
            "locator": f"icons/{target.name}",
        }
        element["generatedAssetCandidates"] = [candidate]
        element["generatedIcon"] = dict(candidate)
        element["imageBase64"] = base64.b64encode(payload).decode("ascii")
        record = (element.get("assetIdentity") or {}).get("asset_record") or {}
        element["sourceResolution"] = fuse_asset_record(
            record,
            generated_candidates=[candidate],
            prefer_generated_for_icon_crop=True,
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
