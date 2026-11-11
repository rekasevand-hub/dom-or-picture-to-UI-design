"""Per-line font sizes: a block whose lines are not the same size.

``5.8折`` on dark-card-grid is one block of two lines at **62 pt** and **30 pt**
(gold nodes ``5.8`` and ``折``).  A single ``fontSize`` cannot express that, so
the pipeline carries ``lineSizes`` beside ``lines``:

* the SVG renderer puts each line in its own ``<tspan>`` with its own size and
  its own baseline -- different sizes do not share an em baseline, so reusing
  one line box would push the small line into the big one;
* the Figma bridge gets the same information as ``richRuns``, which are
  character offsets and therefore only valid against the *joined* string.
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.app.services.rendering.figma_adapter import _line_font_runs
from src.app.services.rendering.svg_adapter import SVGMockAdapter

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _text_spec(**extra: object) -> dict:
    spec = {
        "type": "text",
        "x": 100,
        "y": 50,
        "width": 120,
        "height": 100,
        "text": "5.8折",
        "lines": ["5.8", "折"],
        "style": {"fontSize": 46, "textColor": "#F05943"},
    }
    spec.update(extra)
    return spec


def test_rich_runs_span_the_joined_string() -> None:
    runs = _line_font_runs(["5.8", "折"], [62, 30])

    # "5.8\n折": the newline sits at index 3, so the second run starts at 4.
    assert runs == [
        {"start": 0, "end": 3, "style": {"fontSize": 62}},
        {"start": 4, "end": 5, "style": {"fontSize": 30}},
    ]


def test_rich_runs_skip_a_line_without_a_size() -> None:
    runs = _line_font_runs(["5.8", "折"], [62, None])

    assert runs == [{"start": 0, "end": 3, "style": {"fontSize": 62}}]


def test_rich_runs_require_matching_lists() -> None:
    assert _line_font_runs(["5.8", "折"], [62]) == []
    assert _line_font_runs(None, [62]) == []


def test_svg_gives_each_line_its_own_size(tmp_path: Path) -> None:
    adapter = SVGMockAdapter(tmp_path / "out.svg")

    adapter.render_design(
        {
            "canvas": {"width": 320, "height": 240},
            "elements": [_text_spec(lineSizes=[62, 30])],
        }
    )

    text = next(node for node in adapter.elements if node.tag == "text")
    spans = [node for node in text if node.tag == "tspan"]
    assert [span.get("font-size") for span in spans] == ["62", "30"]

    # Each line is centred in its own box, so the pitch is no longer the
    # uniform 1.4em step -- and a taller first line pushes the second further
    # down. Both are consequences of sizing per line rather than per block.
    def pitch(sizes: list[int], name: str) -> float:
        other = SVGMockAdapter(tmp_path / f"{name}.svg")
        other.render_design(
            {
                "canvas": {"width": 320, "height": 240},
                "elements": [_text_spec(lineSizes=sizes)],
            }
        )
        node = next(item for item in other.elements if item.tag == "text")
        return float(node[1].get("y")) - float(node[0].get("y"))

    uniform = SVGMockAdapter(tmp_path / "uniform.svg")
    uniform.render_design(
        {"canvas": {"width": 320, "height": 240}, "elements": [_text_spec()]}
    )
    uniform_node = next(item for item in uniform.elements if item.tag == "text")
    uniform_pitch = float(uniform_node[1].get("y")) - float(uniform_node[0].get("y"))

    assert pitch([62, 30], "small") != uniform_pitch
    assert pitch([80, 30], "tall") > pitch([62, 30], "small")


def test_svg_without_line_sizes_keeps_the_old_shape(tmp_path: Path) -> None:
    adapter = SVGMockAdapter(tmp_path / "out.svg")

    adapter.render_design(
        {"canvas": {"width": 320, "height": 240}, "elements": [_text_spec()]}
    )

    text = next(node for node in adapter.elements if node.tag == "text")
    spans = [node for node in text if node.tag == "tspan"]
    # No per-line sizes means the old path: one font-size on <text>, none on
    # the spans. Byte-compatibility with every existing render depends on it.
    assert all(span.get("font-size") is None for span in spans)
    assert text.get("font-size") == "46"
