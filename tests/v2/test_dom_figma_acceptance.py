from __future__ import annotations

import base64
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.app.services.evidence.dom_figma_acceptance import (
    build_acceptance_report,
    build_frozen_sample_design,
    run_real_figma_acceptance,
)
from src.app.services.rendering.adapter_base import PrototypeAdapter
from src.app.services.som.direct_design import build_direct_design
from scripts.dom_figma_acceptance import _build_parser


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests/fixtures/dom_quality/real_site_corpus_v1.json"


def _write_frozen_capture(root: Path) -> Path:
    capture = root / "DQ-R02"
    capture.mkdir(parents=True)
    Image.new("RGB", (200, 120), (250, 250, 250)).save(capture / "00_screenshot.png")
    svg = (
        "data:image/svg+xml,"
        "%3Csvg xmlns='http://www.w3.org/2000/svg' width='40' height='40'%3E"
        "%3Crect width='40' height='40' fill='%233366cc'/%3E%3C/svg%3E"
    )
    dom = [
        {
            "tag": "body",
            "x": 0,
            "y": 0,
            "w": 200,
            "h": 120,
            "bg": "#ffffff",
            "position": "static",
            "zIndex": 0,
            "interactive": False,
        },
        {
            "tag": "div",
            "x": 10,
            "y": 10,
            "w": 180,
            "h": 100,
            "bg": "#ffffff",
            "position": "static",
            "zIndex": 0,
            "interactive": False,
        },
        {
            "tag": "p",
            "x": 20,
            "y": 20,
            "w": 100,
            "h": 24,
            "text": "Frozen Dushu sample",
            "bg": "rgba(0, 0, 0, 0)",
            "color": "#111827",
            "fontSize": "16px",
            "fontWeight": "400",
            "fontFamily": "Arial",
            "position": "static",
            "zIndex": 1,
            "interactive": False,
            "textEmBox": [20, 20, 100, 24],
            "textEmLines": 1,
            "textBaseline": {
                "y": 34,
                "ascent": 14,
                "descent": 4,
                "method": "canvas-font-metrics",
                "lineCount": 1,
            },
        },
        {
            "tag": "img",
            "x": 130,
            "y": 20,
            "w": 40,
            "h": 40,
            "assetSrc": svg,
            "naturalWidth": 40,
            "naturalHeight": 40,
            "objectFit": "fill",
            "objectPosition": "50% 50%",
            "position": "static",
            "zIndex": 1,
            "interactive": False,
        },
    ]
    (capture / "00_dom.json").write_text(
        json.dumps(dom),
        encoding="utf-8",
    )
    return capture


class _FrameOriginAdapter(PrototypeAdapter):
    def __init__(self) -> None:
        self.frame_spec = None
        self.events = []

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def create_frame(self, spec):
        self.frame_spec = dict(spec)
        return "root"

    def create_rectangle(self, spec, parent_id=None):
        self.events.append(("rectangle", dict(spec)))
        return "rect"

    def create_ellipse(self, spec, parent_id=None):
        self.events.append(("ellipse", dict(spec)))
        return "ellipse"

    def create_text(self, spec, parent_id=None):
        self.events.append(("text", dict(spec)))
        return "text"

    def create_image(self, spec, parent_id=None):
        self.events.append(("image", dict(spec)))
        return "image"

    def flush(self) -> None:
        pass


