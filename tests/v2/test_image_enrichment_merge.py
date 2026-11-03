from __future__ import annotations

from src.app.services.structure.image_enrichment.merge import (
    merge_tiled_graphs,
)


def _graph(
    tile_id: str,
    source_y: int,
    *,
    containers: list[dict] | None = None,
    elements: list[dict] | None = None,
    height: int = 100,
) -> dict:
    return {
        "image": "page.png",
        "image_w": 200,
        "image_h": 400,
        "route": "grounding",
        "containers": containers or [],
        "elements": elements or [],
        "provenance": {
            "route": "grounding",
            "fallbacks": [],
            "warnings": [],
            "tiling": {
                "tile": {
                    "id": tile_id,
                    "source_rect": [0, source_y, 200, height],
                    "page_origin": [0, source_y],
                    "reason": "configured-height",
                }
            },
        },
    }


def _element(
    bbox: list[int],
    *,
    type_: str = "text",
    text: str = "",
) -> dict:
    return {
        "bbox": bbox,
        "type": type_,
        "text": text,
        "role": "",
        "container": None,
        "confidence": 1.0,
        "source": "grounding",
    }


def _container(bbox: list[int], role: str) -> dict:
    return {
        "bbox": bbox,
        "role": role,
        "source": "grounding",
        "confidence": 1.0,
    }


def test_merge_deduplicates_tiles_but_keeps_repeated_sidebar_text():
    graphs = [
        _graph(
            "tile-0000",
            0,
            containers=[_container([0, 0, 200, 24], "banner")],
            elements=[
                _element([8, 6, 40, 12], text="Home"),
                _element([10, 30, 50, 12], text="Settings"),
                _element([10, 45, 30, 20], type_="button"),
                _element([40, 60, 40, 12], text="Hello"),
            ],
        ),
        _graph(
            "tile-0001",
            100,
            containers=[_container([0, 0, 200, 24], "banner")],
            elements=[
                _element([8, 6, 40, 12], text="Home"),
                _element([10, 130, 50, 12], text="Settings"),
                _element([81, 60, 40, 12], text="World"),
            ],
        ),
        _graph(
            "tile-0002",
            200,
            elements=[
                _element([10, 230, 50, 12], text="Settings"),
                _element([12, 46, 30, 20], type_="button"),
            ],
        ),
    ]

    merged, report = merge_tiled_graphs(graphs, 200, 400)

    assert len(merged["containers"]) == 1
    assert [element["text"] for element in merged["elements"]] == [
        "Home",
        "Settings",
        "",
        "Hello World",
        "Settings",
        "Settings",
    ]
    assert [item["bbox"][1] for item in merged["elements"]] == [
        6,
        30,
        45,
        60,
        130,
        230,
    ]
    diagnostics = report["diagnostics"]
    assert {item["code"] for item in diagnostics} >= {
        "duplicate_container",
        "duplicate_text",
        "duplicate_visual",
        "adjacent_text_merged",
    }
    assert report["repeated_text_fingerprints"] == [
        {
            "text": "Settings",
            "count": 3,
            "tile_ids": ["tile-0000", "tile-0001", "tile-0002"],
        }
    ]
    assert merged["provenance"]["tiling"] == report


def test_merge_reports_ambiguous_duplicates_without_dropping_them():
    graphs = [
        _graph(
            "tile-0000",
            0,
            elements=[_element([10, 10, 30, 12], text="Submit")],
        ),
        _graph(
            "tile-0001",
            100,
            elements=[_element([20, 10, 30, 12], text="Submit")],
        ),
    ]

    merged, report = merge_tiled_graphs(graphs, 200, 400)

    assert [element["text"] for element in merged["elements"]] == [
        "Submit",
        "Submit",
    ]
    assert report["ambiguous_count"] == 1
    ambiguous = [
        item
        for item in report["diagnostics"]
        if item["code"] == "ambiguous_text_duplicate"
    ]
    assert len(ambiguous) == 1
    assert ambiguous[0]["action"] == "kept"
    assert ambiguous[0]["tile_ids"] == ["tile-0000", "tile-0001"]


def test_merge_keeps_adjacent_text_cells_from_the_same_tile():
    graphs = [
        _graph(
            "tile-0000",
            0,
            elements=[
                _element([20, 10, 40, 12], text="Started"),
                _element([62, 10, 40, 12], text="Status"),
            ],
        )
    ]

    merged, report = merge_tiled_graphs(graphs, 200, 400)

    assert [element["text"] for element in merged["elements"]] == [
        "Started",
        "Status",
    ]
    assert not any(
        item["code"] == "adjacent_text_merged"
        for item in report["diagnostics"]
    )


def test_merge_reading_order_is_deterministic_across_input_order():
    graphs = [
        _graph(
            "tile-0001",
            100,
            elements=[_element([10, 120, 30, 12], text="Later")],
        ),
        _graph(
            "tile-0000",
            0,
            elements=[_element([10, 20, 30, 12], text="Earlier")],
        ),
    ]

    forward, forward_report = merge_tiled_graphs(graphs, 200, 400)
    reverse, reverse_report = merge_tiled_graphs(list(reversed(graphs)), 200, 400)

    assert forward["containers"] == reverse["containers"]
    assert forward["elements"] == reverse["elements"]
    assert forward_report == reverse_report
    assert [item["text"] for item in forward["elements"]] == [
        "Earlier",
        "Later",
    ]
    assert [item["id"] for item in forward["elements"]] == [1, 2]
