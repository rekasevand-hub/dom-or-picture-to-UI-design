"""P1 sample scope for evidence-adapter acceptance."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SampleScenario:
    scenario_id: str
    category: str
    purpose: str
    required_signals: tuple[str, ...]
    minimum_runs: int = 2
    real_source_required: bool = True


@dataclass(frozen=True, slots=True)
class SampleScope:
    scope_version: str
    browser_scope: tuple[str, ...]
    required_page_states: tuple[str, ...]
    scenarios: tuple[SampleScenario, ...]


def validate_sample_scope(scope: SampleScope) -> tuple[str, ...]:
    errors: list[str] = []
    if not scope.browser_scope:
        errors.append("browser scope cannot be empty")
    if "content" not in scope.required_page_states:
        errors.append("content page state is required")
    seen: set[str] = set()
    for scenario in scope.scenarios:
        if scenario.scenario_id in seen:
            errors.append(f"duplicate scenario id: {scenario.scenario_id}")
        seen.add(scenario.scenario_id)
        if scenario.minimum_runs < 1:
            errors.append(f"scenario {scenario.scenario_id} must have minimum_runs >= 1")
        if not scenario.real_source_required:
            errors.append(f"scenario {scenario.scenario_id} must require a real source")
        if not scenario.required_signals:
            errors.append(f"scenario {scenario.scenario_id} must declare required signals")
    if not scope.scenarios:
        errors.append("sample scope must contain at least one scenario")
    return tuple(errors)


DEFAULT_SAMPLE_SCOPE = SampleScope(
    scope_version="p1-sample-scope/1.0",
    browser_scope=("chromium",),
    required_page_states=("content", "soft_block", "hard_login"),
    scenarios=(
        SampleScenario(
            scenario_id="P1-S01",
            category="iframe",
            purpose="Accessible and sandboxed iframe boundaries.",
            required_signals=("accessible-iframe", "sandboxed-iframe"),
        ),
        SampleScenario(
            scenario_id="P1-S02",
            category="shadow-dom",
            purpose="Open and closed shadow-root visibility boundaries.",
            required_signals=("open-shadow", "closed-shadow"),
        ),
        SampleScenario(
            scenario_id="P1-S03",
            category="canvas",
            purpose="Canvas-rendered text and screenshot-only appearance.",
            required_signals=("canvas-text", "overlay-text"),
        ),
        SampleScenario(
            scenario_id="P1-S04",
            category="dynamic-state",
            purpose="Hydration and lazy-content state transitions.",
            required_signals=("m0-shell", "m1-content"),
        ),
        SampleScenario(
            scenario_id="P1-S05",
            category="ocr",
            purpose="Screenshot-only text candidates and low-contrast text.",
            required_signals=("screenshot-only-text", "low-contrast-text"),
        ),
        SampleScenario(
            scenario_id="P1-S06",
            category="assets",
            purpose="Image, background image, SVG and icon source evidence.",
            required_signals=("image", "background-image", "svg-or-icon"),
        ),
        SampleScenario(
            scenario_id="P1-S07",
            category="capture-fallback",
            purpose="Soft-block and hard-login evidence preservation.",
            required_signals=("soft-block", "hard-login"),
        ),
    ),
)
