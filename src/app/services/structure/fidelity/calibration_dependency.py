# -*- coding: utf-8 -*-
"""What each calibration strategy reads, and what it makes stale.

This module is **declaration only**: the scheduler still runs the groups in
``CALIBRATION_GROUPS`` order and renders whenever a group reported an
adjustment.  Nothing here can change a pixel; the point is to make the
dependency graph explicit before anyone tries to cut render passes.

Why it is needed
----------------
``light-form`` renders 16 times in one run.  Each render is a Figma round trip,
so the cost sits in the *number of groups that adjust something*, not in the
page size.  Cutting them requires knowing which strategies actually need a
fresh render and which only transform the design (or read the source
screenshot).  That information is not in the code today -- it lives in the
body of thirty small runner functions, which is the wrong place to reason from.

The dependency unit is the strategy, not the group
--------------------------------------------------
``font-initial`` bundles eleven strategies that never look at a render
(fragment-image, duplicate-owner, display-weight, ...) with three that do
(table-fonts, form-text-positions via readback, ...).  A group-level
``reads`` set would therefore be "everything", and would say nothing.  The
report aggregates to the group anyway, because that is the scheduling unit
today.

Vocabulary
----------
``reads`` is the set of *external* channels a strategy consults, beyond the
design tree it is handed:

* ``reference`` -- the source screenshot
* ``readback``  -- the Figma node tree of the latest render
* ``render``    -- the pixels of the latest render
* ``decisions`` -- a frozen adjudication file inside the run

``invalidates`` is what a later strategy may no longer trust once this one has
written to the design:

* ``render``   -- the pixels no longer show the current design
* ``readback`` -- the node tree no longer mirrors the element list

The design tree itself is always an input and always written, so it is
implicit and left out of both sets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CHANNELS = frozenset({"reference", "readback", "render", "decisions"})
WRITES = frozenset({"render", "readback"})


@dataclass(frozen=True)
class StrategyIO:
    """One strategy's inputs and the evidence it invalidates."""

    reads: frozenset[str]
    invalidates: frozenset[str]

    @property
    def needs_render(self) -> bool:
        """True when the strategy cannot run before the next render."""
        return bool(self.reads & {"render", "readback"})


def _io(reads: str = "", invalidates: str = "render") -> StrategyIO:
    """Build a declaration from space-separated channel names."""
    return StrategyIO(
        reads=frozenset(reads.split()),
        invalidates=frozenset(invalidates.split()),
    )


#: Per-strategy declaration.  Every strategy in ``CALIBRATION_GROUPS`` must
#: appear here -- ``validate`` fails otherwise, so adding a strategy forces a
#: decision instead of silently inheriting "reads everything".
STRATEGY_IO: dict[str, StrategyIO] = {
    # --- design-only transforms: no screenshot, no render -------------------
    "fragment-image": _io("", "readback render"),
    "duplicate-owner": _io("", "readback render"),
    "same-slot-conflict": _io(),
    "table-cell-scale": _io(),
    "display-weight": _io(),
    "nav-row-weight": _io(),
    "adjudicated-conflict": _io("decisions"),
    # --- read the source screenshot to synthesise a missing shape -----------
    "badge-outline": _io("reference"),
    "selection-plate": _io("reference"),
    "text-rotation": _io("reference"),
    "text-block-lines": _io("reference", "readback render"),
    # --- read the node tree of the last render ------------------------------
    "control-fonts": _io("readback"),
    "form-text-positions": _io("readback"),
    # --- read the rendered pixels -------------------------------------------
    "table-fonts": _io("reference render"),
    "table-positions": _io("render"),
    "table-letter-spacing": _io("render"),
    "form-fonts": _io("render"),
    "form-weight": _io("render"),
    "form-shape": _io("render"),
    "form-positions": _io("readback render"),
    "form-positions-second": _io("readback render"),
    "placeholder": _io("reference render"),
    "toolbar-letter-spacing": _io("render"),
    "toolbar-letter-spacing-second": _io("render"),
    "toolbar-weight": _io("render"),
    "search-control": _io("render"),
    "ink-convergence": _io("readback render"),
    "ink-convergence-second": _io("readback render"),
    "weight-convergence": _io("readback render"),
    "text-positions": _io("render"),
}


def validate(groups: Any) -> list[str]:
    """Return the declaration problems for a group list; empty means clean."""
    problems: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for strategy in group.strategies:
            name = strategy.name
            if name in seen:
                problems.append(f"{name}: declared twice in CALIBRATION_GROUPS")
            seen.add(name)
            if name not in STRATEGY_IO:
                problems.append(f"{name}: no reads/invalidates declaration")
    for name in STRATEGY_IO:
        if name not in seen:
            problems.append(f"{name}: declared but no strategy owns it")
    for name, io in STRATEGY_IO.items():
        unknown = (io.reads | io.invalidates) - CHANNELS - WRITES
        if unknown:
            problems.append(f"{name}: unknown channel(s) {sorted(unknown)}")
    return problems


def dependency_report(groups: Any) -> dict[str, Any]:
    """Per-group and per-strategy dependency picture, plus the saving on offer.

    ``render_points`` are the groups that currently force a render because at
    least one of their strategies reports an adjustment *and* the group is
    allowed to run.  ``design_only_strategies`` are the ones that could be
    batched ahead of the next render without changing their inputs; today they
    sit inside groups that also contain render readers, so the group as a whole
    cannot move.
    """
    rows: list[dict[str, Any]] = []
    design_only: list[str] = []
    single_region: dict[str, list[str]] = {}
    for group in groups:
        reads: set[str] = set()
        invalidates: set[str] = set()
        regions: set[str] = set()
        forcing: list[str] = []
        for strategy in group.strategies:
            io = STRATEGY_IO.get(strategy.name)
            if io is None:
                continue
            reads |= io.reads
            invalidates |= io.invalidates
            regions |= set(strategy.regions)
            if io.needs_render:
                forcing.append(strategy.name)
            else:
                design_only.append(strategy.name)
        if len(regions) == 1:
            single_region.setdefault(next(iter(regions)), []).append(group.name)
        rows.append(
            {
                "group": group.name,
                "strategies": [s.name for s in group.strategies],
                "reads": sorted(reads),
                "invalidates": sorted(invalidates),
                "regions": sorted(regions),
                "render_forcing": forcing,
                "runs_without_a_render": not forcing,
            }
        )
    return {
        "schema_version": "grounding-calibration-dependency/1.0",
        "channels": sorted(CHANNELS),
        "groups": rows,
        "design_only_strategies": design_only,
        "groups_that_never_read_a_render": [
            row["group"] for row in rows if row["runs_without_a_render"]
        ],
        # Groups that touch exactly one region cannot see another region's
        # writes, so two *different* clusters can advance in the same round:
        # edit both, render once.  Within one cluster they stay serial -- each
        # pass measures the previous pass's effect (form-fonts moves ink
        # coverage, which form-weight then reads).  So the saving is
        # ``sum(cluster sizes) - max(cluster size)``, not ``sum(size - 1)``.
        "single_region_groups": single_region,
        "round_robin_saving": (
            sum(len(names) for names in single_region.values())
            - max((len(names) for names in single_region.values()), default=0)
        ),
    }
