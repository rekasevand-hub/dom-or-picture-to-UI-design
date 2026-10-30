from __future__ import annotations

import json

from src.app.services.rendering.figma_adapter import (
    FigmaBridgeAdapter,
    persist_semantic_componentization_result,
)
from src.config.settings import Config


class _RecordingAdapter(FigmaBridgeAdapter):
    def __init__(self, response=None) -> None:
        self.calls = []
        self.response = response or {
            "status": "committed",
            "masters": [],
            "instances": [],
            "rejected": [],
            "geometry_checks": [],
        }
        self.client_id = "adapter-client"
        self.allow_legacy_job_ids = False

    def _send(self, action, params, *, request_id=None):
        self.calls.append((action, params))
        return dict(self.response)


class _AutoComponentAdapter(FigmaBridgeAdapter):
    def __init__(self) -> None:
        self.calls = []
        self._next_id = 1
        self.disconnected = False
        self._semantic_rendered = {}
        self._semantic_componentization_attempted = False
        self.semantic_componentization_result = None
        self.client_id = "adapter-client"
        self.allow_legacy_job_ids = False

    def _send(self, action, params, *, request_id=None):
        self.calls.append((action, params))
        if action.startswith("create_"):
            node_id = f"node:{self._next_id}"
            self._next_id += 1
            return node_id
        if action == "componentize_semantic_groups":
            return {
                "status": "committed",
                "masters": [{"nodeId": "component:1"}],
                "instances": [{"nodeId": "instance:2"}],
                "rejected": [],
                "geometry_checks": [{"matched": True}],
            }
        return {}

    def disconnect(self) -> None:
        self.disconnected = True


def _group(group_id: str, signature: str, members: list[dict]) -> dict:
    return {
        "groupId": group_id,
        "role": "button" if group_id.startswith("button") else "card",
        "structuralSignature": signature,
        "members": members,
    }


def test_two_identical_buttons_create_one_master_and_one_instance(monkeypatch) -> None:
    monkeypatch.setenv("DOM_SEMANTIC_COMPONENT_INSTANCES", "true")
    adapter = _RecordingAdapter(
        {
            "status": "committed",
            "masters": [{"groupId": "button-set-0", "nodeId": "component:1"}],
            "instances": [
                {
                    "groupId": "button-set-0",
                    "nodeId": "instance:2",
                    "sourceNodeId": "button:2",
                }
            ],
            "rejected": [],
            "geometry_checks": [],
        }
    )

    result = adapter.componentize_semantic_groups(
        [
            _group(
                "button-set-0",
                "visual:0|text:1|interactive:0",
                [
                    {"nodeId": "button:1", "sourceDomIndices": [4]},
                    {"nodeId": "button:2", "sourceDomIndices": [5]},
                ],
            )
        ]
    )

    assert result["status"] == "committed"
    assert len(result["masters"]) == 1
    assert len(result["instances"]) == 1
    assert adapter.calls[0][0] == "componentize_semantic_groups"


def test_three_identical_cards_create_one_master_and_two_instances(monkeypatch) -> None:
    monkeypatch.setenv("DOM_SEMANTIC_COMPONENT_INSTANCES", "true")
    adapter = _RecordingAdapter(
        {
            "status": "committed",
            "masters": [{"groupId": "card-set-0", "nodeId": "component:1"}],
            "instances": [
                {"nodeId": "instance:2", "sourceNodeId": "card:2"},
                {"nodeId": "instance:3", "sourceNodeId": "card:3"},
            ],
            "rejected": [],
            "geometry_checks": [],
        }
    )

    result = adapter.componentize_semantic_groups(
        [
            _group(
                "card-set-0",
                "visual:1|text:2|interactive:1",
                [
                    {"nodeId": "card:1", "sourceDomIndices": [10]},
                    {"nodeId": "card:2", "sourceDomIndices": [12]},
                    {"nodeId": "card:3", "sourceDomIndices": [14]},
                ],
            )
        ]
    )

    assert len(result["masters"]) == 1
    assert len(result["instances"]) == 2


def test_mismatched_member_signatures_are_rejected_without_bridge_write(monkeypatch) -> None:
    monkeypatch.setenv("DOM_SEMANTIC_COMPONENT_INSTANCES", "true")
    adapter = _RecordingAdapter()

    result = adapter.componentize_semantic_groups(
        [
            _group(
                "card-set-0",
                "visual:1|text:2|interactive:1",
                [
                    {
                        "nodeId": "card:1",
                        "structuralSignature": "visual:1|text:2|interactive:1",
                    },
                    {
                        "nodeId": "card:2",
                        "structuralSignature": "visual:0|text:3|interactive:1",
                    },
                ],
            )
        ]
    )

    assert result["status"] == "rejected"
    assert result["rejected"][0]["code"] == "STRUCTURAL_SIGNATURE_MISMATCH"
    assert adapter.calls == []


