from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.app.services.structure.image_contract import (
    attach_chrome_icon_evidence,
)


def _graph() -> dict:
    return {
        "image_w": 1920,
        "image_h": 826,
        "containers": [
            {
                "id": "sidebar",
                "role": "sidebar",
                "bbox": [0, 0, 276, 826],
            },
            {
                "id": "header",
                "role": "header",
                "bbox": [276, 0, 1644, 64],
            },
            {
                "id": "main",
                "role": "main-content",
                "bbox": [276, 64, 1644, 762],
            },
            {
                "id": "table-search",
                "role": "table-search",
                "bbox": [1715, 501, 176, 38],
            },
        ],
        "elements": [
            {
                "id": 1,
                "type": "text",
                "bbox": [323, 24, 153, 20],
                "text": "FlexWeaver",
            },
            {
                "id": 2,
                "type": "text",
                "bbox": [461, 24, 123, 20],
                "text": "自动备份",
            },
            {
                "id": 3,
                "type": "text",
                "bbox": [46, 208, 92, 24],
                "text": "首页",
            },
            {
                "id": 4,
                "type": "text",
                "bbox": [1751, 24, 123, 20],
                "text": "刘治强",
            },
            {
                "id": 5,
                "type": "input",
                "controlType": "input",
                "controlValue": "0 30 3 * * ?",
                "bbox": [1447, 135, 414, 39],
            },
        ],
        "imageEnrichment": {
            "mode": "apply",
            "status": "applied",
            "assets": [],
        },
    }


def test_chrome_icon_evidence_is_attached_before_scene_planning(
    tmp_path: Path,
) -> None:
    path = tmp_path / "chrome.png"
    image = Image.new("RGB", (1920, 826), "#313c49")
    image.save(path)

    graph = attach_chrome_icon_evidence(
        _graph(),
        str(path),
        width=1920,
        height=826,
    )

    assets = graph["imageEnrichment"]["assets"]
    by_name = {asset["name"]: asset for asset in assets}
    assert by_name["chrome_search"]["bbox"] == [1553, 23, 22, 22]
    assert by_name["chrome_mail"]["bbox"] == [1599, 23, 22, 22]
    assert by_name["chrome_list"]["bbox"] == [1658, 26, 22, 18]
    assert by_name["chrome_home"]["bbox"] == [20, 208, 22, 22]
    assert by_name["chrome_brand"]["bbox"] == [307, 22, 169, 24]
    assert by_name["chrome_user_label"]["bbox"] == [1748, 21, 62, 26]
    assert by_name["chrome_table_search"]["bbox"] == [1865, 510, 18, 18]
    assert by_name["chrome_calendar"]["bbox"] == [1818, 135, 34, 39]
    assert by_name["chrome_brand"]["kind"] == "logo"
    assert by_name["chrome_user_label"]["kind"] == "identity"
    assert all(asset["kind"] in {"icon", "logo", "identity"} for asset in assets)
    assert all(asset["referenceOnly"] is True for asset in assets)
    assert all(asset["original"] is False for asset in assets)
    schedule = next(element for element in graph["elements"] if element.get("id") == 5)
    assert schedule["bbox"] == [1447, 135, 371, 39]
    graph = attach_chrome_icon_evidence(
        graph,
        str(path),
        width=1920,
        height=826,
    )
    schedule = next(element for element in graph["elements"] if element.get("id") == 5)
    calendar_assets = [
        asset
        for asset in graph["imageEnrichment"]["assets"]
        if asset.get("name") == "chrome_calendar"
    ]
    assert schedule["bbox"] == [1447, 135, 371, 39]
    assert len(calendar_assets) == 1
    assert calendar_assets[0]["bbox"] == [1818, 135, 34, 39]


def test_table_search_control_uses_detected_reference_border() -> None:
    path = Path(
        "tests/fixtures/image_to_slice_benchmark_2026-11-02/" "IMG-FLEXWEAVER-ADMIN.png"
    ).resolve()
    graph = _graph()
    graph["elements"].append(
        {
            "id": 6,
            "type": "input",
            "controlType": "input",
            "controlValue": "表内搜索",
            "bbox": [1715, 501, 176, 38],
        }
    )

    attached = attach_chrome_icon_evidence(
        graph,
        str(path),
        width=1920,
        height=826,
    )
    table_search = next(
        element for element in attached["elements"] if element.get("id") == 6
    )

    assert table_search["bbox"] == [1716, 502, 174, 36]


def test_toolbar_buttons_use_detected_reference_boundaries() -> None:
    path = Path(
        "tests/fixtures/image_to_slice_benchmark_2026-11-02/" "IMG-FLEXWEAVER-ADMIN.png"
    ).resolve()
    graph = _graph()
    graph["elements"].extend(
        [
            {
                "id": 7,
                "type": "link",
                "controlType": "link",
                "controlValue": "暂停自动刷新",
                "bbox": [305, 501, 133, 38],
            },
            {
                "id": 8,
                "type": "button",
                "controlType": "button",
                "controlValue": "刷新",
                "bbox": [572, 501, 66, 37],
            },
        ]
    )

    attached = attach_chrome_icon_evidence(
        graph,
        str(path),
        width=1920,
        height=826,
    )
    by_id = {
        element["id"]: element
        for element in attached["elements"]
        if isinstance(element.get("id"), int)
    }

    assert by_id[7]["bbox"] == [306, 502, 131, 36]
    assert by_id[7]["geometryEvidence"]["source"] == "source-pixel-grayscale-border"
    assert by_id[8]["bbox"] == [573, 502, 65, 36]
    assert by_id[8]["geometryEvidence"]["source"] == "source-pixel-color-surface"