class _FakeAcceptanceAdapter:
    def __init__(self) -> None:
        self.frame_id = None
        self.calls = []
        self.connected = False
        self.tree = {
            "id": "root",
            "name": "D008 DQ-R02 DOM Real Figma Acceptance",
            "type": "FRAME",
            "x": 1600,
            "y": 0,
            "width": 200,
            "height": 120,
            "absolute": {"x": 1600, "y": 0, "width": 200, "height": 120},
            "children": [
                {
                    "id": "text-1",
                    "name": "Frozen text",
                    "type": "TEXT",
                    "characters": "Frozen Dushu sample",
                    "x": 20,
                    "y": 20,
                    "width": 100,
                    "height": 24,
                    "fontName": {"family": "Arial", "style": "Regular"},
                    "fontSize": 16,
                },
                {
                    "id": "image-1",
                    "name": "Image",
                    "type": "RECTANGLE",
                    "x": 130,
                    "y": 20,
                    "width": 40,
                    "height": 40,
                    "fills": [
                        {
                            "type": "IMAGE",
                            "imageHash": "original-hash",
                            "scaleMode": "FILL",
                        }
                    ],
                },
            ],
        }
        png = io.BytesIO()
        Image.new("RGB", (200, 120), (245, 245, 245)).save(
            png,
            format="PNG",
        )
        self.export_base64 = base64.b64encode(png.getvalue()).decode("ascii")
        self.original_image_base64 = base64.b64encode(b"original-pixels").decode(
            "ascii"
        )

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def render_design(self, design) -> None:
        self.frame_id = "root"
        self.calls.append(("render_design", len(design["elements"])))

    def image_fill_report(self, node_id):
        return self._send("image_fill_report", {"nodeId": node_id})

    def set_text(self, node_id, text):
        return self._send("set_text", {"nodeId": node_id, "text": text})

    def replace_image_fill(self, node_id, image_base64, *, fill_index=0):
        return self._send(
            "replace_image_fill",
            {
                "nodeId": node_id,
                "imageBase64": image_base64,
                "fillIndex": fill_index,
            },
        )

    def _send(self, action, params, *, request_id=None):
        self.calls.append((action, dict(params)))
        if action == "get_node_tree":
            return json.loads(json.dumps(self.tree))
        if action == "set_text":
            node = self._node(params["nodeId"])
            node["characters"] = params["text"]
            node["width"] = 140 if "D008" in params["text"] else 100
            return {"ok": True}
        if action == "image_fill_report":
            return {
                "nodeId": "root",
                "fillCount": 1,
                "fills": [
                    {
                        "nodeId": "image-1",
                        "nodeType": "RECTANGLE",
                        "fillIndex": 0,
                        "imageHash": self._node("image-1")["fills"][0]["imageHash"],
                        "scaleMode": self._node("image-1")["fills"][0]["scaleMode"],
                        "byteLength": len(b"original-pixels"),
                        "byteBase64": self.original_image_base64,
                    }
                ],
            }
        if action == "replace_image_fill":
            self._node(params["nodeId"])["fills"][0]["imageHash"] = (
                "replacement-hash"
                if params["imageBase64"] != self.original_image_base64
                else "original-hash"
            )
            return {"ok": True}
        if action == "export_frame":
            return {"nodeId": params["nodeId"], "base64": self.export_base64}
        raise AssertionError(f"unexpected action: {action}")

    def _node(self, node_id):
        if self.tree["id"] == node_id:
            return self.tree
        for child in self.tree["children"]:
            if child["id"] == node_id:
                return child
        raise AssertionError(node_id)


