from __future__ import annotations

import copy
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SEMANTIC_GROUPS_SCHEMA_VERSION = "semantic-design-groups/1.0"
SEMANTIC_COMPONENTS_FILENAME = "20_semantic_components.json"
_ROLE_PREFIX = {
    "navigation": "Nav",
    "list": "List",
    "card": "Card",
    "button": "Button",
    "link": "Link",
}


def load_semantic_components(path: str | Path) -> dict[str, Any] | None:
    source = Path(path)
    if not source.is_file():
        return None
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("components"), list):
        return None
    return value


def _source_indices(component: Mapping[str, Any]) -> list[int]:
    values = component.get("sourceDomIndices")
    if not isinstance(values, list):
        return []
    return sorted(
        {
            value
            for value in values
            if isinstance(value, int) and not isinstance(value, bool)
        }
    )


def _label(value: Any, fallback: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:60] if text else fallback


def _representative(
    indices: Sequence[int],
    elements: Sequence[Mapping[str, Any]],
) -> int | None:
    if not indices:
        return None

    def rank(index: int) -> tuple[int, int, int]:
        element = elements[index]
        element_type = str(element.get("type") or "")
        return (
            4 if element.get("layout") is not None else 0,
            3 if element_type == "container" else 2 if element_type in {"button", "input"} else 1,
            -index,
        )

    return max(indices, key=rank)


def _semantic_name(
    role: str,
    component: Mapping[str, Any],
    element: Mapping[str, Any],
    counters: Counter[str],
) -> str:
    prefix = _ROLE_PREFIX[role]
    counters[role] += 1
    if role == "navigation":
        label = "Primary" if counters[role] == 1 else "Secondary"
    elif role == "list":
        label = (
            "Article grid"
            if int(component.get("memberCount") or 0) >= 3
            else f"Group {counters[role]}"
        )
    elif role == "card":
        member_index = component.get("memberIndex")
        number = int(member_index) + 1 if isinstance(member_index, int) else counters[role]
        label = f"Article {number}"
    else:
        label = _label(
            element.get("text")
            or element.get("ariaLabel")
            or element.get("name"),
            f"Action {counters[role]}",
        )
    return f"{prefix} / {label}"


def apply_semantic_groups(
    design: Mapping[str, Any],
    semantics: Mapping[str, Any],
) -> dict[str, Any]:
    result = copy.deepcopy(dict(design))
    elements = [
        element
        for element in result.get("elements") or []
        if isinstance(element, dict)
    ]
    by_dom: dict[int, list[int]] = {}
    for index, element in enumerate(elements):
        dom_index = element.get("domIndex")
        if isinstance(dom_index, int) and not isinstance(dom_index, bool):
            by_dom.setdefault(dom_index, []).append(index)

    components = [
        component
        for component in semantics.get("components") or []
        if isinstance(component, Mapping)
        and str(component.get("role") or "") in _ROLE_PREFIX
    ]
    components.sort(
        key=lambda component: (
            min(_source_indices(component), default=10**9),
            str(component.get("id") or ""),
        )
    )
    counters: Counter[str] = Counter()
    for component in components:
        role = str(component["role"])
        representative = _representative(
            [
                index
                for source in _source_indices(component)
                for index in by_dom.get(source, [])
            ],
            elements,
        )
        if representative is None:
            continue
        element = elements[representative]
        group_id = str(
            component.get("groupId")
            or f"semantic-{min(_source_indices(component), default=representative)}"
        )
        element["semanticRole"] = role
        element["semanticGroupId"] = group_id
        element["semanticConfidence"] = round(
            float(component.get("confidence") or 0.0),
            4,
        )
        element["semanticEvidence"] = copy.deepcopy(
            list(component.get("evidence") or [])
        )
        element["semanticSourceDomIndices"] = _source_indices(component)
        structural_signature = str(
            component.get("structuralSignature") or ""
        ).strip()
        if structural_signature:
            element["semanticStructuralSignature"] = structural_signature
        element["name"] = _semantic_name(role, component, element, counters)
    return result
