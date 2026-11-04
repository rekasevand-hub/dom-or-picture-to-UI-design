"""Grounding high-fidelity evidence and scene contracts."""

from src.app.services.structure.fidelity.inventory import (
    build_content_inventory,
    build_evidence_bundle,
    build_geometry_manifest,
)
from src.app.services.structure.fidelity.local_repair import (
    GroundingLocalRepairer,
)
from src.app.services.structure.fidelity.scene_plan import (
    apply_scene_plan,
    build_scene_plan,
)
from src.app.services.structure.fidelity.repair import (
    apply_repair_patch,
    plan_repair_requests,
    run_bounded_repair_loop,
)

__all__ = [
    "apply_repair_patch",
    "apply_scene_plan",
    "build_content_inventory",
    "build_evidence_bundle",
    "build_geometry_manifest",
    "build_scene_plan",
    "GroundingLocalRepairer",
    "plan_repair_requests",
    "run_bounded_repair_loop",
]
