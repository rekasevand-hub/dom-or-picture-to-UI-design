"""Declarative calibration strategy registry for image-to-Figma.

The historical runner executed fifteen calibration stages in a hard-coded
sequence.  This module keeps the same render groups and strategy order, but
makes each stage declarative so a residual profile can skip stages whose
residual class is absent.  ``legacy`` mode reproduces the historical order.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.app.services.structure.fidelity.text_calibration import (
    apply_display_weight_by_scale,
    apply_adjudicated_conflicts,
    apply_nav_row_weight,
    clamp_table_cell_font_outliers,
    drop_implausible_duplicate_owners,
    drop_text_fragment_images,
    apply_text_rotation,
    restructure_tilted_text_block,
    resolve_same_slot_conflicts,
    synthesize_badge_outline,
    synthesize_selection_plate,
    calibrate_control_fonts,
    calibrate_form_fonts_from_render,
    calibrate_form_positions_from_render,
    calibrate_form_text_positions,
    calibrate_form_text_shape_from_render,
    calibrate_form_text_weight_from_render,
    calibrate_ink_convergence_from_render,
    calibrate_low_contrast_placeholder_from_render,
    calibrate_search_control_from_render,
    calibrate_table_fonts_from_render,
    calibrate_table_letter_spacing_from_render,
    calibrate_table_positions_from_render,
    calibrate_toolbar_font_weight_from_render,
    calibrate_toolbar_letter_spacing_from_render,
)

CALIBRATION_MODES = ("legacy", "residual")
SCHEMA_VERSION = "image-calibration-strategies/1.0"


@dataclass(frozen=True)
class CalibrationContext:
    design: dict[str, Any]
    image: str
    run_root: Path
    readback: dict[str, Any]
    ocr_supplement: dict[str, Any]


@dataclass(frozen=True)
class CalibrationStrategy:
    name: str
    residuals: frozenset[str]
    regions: frozenset[str]
    runner: Callable[[CalibrationContext], tuple[dict[str, Any], dict[str, Any]]] = (
        field(
            compare=False,
            repr=False,
        )
    )
    always: bool = False


@dataclass(frozen=True)
class CalibrationGroup:
    name: str
    render_suffix: str
    strategies: tuple[CalibrationStrategy, ...]


@dataclass
class CalibrationPipelineResult:
    design: dict[str, Any]
    run_root: Path
    readback: dict[str, Any]
    reports: dict[str, dict[str, Any]]
    selected_groups: list[str]
    profile: dict[str, Any] | None


class CalibrationRenderError(RuntimeError):
    def __init__(self, group_name: str, summary: Mapping[str, Any]) -> None:
        self.group_name = group_name
        self.summary = dict(summary)
        super().__init__(
            f"calibration render failed for group {group_name}: "
            f"{summary.get('status') or 'unknown'}"
        )


def _export(ctx: CalibrationContext) -> str:
    return str(ctx.run_root / "export.png")


def _display_weight(ctx: CalibrationContext) -> tuple[dict[str, Any], dict[str, Any]]:
    return apply_display_weight_by_scale(ctx.design)


def _nav_weight(ctx: CalibrationContext) -> tuple[dict[str, Any], dict[str, Any]]:
    return apply_nav_row_weight(ctx.design)


def _selection_plate(
    ctx: CalibrationContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return synthesize_selection_plate(ctx.design, ctx.image)


def _drop_fragment_images(
    ctx: CalibrationContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return drop_text_fragment_images(ctx.design)


def _badge_outline(
    ctx: CalibrationContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return synthesize_badge_outline(ctx.design, ctx.image)


def _text_rotation(
    ctx: CalibrationContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return apply_text_rotation(ctx.design, ctx.image)


def _text_block_lines(
    ctx: CalibrationContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return restructure_tilted_text_block(ctx.design, ctx.image)


def _drop_duplicate_owners(
    ctx: CalibrationContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return drop_implausible_duplicate_owners(ctx.design)


def _adjudicated_conflicts(
    ctx: CalibrationContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidates: list[Path] = []
    parts = Path(str(ctx.image)).parts
    if "benchmark_families" in parts:
        index = parts.index("benchmark_families")
        if index + 1 < len(parts):
            family = parts[index + 1]
            root = Path(__file__).resolve().parents[5]
            candidates.append(
                root / "output/_conflict_decisions" / f"{family}.json"
            )
            candidates.append(
                Path.cwd() / "output/_conflict_decisions" / f"{family}.json"
            )
    for base in (ctx.run_root, *list(ctx.run_root.parents)[:3]):
        candidates.append(base / "conflict_adjudication/decisions.json")
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        return ctx.design, {
            "schema_version": "grounding-adjudicated-conflict/1.0",
            "status": "not-needed",
            "adjusted_count": 0,
            "reason": "no decisions file",
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    return apply_adjudicated_conflicts(ctx.design, payload.get("decisions") or [])


def _same_slot_conflict(
    ctx: CalibrationContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return resolve_same_slot_conflicts(ctx.design)


def _table_cell_scale(
    ctx: CalibrationContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return clamp_table_cell_font_outliers(ctx.design)


def _control_fonts(ctx: CalibrationContext) -> tuple[dict[str, Any], dict[str, Any]]:
    return calibrate_control_fonts(ctx.design, ctx.readback)


def _table_fonts(ctx: CalibrationContext) -> tuple[dict[str, Any], dict[str, Any]]:
    return calibrate_table_fonts_from_render(ctx.design, ctx.image, _export(ctx))


def _form_text_positions(
    ctx: CalibrationContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return calibrate_form_text_positions(ctx.design, ctx.readback)


def _table_positions(
    ctx: CalibrationContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return calibrate_table_positions_from_render(ctx.design, ctx.image, _export(ctx))


def _table_letter_spacing(
    ctx: CalibrationContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return calibrate_table_letter_spacing_from_render(
        ctx.design,
        ctx.image,
        _export(ctx),
    )


def _form_fonts(ctx: CalibrationContext) -> tuple[dict[str, Any], dict[str, Any]]:
    return calibrate_form_fonts_from_render(ctx.design, ctx.image, _export(ctx))


def _form_weight(ctx: CalibrationContext) -> tuple[dict[str, Any], dict[str, Any]]:
    return calibrate_form_text_weight_from_render(ctx.design, ctx.image, _export(ctx))


def _form_shape(ctx: CalibrationContext) -> tuple[dict[str, Any], dict[str, Any]]:
    return calibrate_form_text_shape_from_render(ctx.design, ctx.image, _export(ctx))


def _form_positions(ctx: CalibrationContext) -> tuple[dict[str, Any], dict[str, Any]]:
    return calibrate_form_positions_from_render(
        ctx.design,
        ctx.readback,
        ctx.image,
        _export(ctx),
    )


def _placeholder(ctx: CalibrationContext) -> tuple[dict[str, Any], dict[str, Any]]:
    return calibrate_low_contrast_placeholder_from_render(
        ctx.design,
        ctx.image,
        _export(ctx),
        ocr_supplement=ctx.ocr_supplement,
    )


def _toolbar_letter_spacing(
    ctx: CalibrationContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return calibrate_toolbar_letter_spacing_from_render(
        ctx.design,
        ctx.image,
        _export(ctx),
    )


def _toolbar_weight(ctx: CalibrationContext) -> tuple[dict[str, Any], dict[str, Any]]:
    return calibrate_toolbar_font_weight_from_render(
        ctx.design, ctx.image, _export(ctx)
    )


def _search_control(ctx: CalibrationContext) -> tuple[dict[str, Any], dict[str, Any]]:
    return calibrate_search_control_from_render(ctx.design, ctx.image, _export(ctx))


def _ink_convergence(ctx: CalibrationContext) -> tuple[dict[str, Any], dict[str, Any]]:
    return calibrate_ink_convergence_from_render(
        ctx.design, ctx.image, _export(ctx), ctx.readback
    )


def _strategy(
    name: str,
    residuals: Sequence[str],
    regions: Sequence[str],
    runner: Callable[[CalibrationContext], tuple[dict[str, Any], dict[str, Any]]],
    *,
    always: bool = False,
) -> CalibrationStrategy:
    return CalibrationStrategy(
        name=name,
        residuals=frozenset(residuals),
        regions=frozenset(regions),
        runner=runner,
        always=always,
    )


CALIBRATION_GROUPS: tuple[CalibrationGroup, ...] = (
    CalibrationGroup(
        name="font-initial",
        render_suffix="figma_font_calibrated",
        strategies=(
            # A logo crop keeps whatever pixels fell inside the detector box,
            # so it can carry the first letters of the label beside it.  Drop
            # such crops before anything else looks at the element list.
            _strategy(
                "fragment-image",
                (),
                (),
                _drop_fragment_images,
                always=True,
            ),
            # The mirror image of the case above: a badge crop that is *wider*
            # than its label (so fragment-image cannot fire) but too short to
            # hold the badge carries the glyphs too.  Replace it with the
            # outline it was standing in for; keep the label, drop the copy.
            _strategy(
                "badge-outline",
                (),
                (),
                _badge_outline,
                always=True,
            ),
            # A selected header tab is a filled shape the asset pass does not
            # see; recover it from the screenshot so the label is not left
            # floating on the page background.
            _strategy(
                "selection-plate",
                (),
                (),
                _selection_plate,
                always=True,
            ),
            # A phantom owner cannot hold its own text and repeats a roomier
            # owner elsewhere (the nav-row search box on dark-card-grid); drop
            # it before any weight rule makes it more visible.
            _strategy(
                "duplicate-owner",
                (),
                (),
                _drop_duplicate_owners,
                always=True,
            ),
            # Frozen VLM decisions from conflict_adjudicator.py; no-ops unless
            # that report exists for this run.
            _strategy(
                "adjudicated-conflict",
                (),
                (),
                _adjudicated_conflicts,
                always=True,
            ),
            # Two different strings in one slot: only the provable OCR
            # concatenation is dropped; the rest is recorded for adjudication.
            _strategy(
                "same-slot-conflict",
                (),
                (),
                _same_slot_conflict,
                always=True,
            ),
            # A table states its own type scale: cells at 48.5 pt beside cells
            # at 21 pt are a box-height artefact, not a hierarchy decision.
            _strategy(
                "table-cell-scale",
                (),
                (),
                _table_cell_scale,
                always=True,
            ),
            # Structural, not statistical: the page's own type scale decides
            # which text is display-scale.  Runs first so the initial write
            # already carries the hierarchy.
            _strategy(
                "display-weight",
                (),
                (),
                _display_weight,
                always=True,
            ),
            # Header menu rows are chrome: one band of short labels at one
            # size, above the content.  Promoted to Medium only (400 -> 500);
            # see apply_nav_row_weight for why "equally spaced" is not the
            # signal that survives perception-box padding.
            _strategy(
                "nav-row-weight",
                (),
                (),
                _nav_weight,
                always=True,
            ),
            # A tilted sticker arrives axis-aligned because no layer has a
            # rotation field; measure it off the screenshot so the SVG render
            # and the Figma write can both honour it.  Upright text is cleared,
            # not nudged -- the dead zone is where the measurement noise is.
            _strategy(
                "text-rotation",
                (),
                (),
                _text_rotation,
                always=True,
            ),
            # A tilted block of ink is a sticker (price + unit), not a
            # paragraph, and the design merged its lines into one string sized
            # from the block height.  Runs after text-rotation, which is where
            # the tilt it keys on comes from.
            _strategy(
                "text-block-lines",
                (),
                (),
                _text_block_lines,
                always=True,
            ),
            _strategy("control-fonts", (), (), _control_fonts, always=True),
            _strategy(
                "table-fonts", ("size", "coverage", "edgeF1"), ("table",), _table_fonts
            ),
            _strategy(
                "form-text-positions",
                ("position",),
                ("form",),
                _form_text_positions,
            ),
        ),
    ),
    CalibrationGroup(
        name="table-positions",
        render_suffix="figma_calibrated",
        strategies=(
            _strategy(
                "table-positions",
                ("position",),
                ("table",),
                _table_positions,
            ),
        ),
    ),
    CalibrationGroup(
        name="table-spacing",
        render_suffix="figma_table_spacing",
        strategies=(
            _strategy(
                "table-letter-spacing",
                ("size", "coverage", "edgeF1"),
                ("table",),
                _table_letter_spacing,
            ),
        ),
    ),
    CalibrationGroup(
        name="form-fonts",
        render_suffix="figma_form_font",
        strategies=(
            _strategy(
                "form-fonts",
                ("size", "coverage", "edgeF1"),
                ("form",),
                _form_fonts,
            ),
        ),
    ),
    CalibrationGroup(
        name="form-weight",
        render_suffix="figma_form_weight",
        strategies=(
            _strategy(
                "form-weight",
                ("coverage", "edgeF1"),
                ("form",),
                _form_weight,
            ),
        ),
    ),
    CalibrationGroup(
        name="form-shape",
        render_suffix="figma_form_shape",
        strategies=(
            _strategy(
                "form-shape",
                ("size", "coverage", "edgeF1"),
                ("form",),
                _form_shape,
            ),
        ),
    ),
    CalibrationGroup(
        name="form-positions",
        render_suffix="figma_form_calibrated",
        strategies=(
            _strategy(
                "form-positions",
                ("position",),
                ("form",),
                _form_positions,
            ),
        ),
    ),
    CalibrationGroup(
        name="form-positions-second",
        render_suffix="figma_form_calibrated_2",
        strategies=(
            _strategy(
                "form-positions-second",
                ("position",),
                ("form",),
                _form_positions,
            ),
        ),
    ),
    CalibrationGroup(
        name="placeholder",
        render_suffix="figma_placeholder",
        strategies=(
            _strategy(
                "placeholder",
                ("coverage", "edgeF1"),
                ("form", "search", "page"),
                _placeholder,
                always=True,
            ),
        ),
    ),
    CalibrationGroup(
        name="toolbar-spacing",
        render_suffix="figma_toolbar_calibrated",
        strategies=(
            _strategy(
                "toolbar-letter-spacing",
                ("size", "coverage", "edgeF1"),
                ("toolbar", "table", "form", "page"),
                _toolbar_letter_spacing,
            ),
        ),
    ),
    CalibrationGroup(
        name="toolbar-weight",
        render_suffix="figma_toolbar_weight",
        strategies=(
            _strategy(
                "toolbar-weight",
                ("coverage", "edgeF1"),
                ("toolbar", "table", "form", "page"),
                _toolbar_weight,
            ),
        ),
    ),
    CalibrationGroup(
        name="toolbar-spacing-second",
        render_suffix="figma_toolbar_calibrated_2",
        strategies=(
            _strategy(
                "toolbar-letter-spacing-second",
                ("size", "coverage", "edgeF1"),
                ("toolbar", "table", "form", "page"),
                _toolbar_letter_spacing,
            ),
        ),
    ),
    CalibrationGroup(
        name="search-control",
        render_suffix="figma_search_control",
        strategies=(
            _strategy(
                "search-control",
                ("position", "size", "coverage", "edgeF1"),
                ("search", "table", "toolbar", "page"),
                _search_control,
                always=True,
            ),
        ),
    ),
    CalibrationGroup(
        name="ink-convergence",
        render_suffix="figma_ink_converged",
        strategies=(
            _strategy(
                "ink-convergence",
                ("size", "coverage", "edgeF1", "position"),
                ("table", "form", "toolbar", "page", "search"),
                _ink_convergence,
                always=True,
            ),
        ),
    ),
)


def _strategy_matches(
    strategy: CalibrationStrategy,
    profile: Mapping[str, Any],
) -> bool:
    if strategy.always:
        return True
    if not strategy.residuals:
        return True
    measured = int(profile.get("measuredOwnerCount") or 0)
    if measured <= 0:
        return True
    regions = set(profile.get("regions") or [])
    if strategy.regions and not (strategy.regions & regions):
        return False
    residuals = profile.get("residuals") or {}
    if any(int(residuals.get(kind) or 0) > 0 for kind in strategy.residuals):
        return True
    by_region = profile.get("byRegion") or {}
    return any(
        int((by_region.get(region) or {}).get(kind) or 0) > 0
        for region in strategy.regions
        for kind in strategy.residuals
    )


def select_calibration_groups(
    profile: Mapping[str, Any] | None,
    *,
    mode: str = "legacy",
) -> list[tuple[CalibrationGroup, tuple[CalibrationStrategy, ...]]]:
    """Select groups in historical order; residual mode skips absent classes."""
    if mode not in CALIBRATION_MODES:
        raise ValueError(f"unsupported calibration mode: {mode}")
    if mode == "legacy" or not profile:
        return [(group, group.strategies) for group in CALIBRATION_GROUPS]
    if int(profile.get("measuredOwnerCount") or 0) <= 0:
        return [(group, group.strategies) for group in CALIBRATION_GROUPS]
    selected: list[tuple[CalibrationGroup, tuple[CalibrationStrategy, ...]]] = []
    for group in CALIBRATION_GROUPS:
        strategies = tuple(
            strategy
            for strategy in group.strategies
            if _strategy_matches(strategy, profile)
        )
        if strategies:
            selected.append((group, strategies))
    return selected


def run_calibration_pipeline(
    *,
    design: dict[str, Any],
    image: str,
    run_root: Path,
    readback: dict[str, Any],
    ocr_supplement: dict[str, Any],
    render: Callable[[dict[str, Any], str], tuple[Path, dict[str, Any]]],
    mode: str = "legacy",
    profile_builder: Callable[
        [dict[str, Any], Path, dict[str, Any]], Mapping[str, Any] | None
    ]
    | None = None,
) -> CalibrationPipelineResult:
    """Run selected groups, re-rendering once per group when needed."""
    current_design = design
    current_run_root = run_root
    current_readback = readback
    profile = None
    if mode == "residual":
        if profile_builder is None:
            raise ValueError("residual calibration mode requires profile_builder")
        profile = profile_builder(current_design, current_run_root, current_readback)
    reports: dict[str, dict[str, Any]] = {}
    selected_groups: list[str] = []
    for group in CALIBRATION_GROUPS:
        if mode == "legacy" or profile is None:
            strategies = group.strategies
        else:
            strategies = tuple(
                strategy
                for strategy in group.strategies
                if _strategy_matches(strategy, profile)
            )
        if not strategies:
            continue
        selected_groups.append(group.name)
        group_design = current_design
        group_reports: list[dict[str, Any]] = []
        for strategy in strategies:
            ctx = CalibrationContext(
                design=group_design,
                image=image,
                run_root=current_run_root,
                readback=current_readback,
                ocr_supplement=ocr_supplement,
            )
            candidate_design, report = strategy.runner(ctx)
            enriched = {
                **report,
                "strategy": strategy.name,
                "group": group.name,
            }
            reports[strategy.name] = enriched
            group_reports.append(enriched)
            if int(report.get("adjusted_count") or 0) > 0:
                group_design = candidate_design
        if not any(
            int(report.get("adjusted_count") or 0) > 0 for report in group_reports
        ):
            continue
        current_design = group_design
        current_run_root, summary = render(current_design, group.render_suffix)
        if summary.get("status") != "captured-figma-evidence":
            raise CalibrationRenderError(group.name, summary)
        current_readback = json.loads(
            (current_run_root / "readback.json").read_text(encoding="utf-8")
        )
        if mode == "residual" and profile_builder is not None:
            profile = profile_builder(
                current_design,
                current_run_root,
                current_readback,
            )
    return CalibrationPipelineResult(
        design=current_design,
        run_root=current_run_root,
        readback=current_readback,
        reports=reports,
        selected_groups=selected_groups,
        profile=dict(profile) if profile is not None else None,
    )
