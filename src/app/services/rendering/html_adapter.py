"""Deterministic standalone HTML renderer for fixed-coordinate DesignSpec."""

from __future__ import annotations

import base64
import hashlib
import html
import io
import re
from pathlib import Path
from typing import Any

from PIL import Image

from src.app.services.rendering.adapter_base import PrototypeAdapter, paint_order
from src.app.services.structure.image_contract import audit_native_reconstruction


def _safe_identifier(value: Any, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "")).strip("-")
    return text[:72] or fallback


def _css_value(value: Any) -> str:
    return str(value or "").replace(";", "").replace("{", "").replace("}", "")


def _image_bytes(value: Any) -> bytes:
    text = str(value or "").strip()
    if "," in text and text.lower().startswith("data:"):
        text = text.split(",", 1)[1]
    try:
        payload = base64.b64decode(text, validate=False)
        with Image.open(io.BytesIO(payload)) as image:
            image.verify()
        return payload
    except Exception:  # noqa: BLE001 - malformed display payloads get a placeholder
        output = io.BytesIO()
        Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(output, format="PNG")
        return output.getvalue()


def _is_generated(element: dict[str, Any]) -> bool:
    image_meta = element.get("imageMVP")
    if isinstance(image_meta, dict) and image_meta.get("generated") is True:
        return True
    generated = element.get("generatedApproximation")
    if isinstance(generated, dict) and generated.get("generated") is True:
        return True
    return any(
        isinstance(candidate, dict) and candidate.get("generated") is True
        for candidate in element.get("generatedAssetCandidates") or []
    )


