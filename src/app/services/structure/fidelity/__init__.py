"""Grounding high-fidelity evidence and scene contracts."""

from src.app.services.structure.fidelity.inventory import (
    build_content_inventory,
    build_evidence_bundle,
    build_geometry_manifest,
)
from src.app.services.structure.fidelity.container_manifest import (
    build_container_manifest,
)
from src.app.services.structure.fidelity.fixed_canvas_compiler import (
    compile_scene_plan_to_design,
)
from src.app.services.structure.fidelity.local_repair import (
    GroundingLocalRepairer,
)
from src.app.services.structure.fidelity.regions import (
    reconcile_region_containers,
)
from src.app.services.structure.fidelity.scene_plan import (
    apply_scene_plan,
    build_scene_plan,
)
from src.app.services.structure.fidelity.style_resolver import resolve_text_style
from src.app.services.structure.fidelity.repair import (
    apply_repair_patch,
    plan_repair_requests,
    run_bounded_repair_loop,
)

__all__ = [
    "apply_repair_patch",
    "apply_scene_plan",
    "build_content_inventory",
    "build_container_manifest",
    "build_evidence_bundle",
    "build_geometry_manifest",
    "build_scene_plan",
    "compile_scene_plan_to_design",
    "GroundingLocalRepairer",
    "plan_repair_requests",
    "reconcile_region_containers",
    "run_bounded_repair_loop",
    "resolve_text_style",
]
