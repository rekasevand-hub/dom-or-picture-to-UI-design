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


def test_component_instances_are_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("DOM_SEMANTIC_COMPONENT_INSTANCES", raising=False)
    assert Config().dom_semantic_component_instances is False

    monkeypatch.setenv("DOM_SEMANTIC_COMPONENT_INSTANCES", "true")
    assert Config().dom_semantic_component_instances is True


def test_disabled_feature_does_not_send_componentization(monkeypatch) -> None:
    monkeypatch.delenv("DOM_SEMANTIC_COMPONENT_INSTANCES", raising=False)
    adapter = _RecordingAdapter()

    result = adapter.componentize_semantic_groups([])

    assert result["status"] == "disabled"
    assert adapter.calls == []


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
