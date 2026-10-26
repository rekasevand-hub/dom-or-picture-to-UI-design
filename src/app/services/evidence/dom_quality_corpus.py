"""Machine-readable real-site DOM corpus contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from src.app.services.structure.capture_state import (
    capture_state_signature,
    normalize_capture_url,
    text_sequence,
)


CORPUS_SCHEMA = "dom-quality-real-site-corpus/1.0"
ENVIRONMENT_SCHEMA = "dom-quality-environment/1.0"
REQUIRED_SAMPLE_IDS = ("DQ-R01", "DQ-R02", "DQ-R03")

THRESHOLD_PATHS = (
    ("content", "required_text_match_rate"),
    ("content", "forbidden_text_match_rate"),
    ("content", "required_page_state"),
    ("structure", "required_object_match_rate"),
    ("structure", "geometry_tolerance_px"),
    ("structure", "node_count_drift_ratio"),
    ("structure", "text_count_drift_ratio"),
    ("text", "linebreak_match_rate"),
    ("text", "box_tolerance_px"),
    ("text", "baseline_tolerance_px"),
    ("text", "glyph_identity_status"),
    ("layout", "l1_pass_required"),
    ("layout", "l2_required_mutation_rate"),
    ("layout", "l3_required_mutation_rate"),
    ("assets", "required_original_identity_rate"),
    ("assets", "replacement_probe_rate"),
    ("assets", "missing_asset_outcome"),
    ("edit", "required_native_text_rate"),
    ("visual", "max_mean"),
    ("visual", "max_ink_mean"),
    ("visual", "max_over30_pct"),
    ("visual", "max_bad_pixel_ratio"),
    ("visual", "require_size_match"),
)


def load_corpus(path: str | Path) -> dict[str, Any]:
    corpus_path = Path(path)
    try:
        document = json.loads(corpus_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read DOM quality corpus: {corpus_path}") from exc
    if not isinstance(document, dict):
        raise ValueError("DOM quality corpus must be a JSON object")
    return document


def thresholds_sha256(document: Mapping[str, Any]) -> str:
    return _json_sha256(document.get("thresholds") or {})


def corpus_sha256(document: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "corpus_sha256"}
    return _json_sha256(payload)


def build_capture_fingerprint(capture_dir: str | Path) -> dict[str, Any]:
    root = Path(capture_dir)
    dom_path = root / "00_dom.json"
    page_state_path = root / "00_page_state.json"
    screenshot_path = root / "00_screenshot.png"
    dom = _read_json(dom_path)
    page_state = _read_json(page_state_path)
    if not isinstance(dom, list):
        raise ValueError(f"captured DOM must be an array: {dom_path}")
    if not isinstance(page_state, dict):
        raise ValueError(f"captured page state must be an object: {page_state_path}")
    signature = capture_state_signature(dom, page_state)
    stability = page_state.get("capture_stability")
    return {
        "dom_sha256": _file_sha256(dom_path),
        "page_state_sha256": _file_sha256(page_state_path),
        "screenshot_sha256": _file_sha256(screenshot_path),
        "structure_sha256": signature["structure_sha256"],
        "text_sha256": signature["text_sha256"],
        "state_signature_sha256": _json_sha256(signature),
        "node_count": signature["node_count"],
        "text_count": signature["text_count"],
        "frame_count": signature["frame_count"],
        "page_state_kind": str(page_state.get("kind") or ""),
        "navigation_status": str(
            (page_state.get("navigation") or {}).get("status") or ""
        ),
        "stable": isinstance(stability, Mapping) and stability.get("stable") is True,
        "browser_engine": str(page_state.get("browser_engine") or ""),
        "capture_profile": str(page_state.get("capture_profile") or ""),
    }


def evaluate_capture(
    sample: Mapping[str, Any],
    capture_dir: str | Path,
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    root = Path(capture_dir)
    dom = _read_json(root / "00_dom.json")
    page_state = _read_json(root / "00_page_state.json")
    if not isinstance(dom, list) or not isinstance(page_state, dict):
        raise ValueError(f"invalid capture evidence: {root}")
    fingerprint = build_capture_fingerprint(root)
    texts = [value for value in text_sequence(dom) if value]
    haystack = "\n".join(texts).casefold()
    checks: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []

    expected_url = normalize_capture_url(
        str(sample.get("expected_final_url") or sample.get("url") or "")
    )
    actual_url = normalize_capture_url(str(page_state.get("final_url") or ""))
    _record_check(
        checks,
        reasons,
        "url",
        actual_url == expected_url,
        "url-mismatch",
        {"expected": expected_url, "actual": actual_url},
    )
    content_thresholds = thresholds.get("content") or {}
    required_state = str(content_thresholds.get("required_page_state") or "content")
    kind = str(page_state.get("kind") or "")
    _record_check(
        checks,
        reasons,
        "page_state",
        kind == required_state,
        "page-state-mismatch",
        {"expected": required_state, "actual": kind},
    )
    navigation_status = str((page_state.get("navigation") or {}).get("status") or "")
    _record_check(
        checks,
        reasons,
        "navigation",
        navigation_status in {"ok", "redirected"},
        "navigation-failure",
        {"actual": navigation_status},
    )
    stability = page_state.get("capture_stability")
    stable = isinstance(stability, Mapping) and stability.get("stable") is True
    _record_check(
        checks,
        reasons,
        "state",
        stable,
        "state-unstable",
        {"stable": stable},
    )

    required_text = [str(value) for value in sample.get("required_text") or []]
    missing_text = [
        value for value in required_text if value.casefold() not in haystack
    ]
    _record_check(
        checks,
        reasons,
        "required_text",
        not missing_text,
        "critical-text-missing",
        {"missing": missing_text, "required": required_text},
    )
    forbidden_text = [str(value) for value in sample.get("forbidden_text") or []]
    matched_forbidden = [
        value for value in forbidden_text if value.casefold() in haystack
    ]
    _record_check(
        checks,
        reasons,
        "forbidden_text",
        not matched_forbidden,
        "forbidden-text",
        {"matched": matched_forbidden},
    )

    actual_markers = marker_counts(dom)
    required_markers = {
        str(key): int(value)
        for key, value in (sample.get("required_markers") or {}).items()
    }
    marker_results = {
        key: {
            "minimum": minimum,
            "actual": actual_markers.get(key, 0),
            "pass": actual_markers.get(key, 0) >= minimum,
        }
        for key, minimum in required_markers.items()
    }
    _record_check(
        checks,
        reasons,
        "required_markers",
        all(item["pass"] for item in marker_results.values()),
        "required-object-missing",
        marker_results,
    )

    baseline = sample.get("fingerprint")
    baseline = baseline if isinstance(baseline, Mapping) else {}
    drift = sample.get("drift")
    drift = drift if isinstance(drift, Mapping) else {}
    structure_thresholds = thresholds.get("structure") or {}
    node_ratio = _drift_ratio(
        int(fingerprint["node_count"]),
        int(baseline.get("node_count") or 0),
    )
    node_limit = float(
        drift.get("node_count_ratio")
        or structure_thresholds.get("node_count_drift_ratio")
        or 0.0
    )
    _record_check(
        checks,
        reasons,
        "node_count_drift",
        node_ratio <= node_limit,
        "node-count-drift",
        {"ratio": node_ratio, "max": node_limit},
    )
    text_ratio = _drift_ratio(
        int(fingerprint["text_count"]),
        int(baseline.get("text_count") or 0),
    )
    text_limit = float(
        drift.get("text_count_ratio")
        or structure_thresholds.get("text_count_drift_ratio")
        or 0.0
    )
    _record_check(
        checks,
        reasons,
        "text_count_drift",
        text_ratio <= text_limit,
        "text-count-drift",
        {"ratio": text_ratio, "max": text_limit},
    )
    return {
        "sample_id": sample.get("sample_id"),
        "status": "pass" if not reasons else "fail",
        "reasons": reasons,
        "checks": checks,
        "fingerprint": fingerprint,
    }


def marker_counts(dom: list[Mapping[str, Any]]) -> dict[str, int]:
    texts = [node for node in dom if str(node.get("text") or "").strip()]
    return {
        "dom_nodes": len(dom),
        "text_nodes": len(texts),
        "img": sum(node.get("tag") == "img" for node in dom),
        "svg": sum(node.get("tag") == "svg" for node in dom),
        "shadow": sum(bool(node.get("shadow")) for node in dom),
        "iframe": sum(node.get("tag") == "iframe" for node in dom),
        "canvas": sum(node.get("tag") == "canvas" for node in dom),
        "background_image": sum(bool(node.get("bgImage")) for node in dom),
    }


def validate_corpus(document: Mapping[str, Any]) -> tuple[str, ...]:
    errors: list[str] = []
    if document.get("schema_version") != CORPUS_SCHEMA:
        errors.append(f"schema_version must be {CORPUS_SCHEMA}")
    status = document.get("status")
    if status not in {"draft", "frozen"}:
        errors.append("status must be draft or frozen")
    if not str(document.get("corpus_id") or "").strip():
        errors.append("corpus_id is required")

    environment = document.get("environment")
    _validate_environment(environment, errors, frozen=status == "frozen")
    _validate_thresholds(document.get("thresholds"), errors)
    _validate_samples(document.get("samples"), errors)
    _validate_excluded_sites(document.get("excluded_sites"), errors)

    if status == "frozen":
        if not str(document.get("frozen_at") or "").strip():
            errors.append("frozen_at is required for frozen corpus")
        if document.get("thresholds_sha256") != thresholds_sha256(document):
            errors.append("thresholds_sha256 does not match frozen thresholds")
        if document.get("corpus_sha256") != corpus_sha256(document):
            errors.append("corpus_sha256 does not match frozen corpus content")
        for sample in document.get("samples") or []:
            if not isinstance(sample, Mapping):
                continue
            if not isinstance(sample.get("fingerprint"), Mapping):
                errors.append(
                    f"sample {sample.get('sample_id')} fingerprint is required for frozen corpus"
                )
    return tuple(errors)


def _validate_environment(
    environment: Any,
    errors: list[str],
    *,
    frozen: bool,
) -> None:
    if not isinstance(environment, Mapping):
        errors.append("environment object is required")
        return
    if environment.get("schema_version") != ENVIRONMENT_SCHEMA:
        errors.append(f"environment.schema_version must be {ENVIRONMENT_SCHEMA}")
    if environment.get("engine") != "chromium":
        errors.append("environment.engine must be chromium")
    viewport = environment.get("viewport")
    if not isinstance(viewport, Mapping) or not all(
        isinstance(viewport.get(key), int) and viewport.get(key) > 0
        for key in ("width", "height")
    ):
        errors.append("environment.viewport must contain positive width and height")
    if environment.get("device_scale_factor") != 1:
        errors.append("environment.device_scale_factor must be 1")
    if environment.get("locale") != "zh-CN":
        errors.append("environment.locale must be zh-CN")
    if environment.get("timezone") != "Asia/Shanghai":
        errors.append("environment.timezone must be Asia/Shanghai")
    if environment.get("headless") is not True:
        errors.append("environment.headless must be true")
    required = (
        "browser_version",
        "executable_path",
        "executable_sha256",
        "font_files",
    )
    for key in required:
        if key not in environment:
            errors.append(f"environment.{key} is required")
    if frozen:
        for key in ("browser_version", "executable_path", "executable_sha256"):
            value = str(environment.get(key) or "").strip()
            if not value or value.startswith("pending"):
                errors.append(f"environment.{key} must be resolved before freeze")
        fonts = environment.get("font_files")
        if not isinstance(fonts, list) or not fonts:
            errors.append("environment.font_files must be frozen")
        elif any(
            not isinstance(item, Mapping)
            or item.get("status") != "present"
            or not str(item.get("sha256") or "").strip()
            for item in fonts
        ):
            errors.append("environment.font_files must contain present hashed files")


def _validate_thresholds(thresholds: Any, errors: list[str]) -> None:
    if not isinstance(thresholds, Mapping):
        errors.append("thresholds object is required")
        return
    for section, key in THRESHOLD_PATHS:
        value = thresholds.get(section)
        label = f"thresholds.{section}.{key}"
        if not isinstance(value, Mapping) or key not in value or value[key] is None:
            errors.append(f"{label} is required")
    if thresholds.get("composite_score_allowed") is not False:
        errors.append("thresholds.composite_score_allowed must be false")


def _validate_samples(samples: Any, errors: list[str]) -> None:
    if not isinstance(samples, list):
        errors.append("samples must be an array")
        return
    if len(samples) != len(REQUIRED_SAMPLE_IDS):
        errors.append("corpus must contain exactly three required samples")
    seen: set[str] = set()
    gate_ids: list[str] = []
    for item in samples:
        if not isinstance(item, Mapping):
            errors.append("each sample must be an object")
            continue
        sample_id = str(item.get("sample_id") or "")
        if not sample_id:
            errors.append("sample_id is required")
        elif sample_id in seen:
            errors.append(f"duplicate sample_id: {sample_id}")
        seen.add(sample_id)
        url = str(item.get("url") or "")
        if urlparse(url).scheme != "https":
            errors.append(f"sample {sample_id or '<unknown>'} url must use https")
        if item.get("gate_role") == "required":
            gate_ids.append(sample_id)
            for key in ("site", "scenario", "expected_final_url", "state"):
                if not item.get(key):
                    errors.append(f"sample {sample_id} {key} is required")
            texts = item.get("required_text")
            if (
                not isinstance(texts, list)
                or not texts
                or not all(str(value).strip() for value in texts)
            ):
                errors.append(f"sample {sample_id} required_text must be non-empty")
            markers = item.get("required_markers")
            if not isinstance(markers, Mapping) or not markers:
                errors.append(f"sample {sample_id} required_markers are required")
            drift = item.get("drift")
            if not isinstance(drift, Mapping):
                errors.append(f"sample {sample_id} drift thresholds are required")
            exclusions = item.get("known_exclusions")
            if not isinstance(exclusions, list) or not exclusions:
                errors.append(f"sample {sample_id} known_exclusions are required")
    if tuple(gate_ids) != REQUIRED_SAMPLE_IDS:
        errors.append("required sample IDs must be DQ-R01, DQ-R02, DQ-R03 in order")


def _validate_excluded_sites(excluded: Any, errors: list[str]) -> None:
    if not isinstance(excluded, list) or not excluded:
        errors.append("excluded_sites must list at least one known exclusion")
        return
    if not any(
        isinstance(item, Mapping)
        and str(item.get("url") or "").startswith(
            "https://www.w3schools.com/html/html_iframe.asp"
        )
        and item.get("status") == "excluded-state-unstable"
        for item in excluded
    ):
        errors.append("W3Schools iframe must remain an explicit unstable exclusion")


def _json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read corpus evidence: {path}") from exc


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"cannot read corpus evidence: {path}") from exc
    return digest.hexdigest()


def _record_check(
    checks: dict[str, dict[str, Any]],
    reasons: list[str],
    name: str,
    passed: bool,
    reason: str,
    evidence: Mapping[str, Any],
) -> None:
    checks[name] = {"pass": bool(passed), "evidence": dict(evidence)}
    if not passed:
        reasons.append(reason)


def _drift_ratio(actual: int, baseline: int) -> float:
    if baseline <= 0:
        return 0.0 if actual == 0 else 1.0
    return abs(actual - baseline) / baseline