class FrozenDomFigmaDesignTests(unittest.TestCase):
    def test_builds_unique_design_from_frozen_dq_r02(self) -> None:
        corpus = json.loads(MANIFEST.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_root = root / "capture"
            output = root / "out"
            capture = _write_frozen_capture(capture_root)
            result = build_frozen_sample_design(
                corpus,
                capture_root,
                "DQ-R02",
                output,
                canvas_origin=(1600, 0),
            )
            metadata = json.loads(
                (output / "sample_metadata.json").read_text(encoding="utf-8")
            )
            dom_bytes = (capture / "00_dom.json").read_bytes()
            screenshot_bytes = (capture / "00_screenshot.png").read_bytes()
            som_exists = (output / "11_som.json").is_file()
            pagegraph_exists = (output / "10_pagegraph.json").is_file()

        design = result["design"]
        self.assertEqual(design["name"], "D008 DQ-R02 DOM Real Figma Acceptance")
        self.assertEqual(design["canvas"]["x"], 1600)
        self.assertEqual(design["canvas"]["y"], 0)
        self.assertEqual(design["canvas"]["width"], 200)
        self.assertEqual(design["canvas"]["height"], 120)
        self.assertTrue(any(item.get("type") == "text" for item in design["elements"]))
        self.assertTrue(any(item.get("type") == "image" for item in design["elements"]))
        text_element = next(
            item for item in design["elements"] if item.get("type") == "text"
        )
        self.assertEqual(text_element["textBaseline"]["y"], 34)
        self.assertEqual(
            text_element["textBaseline"]["method"],
            "canvas-font-metrics",
        )
        self.assertEqual(
            metadata["dom_sha256"],
            hashlib.sha256(dom_bytes).hexdigest(),
        )
        self.assertEqual(
            metadata["screenshot_sha256"],
            hashlib.sha256(screenshot_bytes).hexdigest(),
        )
        self.assertEqual(metadata["sample_id"], "DQ-R02")
        self.assertEqual(
            metadata["corpus_sha256"],
            corpus["corpus_sha256"],
        )
        self.assertEqual(
            metadata["thresholds_sha256"],
            corpus["thresholds_sha256"],
        )
        self.assertEqual(metadata["artifacts"]["design"], "design.json")
        self.assertTrue(som_exists)
        self.assertTrue(pagegraph_exists)

    def test_unknown_sample_and_missing_artifacts_fail_closed(self) -> None:
        corpus = json.loads(MANIFEST.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            with self.assertRaises(ValueError):
                build_frozen_sample_design(
                    corpus,
                    Path(tmp) / "capture",
                    "DQ-UNKNOWN",
                    output,
                )
            with self.assertRaises(FileNotFoundError):
                build_frozen_sample_design(
                    corpus,
                    Path(tmp) / "capture",
                    "DQ-R02",
                    output,
                )

    def test_canvas_origin_controls_root_frame_without_changing_default(self) -> None:
        adapter = _FrameOriginAdapter()
        adapter.render_design(
            {
                "canvas": {
                    "width": 200,
                    "height": 120,
                    "background": "#ffffff",
                    "x": 1600,
                    "y": 40,
                },
                "elements": [],
            }
        )
        self.assertEqual(adapter.frame_spec["x"], 1600)
        self.assertEqual(adapter.frame_spec["y"], 40)

        default_adapter = _FrameOriginAdapter()
        default_adapter.render_design(
            {
                "canvas": {
                    "width": 200,
                    "height": 120,
                    "background": "#ffffff",
                },
                "elements": [],
            }
        )
        self.assertEqual(default_adapter.frame_spec["x"], 0)
        self.assertEqual(default_adapter.frame_spec["y"], 0)

    def test_real_runner_uses_same_frame_and_restores_probes(self) -> None:
        design = {
            "name": "D008 DQ-R02 DOM Real Figma Acceptance",
            "canvas": {
                "width": 200,
                "height": 120,
                "background": "#ffffff",
                "x": 1600,
                "y": 0,
            },
            "elements": [
                {
                    "id": "text-1",
                    "type": "text",
                    "text": "Frozen Dushu sample",
                },
                {"id": "image-1", "type": "image"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            result = run_real_figma_acceptance(
                design,
                output_dir=output,
                sample_id="DQ-R02",
                adapter_factory=_FakeAcceptanceAdapter,
            )
            artifacts = {
                name: (output / name).is_file()
                for name in (
                    "readback.json",
                    "export.png",
                    "text_edit_probe.json",
                    "asset_probe.json",
                    "summary.json",
                )
            }

        self.assertEqual(
            result["status"],
            "captured-figma-evidence",
            result.get("error"),
        )
        self.assertEqual(result["frame_id"], "root")
        self.assertTrue(result["text_edit_probe"]["status"] == "pass")
        self.assertTrue(result["asset_probe"]["status"] == "pass")
        self.assertTrue(all(artifacts.values()))
        actions = [name for name, _params in result["calls"]]
        self.assertNotIn("remove_nodes_by_name", actions)
        self.assertNotIn("cleanup_owned_job", actions)
        self.assertGreaterEqual(actions.count("get_node_tree"), 3)
        self.assertEqual(actions.count("export_frame"), 1)

    def test_real_runner_reports_bridge_unavailable_without_writing(self) -> None:
        def unavailable():
            raise RuntimeError("plugin-disconnected")

        with tempfile.TemporaryDirectory() as tmp:
            result = run_real_figma_acceptance(
                {"canvas": {"width": 1, "height": 1}, "elements": []},
                output_dir=Path(tmp),
                sample_id="DQ-R02",
                adapter_factory=unavailable,
            )

        self.assertEqual(result["status"], "blocked-environment")
        self.assertEqual(result["frame_id"], None)
        self.assertIn("plugin-disconnected", result["error"])

    def test_cli_has_prepare_run_and_report_modes(self) -> None:
        parser = _build_parser()
        prepare = parser.parse_args(
            [
                "prepare",
                "--manifest",
                "manifest.json",
                "--capture-root",
                "capture",
                "--sample-id",
                "DQ-R02",
                "--out",
                "out",
                "--recover-network-assets",
                "--generate-icon-approximations",
            ]
        )
        run = parser.parse_args(
            [
                "run",
                "--sample-root",
                "sample",
                "--out",
                "out",
            ]
        )
        report = parser.parse_args(
            [
                "report",
                "--manifest",
                "manifest.json",
                "--sample-root",
                "sample",
                "--out",
                "out",
            ]
        )
        self.assertEqual(prepare.command, "prepare")
        self.assertTrue(prepare.recover_network_assets)
        self.assertTrue(prepare.generate_icon_approximations)
        self.assertEqual(run.command, "run")
        self.assertEqual(report.command, "report")

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "dom_figma_acceptance.py"),
                "--help",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("prepare", result.stdout)
        self.assertIn("run", result.stdout)

    def test_report_keeps_dimensions_and_export_identity(self) -> None:
        corpus = json.loads(MANIFEST.read_text(encoding="utf-8"))
        design = {
            "name": "D008 DQ-R02 DOM Real Figma Acceptance",
            "canvas": {
                "width": 200,
                "height": 120,
                "background": "#ffffff",
                "x": 1600,
                "y": 0,
            },
            "elements": [
                {
                    "id": "text-1",
                    "type": "text",
                    "text": "Frozen Dushu sample",
                    "x": 20,
                    "y": 20,
                    "width": 100,
                    "height": 24,
                    "style": {"fontFamily": "Arial", "fontSize": 16},
                    "textEmLines": 1,
                    "textBaseline": {
                        "y": 33,
                        "ascent": 13,
                        "descent": 4,
                        "method": "canvas-font-metrics",
                        "lineCount": 1,
                    },
                },
                {
                    "id": "image-1",
                    "type": "image",
                    "x": 130,
                    "y": 20,
                    "width": 40,
                    "height": 40,
                    "imageBase64": base64.b64encode(b"image").decode("ascii"),
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = root / "sample"
            run = root / "run"
            sample.mkdir()
            reference = sample / "reference.png"
            Image.new("RGB", (200, 120), (255, 255, 255)).save(reference)
            (sample / "design.json").write_text(
                json.dumps(design),
                encoding="utf-8",
            )
            (sample / "sample_metadata.json").write_text(
                json.dumps(
                    {
                        "sample_id": "DQ-R02",
                        "artifacts": {"screenshot": str(reference)},
                        "counts": {"elements": 2},
                    }
                ),
                encoding="utf-8",
            )
            run_real_figma_acceptance(
                design,
                output_dir=run,
                sample_id="DQ-R02",
                adapter_factory=_FakeAcceptanceAdapter,
            )
            report = build_acceptance_report(
                corpus,
                sample_root=sample,
                run_root=run,
            )

        self.assertEqual(report["sample_id"], "DQ-R02")
        self.assertEqual(report["frame_id"], "root")
        self.assertEqual(
            set(report["dimensions"]),
            {
                "visual",
                "structure",
                "edit",
                "asset",
                "text",
                "layout",
                "export",
                "source_resolution",
            },
        )
        self.assertTrue(report["export"]["exists"])
        self.assertFalse(report["composite_score_used"])
        self.assertEqual(
            report["text_metrics"]["dimensions"]["linebreak"]["status"],
            "pass",
        )
        self.assertEqual(
            report["text_metrics"]["dimensions"]["baseline"]["status"],
            "pass",
        )
        self.assertEqual(report["dimensions"]["text"]["linebreak"], "pass")
        self.assertEqual(report["dimensions"]["text"]["baseline"], "pass")
        self.assertEqual(report["dimensions"]["text"]["glyph"], "not-required")
        self.assertEqual(report["layout"]["parent_propagation"], "not-evaluated")
        self.assertEqual(report["critical_text"]["status"], "fail")
        self.assertTrue(report["critical_text"]["rows"])
        self.assertTrue(
            all(row["present"] is False for row in report["critical_text"]["rows"])
        )

    def test_missing_image_payload_uses_transparent_rectangle_placeholder(self) -> None:
        adapter = _FrameOriginAdapter()
        adapter.render_design(
            {
                "canvas": {"width": 100, "height": 80, "background": "#ffffff"},
                "elements": [
                    {
                        "id": "missing-image",
                        "type": "image",
                        "x": 10,
                        "y": 10,
                        "width": 40,
                        "height": 30,
                    }
                ],
            }
        )

        self.assertEqual(adapter.events[-1][0], "rectangle")
        self.assertEqual(adapter.events[-1][1]["name"], "missing-image")
        self.assertNotIn("imageBase64", adapter.events[-1][1])

    def test_capture_canvas_size_extends_full_page_image_crop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            screenshot = Path(tmp) / "page.png"
            Image.new("RGB", (100, 300), (240, 240, 240)).save(screenshot)
            design = build_direct_design(
                {
                    "image": str(screenshot),
                    "size": [100, 300],
                    "containers": [],
                    "elements": [
                        {
                            "id": "below-fold",
                            "type": "image",
                            "bbox": [10, 200, 40, 40],
                        }
                    ],
                    "provenance": {
                        "route": "dom",
                        "capture": {
                            "device_scale_factor": 1,
                            "viewport": {"width": 100, "height": 100},
                            "canvas_size": [100, 300],
                        },
                    },
                }
            )

        self.assertEqual(design["canvas"]["height"], 300)
        self.assertTrue(design["elements"][0].get("imageBase64"))


if __name__ == "__main__":
    unittest.main()
