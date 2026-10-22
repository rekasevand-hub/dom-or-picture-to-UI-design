"""Machine-readable P1 sample registry and validation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.app.services.evidence.sample_scope import DEFAULT_SAMPLE_SCOPE


@dataclass(frozen=True, slots=True)
class SampleSpec:
    sample_id: str
    scenario_id: str
    source_kind: str
    locator: str
    expected_page_state: str
    notes: str = ""
    expected_markers: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SampleRegistry:
    schema_version: str
    scope_version: str
    browser: str
    samples: tuple[SampleSpec, ...]


def load_sample_registry(path: str | Path) -> SampleRegistry:
    registry_path = Path(path)
    try:
        document = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read sample registry: {registry_path}") from exc
    if not isinstance(document, dict):
        raise ValueError("sample registry must be a JSON object")
    samples = document.get("samples")
    if not isinstance(samples, list):
        raise ValueError("sample registry samples must be a JSON array")
    parsed: list[SampleSpec] = []
    for index, item in enumerate(samples):
        if not isinstance(item, dict):
            raise ValueError(f"sample registry samples[{index}] must be an object")
        parsed.append(
            SampleSpec(
                sample_id=str(item.get("sample_id") or ""),
                scenario_id=str(item.get("scenario_id") or ""),
                source_kind=str(item.get("source_kind") or ""),
                locator=str(item.get("locator") or ""),
                expected_page_state=str(item.get("expected_page_state") or ""),
                notes=str(item.get("notes") or ""),
                expected_markers=_markers(item.get("expected_markers")),
            )
        )
    return SampleRegistry(
        schema_version=str(document.get("schema_version") or ""),
        scope_version=str(document.get("scope_version") or ""),
        browser=str(document.get("browser") or ""),
        samples=tuple(parsed),
    )


def validate_sample_registry(registry: SampleRegistry) -> tuple[str, ...]:
    errors: list[str] = []
    if registry.schema_version != "p1-sample-registry/1.0":
        errors.append("unexpected sample registry schema")
    if registry.scope_version != DEFAULT_SAMPLE_SCOPE.scope_version:
        errors.append("sample registry scope version does not match default scope")
    if registry.browser not in DEFAULT_SAMPLE_SCOPE.browser_scope:
        errors.append(f"unsupported browser scope: {registry.browser}")
    expected_states = set(DEFAULT_SAMPLE_SCOPE.required_page_states)
    allowed_markers = set(MARKER_KEYS)
    scenario_ids = {item.scenario_id for item in DEFAULT_SAMPLE_SCOPE.scenarios}
    seen: set[str] = set()
    for sample in registry.samples:
        if not sample.sample_id:
            errors.append("sample id cannot be empty")
        if sample.sample_id in seen:
            errors.append(f"duplicate sample id: {sample.sample_id}")
        seen.add(sample.sample_id)
        if sample.scenario_id not in scenario_ids:
            errors.append(f"unknown scenario id: {sample.scenario_id}")
        if sample.source_kind not in {"controlled", "real"}:
            errors.append(f"unknown source kind: {sample.source_kind}")
        if not sample.locator:
            errors.append(f"sample {sample.sample_id} has no locator")
        if sample.expected_page_state not in expected_states:
            errors.append(
                f"sample {sample.sample_id} has unknown page state: "
                f"{sample.expected_page_state}"
            )
        for marker, minimum in sample.expected_markers.items():
            if marker not in allowed_markers:
                errors.append(
                    f"sample {sample.sample_id} has unknown marker: {marker}"
                )
            if minimum < 0:
                errors.append(
                    f"sample {sample.sample_id} marker {marker} is negative"
                )
    for scenario in DEFAULT_SAMPLE_SCOPE.scenarios:
        samples = [
            item for item in registry.samples
            if item.scenario_id == scenario.scenario_id
        ]
        if len(samples) < scenario.minimum_runs:
            errors.append(
                f"scenario {scenario.scenario_id} has {len(samples)} runs; "
                f"minimum is {scenario.minimum_runs}"
            )
        if scenario.real_source_required and not any(
            item.source_kind == "real" for item in samples
        ):
            errors.append(f"scenario {scenario.scenario_id} lacks a real source")
    return tuple(errors)


MARKER_KEYS = (
    "dom_nodes",
    "iframe",
    "shadow",
    "canvas",
    "img",
    "svg",
    "background_image",
    "icon_box",
)


def marker_counts(dom: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "dom_nodes": len(dom),
        "iframe": sum(node.get("tag") == "iframe" for node in dom),
        "shadow": sum(bool(node.get("shadow")) for node in dom),
        "canvas": sum(node.get("tag") == "canvas" for node in dom),
        "img": sum(node.get("tag") == "img" for node in dom),
        "svg": sum(node.get("tag") == "svg" for node in dom),
        "background_image": sum(bool(node.get("bgImage")) for node in dom),
        "icon_box": sum(bool(node.get("iconBox")) for node in dom),
    }


def evaluate_sample_markers(
    sample: SampleSpec,
    dom: list[dict[str, Any]],
    page_state: dict[str, Any],
) -> dict[str, Any]:
    counts = marker_counts(dom)
    markers = {
        marker: {
            "minimum": minimum,
            "actual": counts.get(marker, 0),
            "pass": counts.get(marker, 0) >= minimum,
        }
        for marker, minimum in sample.expected_markers.items()
    }
    page_state_match = str(page_state.get("kind") or "unknown") == sample.expected_page_state
    passed = page_state_match and all(item["pass"] for item in markers.values())
    return {
        "status": "pass" if passed else "fail",
        "page_state": page_state.get("kind"),
        "page_state_match": page_state_match,
        "markers": markers,
        "counts": counts,
    }


def _markers(value: Any) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("sample expected_markers must be an object")
    markers: dict[str, int] = {}
    for key, raw in value.items():
        try:
            markers[str(key)] = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"sample marker {key} must be an integer") from exc
    return markers


def locate_sample(sample: SampleSpec, project_root: str | Path) -> str:
    locator = sample.locator.strip()
    if locator.startswith(("http://", "https://", "file://")):
        return locator
    path = Path(project_root) / locator
    return path.resolve().as_uri()
