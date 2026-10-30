from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.services.rendering.adapter_base import paint_order
from src.app.services.rendering.semantic_groups import apply_semantic_groups
from src.app.services.structure.capture_bundle import (
    capture_bundle_artifact_path,
    load_capture_bundle,
)
from src.app.services.structure.component_patterns import infer_component_patterns
from src.app.services.structure.semantic_components import (
    classify_semantic_components,
)
from src.app.services.structure.semantic_merge import merge_semantic_candidates
from src.config.settings import Config

BENCHMARK_SCHEMA_VERSION = "dom-semantic-benchmark/1.0"
_TABLE_TAGS = {"table", "thead", "tbody", "tfoot", "tr", "td", "th"}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _normal_name(value: str) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "it之家": "it-home",
        "ithome": "it-home",
        "21ic": "21ic",
        "bbs21": "21ic",
        "国家数据": "stats",
        "national-data": "stats",
        "小米": "xiaomi",
        "postgres": "postgresql",
        "postgresql": "postgresql",
    }
    return aliases.get(text, text)


def _visual_result(readback: Mapping[str, Any], name: str) -> dict[str, Any]:
    cases = readback.get("cases")
    if isinstance(cases, list):
        selected = next(
            (
                case
                for case in cases
                if isinstance(case, Mapping)
                and _normal_name(str(case.get("name") or "")) == _normal_name(name)
            ),
            None,
        )
        if selected is None:
            return {
                "status": "not-evaluated",
                "metrics": {},
                "source": "case-not-found",
            }
        if "treatment_status" in selected:
            metrics = selected.get("metrics")
            treatment = metrics.get("treatment") if isinstance(metrics, Mapping) else {}
            return {
                "status": selected.get("treatment_status"),
                "baselineStatus": selected.get("baseline_status"),
                "metrics": dict(treatment or {}),
                "regressions": list(selected.get("regressions") or []),
                "source": "legacy-p1-ab",
            }
        visual = selected.get("visual")
        metrics = (
            visual.get("metrics")
            if isinstance(visual, Mapping)
            else selected.get("metrics")
        )
        return {
            "status": selected.get("status")
            or (visual.get("status") if isinstance(visual, Mapping) else None),
            "metrics": dict(metrics or {}),
            "checks": (
                dict(visual.get("checks") or {})
                if isinstance(visual, Mapping)
                else dict(selected.get("checks") or {})
            ),
            "figmaReadbackPresent": bool(
                selected.get("figma_readback_present")
            ),
            "source": "visual-benchmark",
        }
    visual = readback.get("visual")
    metrics = (
        visual.get("metrics")
        if isinstance(visual, Mapping)
        else readback.get("metrics")
    )
    return {
        "status": readback.get("status")
        or (visual.get("status") if isinstance(visual, Mapping) else None),
        "metrics": dict(metrics or {}),
        "checks": (
            dict(visual.get("checks") or {})
            if isinstance(visual, Mapping)
            else dict(readback.get("checks") or {})
        ),
        "figmaReadbackPresent": bool(readback.get("figma_readback_present")),
        "source": "single-case",
    }