class HTMLAdapter(PrototypeAdapter):
    """Write a static absolute-positioned HTML prototype and local assets."""

    def __init__(
        self,
        output_dir: str | Path,
        *,
        allow_reference_underlay: bool = False,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.allow_reference_underlay = allow_reference_underlay
        self.last_audit: dict[str, Any] = {}
        self.last_render_report: dict[str, Any] = {}

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None

    def create_frame(self, spec: dict[str, Any]) -> str | None:
        return None

    def create_rectangle(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        return None

    def create_ellipse(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        return None

    def create_text(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        return None

    def create_image(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        return None

    def flush(self) -> None:
        return None

    def render_design(self, design: dict[str, Any]) -> None:
        if not isinstance(design, dict):
            raise ValueError("design must be an object")
        canvas = design.get("canvas") or {}
        try:
            width = int(canvas.get("width") or 0)
            height = int(canvas.get("height") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("canvas width and height must be integers") from exc
        if width <= 0 or height <= 0:
            raise ValueError("canvas width and height must be positive")

        audit = audit_native_reconstruction(design)
        self.last_audit = audit
        reference_mode = bool(
            self.allow_reference_underlay
            or (design.get("_meta") or {}).get("referenceMode")
            or ((design.get("_meta") or {}).get("imageMVP") or {}).get(
                "referenceMode"
            )
        )
        underlay_ids = {
            item["id"] for item in audit["underlays"] if item.get("id")
        }
        if audit["status"] == "blocked" and not reference_mode:
            raise ValueError(
                "visible full-screenshot underlay is blocked in native reconstruction"
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        assets_dir = self.output_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        css_rules = [
            "html,body{margin:0;padding:0;background:transparent;}",
            ".screen{position:relative;overflow:hidden;box-sizing:border-box;}",
            (
                f"#design-screen{{width:{width}px;height:{height}px;"
                f"background:{_css_value(canvas.get('background') or '#ffffff')};}}"
            ),
            ".element{position:absolute;box-sizing:border-box;}",
            ".element-clipped{overflow:hidden;}",
            ".generated-asset{object-fit:fill;}",
            ".reference-underlay{opacity:1;}",
        ]
        body: list[str] = []
        image_count = 0
        text_count = 0
        ordered = paint_order(
            [element for element in design.get("elements") or [] if isinstance(element, dict)]
        )
        for paint_index, (_index, element) in enumerate(ordered):
            element_id = str(element.get("id") or f"element-{paint_index}")
            css_id = f"element-{_safe_identifier(element_id, str(paint_index))}"
            element_type = str(element.get("type") or "rectangle").lower()
            style = element.get("style") if isinstance(element.get("style"), dict) else {}
            x = int(round(float(element.get("x") or 0)))
            y = int(round(float(element.get("y") or 0)))
            element_width = max(0, int(round(float(element.get("width") or 0))))
            element_height = max(0, int(round(float(element.get("height") or 0))))
            clipped = bool(
                element.get("clipToBounds")
                or str(element.get("overflowX") or "").lower() in {"hidden", "clip"}
                or str(element.get("overflowY") or "").lower() in {"hidden", "clip"}
            )
            rule = [
                f"left:{x}px",
                f"top:{y}px",
                f"width:{element_width}px",
                f"height:{element_height}px",
            ]
            z_index = int(element.get("zIndex") or 0)
            if z_index:
                rule.append(f"z-index:{z_index}")
            if style.get("fillColor") and element_type not in {"image", "avatar"}:
                rule.append(f"background:{_css_value(style['fillColor'])}")
            if style.get("textColor"):
                rule.append(f"color:{_css_value(style['textColor'])}")
            if style.get("fontFamily"):
                rule.append(f"font-family:{_css_value(style['fontFamily'])}")
            if style.get("fontSize"):
                rule.append(f"font-size:{_css_value(style['fontSize'])}px")
            if style.get("fontWeight"):
                rule.append(f"font-weight:{_css_value(style['fontWeight'])}")
            if style.get("borderColor"):
                rule.append(f"border-color:{_css_value(style['borderColor'])}")
            if style.get("borderWidth"):
                rule.append(f"border-width:{_css_value(style['borderWidth'])}px")
            if style.get("borderStyle"):
                rule.append(f"border-style:{_css_value(style['borderStyle'])}")
            elif style.get("borderWidth"):
                rule.append("border-style:solid")
            if style.get("borderRadius"):
                rule.append(f"border-radius:{_css_value(style['borderRadius'])}px")
            if style.get("opacity") is not None:
                rule.append(f"opacity:{_css_value(style['opacity'])}")
            css_rules.append(f"#{css_id}{{{';'.join(rule)};}}")

            common = (
                f' id="{html.escape(css_id, quote=True)}"'
                f' class="element{" element-clipped" if clipped else ""}"'
                f' data-element-id="{html.escape(element_id, quote=True)}"'
                f' data-element-type="{html.escape(element_type, quote=True)}"'
                f' data-paint-order="{paint_index}"'
            )
            if element_id in underlay_ids:
                common += ' data-reference-underlay="true"'
            if _is_generated(element):
                common += ' data-generated="true"'
            if element_type in {"image", "avatar"} or element.get("imageBase64"):
                payload = _image_bytes(element.get("imageBase64"))
                digest = hashlib.sha256(payload).hexdigest()
                asset_name = f"{digest}.png"
                (assets_dir / asset_name).write_bytes(payload)
                image_class = "element generated-asset"
                if clipped:
                    image_class += " element-clipped"
                body.append(
                    f'<img{common} class="{image_class}" '
                    f'src="assets/{asset_name}" alt="" />'
                )
                image_count += 1
                continue

            tag = "button" if element_type == "button" else "div"
            role_attr = ""
            if element_type == "input":
                role_attr = ' role="textbox" contenteditable="true"'
            elif element_type in {"text", "button"}:
                role_attr = ' contenteditable="true"'
            text = str(element.get("text") or "")
            if text:
                text_count += 1
            body.append(
                f'<{tag}{common}{role_attr}>{html.escape(text)}</{tag}>'
            )

        document = "\n".join(
            [
                "<!doctype html>",
                '<html lang="en">',
                "<head>",
                '<meta charset="utf-8" />',
                '<meta name="viewport" content="width=device-width, initial-scale=1" />',
                f"<title>{html.escape(str(design.get('name') or 'Prototype'))}</title>",
                '<link rel="stylesheet" href="styles.css" />',
                "</head>",
                "<body>",
                (
                    f'<main id="design-screen" class="screen" '
                    f'style="width:{width}px;height:{height}px;'
                    f'background:{_css_value(canvas.get("background") or "#ffffff")}">'
                ),
                *body,
                "</main>",
                "</body>",
                "</html>",
                "",
            ]
        )
        (self.output_dir / "styles.css").write_text(
            "\n".join(css_rules) + "\n",
            encoding="utf-8",
        )
        (self.output_dir / "prototype.html").write_text(
            document,
            encoding="utf-8",
        )
        self.last_render_report = {
            "status": "pass",
            "canvas": {"width": width, "height": height},
            "native_text": text_count,
            "image_assets": image_count,
            "underlay_audit": audit,
            "reference_mode": reference_mode,
        }
