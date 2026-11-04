from __future__ import annotations

import copy

from src.app.services.structure.fidelity.repair import (
    apply_repair_patch,
    plan_repair_requests,
    run_bounded_repair_loop,
)


def _scene_plan() -> dict:
    return {
        "schema_version": "grounding-scene-plan/1.0",
        "image_size": [1920, 826],
        "coordinate_basis": "source-pixel-top-left",
        "nodes": [
            {
                "id": "main:main",
                "parent_id": None,
                "type": "container",
                "role": "main",
                "bbox": [300, 56, 1620, 770],
                "content_ref": None,
                "geometry_ref": "geometry:main",
                "children": ["form:settings", "table-node:0"],
            },
            {
                "id": "form:settings",
                "parent_id": "main:main",
                "type": "container",
                "role": "form",
                "bbox": [340, 120, 1540, 360],
                "content_ref": None,
                "geometry_ref": "geometry:form",
                "children": ["control:29", "text:checkbox-label"],
            },
            {
                "id": "table-node:0",
                "parent_id": "main:main",
                "type": "table",
                "role": "table",
                "bbox": [300, 550, 1600, 276],
                "content_ref": "0",
                "geometry_ref": "geometry:table",
                "children": [],
            },
            {
                "id": "control:29",
                "parent_id": "form:settings",
                "type": "control",
                "role": "checkbox",
                "bbox": [380, 220, 16, 16],
                "content_ref": "control:29",
                "geometry_ref": "geometry:control",
                "children": [],
                "state": "unchecked",
                "text_owner_ref": "text:checkbox-label",
            },
            {
                "id": "text:checkbox-label",
                "parent_id": "form:settings",
                "type": "text",
                "role": "control-label",
                "bbox": [404, 216, 180, 24],
                "content_ref": "text:checkbox-label",
                "geometry_ref": "geometry:label",
                "children": [],
                "text": "以auto用户身份执行",
            },
        ],
        "suppressed": [],
    }


def _report_with_missing_table() -> dict:
    return {
        "status": "fail",
        "blockers": [
            {
                "id": "table-missing",
                "kind": "table",
                "bbox": [300, 550, 1600, 276],
                "target_ids": ["table-node:0"],
                "reason": "missing or incomplete table",
            }
        ],
    }


def _patch_that_removes_native_text() -> dict:
    return {
        "region_id": "form.settings",
        "target_ids": ["text:checkbox-label"],
        "reason": "invalid removal",
        "operations": [
            {"op": "remove_node", "id": "text:checkbox-label"},
        ],
    }


def _always_failing_verify(_plan):
    return {
        "status": "fail",
        "blockers": [
            {
                "id": "control-state",
                "kind": "control",
                "target_ids": ["control:29"],
                "reason": "state remains wrong",
            }
        ],
    }


def _always_returning_patch(_request, _plan):
    return {
        "region_id": "form.settings",
        "target_ids": ["control:29"],
        "reason": "set state",
        "operations": [
            {"op": "set_state", "id": "control:29", "state": "checked"},
        ],
    }


def test_missing_table_emits_one_local_repair_request() -> None:
    requests = plan_repair_requests(
        _report_with_missing_table(),
        _scene_plan(),
        max_requests=3,
    )

    assert len(requests) == 1
    assert requests[0]["kind"] == "table"
    assert requests[0]["bbox"] == [300, 550, 1600, 276]
    assert requests[0]["target_ids"] == ["table-node:0"]
    assert requests[0]["reason"] == "missing or incomplete table"
    assert requests[0]["acceptance"]["must_resolve"] is True


def test_control_blocker_uses_control_and_label_bbox() -> None:
    report = {
        "status": "fail",
        "blockers": [
            {
                "kind": "control",
                "target_ids": ["control:29"],
                "reason": "wrong state",
            }
        ],
    }
    request = plan_repair_requests(report, _scene_plan(), max_requests=1)[0]

    assert request["bbox"] == [380, 216, 204, 24]
    assert request["target_ids"] == ["control:29", "text:checkbox-label"]


