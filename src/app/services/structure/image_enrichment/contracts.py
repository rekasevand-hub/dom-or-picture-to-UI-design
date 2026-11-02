"""Validated truth and geometry contracts for image-enrichment evaluation."""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

IMAGE_SIZE_FIELDS = ("width", "height")
ASSET_KINDS = {
    "avatar",
    "chart",
    "decoration",
    "icon",
    "illustration",
    "image",
    "logo",
    "map",
    "photo",
    "product",
    "screenshot",
}
CONTROL_TYPES = {
    "button",
    "checkbox",
    "icon-button",
    "input",
    "link",
    "navigation",
    "pagination",
    "radio",
    "select",
    "textarea",
    "toggle",
}
CONTROL_STATES = {
    "checked",
    "closed",
    "default",
    "disabled",
    "enabled",
    "error",
    "focus",
    "hover",
    "loading",
    "open",
    "selected",
    "success",
    "unchecked",
}
CONTAINER_ROLES = {
    "article",
    "aside",
    "banner",
    "card",
    "content",
    "dialog",
    "footer",
    "form",
    "header",
    "main",
    "navigation",
    "overlay",
    "page",
    "panel",
    "popover",
    "sidebar",
    "table",
    "toolbar",
}
OVERLAY_KINDS = {
    "code-overlay",
    "container-overlay",
    "control-overlay",
    "text-overlay",
    "visual-overlay",
}
BLOCKING_METRICS = [
    "critical_text_recall",
    "critical_asset_accuracy",
    "visual_mae",
]
DEFAULT_PRODUCT_CONTRACT = {
    "mode": "fixed-canvas-1:1",
    "component_reuse": False,
    "responsive_reflow": False,
    "external_provenance_required": False,
    "visible_full_screenshot_underlay": "blocked",
}
HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _sequence(value: Any, path: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{path} must be a list")
    return value


def _required(mapping: Mapping[str, Any], keys: Sequence[str], path: str) -> None:
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise ValueError(f"{path} missing required fields: {', '.join(missing)}")


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{path} must be finite")
    return number


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{path} must be a boolean")
    return value


def _bbox(value: Any, image_size: tuple[int, int], path: str) -> list[int]:
    values = _sequence(value, path)
    if len(values) != 4 or any(
        isinstance(item, bool) or not isinstance(item, int) for item in values
    ):
        raise ValueError(f"{path} bbox must contain four integers")
    x, y, width, height = (int(item) for item in values)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError(f"{path} bbox must use non-negative origin and positive size")
    page_width, page_height = image_size
    if x + width > page_width or y + height > page_height:
        raise ValueError(f"{path} bbox exceeds image bounds")
    return [x, y, width, height]


def _string_list(value: Any, path: str, *, allow_empty: bool) -> list[str]:
    items = _sequence(value, path)
    if not items and not allow_empty:
        raise ValueError(f"{path} must not be empty")
    return [_text(item, f"{path}[{index}]") for index, item in enumerate(items)]


def _validation_bbox(value: Any) -> tuple[int, int, int, int]:
    values = _sequence(value, "bbox")
    if len(values) != 4 or any(
        isinstance(item, bool) or not isinstance(item, int) for item in values
    ):
        raise ValueError("bbox must contain four integers")
    x, y, width, height = (int(item) for item in values)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("bbox must use non-negative origin and positive size")
    return x, y, width, height


def asset_match_iou(
    expected_bbox: list[int], actual_bbox: list[int]
) -> float:
    """Return intersection-over-union for ``[x, y, width, height]`` boxes."""

    expected = _validation_bbox(expected_bbox)
    actual = _validation_bbox(actual_bbox)
    expected_x1, expected_y1 = expected[0] + expected[2], expected[1] + expected[3]
    actual_x1, actual_y1 = actual[0] + actual[2], actual[1] + actual[3]
    intersection_width = max(
        0, min(expected_x1, actual_x1) - max(expected[0], actual[0])
    )
    intersection_height = max(
        0, min(expected_y1, actual_y1) - max(expected[1], actual[1])
    )
    intersection = intersection_width * intersection_height
    union = expected[2] * expected[3] + actual[2] * actual[3] - intersection
    return intersection / union if union else 0.0


def _normalize_controls(
    value: Any, image_size: tuple[int, int]
) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, raw in enumerate(_sequence(value, "controls")):
        path = f"controls[{index}]"
        item = _mapping(raw, path)
        _required(item, ("name", "type", "bbox", "value", "critical"), path)
        if "state" not in item:
            raise ValueError(f"{path}.control.state is required")
        name = _text(item["name"], f"{path}.name")
        if name in seen_names:
            raise ValueError(f"{path}.name must be unique")
        seen_names.add(name)
        control_type = _text(item["type"], f"{path}.type")
        if control_type not in CONTROL_TYPES:
            raise ValueError(f"{path}.control.type is unsupported: {control_type}")
        state = _text(item["state"], f"{path}.state")
        if state not in CONTROL_STATES:
            raise ValueError(f"{path}.state is unsupported: {state}")
        raw_value = item["value"]
        if raw_value is None:
            raise ValueError(f"{path}.value must not be null")
        normalized_value = (
            raw_value
            if isinstance(raw_value, str)
            else str(raw_value).lower()
            if isinstance(raw_value, bool)
            else str(raw_value)
        )
        controls.append(
            {
                **copy.deepcopy(dict(item)),
                "name": name,
                "type": control_type,
                "bbox": _bbox(item["bbox"], image_size, f"{path}.bbox"),
                "value": normalized_value,
                "state": state,
                "critical": _boolean(item["critical"], f"{path}.critical"),
            }
        )
    return controls


def _normalize_containers(
    value: Any, image_size: tuple[int, int]
) -> list[dict[str, Any]]:
    containers: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, raw in enumerate(_sequence(value, "containers")):
        path = f"containers[{index}]"
        item = _mapping(raw, path)
        _required(item, ("name", "role", "bbox", "critical"), path)
        name = _text(item["name"], f"{path}.name")
        if name in seen_names:
            raise ValueError(f"{path}.name must be unique")
        seen_names.add(name)
        role = _text(item["role"], f"{path}.role")
        if role not in CONTAINER_ROLES:
            raise ValueError(f"{path}.container.role is unsupported: {role}")
        containers.append(
            {
                **copy.deepcopy(dict(item)),
                "name": name,
                "role": role,
                "bbox": _bbox(item["bbox"], image_size, f"{path}.bbox"),
                "critical": _boolean(item["critical"], f"{path}.critical"),
            }
        )
    return containers


def _normalize_tables(
    value: Any, image_size: tuple[int, int]
) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, raw in enumerate(_sequence(value, "tables")):
        path = f"tables[{index}]"
        item = _mapping(raw, path)
        _required(
            item,
            ("name", "bbox", "header_texts", "rows", "critical"),
            path,
        )
        name = _text(item["name"], f"{path}.name")
        if name in seen_names:
            raise ValueError(f"{path}.name must be unique")
        seen_names.add(name)
        headers = _string_list(
            item["header_texts"], f"{path}.header_texts", allow_empty=False
        )
        if len(set(headers)) != len(headers):
            raise ValueError(f"{path}.header_texts must be unique")
        rows: list[list[str]] = []
        for row_index, raw_row in enumerate(_sequence(item["rows"], f"{path}.rows")):
            row = _string_list(
                raw_row, f"{path}.table.rows[{row_index}]", allow_empty=False
            )
            if len(row) != len(headers):
                raise ValueError(
                    f"{path}.table.rows[{row_index}] must match header count"
                )
            rows.append(row)
        if not rows:
            raise ValueError(f"{path}.table.rows must not be empty")
        tables.append(
            {
                **copy.deepcopy(dict(item)),
                "name": name,
                "bbox": _bbox(item["bbox"], image_size, f"{path}.bbox"),
                "header_texts": headers,
                "rows": rows,
                "critical": _boolean(item["critical"], f"{path}.critical"),
            }
        )
    return tables


def _normalize_assets(
    value: Any, image_size: tuple[int, int]
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, raw in enumerate(_sequence(value, "assets")):
        path = f"assets[{index}]"
        item = _mapping(raw, path)
        _required(
            item,
            ("name", "kind", "bbox", "critical", "minimum_iou"),
            path,
        )
        name = _text(item["name"], f"{path}.name")
        if name in seen_names:
            raise ValueError(f"{path}.name must be unique")
        seen_names.add(name)
        kind = _text(item["kind"], f"{path}.kind")
        if kind not in ASSET_KINDS:
            raise ValueError(f"{path}.asset kind is unsupported: {kind}")
        minimum_iou = _number(item["minimum_iou"], f"{path}.minimum_iou")
        if not 0 <= minimum_iou <= 1:
            raise ValueError(f"{path}.minimum_iou must be between zero and one")
        occurrence_count = _positive_int(
            item.get("occurrence_count", 1), f"{path}.occurrence_count"
        )
        assets.append(
            {
                **copy.deepcopy(dict(item)),
                "name": name,
                "kind": kind,
                "bbox": _bbox(item["bbox"], image_size, f"{path}.bbox"),
                "critical": _boolean(item["critical"], f"{path}.critical"),
                "minimum_iou": minimum_iou,
                "occurrence_count": occurrence_count,
            }
        )
    return assets


def _normalize_backgrounds(
    value: Any, image_size: tuple[int, int]
) -> list[dict[str, Any]]:
    backgrounds: list[dict[str, Any]] = []
    seen_background_ids: set[str] = set()
    for index, raw in enumerate(_sequence(value, "backgrounds")):
        path = f"backgrounds[{index}]"
        item = _mapping(raw, path)
        _required(
            item,
            (
                "id",
                "bbox",
                "critical",
                "overlays",
                "allowed_substitutions",
            ),
            path,
        )
        background_id = _text(item["id"], f"{path}.id")
        if background_id in seen_background_ids:
            raise ValueError(f"{path}.id must be unique")
        seen_background_ids.add(background_id)
        background_bbox = _bbox(item["bbox"], image_size, f"{path}.bbox")
        overlays: list[dict[str, Any]] = []
        seen_overlay_ids: set[str] = set()
        for overlay_index, raw_overlay in enumerate(
            _sequence(item["overlays"], f"{path}.overlays")
        ):
            overlay_path = f"{path}.overlays[{overlay_index}]"
            overlay = _mapping(raw_overlay, overlay_path)
            _required(overlay, ("id", "name", "kind", "bbox"), overlay_path)
            overlay_id = _text(overlay["id"], f"{overlay_path}.id")
            if overlay_id in seen_overlay_ids:
                raise ValueError(f"{overlay_path}.id must be unique")
            seen_overlay_ids.add(overlay_id)
            overlay_kind = _text(overlay["kind"], f"{overlay_path}.kind")
            if overlay_kind not in OVERLAY_KINDS:
                raise ValueError(
                    f"{overlay_path}.overlay kind is unsupported: {overlay_kind}"
                )
            overlay_bbox = _bbox(
                overlay["bbox"], image_size, f"{overlay_path}.bbox"
            )
            background_right = background_bbox[0] + background_bbox[2]
            background_bottom = background_bbox[1] + background_bbox[3]
            overlay_right = overlay_bbox[0] + overlay_bbox[2]
            overlay_bottom = overlay_bbox[1] + overlay_bbox[3]
            if (
                overlay_bbox[0] < background_bbox[0]
                or overlay_bbox[1] < background_bbox[1]
                or overlay_right > background_right
                or overlay_bottom > background_bottom
            ):
                raise ValueError(
                    f"{overlay_path} overlay must be contained by its background"
                )
            overlays.append(
                {
                    **copy.deepcopy(dict(overlay)),
                    "id": overlay_id,
                    "name": _text(overlay["name"], f"{overlay_path}.name"),
                    "kind": overlay_kind,
                    "bbox": overlay_bbox,
                }
            )
        backgrounds.append(
            {
                **copy.deepcopy(dict(item)),
                "id": background_id,
                "bbox": background_bbox,
                "critical": _boolean(item["critical"], f"{path}.critical"),
                "overlays": overlays,
                "allowed_substitutions": _string_list(
                    item["allowed_substitutions"],
                    f"{path}.allowed_substitutions",
                    allow_empty=True,
                ),
            }
        )
    return backgrounds


def _normalize_visual_policy(value: Any) -> dict[str, Any]:
    policy = dict(_mapping(value, "visual_policy"))
    if "mae_max" not in policy:
        raise ValueError("visual_policy.mae_max is required")
    policy["mae_max"] = _number(policy["mae_max"], "visual_policy.mae_max")
    if policy["mae_max"] <= 0:
        raise ValueError("visual_policy.mae_max must be greater than zero")
    policy.setdefault("bad_pixel_threshold", 30)
    policy.setdefault("bad_pixel_ratio_max", 0.15)
    policy.setdefault("underlay_visible_ratio_max", 0.0)
    policy.setdefault("content_coverage_min", 0.02)
    for field in (
        "bad_pixel_ratio_max",
        "underlay_visible_ratio_max",
        "content_coverage_min",
    ):
        ratio = _number(policy[field], f"visual_policy.{field}")
        if not 0 <= ratio <= 1:
            raise ValueError(f"visual_policy.{field} must be between zero and one")
        policy[field] = ratio
    policy["bad_pixel_threshold"] = _positive_int(
        policy["bad_pixel_threshold"], "visual_policy.bad_pixel_threshold"
    )
    return policy


def _normalize_product_contract(value: Any) -> dict[str, Any]:
    if value is None:
        return copy.deepcopy(DEFAULT_PRODUCT_CONTRACT)
    contract = dict(_mapping(value, "product_contract"))
    _required(contract, tuple(DEFAULT_PRODUCT_CONTRACT), "product_contract")
    for field in (
        "component_reuse",
        "responsive_reflow",
        "external_provenance_required",
    ):
        contract[field] = _boolean(contract[field], f"product_contract.{field}")
    contract["mode"] = _text(contract["mode"], "product_contract.mode")
    contract["visible_full_screenshot_underlay"] = _text(
        contract["visible_full_screenshot_underlay"],
        "product_contract.visible_full_screenshot_underlay",
    )
    expected = DEFAULT_PRODUCT_CONTRACT
    if contract["mode"] != expected["mode"]:
        raise ValueError("product_contract.mode must be fixed-canvas-1:1")
    for field in (
        "component_reuse",
        "responsive_reflow",
        "external_provenance_required",
    ):
        if contract[field] is not expected[field]:
            raise ValueError(f"product_contract.{field} must be false")
    if contract["visible_full_screenshot_underlay"] != expected[
        "visible_full_screenshot_underlay"
    ]:
        raise ValueError(
            "product_contract.visible_full_screenshot_underlay must be blocked"
        )
    return contract


def validate_image_truth(value: object) -> dict[str, Any]:
    """Validate and normalize one reviewed image-truth document."""

    truth = copy.deepcopy(dict(_mapping(value, "truth")))
    _required(
        truth,
        (
            "sample_id",
            "image_sha256",
            "image_size",
            "critical_texts",
            "controls",
            "containers",
            "tables",
            "assets",
            "backgrounds",
            "visual_policy",
        ),
        "truth",
    )
    truth["sample_id"] = _text(truth["sample_id"], "sample_id")
    image_sha256 = _text(truth["image_sha256"], "image_sha256")
    if not HASH_PATTERN.fullmatch(image_sha256):
        raise ValueError("image_sha256 must be a 64-character hexadecimal digest")
    truth["image_sha256"] = image_sha256.lower()

    size = _sequence(truth["image_size"], "image_size")
    if len(size) != 2:
        raise ValueError("image_size must contain width and height")
    width = _positive_int(size[0], "image_size[0]")
    height = _positive_int(size[1], "image_size[1]")
    image_size = (width, height)
    truth["image_size"] = [width, height]

    truth["critical_texts"] = _string_list(
        truth["critical_texts"], "critical_texts", allow_empty=True
    )
    if len(set(truth["critical_texts"])) != len(truth["critical_texts"]):
        raise ValueError("critical_texts must be unique")
    truth["controls"] = _normalize_controls(truth["controls"], image_size)
    truth["containers"] = _normalize_containers(truth["containers"], image_size)
    truth["tables"] = _normalize_tables(truth["tables"], image_size)
    truth["assets"] = _normalize_assets(truth["assets"], image_size)
    truth["backgrounds"] = _normalize_backgrounds(
        truth["backgrounds"], image_size
    )
    truth["visual_policy"] = _normalize_visual_policy(truth["visual_policy"])
    truth["product_contract"] = _normalize_product_contract(
        truth.get("product_contract")
    )

    has_blocking_content = any(
        (
            truth["critical_texts"],
            any(item["critical"] for item in truth["controls"]),
            any(item["critical"] for item in truth["containers"]),
            any(item["critical"] for item in truth["tables"]),
            any(item["critical"] for item in truth["assets"]),
        )
    )
    if not has_blocking_content:
        raise ValueError("truth must contain blocking content")

    truth["critical_assets"] = [
        item["name"] for item in truth["assets"] if item["critical"]
    ]
    truth["blocking_metrics"] = list(BLOCKING_METRICS)
    return truth