def _geometry_signature(design: Mapping[str, Any]) -> str:
    elements = design.get("elements") or []
    rows = [
        {
            key: element.get(key)
            for key in (
                "id",
                "type",
                "x",
                "y",
                "width",
                "height",
                "clip",
                "textEmBox",
                "textBox",
                "layoutChildren",
            )
        }
        for element in elements
        if isinstance(element, Mapping)
    ]
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _style_signature(design: Mapping[str, Any]) -> str:
    rows = [
        element.get("style") or {}
        for element in design.get("elements") or []
        if isinstance(element, Mapping)
    ]
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _paint_signature(design: Mapping[str, Any]) -> str:
    elements = [
        element
        for element in design.get("elements") or []
        if isinstance(element, dict)
    ]
    return json.dumps(
        [element.get("id") for _index, element in paint_order(elements)],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _parents(nodes: Sequence[Mapping[str, Any]]) -> list[int | None]:
    result: list[int | None] = [None] * len(nodes)
    for index, node in enumerate(nodes):
        parent = node.get("pIdx")
        if (
            isinstance(parent, int)
            and not isinstance(parent, bool)
            and 0 <= parent < len(nodes)
            and parent != index
        ):
            result[index] = parent
    return result


def _ancestors(index: int, parents: Sequence[int | None]) -> list[int]:
    result: list[int] = []
    seen = {index}
    current = parents[index]
    while current is not None and current not in seen:
        result.append(current)
        seen.add(current)
        current = parents[current]
    return result


def _children(parents: Sequence[int | None]) -> list[list[int]]:
    result: list[list[int]] = [[] for _ in parents]
    for index, parent in enumerate(parents):
        if parent is not None:
            result[parent].append(index)
    return result


def _descendants(index: int, children: Sequence[Sequence[int]]) -> list[int]:
    result = []
    stack = list(reversed(children[index]))
    while stack:
        current = stack.pop()
        result.append(current)
        stack.extend(reversed(children[current]))
    return result


def _false_positive_candidates(
    nodes: Sequence[Mapping[str, Any]],
    components: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    parents = _parents(nodes)
    children = _children(parents)
    rows = []
    bounds: dict[tuple[int, int, int, int], list[Mapping[str, Any]]] = {}
    for component in components:
        source_indices = [
            value
            for value in component.get("sourceDomIndices") or []
            if isinstance(value, int) and 0 <= value < len(nodes)
        ]
        box = component.get("bbox")
        if isinstance(box, list) and len(box) >= 4:
            key = tuple(int(value) for value in box[:4])
            bounds.setdefault(key, []).append(component)
        for source in source_indices:
            table_ancestor = next(
                (
                    index
                    for index in [source, *_ancestors(source, parents)]
                    if str(nodes[index].get("tag") or "").lower() in _TABLE_TAGS
                ),
                None,
            )
            if table_ancestor is not None and component.get("role") in {
                "card",
                "list",
            }:
                rows.append(
                    {
                        "kind": "table-semantic-confusion",
                        "sourceDomIndex": source,
                        "role": component.get("role"),
                    }
                )
            if component.get("role") == "navigation":
                evidence_kinds = {
                    str(item.get("kind") or "")
                    for item in component.get("evidence") or []
                    if isinstance(item, Mapping)
                }
                if not evidence_kinds & {"tag", "aria-role"}:
                    identity = (
                        f"{nodes[source].get('id') or ''} "
                        f"{nodes[source].get('clsAll') or ''} "
                        f"{nodes[source].get('name') or ''}"
                    ).lower()
                    specificity_markers = (
                        "title",
                        "ranking",
                        "share",
                        "info-text",
                        "sites",
                        "copyright",
                        "footer",
                    )
                    if any(marker in identity for marker in specificity_markers):
                        rows.append(
                            {
                                "kind": "navigation-specificity-review",
                                "sourceDomIndex": source,
                                "role": "navigation",
                                "identity": identity.strip()[:160],
                            }
                        )
                    if int(component.get("bbox")[3]) > 200:
                        rows.append(
                            {
                                "kind": "large-inferred-navigation",
                                "sourceDomIndex": source,
                                "role": "navigation",
                                "height": component.get("bbox")[3],
                            }
                        )
        if component.get("role") != "button":
            if component.get("role") == "card":
                visual_sizes = [
                    (
                        int(nodes[current].get("w") or 0),
                        int(nodes[current].get("h") or 0),
                    )
                    for source in source_indices
                    for current in _descendants(source, children)
                    if str(nodes[current].get("tag") or "").lower()
                    in {"img", "svg", "video", "canvas", "picture"}
                ]
                if visual_sizes and max(max(size) for size in visual_sizes) < 96:
                    rows.append(
                        {
                            "kind": "small-visual-card-review",
                            "sourceDomIndex": source_indices[0] if source_indices else None,
                            "role": "card",
                            "visualSizes": [list(size) for size in visual_sizes[:4]],
                        }
                    )
            continue
        evidence_kinds = {
            str(item.get("kind") or "")
            for item in component.get("evidence") or []
            if isinstance(item, Mapping)
        }
        if (
            not evidence_kinds & {"tag", "aria-role"}
            and not evidence_kinds & {"border", "background", "min-height"}
        ):
            rows.append(
                {
                    "kind": "unstyled-link-button",
                    "sourceDomIndex": source_indices[0] if source_indices else None,
                    "role": "button",
                }
            )
    for box, members in sorted(bounds.items()):
        if len(members) < 2:
            continue
        for member in members[1:]:
            rows.append(
                {
                    "kind": "duplicate-semantic-bounds",
                    "bbox": list(box),
                    "role": member.get("role"),
                    "componentId": member.get("id"),
                }
            )
    return rows


def _case_kind(name: str, bundle_dir: Path) -> str:
    combined = f"{name} {bundle_dir}".lower()
    return "holdout" if "holdout" in combined else "regression"


def _analyze_case(name: str, bundle_dir: Path, readback_path: Path) -> dict[str, Any]:
    bundle = load_capture_bundle(bundle_dir)
    dom_path = capture_bundle_artifact_path(bundle_dir, bundle, "dom")
    dom_nodes = _load_json(dom_path)
    if not isinstance(dom_nodes, list):
        raise ValueError(f"DOM artifact is not an array: {dom_path}")

    semantic_base = classify_semantic_components(dom_nodes)
    patterns = infer_component_patterns(dom_nodes, semantic_base)
    semantic_result = merge_semantic_candidates(patterns, [])
    components = [
        item
        for item in semantic_result.get("components") or []
        if isinstance(item, Mapping)
    ]

    design_path = bundle_dir / "12_design.json"
    if not design_path.is_file():
        raise FileNotFoundError(design_path)
    baseline = _load_json(design_path)
    if not isinstance(baseline, dict):
        raise ValueError(f"DesignSpec is not an object: {design_path}")
    semantic_design = apply_semantic_groups(baseline, semantic_result)
    geometry_invariant = (
        _geometry_signature(baseline) == _geometry_signature(semantic_design)
        and _style_signature(baseline) == _style_signature(semantic_design)
        and _paint_signature(baseline) == _paint_signature(semantic_design)
    )

    false_positives = _false_positive_candidates(dom_nodes, components)
    readback = _load_json(readback_path)
    visual = _visual_result(readback, name)
    groups = semantic_result.get("groups") if isinstance(semantic_result, Mapping) else {}
    if not isinstance(groups, Mapping):
        groups = {}
    groups_not_componentized = [
        {
            "groupId": group_id,
            "role": group.get("role"),
            "memberCount": len(group.get("members") or []),
            "reason": "feature-disabled",
        }
        for group_id, group in sorted(groups.items())
        if isinstance(group, Mapping)
    ]
    config = Config()
    feature_flags = {
        "domSemanticComponents": config.dom_semantic_components,
        "domSemanticComponentInstances": config.dom_semantic_component_instances,
    }
    visual_status = str(visual.get("status") or "not-evaluated")
    if not geometry_invariant or visual_status == "fail":
        status = "fail"
    elif false_positives or visual_status == "warn":
        status = "warn"
    elif visual_status == "pass":
        status = "pass"
    else:
        status = "not-evaluated"
    return {
        "name": name,
        "kind": _case_kind(name, bundle_dir),
        "status": status,
        "bundle": str(bundle_dir),
        "readback": str(readback_path),
        "visual": visual,
        "semantics": {
            "roleCounts": dict(semantic_result.get("roleCounts") or {}),
            "unknownCount": sum(
                item.get("role") == "unknown" for item in components
            ),
            "componentCount": len(components),
        },
        "falsePositiveCandidates": false_positives,
        "groupsNotComponentized": groups_not_componentized,
        "geometryInvariant": geometry_invariant,
        "featureFlags": feature_flags,
        "browserUsed": bool(visual.get("browserUsed") or bundle.get("browser_used")),
        "networkUsed": bool(visual.get("networkUsed") or bundle.get("network_used")),
    }


def build_semantic_benchmark_report(
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = sorted(
        [dict(case) for case in cases],
        key=lambda case: (str(case.get("name") or ""), str(case.get("bundle") or "")),
    )
    role_totals: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    false_positive_count = 0
    groups_count = 0
    geometry_invariant_count = 0
    unknown_count = 0
    for row in rows:
        semantics = row.get("semantics")
        if isinstance(semantics, Mapping):
            role_totals.update(
                {
                    str(role): int(count or 0)
                    for role, count in (semantics.get("roleCounts") or {}).items()
                }
            )
            unknown_count += int(semantics.get("unknownCount") or 0)
        status_counts[str(row.get("status") or "not-evaluated")] += 1
        false_positive_count += len(row.get("falsePositiveCandidates") or [])
        groups_count += len(row.get("groupsNotComponentized") or [])
        geometry_invariant_count += bool(row.get("geometryInvariant"))
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "cases": rows,
        "aggregate": {
            "caseCount": len(rows),
            "regressionCaseCount": sum(
                row.get("kind") == "regression" for row in rows
            ),
            "holdoutCaseCount": sum(row.get("kind") == "holdout" for row in rows),
            "statusCounts": dict(sorted(status_counts.items())),
            "roleTotals": dict(sorted(role_totals.items())),
            "unknownCount": unknown_count,
            "falsePositiveCandidateCount": false_positive_count,
            "groupsNotComponentizedCount": groups_count,
            "geometryInvariantCaseCount": geometry_invariant_count,
            "browserUsed": any(bool(row.get("browserUsed")) for row in rows),
            "networkUsed": any(bool(row.get("networkUsed")) for row in rows),
        },
    }


def _parse_case(value: str) -> tuple[str, Path, Path]:
    parts = value.split("=", 2)
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise argparse.ArgumentTypeError(
            "--case must be NAME=BUNDLE_DIR=FIGMA_READBACK_JSON"
        )
    return parts[0].strip(), Path(parts[1]).resolve(), Path(parts[2]).resolve()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark DOM semantics and Figma visual readback per page."
    )
    parser.add_argument(
        "--case",
        action="append",
        required=True,
        type=_parse_case,
        metavar="NAME=BUNDLE_DIR=FIGMA_READBACK_JSON",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("output/_dom_semantic_benchmark/dom-semantic-benchmark.json"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        cases = [
            _analyze_case(name, bundle_dir, readback_path)
            for name, bundle_dir, readback_path in args.case
        ]
        report = build_semantic_benchmark_report(cases)
        _write_json(args.out, report)
    except Exception as exc:  # noqa: BLE001 - benchmark must fail closed
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 1 if report["aggregate"]["statusCounts"].get("fail") else 0


if __name__ == "__main__":
    raise SystemExit(main())
