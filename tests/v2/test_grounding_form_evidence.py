from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.app.services.structure.fidelity.form_evidence import (
    reconcile_form_evidence,
)


def test_form_evidence_deduplicates_schedule_and_repairs_status() -> None:
    graph = {
        "elements": [
            {
                "id": 1,
                "type": "button",
                "controlType": "icon-button",
                "controlValue": "0303**?",
                "bbox": [1447, 135, 414, 39],
            },
            {
                "id": 2,
                "type": "input",
                "controlType": "input",
                "controlValue": "0 30 3 * * ?",
                "bbox": [1447, 135, 414, 39],
            },
            {
                "id": 3,
                "type": "text",
                "text": "0303**?",
                "bbox": [1461, 145, 86, 20],
            },
            {
                "id": 4,
                "type": "input",
                "controlType": "icon-button",
                "controlValue": "2026-11-023:30:00",
                "bbox": [1447, 187, 414, 38],
            },
            {
                "id": 5,
                "type": "text",
                "text": "执行成功",
                "bbox": [760, 296, 123, 16],
            },
            {
                "id": 6,
                "type": "text",
                "text": "SUCCESS",
                "bbox": [1236, 296, 123, 16],
            },
            {
                "id": 7,
                "type": "text",
                "text": "自动备份",
                "bbox": [461, 24, 123, 20],
            },
        ]
    }
    ocr = {
        "observations": [
            {
                "text": "执行成功",
                "bbox": [790, 244, 74, 24],
                "confidence": 0.95,
            },
            {
                "text": "SUCCESS",
                "bbox": [1239, 241, 72, 20],
                "confidence": 0.99,
            },
            {
                "text": "自动备份",
                "bbox": [884, 142, 72, 24],
                "confidence": 0.99,
            },
            {
                "text": "执行时间",
                "bbox": [1366, 142, 76, 24],
                "confidence": 0.97,
            },
            {
                "text": "执行者",
                "bbox": [807, 197, 54, 20],
                "confidence": 0.95,
            },
        ]
    }

    reconciled = reconcile_form_evidence(
        graph,
        ocr,
        width=1920,
        height=826,
    )
    by_id = {element["id"]: element for element in reconciled["elements"]}

    assert 1 not in by_id
    assert 3 not in by_id
    assert by_id[2]["controlValue"] == "0 30 3 * * ?"
    assert by_id[4]["controlValue"] == "2026-11-02 3:30:00"
    assert by_id[5]["bbox"] == [790, 244, 74, 24]
    assert by_id[5]["role"] == "form-status"
    assert by_id[6]["bbox"] == [1239, 241, 72, 20]
    assert by_id[6]["role"] == "form-status"
    assert by_id[7]["bbox"] == [461, 24, 123, 20]
    labels = [
        element
        for element in reconciled["elements"]
        if element.get("role") == "form-label"
    ]
    assert {label["text"] for label in labels} == {"执行时间", "执行者"}
    assert {tuple(label["bbox"]) for label in labels} == {
        (1366, 142, 76, 24),
        (807, 197, 54, 20),
    }
    assert reconciled["provenance"]["formEvidenceReconciliation"]["removed_count"] == 2

    replayed = reconcile_form_evidence(
        reconciled,
        ocr,
        width=1920,
        height=826,
    )
    assert (
        len(
            [
                element
                for element in replayed["elements"]
                if element.get("role") == "form-label"
            ]
        )
        == 2
    )


def test_invalid_checkbox_label_is_recovered_from_adjacent_ocr_and_tesseract() -> None:
    image = Path(
        "tests/fixtures/image_to_slice_benchmark_2026-11-02/" "IMG-FLEXWEAVER-ADMIN.png"
    ).resolve()
    graph = {
        "image": str(image),
        "elements": [
            {
                "id": 1,
                "type": "checkbox",
                "controlType": "checkbox",
                "controlValue": "true",
                "controlState": "checked",
                "bbox": [1644, 290, 24, 23],
            },
            {
                "id": 2,
                "type": "text",
                "text": "Wauto用户身份执行",
                "bbox": [1480, 288, 158, 26],
                "source": "ocr-supplement:easyocr",
            },
        ],
    }
    ocr = {
        "observations": [
            {
                "text": "Wauto用户身份执行",
                "bbox": [1480, 288, 158, 26],
                "confidence": 0.95,
            }
        ]
    }

    with patch(
        "src.app.services.structure.fidelity.form_evidence."
        "_recognize_checkbox_label",
        return_value="以auto用户身份执行",
    ):
        reconciled = reconcile_form_evidence(
            graph,
            ocr,
            width=1920,
            height=826,
        )

    by_id = {element["id"]: element for element in reconciled["elements"]}
    assert by_id[1]["controlValue"] == "以auto用户身份执行"
    assert by_id[1]["label"] == "以auto用户身份执行"
    assert by_id[2]["text"] == "以auto用户身份执行"
    assert by_id[2]["role"] == "control-label"
