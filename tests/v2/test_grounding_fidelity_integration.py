from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.app.agents.precise_agent import PreciseAgent
from src.config.settings import Config

ARTIFACT_NAMES = (
    "09_evidence_bundle.json",
    "10_content_inventory.json",
    "10_geometry_manifest.json",
    "11_scene_plan.json",
    "13_fidelity_report.json",
    "14_repair_history.json",
)


def _fixture_image(path: Path) -> None:
    Image.new("RGB", (400, 240), "#eef2f7").save(path)


class _HighFidelityProvider:
    def run(self, ctx):
        return {
            "image": ctx.image_path,
            "image_w": ctx.image_w,
            "image_h": ctx.image_h,
            "route": "grounding",
            "containers": [
                {
                    "id": "C1",
                    "bbox": [16, 16, 368, 208],
                    "role": "form",
                    "source": "grounding",
                    "parent": None,
                    "depth": 0,
                },
                {
                    "id": "C2",
                    "bbox": [32, 104, 336, 100],
                    "role": "table",
                    "source": "grounding",
                    "parent": "C1",
                    "depth": 1,
                },
            ],
            "elements": [
                {
                    "id": 1,
                    "bbox": [32, 32, 120, 24],
                    "type": "text",
                    "text": "自动备份管理",
                    "role": "",
                    "source": "grounding",
                    "container": "C1",
                },
                {
                    "id": 2,
                    "bbox": [32, 72, 16, 16],
                    "type": "checkbox",
                    "controlType": "checkbox",
                    "controlValue": "以auto用户身份执行",
                    "controlState": "checked",
                    "text": "",
                    "source": "image-enrichment:control-recovery",
                    "container": "C1",
                },
                {
                    "id": 3,
                    "bbox": [48, 128, 80, 20],
                    "type": "text",
                    "text": "Alpha",
                    "role": "",
                    "source": "grounding",
                    "container": "C2",
                },
                {
                    "id": 4,
                    "bbox": [320, 24, 40, 40],
                    "type": "image",
                    "text": "",
                    "role": "logo",
                    "source": "grounding",
                    "container": "C1",
                },
            ],
            "tables": [
                {
                    "name": "Results",
                    "bbox": [32, 104, 336, 100],
                    "header_texts": ["Name", "Status"],
                    "rows": [["Alpha", "Ready"]],
                    "source": "image-enrichment",
                }
            ],
            "imageEnrichment": {
                "mode": "apply",
                "status": "applied",
                "assets": [
                    {
                        "name": "brand_logo",
                        "kind": "logo",
                        "bbox": [320, 24, 40, 40],
                        "source": "slice",
                    }
                ],
                "backgrounds": [],
            },
            "sliceAnalysis": {
                "assets": [
                    {
                        "name": "brand_logo",
                        "kind": "logo",
                        "bbox": [320, 24, 40, 40],
                        "source": "slice",
                    }
                ],
                "backgrounds": [],
                "provenance": {"authority": "candidate"},
            },
            "provenance": {
                "route": "grounding",
                "fallbacks": [],
                "warnings": [],
                "grounding_reliability": {"status": "accepted"},
            },
        }


class _CVProvider:
    def run(self, ctx):
        return {
            "image": ctx.image_path,
            "image_w": ctx.image_w,
            "image_h": ctx.image_h,
            "route": "cv",
            "containers": [],
            "elements": [
                {
                    "id": 1,
                    "bbox": [16, 16, 100, 20],
                    "type": "text",
                    "text": "CV",
                    "source": "cv:ocr",
                }
            ],
            "provenance": {"route": "cv"},
        }


def _identity_recovery(graph, _image_path):
    return graph, {
        "schema_version": "test",
        "status": "not-needed",
        "source": "test",
        "added_count": 0,
        "observation_count": 0,
        "added": [],
    }


def _identity_control_recovery(
    graph,
    _image_path,
    *,
    add_from_assets,
    text_observations,
):
    return graph, {
        "schema_version": "image-control-recovery/1.0",
        "status": "not-needed",
        "snapped_count": 0,
        "added_count": 0,
    }