def test_missing_node_id_returns_typed_rejection_without_bridge_write(monkeypatch) -> None:
    monkeypatch.setenv("DOM_SEMANTIC_COMPONENT_INSTANCES", "true")
    adapter = _RecordingAdapter()

    result = adapter.componentize_semantic_groups(
        [
            _group(
                "button-set-0",
                "visual:0|text:1|interactive:0",
                [
                    {"nodeId": "button:1"},
                    {"sourceDomIndices": [5]},
                ],
            )
        ]
    )

    assert result["status"] == "rejected"
    assert result["rejected"][0]["code"] == "NODE_ID_REQUIRED"
    assert adapter.calls == []


def test_component_instances_are_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("DOM_SEMANTIC_COMPONENT_INSTANCES", raising=False)
    assert Config().dom_semantic_component_instances is True

    monkeypatch.setenv("DOM_SEMANTIC_COMPONENT_INSTANCES", "false")
    assert Config().dom_semantic_component_instances is False


def test_disabled_feature_does_not_send_componentization(monkeypatch) -> None:
    monkeypatch.setenv("DOM_SEMANTIC_COMPONENT_INSTANCES", "false")
    adapter = _RecordingAdapter()

    result = adapter.componentize_semantic_groups([])

    assert result["status"] == "disabled"
    assert adapter.calls == []


def test_flush_automatically_componentizes_complete_semantic_group(monkeypatch) -> None:
    monkeypatch.delenv("DOM_SEMANTIC_COMPONENT_INSTANCES", raising=False)
    adapter = _AutoComponentAdapter()

    adapter.create_frame(
        {
            "name": "Save",
            "x": 0,
            "y": 0,
            "width": 100,
            "height": 40,
            "semanticRole": "button",
            "semanticGroupId": "button-set-0",
            "semanticStructuralSignature": "visual:0|text:1|interactive:0",
            "semanticMemberCount": 2,
            "semanticSourceDomIndices": [4],
        }
    )
    adapter.create_frame(
        {
            "name": "Cancel",
            "x": 124,
            "y": 0,
            "width": 100,
            "height": 40,
            "semanticRole": "button",
            "semanticGroupId": "button-set-0",
            "semanticStructuralSignature": "visual:0|text:1|interactive:0",
            "semanticMemberCount": 2,
            "semanticSourceDomIndices": [5],
        }
    )

    adapter.flush()

    component_calls = [
        params
        for action, params in adapter.calls
        if action == "componentize_semantic_groups"
    ]
    assert len(component_calls) == 1
    group = component_calls[0]["groups"][0]
    assert group["groupId"] == "button-set-0"
    assert [member["sourceDomIndices"] for member in group["members"]] == [[4], [5]]
    assert adapter.disconnected is True


def test_flush_skips_auto_componentization_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("DOM_SEMANTIC_COMPONENT_INSTANCES", "false")
    adapter = _AutoComponentAdapter()
    adapter.create_rectangle(
        {
            "name": "Save",
            "x": 0,
            "y": 0,
            "width": 100,
            "height": 40,
            "semanticRole": "button",
            "semanticGroupId": "button-set-0",
            "semanticStructuralSignature": "visual:0|text:1|interactive:0",
            "semanticMemberCount": 2,
            "semanticSourceDomIndices": [4],
        }
    )

    adapter.flush()

    assert not any(
        action == "componentize_semantic_groups"
        for action, _params in adapter.calls
    )


def test_flush_skips_unsupported_rectangle_component_group(monkeypatch) -> None:
    monkeypatch.delenv("DOM_SEMANTIC_COMPONENT_INSTANCES", raising=False)
    adapter = _AutoComponentAdapter()
    for source, x in ((4, 0), (5, 124)):
        adapter.create_rectangle(
            {
                "name": f"Button {source}",
                "x": x,
                "y": 0,
                "width": 100,
                "height": 40,
                "semanticRole": "button",
                "semanticGroupId": "button-set-0",
                "semanticStructuralSignature": "visual:0|text:1|interactive:0",
                "semanticMemberCount": 2,
                "semanticSourceDomIndices": [source],
            }
        )

    adapter.flush()

    assert not any(
        action == "componentize_semantic_groups"
        for action, _params in adapter.calls
    )


def test_persists_componentization_result(tmp_path) -> None:
    result = {
        "status": "committed",
        "masters": [{"nodeId": "component:1"}],
        "instances": [{"nodeId": "instance:2"}],
        "rejected": [],
        "geometry_checks": [{"matched": True}],
    }

    path = persist_semantic_componentization_result(tmp_path, result)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "21_semantic_components_figma.json"
    assert payload == result
