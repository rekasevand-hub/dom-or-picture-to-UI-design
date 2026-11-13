# -*- coding: utf-8 -*-
"""The calibration dependency graph must be complete and must not move anything.

Two properties matter.  First, every strategy in ``CALIBRATION_GROUPS`` has a
declaration: adding a strategy without saying what it reads would quietly
inherit "reads everything" and the graph would be a lie.  Second, the
declaration is inert -- it reports, it does not reorder.
"""

from __future__ import annotations

import pytest

from src.app.services.structure.fidelity.calibration_dependency import (
    STRATEGY_IO,
    dependency_report,
    validate,
)
from src.app.services.structure.fidelity.calibration_strategies import (
    CALIBRATION_GROUPS,
    CalibrationGroup,
    CalibrationStrategy,
)


def _strategy(name: str, *, regions: tuple[str, ...] = ()) -> CalibrationStrategy:
    return CalibrationStrategy(
        name=name,
        residuals=frozenset({"size"}),
        regions=frozenset(regions),
        runner=lambda _ctx: ({}, {}),
    )


def test_every_strategy_declares_what_it_reads() -> None:
    assert validate(CALIBRATION_GROUPS) == []


def test_a_strategy_without_a_declaration_is_reported() -> None:
    group = CalibrationGroup(
        name="invented",
        render_suffix="figma_invented",
        strategies=(_strategy("mystery-strategy"),),
    )
    problems = validate((*CALIBRATION_GROUPS, group))
    assert any("mystery-strategy" in problem for problem in problems)


def test_a_declaration_without_an_owner_is_reported() -> None:
    problems = validate(())
    assert any("no strategy owns it" in problem for problem in problems)


def test_declaration_does_not_reorder_the_pipeline() -> None:
    report = dependency_report(CALIBRATION_GROUPS)
    assert [row["group"] for row in report["groups"]] == [
        group.name for group in CALIBRATION_GROUPS
    ]


def test_font_initial_is_the_one_group_that_reads_everything() -> None:
    rows = {row["group"]: row for row in dependency_report(CALIBRATION_GROUPS)["groups"]}
    assert rows["font-initial"]["reads"] == sorted(
        {"decisions", "readback", "reference", "render"}
    )
    assert rows["font-initial"]["runs_without_a_render"] is False


def test_design_only_strategies_never_ask_for_a_render() -> None:
    for name in (
        "fragment-image",
        "duplicate-owner",
        "same-slot-conflict",
        "table-cell-scale",
        "display-weight",
        "nav-row-weight",
    ):
        assert STRATEGY_IO[name].reads == frozenset(), name
        assert STRATEGY_IO[name].needs_render is False, name


def test_single_region_groups_are_grouped_by_region() -> None:
    report = dependency_report(CALIBRATION_GROUPS)
    form = report["single_region_groups"].get("form", [])
    table = report["single_region_groups"].get("table", [])
    assert len(form) >= 4, form
    assert len(table) >= 2, table
    # text-positions declares no region: it may touch anything, so it must not
    # be counted as batchable.
    flat = [name for names in report["single_region_groups"].values() for name in names]
    assert "text-positions" not in flat


@pytest.mark.parametrize("name", sorted(STRATEGY_IO))
def test_declared_channels_are_in_the_vocabulary(name: str) -> None:
    io = STRATEGY_IO[name]
    assert io.reads <= {"reference", "readback", "render", "decisions"}
    assert io.invalidates <= {"render", "readback"}
