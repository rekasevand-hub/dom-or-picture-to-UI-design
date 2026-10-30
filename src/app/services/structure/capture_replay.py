from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image

from src.app.services.som.annotate import annotate_som
from src.app.services.som.direct_design import build_direct_design
from src.app.services.structure.component_patterns import infer_component_patterns
from src.app.services.structure.capture_bundle import (
    CAPTURE_BUNDLE_FILENAME,
    CaptureBundleError,
    capture_bundle_artifact_path,
    load_capture_bundle,
)
from src.app.services.structure.graph import (
    assign_ids,
    assign_parent_depth,
    save_graph,
)
from src.app.services.structure.layer_tree import build_layer_tree
from src.app.services.structure.providers.dom import DomProvider
from src.app.services.structure.providers.base import ProviderContext
from src.app.services.structure.semantic_components import (
    classify_semantic_components,
)
from src.app.services.structure.semantic_merge import (
    SEMANTIC_COMPONENTS_FILENAME,
    merge_semantic_candidates,
    persist_semantic_components,
)
from src.app.services.structure.site_profiles import load_profile

REPLAY_SCHEMA_VERSION = "dom-capture-replay/1.0"
REPLAY_MANIFEST_FILENAME = "replay_manifest.json"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_sha256(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(payload)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def replay_capture_bundle(
    bundle_dir: str | Path,
    output_dir: str | Path,
    *,
    build_design: bool = True,
) -> dict[str, Any]:
    source_root = Path(bundle_dir).resolve()
    destination = Path(output_dir).resolve()
    bundle = load_capture_bundle(source_root)
    dom_path = capture_bundle_artifact_path(source_root, bundle, "dom")
    screenshot_path = capture_bundle_artifact_path(source_root, bundle, "screenshot")

    try:
        dom_nodes = json.loads(dom_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureBundleError(f"invalid DOM artifact: {exc}") from exc
    if not isinstance(dom_nodes, list):
        raise CaptureBundleError("DOM artifact must contain a JSON array")
    with Image.open(screenshot_path) as screenshot:
        image_width, image_height = screenshot.size

    destination.mkdir(parents=True, exist_ok=True)
    graph = DomProvider().run(
        ProviderContext(
            image_path=str(screenshot_path),
            image_w=image_width,
            image_h=image_height,
            route="dom",
            output_dir=str(destination),
            dom_path=str(dom_path),
            url=str(bundle.get("final_url") or bundle.get("requested_url") or ""),
            profile=load_profile(str(bundle.get("final_url") or "")),
        )
    )
    assign_ids(graph)
    assign_parent_depth(graph)
    graph.setdefault("provenance", {})
    graph["provenance"].update(
        {
            "url": bundle.get("final_url") or bundle.get("requested_url"),
            "requested_url": bundle.get("requested_url"),
            "final_url": bundle.get("final_url"),
            "requested_route": "dom",
            "effective_route": "dom",
            "fallbacks": [],
            "capture": dict(bundle.get("capture") or {}),
            "page_state": dict(bundle.get("page_state") or {}),
            "warnings": list(bundle.get("warnings") or []),
            "capture_bundle": {
                "schema_version": bundle.get("schema_version"),
                "artifacts": dict(bundle.get("artifacts") or {}),
            },
        }
    )
    pagegraph_path = destination / "10_pagegraph.json"
    save_graph(graph, str(pagegraph_path))
    som = annotate_som(graph, str(destination))
    som_path = destination / "11_som.json"

    semantic_components = classify_semantic_components(
        dom_nodes,
        layer_tree=build_layer_tree(dom_nodes),
    )
    semantic_patterns = infer_component_patterns(
        dom_nodes,
        semantic_components,
    )
    semantic_merge = merge_semantic_candidates(semantic_patterns, [])
    semantic_path = persist_semantic_components(destination, semantic_merge)
    semantic_sha256 = _canonical_json_sha256(semantic_path)

    design_path = destination / "12_design.json"
    if build_design:
        design = build_direct_design(
            som,
            profile=load_profile(str(bundle.get("final_url") or "")),
            dom_nodes=dom_nodes,
        )
        _write_json(design_path, design)
        design_sha256 = _canonical_json_sha256(design_path)
    else:
        design_sha256 = None

    manifest_path = source_root / CAPTURE_BUNDLE_FILENAME
    replay_manifest = {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "source_schema_version": bundle["schema_version"],
        "source_bundle_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "source_artifacts": {
            role: dict(entry)
            for role, entry in bundle["artifacts"].items()
        },
        "requested_url": bundle["requested_url"],
        "final_url": bundle["final_url"],
        "requested_route": "dom",
        "effective_route": "dom",
        "capture": dict(bundle["capture"]),
        "warnings": list(bundle.get("warnings") or []),
        "browser_used": False,
        "network_used": False,
        "build_design": bool(build_design),
        "artifacts": {
            "pagegraph": {
                "path": pagegraph_path.name,
                "sha256": _canonical_json_sha256(pagegraph_path),
            },
            "som": {
                "path": som_path.name,
                "sha256": _canonical_json_sha256(som_path),
            },
            "semantic_components": {
                "path": SEMANTIC_COMPONENTS_FILENAME,
                "sha256": semantic_sha256,
            },
            **(
                {
                    "design": {
                        "path": design_path.name,
                        "sha256": design_sha256,
                    }
                }
                if design_sha256
                else {}
            ),
        },
    }
    _write_json(destination / REPLAY_MANIFEST_FILENAME, replay_manifest)
    return {
        **replay_manifest,
        "pagegraph_sha256": replay_manifest["artifacts"]["pagegraph"]["sha256"],
        "som_sha256": replay_manifest["artifacts"]["som"]["sha256"],
        "semantic_components_sha256": semantic_sha256,
        "design_sha256": design_sha256,
    }
