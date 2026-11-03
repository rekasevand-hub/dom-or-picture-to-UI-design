from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from src.app.services.structure.providers.base import ProviderContext
from src.app.services.structure.providers.grounding import (
    GroundingProvider,
    ImageEnrichmentBlockedError,
)
from src.app.agents.precise_agent import PreciseAgent


class _Backend:
    def __init__(self, raw: dict) -> None:
        self.raw = raw
        self.ground_calls = 0
        self.prompt_calls: list[str] = []
        self.last_report = None

    def ground(self, _image_path, _width, _height):
        self.ground_calls += 1
        return json.loads(json.dumps(self.raw))

    def ground_with_prompt(
        self,
        _image_path,
        _width,
        _height,
        prompt,
        *,
        strategy_id="grounding-tile",
        metadata=None,
    ):
        self.prompt_calls.append(prompt)
        return json.loads(json.dumps(self.raw))


def _raw() -> dict:
    return {
        "containers": [{"bbox": [0, 0, 200, 30], "role": "banner"}],
        "elements": [
            {"bbox": [10, 5, 80, 12], "type": "text", "text": "Title"}
        ],
        "assets": [
            {
                "name": "brand_logo",
                "kind": "logo",
                "bbox": {"x": 20, "y": 40, "width": 30, "height": 20},
                "confidence": 0.9,
            }
        ],
        "backgrounds": [
            {
                "id": "hero",
                "name": "hero_background",
                "bbox": {"x": 0, "y": 0, "width": 200, "height": 100},
                "overlays": [
                    {
                        "id": "card",
                        "kind": "code-overlay",
                        "bbox": {"x": 20, "y": 35, "width": 60, "height": 30},
                    }
                ],
            }
        ],
    }


def _config(mode: str) -> SimpleNamespace:
    return SimpleNamespace(
        image_enrichment_mode=mode,
        vision_tile_max_height=4096,
        vision_tile_overlap=256,
        image_generation_api_key=None,
        image_generation_base_url=None,
        image_generation_model="seedream-5.0-flash",
        image_generation_timeout=20,
    )


def _run(raw: dict, mode: str) -> tuple[dict, _Backend]:
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        image = Image.new("RGB", (200, 100), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 40, 49, 59), fill="#2f6fed")
        path = root / "page.png"
        image.save(path)
        backend = _Backend(raw)
        with patch(
            "src.app.services.structure.providers.grounding._default_backend",
            return_value=backend,
        ):
            graph = GroundingProvider(_config(mode)).run(
                ProviderContext(
                    image_path=str(path),
                    image_w=200,
                    image_h=100,
                    route="grounding",
                    output_dir=str(root / "out"),
                )
            )
    return graph, backend


def test_off_mode_adds_no_enrichment_fields_or_calls():
    graph, backend = _run(_raw(), "off")

    assert backend.ground_calls == 1
    assert backend.prompt_calls == []
    assert "imageEnrichment" not in graph
    assert "sliceAnalysis" not in graph
    assert [item["text"] for item in graph["elements"]] == ["Title"]


def test_analyze_mode_adds_candidates_but_preserves_elements():
    graph, backend = _run(_raw(), "analyze")

    assert backend.ground_calls == 0
    assert len(backend.prompt_calls) == 1
    assert "assets" in backend.prompt_calls[0]
    assert graph["route"] == "grounding"
    assert [item["text"] for item in graph["elements"]] == ["Title"]
    assert graph["imageEnrichment"]["mode"] == "analyze"
    assert graph["imageEnrichment"]["status"] == "analyzed"
    assert graph["imageEnrichment"]["assets"][0]["name"] == "brand_logo"
    assert graph["imageEnrichment"]["assets"][0]["visibleCrop"]["payload_sha256"]
    assert graph["imageEnrichment"]["backgrounds"][0]["id"] == "hero"
    assert graph["sliceAnalysis"]["assets"][0]["name"] == "brand_logo"


