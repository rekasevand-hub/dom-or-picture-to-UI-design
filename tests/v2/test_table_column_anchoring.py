"""Column anchoring (Phase 2, x axis): grounded evidence picks the boundary set.

``_anchor_table_columns`` re-anchors table column boundaries to grounded text
evidence.  These tests mirror the light-table failure shape: line detection
returns the true rules plus chrome lines, and the gap-variance window keeps
the wrong subset.  Grounded headers/cells must pick the subsequence whose
column intervals contain the most column anchors, and stand down when the
detected window already agrees with the evidence.
"""

from __future__ import annotations

from src.app.services.structure.fidelity.inventory import (
    _anchor_table_columns,
)


def _table(
    headers: list[str],
    rows: list[list[str]],
    bbox: list[int] | None = None,
) -> dict:
    return {
        "id": "table:0",
        "bbox": bbox or [100, 400, 800, 300],
        "headers": headers,
        "rows": rows,
        "column_count": len(headers),
        "row_count": len(rows),
        "source_ref": "graph.tables[0]",
    }


def _item(
    item_id: str,
    text: str,
    bbox: list[int],
    kind: str = "text",
) -> dict:
    return {"id": item_id, "kind": kind, "text": text, "bbox": bbox}


Y_SPAN = (400, 700)


def test_selects_evidence_subsequence_over_variance_window() -> None:
    # 4 columns; true rules [100, 300, 500, 700, 900].  Detection adds a
    # chrome line at 560 (inside column 1's text) and an outer line at 40;
    # the true right edge 900 exists but the variance window (most regular
    # gaps) prefers 560 and drops 900.
    headers = ["H0", "H1", "H2", "H3"]
    items = [
        _item("t0", "H0", [115, 450, 60, 20]),
        _item("t1", "H1", [315, 450, 60, 20]),
        _item("t2", "H2", [515, 450, 60, 20]),
        _item("t3", "H3", [715, 450, 60, 20]),
    ]
    candidates = [40, 100, 300, 500, 560, 700, 900]

    boundaries, evidence = _anchor_table_columns(
        _table(headers, []), items, 4, candidates, Y_SPAN
    )

    assert boundaries == [100, 300, 500, 700, 900]
    assert evidence["source"] == "grounded-text-columns"
    assert evidence["contained"] == 4
    assert evidence["variance_contained"] < 4


def test_stands_down_when_variance_window_agrees() -> None:
    # Exactly the needed candidates: single possible subsequence, the
    # variance window already contains every anchor -> no override.
    headers = ["H0", "H1", "H2"]
    items = [
        _item("t0", "H0", [115, 450, 60, 20]),
        _item("t1", "H1", [315, 450, 60, 20]),
        _item("t2", "H2", [515, 450, 60, 20]),
    ]
    candidates = [100, 300, 500, 700]

    boundaries, evidence = _anchor_table_columns(
        _table(headers, []), items, 3, candidates, Y_SPAN
    )

    assert boundaries is None
    assert evidence["source"] == "grounded-text-columns-consistent-detected"
    assert evidence["contained"] == 3


def test_requires_two_anchors() -> None:
    headers = ["H0", "H1", "H2"]
    items = [_item("t0", "H0", [115, 450, 60, 20])]
    candidates = [100, 300, 500, 700, 900]

    boundaries, evidence = _anchor_table_columns(
        _table(headers, []), items, 3, candidates, Y_SPAN
    )

    assert boundaries is None
    assert evidence == {}


def test_no_candidates_returns_none_with_evidence() -> None:
    headers = ["H0", "H1"]
    items = [
        _item("t0", "H0", [115, 450, 60, 20]),
        _item("t1", "H1", [315, 450, 60, 20]),
    ]

    boundaries, evidence = _anchor_table_columns(
        _table(headers, []), items, 2, [], Y_SPAN
    )

    assert boundaries is None
    assert evidence["status"] == "insufficient-candidates"
    assert evidence["anchored_column_count"] == 2


def test_ignores_instances_outside_table_rows() -> None:
    # The same header text grounds once in page chrome far above the table
    # (y=40) and once in the table; the chrome instance must not anchor.
    # The variance window here already contains both surviving anchors, so
    # the anchor stands down — the exclusion is visible in the evidence.
    headers = ["H0", "H1"]
    items = [
        _item("chrome", "H0", [999, 40, 60, 20]),
        _item("t0", "H0", [115, 450, 60, 20]),
        _item("t1", "H1", [315, 450, 60, 20]),
    ]
    candidates = [40, 100, 300, 500, 700]

    boundaries, evidence = _anchor_table_columns(
        _table(headers, []), items, 2, candidates, Y_SPAN
    )

    assert boundaries is None
    assert evidence["source"] == "grounded-text-columns-consistent-detected"
    assert evidence["column_anchors"] == {"0": 115, "1": 315}


