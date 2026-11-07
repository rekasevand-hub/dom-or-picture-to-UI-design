from __future__ import annotations

from src.app.services.structure.fidelity.regions import (
    reconcile_region_containers,
)


def test_toolbar_region_containers_follow_real_controls() -> None:
    graph = {
        "containers": [
            {
                "id": "table-section",
                "role": "table-section",
                "bbox": [20, 90, 360, 130],
            },
            {
                "id": "toolbar",
                "role": "table-header-controls",
                "bbox": [20, 150, 180, 20],
            },
            {
                "id": "search",
                "role": "table-search",
                "bbox": [300, 150, 80, 20],
            },
        ],
        "tables": [{"bbox": [20, 110, 360, 110]}],
        "elements": [
            {
                "id": 1,
                "type": "button",
                "controlType": "button",
                "controlValue": "Pause",
                "bbox": [22, 70, 60, 30],
            },
            {
                "id": 2,
                "type": "button",
                "controlType": "button",
                "controlValue": "Refresh",
                "bbox": [90, 70, 60, 30],
            },
            {
                "id": 3,
                "type": "input",
                "controlType": "input",
                "controlValue": "Search",
                "bbox": [300, 70, 78, 30],
            },
        ],
    }

    reconciled = reconcile_region_containers(graph, width=400, height=240)
    by_role = {container["role"]: container for container in reconciled["containers"]}

    assert by_role["table-header-controls"]["bbox"] == [22, 70, 128, 30]
    assert by_role["table-search"]["bbox"] == [300, 70, 78, 30]


def test_misnamed_toolbar_regions_are_rebound_to_visible_controls() -> None:
    graph = {
        "containers": [
            {
                "id": "table-section",
                "role": "table-section",
                "bbox": [20, 90, 360, 130],
            },
            {
                "id": "toolbar",
                "role": "toolbar",
                "bbox": [20, 150, 180, 20],
            },
            {
                "id": "header",
                "role": "table-header",
                "bbox": [20, 150, 360, 20],
            },
        ],
        "tables": [{"bbox": [20, 110, 360, 110]}],
        "elements": [
            {
                "id": 1,
                "type": "button",
                "controlType": "button",
                "controlValue": "Pause",
                "bbox": [22, 70, 60, 30],
            },
            {
                "id": 2,
                "type": "button",
                "controlType": "button",
                "controlValue": "Refresh",
                "bbox": [90, 70, 60, 30],
            },
            {
                "id": 3,
                "type": "input",
                "controlType": "input",
                "controlValue": "Search",
                "bbox": [300, 70, 78, 30],
            },
        ],
    }

    reconciled = reconcile_region_containers(graph, width=400, height=240)
    by_role = {container["role"]: container for container in reconciled["containers"]}

    assert by_role["table-header-controls"]["id"] == "toolbar"
    assert by_role["table-header-controls"]["bbox"] == [22, 70, 128, 30]
    assert by_role["table-search"]["id"] == "header"
    assert by_role["table-search"]["bbox"] == [300, 70, 78, 30]