def test_apply_mode_adds_visible_asset_and_background_candidate():
    graph, backend = _run(_raw(), "apply")

    assert backend.ground_calls == 0
    assert graph["imageEnrichment"]["mode"] == "apply"
    assert graph["imageEnrichment"]["status"] == "applied"
    assert [item["text"] for item in graph["elements"] if item["type"] == "text"] == [
        "Title"
    ]
    image_elements = [
        item for item in graph["elements"] if item["type"] == "image"
    ]
    assert len(image_elements) == 1
    assert image_elements[0]["assetName"] == "brand_logo"
    assert image_elements[0]["sourceCrop"]["payload_sha256"]
    background = graph["imageEnrichment"]["backgroundCandidates"][0]
    assert background["sourceCrop"]["payload_sha256"]
    assert background["cleanCandidate"]["generated"] is False


def test_apply_mode_fails_closed_and_marks_full_screenshot_underlay():
    raw = _raw()
    raw["assets"] = [
        {
            "name": "full_page",
            "kind": "screenshot",
            "bbox": {"x": 0, "y": 0, "width": 200, "height": 100},
        }
    ]

    with pytest.raises(ImageEnrichmentBlockedError) as caught:
        _run(raw, "apply")

    assert caught.value.code == "blocked-full-screenshot-underlay"
    assert (
        caught.value.graph["imageEnrichment"]["status"]
        == "blocked-full-screenshot-underlay"
    )


def test_image_enrichment_mode_default_and_validation(monkeypatch):
    from src.config.settings import Config

    monkeypatch.delenv("IMAGE_ENRICHMENT_MODE", raising=False)
    assert Config().image_enrichment_mode == "off"

    monkeypatch.setenv("IMAGE_ENRICHMENT_MODE", "analyze")
    assert Config().image_enrichment_mode == "analyze"

    monkeypatch.setenv("IMAGE_ENRICHMENT_MODE", "mystery")
    with pytest.raises(ValueError, match="IMAGE_ENRICHMENT_MODE"):
        Config()


class _AgentProvider:
    def run(self, ctx):
        return {
            "image": ctx.image_path,
            "image_w": ctx.image_w,
            "image_h": ctx.image_h,
            "route": "grounding",
            "containers": [],
            "elements": [
                {
                    "id": 1,
                    "bbox": [10, 5, 80, 12],
                    "type": "text",
                    "text": "Title",
                    "source": "grounding",
                    "role": "",
                    "container": None,
                    "confidence": 1.0,
                }
            ],
            "imageEnrichment": {
                "mode": "analyze",
                "status": "analyzed",
                "assets": [],
                "backgrounds": [],
                "backgroundCandidates": [],
                "diagnostics": [],
                "underlays": [],
            },
            "sliceAnalysis": {
                "assets": [],
                "backgrounds": [],
                "provenance": {"authority": "candidate"},
            },
            "provenance": {"route": "grounding", "fallbacks": [], "warnings": []},
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


def test_agent_persists_analyze_enrichment_without_changing_effective_route():
    from src.config.settings import Config

    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        path = root / "page.png"
        Image.new("RGB", (200, 100), "white").save(path)
        output = root / "out"
        cfg = Config(
            output_dir=output,
            vision_api_key="configured",
            image_enrichment_mode="analyze",
            text_align=False,
        )
        with (
            patch(
                "src.app.agents.precise_agent._build_provider",
                return_value=_AgentProvider(),
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
                "src.app.controllers.rendering_controller.RenderingController.render",
                return_value=None,
            ),
        ):
            PreciseAgent(cfg).run(image=str(path), route="auto", tool="svg")

        manifest = json.loads((output / "manifest.json").read_text("utf-8"))
        graph = json.loads((output / "10_pagegraph.json").read_text("utf-8"))
        som = json.loads((output / "11_som.json").read_text("utf-8"))
        enrichment = json.loads(
            (output / "image_enrichment.json").read_text("utf-8")
        )

    assert manifest["effective_route"] == "grounding"
    assert manifest["route"] == "grounding"
    assert manifest["imageEnrichment"]["mode"] == "analyze"
    assert manifest["imageEnrichment"]["status"] == "analyzed"
    assert graph["imageEnrichment"]["mode"] == "analyze"
    assert som["imageEnrichment"]["mode"] == "analyze"
    assert enrichment["mode"] == "analyze"
