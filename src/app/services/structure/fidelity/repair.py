"""Bounded, transactional repair planning for a canonical ScenePlan."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import Any

from src.app.services.structure.fidelity.contracts import (
    canonical_json,
    normalize_bbox,
    stable_id,
)

_REQUIRED_NODE_FIELDS = {
    "id",
    "parent_id",
    "type",
    "role",
    "bbox",
    "content_ref",
    "geometry_ref",
    "children",
}
_CONTENT_NODE_TYPES = {"text", "control", "image", "button", "input"}


def _plan_size(plan: Mapping[str, Any]) -> tuple[int, int]:
    try:
        width, height = (int(value) for value in plan.get("image_size"))
    except (TypeError, ValueError):
        raise ValueError(
            "scene plan image size must contain width and height"
        ) from None
    if width <= 0 or height <= 0:
        raise ValueError("scene plan image size must be positive")
    if not isinstance(plan.get("nodes"), list):
        raise ValueError("scene plan nodes must be a list")
    return width, height


def _node_map(plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(node.get("id") or ""): node
        for node in plan.get("nodes") or []
        if isinstance(node, Mapping) and node.get("id")
    }


def _union_bboxes(boxes: list[list[int]]) -> list[int] | None:
    if not boxes:
        return None
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    return [left, top, right - left, bottom - top]


def _blocker_kind(value: Any, reason: str) -> str:
    text = f"{value or ''} {reason}".lower()
    if "table" in text:
        return "table"
    if "control" in text or "checkbox" in text or "field" in text:
        return "control"
    if "asset" in text or "logo" in text or "avatar" in text:
        return "asset"
    if "text" in text:
        return "text"
    if "geometry" in text or "iou" in text:
        return "geometry"
    return "region"


def _blocker_targets(
    blocker: Mapping[str, Any],
    kind: str,
    nodes: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    raw_targets = blocker.get("target_ids") or blocker.get("targets") or []
    if isinstance(raw_targets, str):
        raw_targets = [raw_targets]
    targets = [str(value) for value in raw_targets if str(value)]
    if not targets:
        preferred_types = {
            "table": {"table"},
            "control": {"control"},
            "text": {"text"},
            "asset": {"image"},
            "geometry": {"container", "table", "control", "text"},
        }.get(kind, set())
        targets = [
            str(node["id"])
            for node in nodes.values()
            if not preferred_types or node.get("type") in preferred_types
        ]
    expanded = list(targets)
    for target in targets:
        node = nodes.get(target)
        owner = str(node.get("text_owner_ref") or "") if node else ""
        if owner and owner not in expanded:
            expanded.append(owner)
    return expanded


def _blocker_bbox(
    blocker: Mapping[str, Any],
    targets: list[str],
    nodes: Mapping[str, Mapping[str, Any]],
    width: int,
    height: int,
) -> list[int]:
    explicit = normalize_bbox(blocker.get("bbox"), width, height)
    if explicit is not None:
        return explicit
    boxes = [
        box
        for target in targets
        if target in nodes
        and (box := normalize_bbox(nodes[target].get("bbox"), width, height))
        is not None
    ]
    union = _union_bboxes(boxes)
    return union or [0, 0, width, height]


def _request_from_blocker(
    blocker: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
    width: int,
    height: int,
) -> dict[str, Any] | None:
    reason = str(
        blocker.get("reason") or blocker.get("blocker") or blocker.get("id") or ""
    ).strip()
    kind = _blocker_kind(blocker.get("kind"), reason)
    targets = _blocker_targets(blocker, kind, nodes)
    bbox = _blocker_bbox(blocker, targets, nodes, width, height)
    if not reason:
        reason = f"{kind} fidelity blocker"
    return {
        "id": stable_id("repair-request", kind, reason, targets, bbox),
        "kind": kind,
        "bbox": bbox,
        "target_ids": targets,
        "reason": reason,
        "acceptance": {
            "must_resolve": True,
            "allow_content_change": False,
            "protect_native_text": True,
            "forbid_underlay": True,
        },
    }


def plan_repair_requests(
    report: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    max_requests: int,
) -> list[dict[str, Any]]:
    """Translate named verifier blockers into bounded local repair requests."""
    if not isinstance(report, Mapping):
        raise ValueError("report must be an object")
    if max_requests <= 0:
        return []
    width, height = _plan_size(plan)
    nodes = _node_map(plan)
    raw_blockers = report.get("blockers") or []
    if isinstance(raw_blockers, (str, Mapping)):
        raw_blockers = [raw_blockers]
    requests: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for raw in raw_blockers:
        if isinstance(raw, Mapping):
            blocker = raw
        else:
            blocker = {"reason": str(raw or "")}
        request = _request_from_blocker(blocker, nodes, width, height)
        if request is None:
            continue
        key = (
            request["kind"],
            tuple(request["target_ids"]),
            tuple(request["bbox"]),
            request["reason"],
        )
        if key in seen:
            continue
        seen.add(key)
        requests.append(request)
        if len(requests) >= max_requests:
            break
    return requests


def _is_full_screenshot_underlay(
    node: Mapping[str, Any], width: int, height: int
) -> bool:
    bbox = normalize_bbox(node.get("bbox"), width, height)
    if bbox is None or node.get("type") != "image":
        return False
    area_ratio = bbox[2] * bbox[3] / float(width * height)
    role = str(node.get("role") or "").lower()
    content = str(node.get("content_ref") or "").lower()
    named_underlay = any(
        token in f"{role} {content}"
        for token in ("underlay", "screenshot", "page-background")
    )
    return area_ratio >= 0.9 or (named_underlay and area_ratio >= 0.5)


def _validate_patch_nodes(
    nodes: list[dict[str, Any]],
    width: int,
    height: int,
) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    content_refs: set[str] = set()
    for node in nodes:
        missing = _REQUIRED_NODE_FIELDS - set(node)
        node_id = str(node.get("id") or "")
        if missing:
            errors.append(
                f"patch node {node_id or '<empty>'} is missing "
                + ", ".join(sorted(missing))
            )
            continue
        if not node_id or node_id in ids:
            errors.append(f"duplicate or empty patch node id: {node_id}")
            continue
        ids.add(node_id)
        if normalize_bbox(node.get("bbox"), width, height) is None:
            errors.append(f"patch node {node_id} has invalid bbox")
        content_ref = str(node.get("content_ref") or "")
        if content_ref:
            if content_ref in content_refs:
                errors.append(f"duplicate content owner: {content_ref}")
            content_refs.add(content_ref)
        if not isinstance(node.get("children"), list):
            errors.append(f"patch node {node_id} children must be a list")
        if _is_full_screenshot_underlay(node, width, height):
            errors.append(f"patch introduces full-screenshot underlay: {node_id}")
    for node in nodes:
        parent_id = str(node.get("parent_id") or "")
        if parent_id and parent_id not in ids:
            errors.append(
                f"patch node {node['id']} references unknown parent {parent_id}"
            )
    return errors


def _operation_nodes(operation: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = operation.get("nodes")
    if isinstance(raw, list):
        return [value for value in raw if isinstance(value, Mapping)]
    node = operation.get("node")
    return [node] if isinstance(node, Mapping) else []


def apply_repair_patch(
    plan: Mapping[str, Any],
    patch: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply one patch atomically, or return the unchanged original plan."""
    if not isinstance(plan, Mapping):
        raise ValueError("plan must be an object")
    if not isinstance(patch, Mapping):
        raise ValueError("patch must be an object")
    width, height = _plan_size(plan)
    original = copy.deepcopy(dict(plan))
    candidate = copy.deepcopy(dict(plan))
    nodes = [
        copy.deepcopy(dict(node))
        for node in candidate.get("nodes") or []
        if isinstance(node, Mapping)
    ]
    node_map = {str(node.get("id") or ""): node for node in nodes}
    removals: set[str] = set()
    additions: list[dict[str, Any]] = []
    errors: list[str] = []
    operations = patch.get("operations")
    if not isinstance(operations, list) or not operations:
        return {
            "accepted": False,
            "plan": original,
            "errors": ["patch operations must be a non-empty list"],
            "applied_operations": 0,
        }

    for index, raw_operation in enumerate(operations):
        if not isinstance(raw_operation, Mapping):
            errors.append(f"operation[{index}] must be an object")
            continue
        operation = raw_operation
        op = str(operation.get("op") or "")
        node_id = str(operation.get("id") or "")
        if (
            op
            in {
                "set_state",
                "set_owner",
                "set_text",
                "update_bbox",
                "set_asset_payload",
                "remove_node",
            }
            and node_id not in node_map
        ):
            errors.append(f"operation {op} target not found: {node_id}")
            continue
        if op == "set_state":
            if str(node_map[node_id].get("type") or "") != "control":
                errors.append(f"set_state target is not a control: {node_id}")
            else:
                state = str(operation.get("state") or operation.get("value") or "")
                if not state:
                    errors.append(f"set_state requires state: {node_id}")
                else:
                    node_map[node_id]["state"] = state
        elif op == "set_owner":
            owner = str(operation.get("text_owner") or operation.get("owner") or "")
            if owner not in node_map:
                errors.append(f"set_owner text owner not found: {owner}")
            else:
                node_map[node_id]["text_owner_ref"] = owner
        elif op == "set_text":
            if "text" not in operation:
                errors.append(f"set_text requires text: {node_id}")
            else:
                old_text = str(node_map[node_id].get("text") or "")
                new_text = str(operation.get("text") or "")
                if old_text.strip() and not new_text.strip():
                    errors.append(f"set_text cannot remove covered content: {node_id}")
                else:
                    node_map[node_id]["text"] = new_text
        elif op == "update_bbox":
            bbox = normalize_bbox(operation.get("bbox"), width, height)
            if bbox is None:
                errors.append(f"update_bbox is invalid: {node_id}")
            else:
                node_map[node_id]["bbox"] = bbox
        elif op == "set_asset_payload":
            payload = operation.get("payload_sha256") or operation.get("payload")
            if not payload:
                errors.append(f"set_asset_payload requires a payload: {node_id}")
            else:
                node_map[node_id]["payload_sha256"] = str(payload)
        elif op == "remove_node":
            removals.add(node_id)
        elif op == "add_node":
            additions.extend(
                copy.deepcopy(dict(node)) for node in _operation_nodes(operation)
            )
        elif op == "replace_region_nodes":
            raw_targets = operation.get("target_ids") or []
            if isinstance(raw_targets, str):
                raw_targets = [raw_targets]
            removals.update(str(value) for value in raw_targets if str(value))
            additions.extend(
                copy.deepcopy(dict(node)) for node in _operation_nodes(operation)
            )
        else:
            errors.append(f"unsupported repair operation: {op}")

    if errors:
        return {
            "accepted": False,
            "plan": original,
            "errors": errors,
            "applied_operations": 0,
        }

    removed_nodes = [node for node in nodes if str(node["id"]) in removals]
    removed_content_refs = {
        str(node.get("content_ref") or "")
        for node in removed_nodes
        if node.get("content_ref")
    }
    added_content_refs = {
        str(node.get("content_ref") or "")
        for node in additions
        if node.get("content_ref")
    }
    removed_without_replacement = removed_content_refs - added_content_refs
    if removed_without_replacement:
        errors.append(
            "patch cannot remove covered content: "
            + ", ".join(sorted(removed_without_replacement))
        )
    if errors:
        return {
            "accepted": False,
            "plan": original,
            "errors": errors,
            "applied_operations": 0,
        }

    replacement_by_id = {str(node["id"]): node for node in additions}
    reparented: dict[str, str | None] = {}
    for removed in removed_nodes:
        for child_id in removed.get("children") or []:
            if str(child_id) in removals:
                continue
            reparented[str(child_id)] = (
                str(removed.get("parent_id"))
                if removed.get("parent_id") is not None
                else None
            )
    nodes = [node for node in nodes if str(node["id"]) not in removals]
    nodes.extend(replacement_by_id.values())
    for node in nodes:
        if str(node["id"]) in reparented:
            node["parent_id"] = reparented[str(node["id"])]
        children = [
            child_id
            for child_id in node.get("children") or []
            if str(child_id) not in removals
        ]
        node["children"] = children
    node_map = {str(node.get("id") or ""): node for node in nodes}
    for node in nodes:
        parent_id = str(node.get("parent_id") or "")
        if not parent_id:
            continue
        parent = node_map.get(parent_id)
        if parent is not None and node["id"] not in (parent.get("children") or []):
            parent.setdefault("children", []).append(node["id"])

    errors.extend(_validate_patch_nodes(nodes, width, height))
    if errors:
        return {
            "accepted": False,
            "plan": original,
            "errors": list(dict.fromkeys(errors)),
            "applied_operations": 0,
        }

    candidate["nodes"] = nodes
    candidate["repairRevision"] = int(plan.get("repairRevision") or 0) + 1
    candidate["lastRepair"] = {
        "region_id": str(patch.get("region_id") or ""),
        "target_ids": list(patch.get("target_ids") or []),
        "reason": str(patch.get("reason") or ""),
        "operations": len(operations),
    }
    return {
        "accepted": True,
        "plan": candidate,
        "errors": [],
        "applied_operations": len(operations),
    }


