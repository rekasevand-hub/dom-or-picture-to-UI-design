from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from src.app.services.structure.fidelity.calibration_profile import (
    build_calibration_residual_profile,
)
from src.app.services.structure.fidelity.calibration_strategies import (
    CALIBRATION_GROUPS,
    CalibrationContext,
    CalibrationGroup,
    CalibrationRenderError,
    CalibrationStrategy,
    run_calibration_pipeline,
    select_calibration_groups,
)


def _group_names(
    selected: list[tuple[CalibrationGroup, tuple[CalibrationStrategy, ...]]],
) -> list[str]:
    return [group.name for group, _strategies in selected]


def test_residual_selection_skips_table_groups_without_table_region() -> None:
    profile = {
        "measuredOwnerCount": 4,
        "regions": ["page", "form"],
        "residuals": {
            "position": 1,
            "size": 0,
            "coverage": 0,
            "edgeF1": 0,
        },
        "byRegion": {
            "form": {
                "position": 1,
                "size": 0,
                "coverage": 0,
                "edgeF1": 0,
            }
        },
    }

    selected = select_calibration_groups(profile, mode="residual")
    names = _group_names(selected)

    assert "font-initial" in names
    assert "form-positions" in names
    assert "table-positions" not in names
    assert "table-spacing" not in names
    assert "toolbar-spacing" not in names


def test_residual_selection_keeps_table_groups_for_size_residuals() -> None:
    profile = {
        "measuredOwnerCount": 4,
        "regions": ["page", "table"],
        "residuals": {
            "position": 0,
            "size": 2,
            "coverage": 1,
            "edgeF1": 0,
        },
        "byRegion": {
            "table": {
                "position": 0,
                "size": 2,
                "coverage": 1,
                "edgeF1": 0,
            }
        },
    }

    selected = select_calibration_groups(profile, mode="residual")
    names = _group_names(selected)

    assert "table-spacing" in names
    assert "table-positions" not in names
    assert "form-fonts" not in names
    assert "toolbar-spacing" in names


def test_residual_selection_falls_back_to_legacy_without_measurements() -> None:
    selected = select_calibration_groups(
        {
            "measuredOwnerCount": 0,
            "regions": ["page"],
            "residuals": {},
            "byRegion": {},
        },
        mode="residual",
    )

    assert [group.name for group, _ in selected] == [
        group.name for group in CALIBRATION_GROUPS
    ]


def test_pipeline_renders_once_per_adjusted_group(tmp_path: Path) -> None:
    render_calls: list[str] = []

    def _strategy(name: str, adjusted: int) -> CalibrationStrategy:
        def _runner(ctx: CalibrationContext) -> tuple[dict, dict]:
            design = dict(ctx.design)
            steps = list(design.get("steps") or [])
            if adjusted:
                steps.append(name)
            design["steps"] = steps
            return design, {"adjusted_count": adjusted}

        return CalibrationStrategy(
            name=name,
            residuals=frozenset(),
            regions=frozenset(),
            runner=_runner,
            always=True,
        )

    def _render(design: dict, suffix: str) -> tuple[Path, dict]:
        render_calls.append(suffix)
        root = tmp_path / suffix
        root.mkdir(parents=True, exist_ok=True)
        (root / "readback.json").write_text(
            json.dumps({"type": "FRAME", "children": []}),
            encoding="utf-8",
        )
        return root, {"status": "captured-figma-evidence"}

    groups = (
        CalibrationGroup(
            name="group-a",
            render_suffix="figma_a",
            strategies=(_strategy("a1", 1), _strategy("a2", 1)),
        ),
        CalibrationGroup(
            name="group-b",
            render_suffix="figma_b",
            strategies=(_strategy("b1", 0),),
        ),
    )

    import src.app.services.structure.fidelity.calibration_strategies as strategies

    original = strategies.CALIBRATION_GROUPS
    strategies.CALIBRATION_GROUPS = groups
    try:
        result = run_calibration_pipeline(
            design={"steps": []},
            image="unused.png",
            run_root=tmp_path / "figma",
            readback={"type": "FRAME", "children": []},
            ocr_supplement={},
            render=_render,
            mode="legacy",
        )
    finally:
        strategies.CALIBRATION_GROUPS = original

    assert render_calls == ["figma_a"]
    assert result.design["steps"] == ["a1", "a2"]
    assert result.reports["a1"]["group"] == "group-a"
    assert result.reports["b1"]["adjusted_count"] == 0
    assert result.selected_groups == ["group-a", "group-b"]


