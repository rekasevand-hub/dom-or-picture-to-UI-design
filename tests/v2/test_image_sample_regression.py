"""Structural regression over the seven benchmark screenshots.

The screenshots themselves cannot be re-run in a unit test — the perception
stage calls a vision model, costs money and does not repeat.  What is frozen
here is the compiled design for each sample, one file per screenshot, with the
frame fields stripped.  Every assertion therefore runs the deterministic half
of the pipeline: shell removal, coincident-text removal, frame assembly,
overlay lifting and the renderer's own acceptance pass.

Two things are locked:

* a floor on the number of accepted frames per sample, so an upstream change
  that quietly costs a container is caught as a failure rather than noticed a
  week later in an export;
* ``written == accepted``, which is the invariant that makes the frame count
  mean something: the meta must never claim a frame the renderer would drop.

A third check guards the export itself: no two text elements may print the same
words over the same area.
"""

from __future__ import annotations

import copy
import json
from difflib import SequenceMatcher
from pathlib import Path

import pytest

from src.app.services.rendering.adapter_base import paint_order, resolve_frames
from src.app.services.structure.fidelity.fixed_canvas_compiler import (
    _drop_coincident_texts,
    _drop_page_coloured_shells,
    _keep_renderable_frames,
    _lift_frame_overlays,
    attach_layout_frames,
)

FIXTURES = Path(__file__).parent / "fixtures" / "image_samples"

#: Accepted frames measured on the frozen designs.  A floor, not an equality:
#: gaining a frame is never a regression, losing one always is.
FRAME_FLOORS = {
    "AtomGit": 9,
    "FluxWeaver": 6,
    "inventory": 9,
    "marketplace": 7,
    "review": 3,
    "wecom-modal": 6,
    "inventory2": 11,
}

#: A frame whose loss has already cost us a debugging round: the modal in the
#: dimmed dialog, and the table block in the inventory page.
REQUIRED_FRAMES = {
    "wecom-modal": {"modal"},
    "inventory": {"sidebar", "table-section"},
}

GHOST_COVERAGE = 0.35
GHOST_SIMILARITY = 0.6


def _load(tag: str) -> dict:
    return json.loads((FIXTURES / f"{tag}.json").read_text(encoding="utf-8"))


def _build(tag: str) -> tuple[list[dict], list[int], dict]:
    design = _load(tag)
    elements = copy.deepcopy(design["elements"])
    background = str((design.get("canvas") or {}).get("background") or "")
    _drop_page_coloured_shells(elements, background)
    _drop_coincident_texts(elements)
    written = attach_layout_frames(elements)
    frames = [index for index, element in enumerate(elements) if element.get("layoutChildren")]
    _lift_frame_overlays(elements, frames)
    reasons: dict[int, str] = {}
    accepted = resolve_frames(elements, paint_order(elements), reasons)
    kept = _keep_renderable_frames(elements, written)
    return elements, sorted(accepted), {"written": written, "kept": kept, "reasons": reasons}


@pytest.mark.parametrize("tag", sorted(FRAME_FLOORS))
def test_sample_keeps_its_frames(tag: str) -> None:
    elements, accepted, report = _build(tag)
    assert len(accepted) >= FRAME_FLOORS[tag], (
        f"{tag}: {len(accepted)} frames, expected at least {FRAME_FLOORS[tag]}; "
        f"rejected {report['reasons']}"
    )
    for name in REQUIRED_FRAMES.get(tag, ()):  # pragma: no branch - tiny loop
        assert any(
            str(elements[index].get("name")) == name for index in accepted
        ), f"{tag}: frame {name!r} disappeared"


@pytest.mark.parametrize("tag", sorted(FRAME_FLOORS))
def test_written_equals_accepted(tag: str) -> None:
    """The frame count in the meta must equal what the renderer will build.

    ``_keep_renderable_frames`` clears the frames the renderer refuses, so this
    catches the case where that self-check stops running or starts disagreeing
    with ``resolve_frames`` — the meta would then promise frames that never
    appear in Figma.
    """
    elements, accepted, report = _build(tag)
    remaining = [
        index
        for index, element in enumerate(elements)
        if element.get("layoutChildren")
    ]
    assert sorted(remaining) == accepted, (
        f"{tag}: {len(remaining)} frames left in the design, "
        f"{len(accepted)} accepted"
    )
    assert report["kept"] == len(accepted)


@pytest.mark.parametrize("tag", sorted(FRAME_FLOORS))
def test_no_double_printed_text(tag: str) -> None:
    elements, _accepted, _report = _build(tag)
    texts = [
        element
        for element in elements
        if element.get("type") == "text" and element.get("text")
    ]
    clashes: list[str] = []
    for position, first in enumerate(texts):
        for second in texts[position + 1 :]:
            overlap_w = min(
                first["x"] + first["width"], second["x"] + second["width"]
            ) - max(first["x"], second["x"])
            overlap_h = min(
                first["y"] + first["height"], second["y"] + second["height"]
            ) - max(first["y"], second["y"])
            if overlap_w <= 0 or overlap_h <= 0:
                continue
            coverage = (overlap_w * overlap_h) / max(
                1,
                min(
                    first["width"] * first["height"],
                    second["width"] * second["height"],
                ),
            )
            if coverage < GHOST_COVERAGE:
                continue
            one = str(first["text"])
            two = str(second["text"])
            if (
                SequenceMatcher(None, one, two).ratio() >= GHOST_SIMILARITY
                or one in two
                or two in one
            ):
                clashes.append(f"{one!r} over {two!r} ({coverage:.2f})")
    assert not clashes, f"{tag}: same words printed twice: {clashes[:3]}"