def _verification_regressed(report: Mapping[str, Any]) -> bool:
    if bool(report.get("regressed")):
        return True
    return any(
        str(blocker).lower().startswith(("regression:", "region-regression:"))
        for blocker in report.get("blockers") or []
    )


def run_bounded_repair_loop(
    plan: Mapping[str, Any],
    verify: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    repair: Callable[
        [Mapping[str, Any], Mapping[str, Any]],
        Mapping[str, Any] | None,
    ],
    *,
    max_rounds: int = 3,
    max_extra_calls: int = 6,
) -> dict[str, Any]:
    """Run a transactional verifier/repair loop within hard budgets."""
    if max_rounds <= 0:
        raise ValueError("max_rounds must be positive")
    if max_extra_calls <= 0:
        raise ValueError("max_extra_calls must be positive")
    current = copy.deepcopy(dict(plan))
    initial_report = dict(verify(current))
    history: list[dict[str, Any]] = []
    extra_calls = 0
    rounds = 0
    report = initial_report
    status = "no-progress"
    if str(report.get("status") or "") == "pass":
        return {
            "status": "pass",
            "plan": current,
            "initial_report": initial_report,
            "final_report": initial_report,
            "history": history,
            "extra_calls": 0,
            "rounds": 0,
        }

    while rounds < max_rounds and extra_calls < max_extra_calls:
        requests = plan_repair_requests(
            report,
            current,
            max_requests=max_extra_calls - extra_calls,
        )
        if not requests:
            status = "no-requests"
            break
        request = requests[0]
        rounds += 1
        extra_calls += 1
        try:
            patch = repair(request, current)
        except Exception as exc:  # noqa: BLE001 - recorded as bounded failure
            history.append(
                {
                    "round": rounds,
                    "request": copy.deepcopy(request),
                    "patch": None,
                    "accepted": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            status = "repair-error"
            break
        if patch is None:
            history.append(
                {
                    "round": rounds,
                    "request": copy.deepcopy(request),
                    "patch": None,
                    "accepted": False,
                    "reason": "no-patch",
                }
            )
            status = "no-patch"
            break
        application = apply_repair_patch(current, patch)
        entry = {
            "round": rounds,
            "request": copy.deepcopy(request),
            "patch": copy.deepcopy(dict(patch)),
            "accepted": bool(application["accepted"]),
            "errors": list(application["errors"]),
            "rolled_back": False,
        }
        history.append(entry)
        if not application["accepted"]:
            status = "patch-rejected"
            break
        candidate = application["plan"]
        try:
            next_report = dict(verify(candidate))
        except Exception as exc:  # noqa: BLE001 - keep last verified plan
            entry["rolled_back"] = True
            entry["error"] = f"{type(exc).__name__}: {exc}"
            status = "rolled-back"
            break
        if _verification_regressed(next_report):
            entry["rolled_back"] = True
            entry["regression_report"] = next_report
            status = "rolled-back"
            break
        current = candidate
        report = next_report
        if str(report.get("status") or "") == "pass":
            status = "pass"
            break

    if status == "no-progress" or rounds == 0:
        if extra_calls >= max_extra_calls:
            status = "budget-exhausted"
        elif rounds >= max_rounds:
            status = "max-rounds-exhausted"
    elif status not in {
        "pass",
        "no-patch",
        "no-requests",
        "patch-rejected",
        "rolled-back",
        "repair-error",
    }:
        if extra_calls >= max_extra_calls and str(report.get("status")) != "pass":
            status = "budget-exhausted"
        elif rounds >= max_rounds and str(report.get("status")) != "pass":
            status = "max-rounds-exhausted"
    return {
        "status": status,
        "plan": current,
        "initial_report": initial_report,
        "final_report": report,
        "history": history,
        "extra_calls": extra_calls,
        "rounds": rounds,
        "budget": {
            "max_rounds": max_rounds,
            "max_extra_calls": max_extra_calls,
        },
        "history_sha256": __import__("hashlib")
        .sha256(canonical_json(history).encode("utf-8"))
        .hexdigest(),
    }