def test_pipeline_surfaces_failed_calibration_render(tmp_path: Path) -> None:
    def _strategy() -> CalibrationStrategy:
        def _runner(ctx: CalibrationContext) -> tuple[dict, dict]:
            return dict(ctx.design), {"adjusted_count": 1}

        return CalibrationStrategy(
            name="adjust",
            residuals=frozenset(),
            regions=frozenset(),
            runner=_runner,
            always=True,
        )

    def _render(_design: dict, suffix: str) -> tuple[Path, dict]:
        return tmp_path / suffix, {"status": "failed"}

    groups = (
        CalibrationGroup(
            name="group-a",
            render_suffix="figma_a",
            strategies=(_strategy(),),
        ),
    )

    import src.app.services.structure.fidelity.calibration_strategies as strategies

    original = strategies.CALIBRATION_GROUPS
    strategies.CALIBRATION_GROUPS = groups
    try:
        with pytest.raises(CalibrationRenderError) as error:
            run_calibration_pipeline(
                design={},
                image="unused.png",
                run_root=tmp_path / "figma",
                readback={"type": "FRAME", "children": []},
                ocr_supplement={},
                render=_render,
                mode="legacy",
            )
    finally:
        strategies.CALIBRATION_GROUPS = original

    assert error.value.group_name == "group-a"
    assert error.value.summary["status"] == "failed"


def test_residual_pipeline_recomputes_profile_after_render(tmp_path: Path) -> None:
    profile_calls: list[dict] = []
    render_calls: list[str] = []

    def _strategy(name: str) -> CalibrationStrategy:
        def _runner(ctx: CalibrationContext) -> tuple[dict, dict]:
            return dict(ctx.design), {"adjusted_count": 1}

        return CalibrationStrategy(
            name=name,
            residuals=frozenset({"position"}),
            regions=frozenset({"page"}),
            runner=_runner,
        )

    def _render(design: dict, suffix: str) -> tuple[Path, dict]:
        render_calls.append(suffix)
        root = tmp_path / suffix
        root.mkdir(parents=True, exist_ok=True)
        (root / "readback.json").write_text(
            json.dumps({"type": "FRAME", "children": []}),
            encoding="utf-8",
        )
        return root, {"status": "captured-figma-evidence"}

    def _profile(*_args) -> dict:
        profile = {
            "measuredOwnerCount": 1,
            "regions": ["page"],
            "residuals": {"position": 1},
            "byRegion": {"page": {"position": 1}},
        }
        if profile_calls:
            profile = {
                "measuredOwnerCount": 1,
                "regions": ["page"],
                "residuals": {"position": 0},
                "byRegion": {"page": {"position": 0}},
            }
        profile_calls.append(profile)
        return profile

    groups = (
        CalibrationGroup(
            name="group-a",
            render_suffix="figma_a",
            strategies=(_strategy("a1"),),
        ),
        CalibrationGroup(
            name="group-b",
            render_suffix="figma_b",
            strategies=(_strategy("b1"),),
        ),
    )

    import src.app.services.structure.fidelity.calibration_strategies as strategies

    original = strategies.CALIBRATION_GROUPS
    strategies.CALIBRATION_GROUPS = groups
    try:
        result = run_calibration_pipeline(
            design={},
            image="unused.png",
            run_root=tmp_path / "figma",
            readback={"type": "FRAME", "children": []},
            ocr_supplement={},
            render=_render,
            mode="residual",
            profile_builder=_profile,
        )
    finally:
        strategies.CALIBRATION_GROUPS = original

    assert len(profile_calls) == 2
    assert render_calls == ["figma_a"]
    assert result.selected_groups == ["group-a"]
    assert "b1" not in result.reports


def test_calibration_profile_maps_position_residual_to_form(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    reference_image = Image.new("RGB", (200, 100), "white")
    reference_draw = ImageDraw.Draw(reference_image)
    reference_draw.rectangle((20, 20, 49, 28), fill="black")
    reference_image.save(reference)
    rendered_image = Image.new("RGB", (200, 100), "white")
    rendered_draw = ImageDraw.Draw(rendered_image)
    rendered_draw.rectangle((23, 20, 52, 28), fill="black")
    rendered_image.save(rendered)
    design = {
        "elements": [
            {
                "type": "text",
                "contentRef": "text:label",
                "text": "Label",
                "x": 20,
                "y": 20,
                "width": 30,
                "height": 9,
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [15, 15, 40, 19],
                        "ink_bbox": [20, 20, 30, 9],
                    }
                },
            }
        ]
    }
    readback = {
        "type": "FRAME",
        "children": [{"type": "TEXT", "characters": "Label"}],
    }

    profile = build_calibration_residual_profile(
        design,
        readback,
        str(reference),
        str(rendered),
        [{"id": "form-section", "role": "form-section", "bbox": [0, 0, 200, 100]}],
    )

    assert profile["measuredOwnerCount"] == 1
    assert profile["residuals"]["position"] == 1
    assert profile["byRegion"]["form"]["position"] == 1
    assert profile["regions"] == ["form", "page"]
