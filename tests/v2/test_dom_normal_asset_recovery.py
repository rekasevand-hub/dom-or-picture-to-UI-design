from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from src.app.agents.precise_agent import PreciseAgent
from src.app.services.evidence.dom_route_quality import DOMRouteQualityError
from src.app.services.structure.capture_bundle import write_capture_bundle


def _image_element(source_url: str, *, verified: bool = False) -> dict:
    source = {
        "source_url": source_url,
        "status": "verified-original" if verified else "reference-only",
        "sha256": "a" * 64 if verified else None,
        "mime": "image/png" if verified else None,
        "natural_size": [320, 180] if verified else None,
        "locator": "assets/hero.png" if verified else None,
        "size_bytes": 1200 if verified else None,
    }
    return {
        "id": "hero",
        "type": "image",
        "x": 10,
        "y": 10,
        "width": 100,
        "height": 60,
        "text": "",
        "style": {},
        "assetIdentity": {
            "asset_record": {
                "source_identity": source,
                "missing": {
                    "is_missing": False,
                    "status": "loaded",
                },
            }
        },
    }


def _prepare_bundle(root: Path) -> None:
    screenshot = root / "00_screenshot.png"
    dom = root / "00_dom.json"
    page_state = root / "00_page_state.json"
    Image.new("RGB", (320, 180), "white").save(screenshot)
    dom.write_text("[]", encoding="utf-8")
    state = {
        "final_url": "https://example.test/",
        "kind": "content",
        "screenshot_only": False,
        "viewport": {"width": 320, "height": 180},
        "device_scale_factor": 1,
        "canvas_size": [320, 180],
    }
    page_state.write_text(json.dumps(state), encoding="utf-8")
    write_capture_bundle(
        root,
        requested_url="https://example.test/",
        page_state=state,
        artifact_paths={
            "screenshot": screenshot,
            "dom": dom,
            "page_state": page_state,
        },
    )


def _run_design(
    root: Path,
    *,
    recovery_enabled: bool,
    strict_route_quality: bool = False,
    regional_redirect: bool = False,
):
    _prepare_bundle(root)
    if regional_redirect:
        bundle_path = root / "00_capture_bundle.json"
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        bundle["final_url"] = "https://example.test/global/support/"
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    image = root / "00_screenshot.png"
    original_design = {
        "canvas": {"width": 320, "height": 180, "background": "#ffffff"},
        "elements": [
            _image_element("https://example.test/one.png"),
            _image_element("https://example.test/two.png"),
        ],
        "_meta": {},
    }
    recovered_design = copy.deepcopy(original_design)
    recovered_design["elements"][0] = _image_element(
        "https://example.test/one.png",
        verified=True,
    )
    calls = []

    def fake_recovery(design, *, page_url, output_dir):
        calls.append((page_url, str(output_dir)))
        return {
            "schema_version": "dom-network-asset-recovery/1.0",
            "status_counts": {"verified-original": 1, "reference-only": 1},
            "rows": [],
            "design": recovered_design,
        }

    class FakeRenderingController:
        def __init__(self, cfg):
            self.cfg = cfg

        def render(self, *args, **kwargs):
            return None

    cfg = SimpleNamespace(
        output_dir=root,
        device_scale_factor=1,
        playwright_viewport_width=320,
        playwright_viewport_height=180,
        vision_api_key=None,
        delivery_profile="legacy",
        dom_network_asset_recovery=recovery_enabled,
        dom_route_quality_strict=strict_route_quality,
    )
    som = {
        "image": str(image),
        "size": [320, 180],
        "containers": [],
        "elements": [],
        "provenance": {
            "route": "dom",
            "url": "https://example.test/",
            "capture": {
                "viewport": {"width": 320, "height": 180},
                "canvas_size": [320, 180],
                "device_scale_factor": 1,
                "screenshot_only": False,
            },
        },
    }
    with (
        patch(
            "src.app.services.som.direct_design.try_build_direct_design",
            return_value=original_design,
        ),
        patch(
            "src.app.services.som.direct_design.build_direct_design",
            return_value=original_design,
        ),
        patch("src.app.services.som.design_crops.apply_crops_to_design", return_value=0),
        patch("src.app.services.som.design_crops.backfill_design_image_crops"),
        patch(
            "src.app.services.structure.network_asset_recovery.recover_network_assets",
            side_effect=fake_recovery,
        ) as recovery,
        patch(
            "src.app.controllers.rendering_controller.RenderingController",
            FakeRenderingController,
        ),
        patch.object(PreciseAgent, "_refine_text_baselines", return_value=None),
    ):
        PreciseAgent(cfg)._design_and_render(
            som,
            image=str(image),
            url="https://example.test/",
            tool="svg",
            out=root,
            t0=0.0,
            route="dom",
            counts={},
            fallbacks=[],
            extra_manifest={},
        )
    return calls, recovery, json.loads((root / "00_assets.json").read_text())


def test_normal_dom_flow_skips_recovery_when_disabled(tmp_path):
    calls, recovery, ledger = _run_design(tmp_path, recovery_enabled=False)

    assert calls == []
    recovery.assert_not_called()
    assert ledger["reference_only_count"] == 2
    assert ledger["verified_count"] == 0


def test_normal_dom_flow_recovers_once_and_updates_bundle(tmp_path):
    calls, recovery, ledger = _run_design(tmp_path, recovery_enabled=True)

    assert len(calls) == 1
    recovery.assert_called_once()
    assert ledger["verified_count"] == 1
    assert ledger["reference_only_count"] == 1
    bundle = json.loads((tmp_path / "00_capture_bundle.json").read_text())
    counts = bundle["artifacts"]["assets"]["counts"]
    assert counts["verified_count"] == ledger["verified_count"]
    assert counts["reference_only_count"] == ledger["reference_only_count"]


def test_strict_route_quality_fails_before_rendering(tmp_path):
    with pytest.raises(DOMRouteQualityError, match="redirect"):
        _run_design(
            tmp_path,
            recovery_enabled=False,
            strict_route_quality=True,
            regional_redirect=True,
        )
