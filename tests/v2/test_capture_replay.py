from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from src.app.services.structure.capture_bundle import (
    CaptureBundleError,
    write_capture_bundle,
)
from src.app.services.structure.capture_replay import replay_capture_bundle


def _write_replay_fixture(root: Path) -> Path:
    root.mkdir(parents=True)
    screenshot = root / "00_screenshot.png"
    dom = root / "00_dom.json"
    page_state = root / "00_page_state.json"
    Image.new("RGB", (320, 180), "white").save(screenshot)
    dom.write_text(
        json.dumps(
            [
                {
                    "tag": "body",
                    "x": 0,
                    "y": 0,
                    "w": 320,
                    "h": 180,
                    "bg": "rgb(255, 255, 255)",
                    "pageBg": "rgb(255, 255, 255)",
                    "interactive": False,
                },
                {
                    "tag": "div",
                    "pIdx": 0,
                    "x": 20,
                    "y": 20,
                    "w": 280,
                    "h": 80,
                    "bg": "rgb(240, 240, 240)",
                    "pageBg": "rgb(255, 255, 255)",
                    "text": "Deterministic replay",
                    "color": "rgb(17, 34, 51)",
                    "fontSize": "20px",
                    "fontWeight": "600",
                    "fontFamily": "Arial",
                    "lineHeight": "24px",
                    "interactive": False,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    state = {
        "final_url": "https://example.test/replay",
        "kind": "content",
        "screenshot_only": False,
        "viewport": {"width": 320, "height": 180},
        "device_scale_factor": 1,
        "canvas_size": [320, 180],
    }
    page_state.write_text(json.dumps(state), encoding="utf-8")
    write_capture_bundle(
        root,
        requested_url="https://example.test/start",
        page_state=state,
        artifact_paths={
            "screenshot": screenshot,
            "dom": dom,
            "page_state": page_state,
        },
    )
    return root


def test_replay_is_browser_free_network_free_and_deterministic(tmp_path):
    bundle_dir = _write_replay_fixture(tmp_path / "bundle")
    first_out = tmp_path / "replay-one"
    second_out = tmp_path / "replay-two"

    with patch(
        "src.app.services.structure.capture.capture_page_with_fallback",
        side_effect=AssertionError("browser capture must not run during replay"),
    ):
        first = replay_capture_bundle(bundle_dir, first_out)
        second = replay_capture_bundle(bundle_dir, second_out)

    assert first["pagegraph_sha256"] == second["pagegraph_sha256"]
    assert first["design_sha256"] == second["design_sha256"]
    assert first["network_used"] is False
    assert first["browser_used"] is False
    assert first["requested_route"] == "dom"
    assert first["effective_route"] == "dom"
    assert first["requested_url"] == "https://example.test/start"
    assert first["final_url"] == "https://example.test/replay"
    assert first["capture"]["viewport"] == {"width": 320, "height": 180}
    for artifact in (
        "10_pagegraph.json",
        "11_som.json",
        "20_semantic_components.json",
        "replay_manifest.json",
        "12_design.json",
    ):
        assert (first_out / artifact).is_file()
    assert first["semantic_components_sha256"] == second["semantic_components_sha256"]

    (bundle_dir / "00_dom.json").write_text("[]", encoding="utf-8")
    with pytest.raises(CaptureBundleError, match="sha256 mismatch"):
        replay_capture_bundle(bundle_dir, tmp_path / "mutated-replay")
