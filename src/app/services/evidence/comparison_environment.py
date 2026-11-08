"""Fail-closed capture environment checks for cross-route comparisons."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "comparison-environment/1.0"


class ComparisonEnvironmentError(ValueError):
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        codes = sorted({str(item.get("code") or "") for item in report["issues"]})
        super().__init__("comparison environment invalid: " + ", ".join(codes))


def _size(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        width, height = int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _viewport(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, Mapping):
        return None
    return _size([value.get("width"), value.get("height")])


def _issue(
    code: str,
    *,
    run: str | None = None,
    expected: Any = None,
    actual: Any = None,
    message: str = "",
) -> dict[str, Any]:
    return {
        "code": code,
        "run": run,
        "expected": expected,
        "actual": actual,
        "message": message,
    }


def freeze_comparison_environment(
    *,
    viewport: tuple[int, int] | list[int],
    device_scale_factor: int,
    profile_id: str = "default",
    reference_size: tuple[int, int] | list[int] | None = None,
) -> dict[str, Any]:
    """Create one immutable breakpoint profile for every compared run."""
    issues: list[dict[str, Any]] = []
    normalized_viewport = _size(viewport)
    if normalized_viewport is None:
        issues.append(
            _issue(
                "INVALID_VIEWPORT",
                actual=list(viewport)
                if isinstance(viewport, (list, tuple))
                else viewport,
                message="viewport must contain positive width and height",
            )
        )
    try:
        dpr = int(device_scale_factor)
    except (TypeError, ValueError):
        dpr = 0
    if dpr <= 0:
        issues.append(
            _issue(
                "INVALID_DEVICE_SCALE_FACTOR",
                actual=device_scale_factor,
                message="device scale factor must be positive",
            )
        )

    reference: dict[str, Any] | None = None
    normalized_reference = _size(reference_size)
    if reference_size is not None and normalized_reference is None:
        issues.append(
            _issue(
                "INVALID_REFERENCE_SIZE",
                actual=reference_size,
                message="reference image size must contain positive width and height",
            )
        )
    if normalized_reference is not None and dpr > 0:
        remainder = tuple(value % dpr for value in normalized_reference)
        css_size = tuple(value // dpr for value in normalized_reference)
        reference = {
            "pixel_size": list(normalized_reference),
            "css_size": list(css_size),
        }
        if any(remainder):
            issues.append(
                _issue(
                    "REFERENCE_DPR_NOT_INTEGRAL",
                    expected=0,
                    actual=list(remainder),
                    message="reference image dimensions must be integral multiples of DPR",
                )
            )
        if normalized_viewport is not None:
            if css_size[0] != normalized_viewport[0]:
                issues.append(
                    _issue(
                        "REFERENCE_BREAKPOINT_MISMATCH",
                        expected=normalized_viewport[0],
                        actual=css_size[0],
                        message="reference image CSS width does not match the frozen viewport",
                    )
                )
            if css_size[1] < normalized_viewport[1]:
                issues.append(
                    _issue(
                        "REFERENCE_HEIGHT_SHORTER_THAN_VIEWPORT",
                        expected=normalized_viewport[1],
                        actual=css_size[1],
                        message="reference image is shorter than the frozen viewport",
                    )
                )

    report = {
        "schema_version": SCHEMA_VERSION,
        "profile_id": str(profile_id or "default"),
        "status": "fail" if issues else "pass",
        "viewport": (
            {"width": normalized_viewport[0], "height": normalized_viewport[1]}
            if normalized_viewport
            else None
        ),
        "device_scale_factor": dpr,
        "reference": reference,
        "issues": issues,
    }
    if issues:
        raise ComparisonEnvironmentError(report)
    return report


def _run_environment(run: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = run.get("manifest")
    capture = run.get("capture")
    if not isinstance(capture, Mapping) and isinstance(manifest, Mapping):
        capture = manifest.get("capture")
    if not isinstance(capture, Mapping):
        capture = {}

    viewport = _viewport(capture.get("viewport"))
    try:
        dpr = int(capture.get("device_scale_factor"))
    except (TypeError, ValueError):
        dpr = 0
    screenshot_size = _size(run.get("screenshot_size") or capture.get("canvas_size"))
    design_canvas = _size(run.get("design_canvas"))
    return (
        {
            "viewport": (
                {"width": viewport[0], "height": viewport[1]} if viewport else None
            ),
            "device_scale_factor": dpr or None,
            "screenshot_size": list(screenshot_size) if screenshot_size else None,
            "design_canvas": list(design_canvas) if design_canvas else None,
        },
        {
            "viewport": viewport,
            "dpr": dpr,
            "screenshot_size": screenshot_size,
            "design_canvas": design_canvas,
        },
    )


def validate_comparison_environment(
    runs: Mapping[str, Mapping[str, Any]],
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate every run against one frozen breakpoint and its own CSS canvas."""
    expected_viewport = _viewport(expected.get("viewport"))
    try:
        expected_dpr = int(expected.get("device_scale_factor"))
    except (TypeError, ValueError):
        expected_dpr = 0
    issues: list[dict[str, Any]] = []
    observed_runs: dict[str, Any] = {}

    for name, run in runs.items():
        normalized, parsed = _run_environment(run)
        observed_runs[name] = normalized
        viewport = parsed["viewport"]
        dpr = parsed["dpr"]
        screenshot_size = parsed["screenshot_size"]
        design_canvas = parsed["design_canvas"]

        if viewport is None:
            issues.append(
                _issue(
                    "MISSING_VIEWPORT",
                    run=name,
                    message="capture.viewport is required for comparison",
                )
            )
        elif viewport != expected_viewport:
            issues.append(
                _issue(
                    "VIEWPORT_MISMATCH",
                    run=name,
                    expected=(
                        list(expected_viewport)
                        if expected_viewport is not None
                        else None
                    ),
                    actual=list(viewport),
                    message="run was captured at a different breakpoint",
                )
            )
        if dpr <= 0:
            issues.append(
                _issue(
                    "MISSING_DEVICE_SCALE_FACTOR",
                    run=name,
                    message="capture.device_scale_factor is required for comparison",
                )
            )
        elif dpr != expected_dpr:
            issues.append(
                _issue(
                    "DEVICE_SCALE_FACTOR_MISMATCH",
                    run=name,
                    expected=expected_dpr,
                    actual=dpr,
                    message="run was captured with a different DPR",
                )
            )

        if screenshot_size is not None and dpr > 0:
            by_dpr = tuple(value // dpr for value in screenshot_size)
            if any(value % dpr for value in screenshot_size):
                issues.append(
                    _issue(
                        "SCREENSHOT_DPR_NOT_INTEGRAL",
                        run=name,
                        actual=list(screenshot_size),
                        message="screenshot dimensions are not integral multiples of DPR",
                    )
                )
            if design_canvas is not None and design_canvas != by_dpr:
                issues.append(
                    _issue(
                        "DESIGN_CANVAS_MISMATCH",
                        run=name,
                        expected=list(by_dpr),
                        actual=list(design_canvas),
                        message="design canvas does not match screenshot pixels divided by DPR",
                    )
                )
        if viewport is not None and design_canvas is not None:
            if viewport[0] != design_canvas[0]:
                issues.append(
                    _issue(
                        "VIEWPORT_WIDTH_MISMATCH",
                        run=name,
                        expected=viewport[0],
                        actual=design_canvas[0],
                        message="design canvas width differs from captured viewport width",
                    )
                )
            if viewport[1] > design_canvas[1]:
                issues.append(
                    _issue(
                        "VIEWPORT_HEIGHT_EXCEEDS_CANVAS",
                        run=name,
                        expected=viewport[1],
                        actual=design_canvas[1],
                        message="captured viewport height exceeds the full-page design canvas",
                    )
                )

    report = {
        "schema_version": SCHEMA_VERSION,
        "profile_id": expected.get("profile_id"),
        "status": "fail" if issues else "pass",
        "expected": {
            "viewport": expected.get("viewport"),
            "device_scale_factor": expected_dpr,
            "reference": expected.get("reference"),
        },
        "runs": observed_runs,
        "issues": issues,
    }
    if issues:
        raise ComparisonEnvironmentError(report)
    return report