def _run_high_fidelity(tmp_path: Path) -> Path:
    output = tmp_path / "out"
    image = tmp_path / "page.png"
    _fixture_image(image)
    cfg = Config(
        output_dir=output,
        vision_api_key="configured",
        grounding_fidelity_mode="high",
        image_enrichment_mode="apply",
        text_align=False,
    )
    with (
        patch(
            "src.app.agents.precise_agent._build_provider",
            return_value=_HighFidelityProvider(),
        ),
        patch(
            "src.app.agents.precise_agent.recover_image_text_candidates",
            side_effect=_identity_recovery,
        ),
        patch(
            "src.app.agents.precise_agent.recover_image_region_candidates",
            side_effect=_identity_recovery,
        ),
        patch(
            "src.app.services.structure.image_enrichment.controls."
            "recover_visible_controls",
            side_effect=_identity_control_recovery,
        ),
        patch(
            "src.app.controllers.rendering_controller.RenderingController.render",
            return_value=None,
        ),
    ):
        PreciseAgent(cfg).run(
            image=str(image),
            route="grounding",
            tool="svg",
        )
    return output


def test_high_fidelity_mode_writes_plan_and_reports(tmp_path: Path) -> None:
    output = _run_high_fidelity(tmp_path)

    for name in ARTIFACT_NAMES:
        assert (output / name).is_file(), name
    graph = json.loads((output / "10_pagegraph.json").read_text("utf-8"))
    som = json.loads((output / "11_som.json").read_text("utf-8"))
    report = json.loads((output / "13_fidelity_report.json").read_text("utf-8"))
    history = json.loads((output / "14_repair_history.json").read_text("utf-8"))

    assert graph["scenePlan"]["schema_version"] == "grounding-scene-plan/1.0"
    assert som["scenePlan"]["schema_version"] == "grounding-scene-plan/1.0"
    assert report["mode"] == "high"
    assert report["counts"]["scene_nodes"] > 0
    assert history["status"] == "not-needed"
    assert history["extra_calls"] == 0


def test_high_fidelity_off_preserves_legacy_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "out"
    image = tmp_path / "page.png"
    _fixture_image(image)
    cfg = Config(
        output_dir=output,
        vision_api_key="configured",
        text_align=False,
    )
    with (
        patch(
            "src.app.agents.precise_agent._build_provider",
            return_value=_HighFidelityProvider(),
        ),
        patch(
            "src.app.agents.precise_agent.recover_image_text_candidates",
            side_effect=_identity_recovery,
        ),
        patch(
            "src.app.agents.precise_agent.recover_image_region_candidates",
            side_effect=_identity_recovery,
        ),
        patch(
            "src.app.services.structure.image_enrichment.controls."
            "recover_visible_controls",
            side_effect=_identity_control_recovery,
        ),
        patch(
            "src.app.controllers.rendering_controller.RenderingController.render",
            return_value=None,
        ),
    ):
        PreciseAgent(cfg).run(
            image=str(image),
            route="grounding",
            tool="svg",
        )
    names = {item.name for item in output.iterdir()}

    assert not set(ARTIFACT_NAMES) & names
    assert "10_pagegraph.json" in names
    assert "11_som.json" in names
    assert "12_design.json" in names


def test_high_fidelity_rejects_non_grounding_route(tmp_path: Path) -> None:
    output = tmp_path / "out"
    image = tmp_path / "page.png"
    _fixture_image(image)
    cfg = Config(
        output_dir=output,
        vision_api_key="configured",
        grounding_fidelity_mode="high",
        image_enrichment_mode="apply",
        text_align=False,
    )
    with (
        patch(
            "src.app.agents.precise_agent._build_provider",
            return_value=_CVProvider(),
        ),
        patch(
            "src.app.agents.precise_agent.recover_image_text_candidates",
            side_effect=_identity_recovery,
        ),
        patch(
            "src.app.agents.precise_agent.recover_image_region_candidates",
            side_effect=_identity_recovery,
        ),
    ):
        try:
            PreciseAgent(cfg).run(
                image=str(image),
                route="cv",
                tool="svg",
            )
        except ValueError as exc:
            assert "requires the grounding route" in str(exc)
        else:
            raise AssertionError("high fidelity accepted a non-grounding route")

    assert not (output / "09_evidence_bundle.json").exists()


def test_high_fidelity_requires_apply_enrichment() -> None:
    try:
        Config(
            grounding_fidelity_mode="high",
            image_enrichment_mode="analyze",
        )
    except ValueError as exc:
        assert "IMAGE_ENRICHMENT_MODE=apply" in str(exc)
    else:
        raise AssertionError("high fidelity accepted analyze enrichment")