def test_invalid_patch_rolls_back() -> None:
    original = _scene_plan()
    result = apply_repair_patch(original, _patch_that_removes_native_text())

    assert result["accepted"] is False
    assert result["plan"] == original
    assert any("remove covered content" in item for item in result["errors"])


def test_patch_rejects_full_screenshot_underlay() -> None:
    original = _scene_plan()
    patch = {
        "region_id": "page",
        "operations": [
            {
                "op": "add_node",
                "node": {
                    "id": "underlay",
                    "parent_id": "main:main",
                    "type": "image",
                    "role": "background",
                    "bbox": [0, 0, 1920, 826],
                    "content_ref": "asset:underlay",
                    "geometry_ref": "geometry:underlay",
                    "children": [],
                },
            }
        ],
    }
    result = apply_repair_patch(original, patch)

    assert result["accepted"] is False
    assert result["plan"] == original
    assert any("underlay" in item for item in result["errors"])


def test_patch_rejects_duplicate_content_owner() -> None:
    original = _scene_plan()
    patch = {
        "region_id": "form.settings",
        "operations": [
            {
                "op": "add_node",
                "node": copy.deepcopy(original["nodes"][4]),
            }
        ],
    }
    patch["operations"][0]["node"]["id"] = "text:duplicate"
    result = apply_repair_patch(original, patch)

    assert result["accepted"] is False
    assert result["plan"] == original
    assert any("duplicate content owner" in item for item in result["errors"])


def test_valid_patch_is_atomic_and_annotated() -> None:
    original = _scene_plan()
    patch = {
        "region_id": "form.settings",
        "target_ids": ["control:29"],
        "reason": "repair state",
        "operations": [
            {"op": "set_state", "id": "control:29", "state": "checked"},
            {
                "op": "update_bbox",
                "id": "text:checkbox-label",
                "bbox": [404, 214, 184, 26],
            },
        ],
    }
    result = apply_repair_patch(original, patch)

    assert result["accepted"] is True
    assert result["plan"]["nodes"][3]["state"] == "checked"
    assert result["plan"]["nodes"][4]["bbox"] == [404, 214, 184, 26]
    assert result["plan"]["repairRevision"] == 1
    assert original["nodes"][3]["state"] == "unchecked"


def test_repair_loop_stops_at_call_budget() -> None:
    result = run_bounded_repair_loop(
        _scene_plan(),
        verify=_always_failing_verify,
        repair=_always_returning_patch,
        max_rounds=3,
        max_extra_calls=2,
    )

    assert result["extra_calls"] == 2
    assert result["rounds"] == 2
    assert result["status"] == "budget-exhausted"
    assert len(result["history"]) == 2


def test_repair_loop_returns_immediately_on_pass() -> None:
    calls = 0

    def verify(_plan):
        return {"status": "pass", "blockers": []}

    def repair(_request, _plan):
        nonlocal calls
        calls += 1
        return _always_returning_patch(_request, _plan)

    result = run_bounded_repair_loop(
        _scene_plan(),
        verify=verify,
        repair=repair,
    )

    assert result["status"] == "pass"
    assert result["extra_calls"] == 0
    assert calls == 0


def test_regressed_patch_rolls_back_to_last_verified_plan() -> None:
    calls = 0

    def verify(plan):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _always_failing_verify(plan)
        return {
            "status": "blocked",
            "regressed": True,
            "blockers": ["region-visual:form"],
        }

    original = _scene_plan()
    result = run_bounded_repair_loop(
        original,
        verify=verify,
        repair=_always_returning_patch,
        max_rounds=3,
        max_extra_calls=6,
    )

    assert result["status"] == "rolled-back"
    assert result["plan"] == original
    assert result["extra_calls"] == 1
    assert result["history"][0]["rolled_back"] is True


def test_repair_loop_no_patch_stops_without_changing_plan() -> None:
    original = _scene_plan()
    result = run_bounded_repair_loop(
        original,
        verify=_always_failing_verify,
        repair=lambda _request, _plan: None,
    )

    assert result["status"] == "no-patch"
    assert result["plan"] == original
    assert result["extra_calls"] == 1