def test_prefers_tightest_instance_for_unique_text() -> None:
    # A unique header grounds twice: a padded box (w=300) that drags into
    # the neighbouring column and a tight box (w=60).  The tight box wins.
    headers = ["H0", "H1"]
    items = [
        _item("wide", "H0", [115, 450, 300, 20]),
        _item("tight", "H0", [118, 450, 60, 20]),
        _item("t1", "H1", [315, 450, 60, 20]),
    ]
    candidates = [40, 100, 300, 500, 700]

    _boundaries, evidence = _anchor_table_columns(
        _table(headers, []), items, 2, candidates, Y_SPAN
    )

    assert evidence["column_anchors"]["0"] == 118


def test_drops_out_of_order_anchors() -> None:
    # Column 1's grounded box is misplaced into column 0's territory; the
    # monotonic rejection drops it and column 0's anchor survives.
    headers = ["H0", "H1", "H2"]
    items = [
        _item("t0", "H0", [115, 450, 60, 20]),
        _item("t1", "H1", [90, 450, 60, 20]),  # before H0: rejected
        _item("t2", "H2", [515, 450, 60, 20]),
    ]
    candidates = [40, 100, 300, 500, 700, 900]

    _boundaries, evidence = _anchor_table_columns(
        _table(headers, []), items, 3, candidates, Y_SPAN
    )

    assert evidence["column_anchors"] == {"0": 115, "2": 515}


def test_ambiguous_cell_values_join_anchored_column() -> None:
    # Headers H0/H1 are unique and anchor both columns; the repeated cell
    # value "x" (occurs twice -> ambiguous) joins the anchored column when
    # its left edge is close.  A single absorbed instance does not move the
    # median anchor, but it is recorded as matched evidence.
    headers = ["H0", "H1"]
    rows = [["x", "y"], ["x", "y"]]
    items = [
        _item("t0", "H0", [115, 450, 60, 20]),
        _item("t1", "H1", [315, 450, 60, 20]),
        _item("c0", "x", [105, 500, 40, 20]),
    ]
    candidates = [40, 100, 300, 500, 700]

    _boundaries, evidence = _anchor_table_columns(
        _table(headers, rows), items, 2, candidates, Y_SPAN
    )

    assert evidence["column_anchors"]["0"] == 115
    assert "c0" in evidence["matched_item_ids"]


def test_inset_consistency_breaks_containment_ties() -> None:
    # True rules [100, 300, 500, 700]; detection adds an outer line at 40
    # and a chrome line at 460 inside column 1.  The gap-variance window
    # picks [40, 100, 300, 460] (contains no anchor); several subsequences
    # contain all three anchors — the inset consistency must prefer the
    # true rules over the shifted variant that keeps 40.
    headers = ["H0", "H1", "H2"]
    items = [
        _item("t0", "H0", [115, 450, 60, 20]),
        _item("t1", "H1", [315, 450, 60, 20]),
        _item("t2", "H2", [515, 450, 60, 20]),
    ]
    candidates = [40, 100, 300, 460, 500, 700]

    boundaries, evidence = _anchor_table_columns(
        _table(headers, []), items, 3, candidates, Y_SPAN
    )

    assert boundaries == [100, 300, 500, 700]
    assert evidence["contained"] == 3
    assert evidence["variance_contained"] == 0


def test_cell_anchors_without_headers() -> None:
    # Table without headers: unique cell values anchor their columns.  The
    # variance window [100, 300, 500] misses the beta cell at 515 (its
    # column rule is 500); the cell anchors override with the rules that
    # give both columns a consistent 15px text inset.
    headers: list[str] = []
    rows = [["alpha", "beta"], ["gamma", "delta"]]
    items = [
        _item("c0", "alpha", [115, 500, 60, 20]),
        _item("c1", "beta", [515, 500, 60, 20]),
        _item("c2", "gamma", [115, 550, 60, 20]),
        _item("c3", "delta", [515, 550, 60, 20]),
    ]
    candidates = [40, 100, 300, 500, 700]

    boundaries, evidence = _anchor_table_columns(
        _table(headers, rows), items, 2, candidates, Y_SPAN
    )

    assert boundaries == [100, 500, 700]
    assert evidence["contained"] == 2
    assert evidence["column_anchors"] == {"0": 115, "1": 515}
