from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.structure.image_contract import (
    _enhance_low_confidence_ocr_observation,
    build_image_design,
    build_image_ir,
    inspect_image_reference,
    merge_ocr_candidates,
    recover_image_region_candidates,
    select_ocr_languages,
)
from src.app.services.structure.image_enrichment.assets import recover_visible_assets


def _rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))


def test_enhance_low_confidence_ocr_expands_and_reruns_cjk_crop() -> None:
    import numpy as np

    class FakeReader:
        def readtext(self, image, text_threshold):
            assert image.shape[0] > 30
            assert image.shape[1] > 40
            return [
                (
                    [[0, 0], [100, 0], [100, 20], [0, 20]],
                    "输入关键字过滤菜单",
                    0.84,
                )
            ]

    observation = {
        "text": "关键字过滤菜单",
        "bbox": [30, 20, 60, 12],
        "confidence": 0.08,
        "engine": "easyocr",
    }
    image = np.full((80, 140, 3), 40, dtype=np.uint8)

    enhanced = _enhance_low_confidence_ocr_observation(
        FakeReader(),
        image,
        observation,
    )

    assert enhanced is not None
    assert enhanced["text"] == "输入关键字过滤菜单"
    assert enhanced["engine"] == "easyocr-enhanced"
    assert enhanced["rawText"] == "关键字过滤菜单"
    assert enhanced["confidence"] == 0.84


def _fixture(root: Path) -> tuple[Path, dict, dict]:
    path = root / "sample.png"
    image = Image.new("RGB", (400, 220), "#eef2f7")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 399, 49), fill="#24324a")
    draw.rectangle((20, 70, 179, 189), fill="#ffffff")
    draw.rectangle((32, 130, 111, 157), fill="#2f6fed")
    draw.rectangle((210, 70, 269, 129), fill="#e85d75")
    draw.text((20, 13), "Workspace", fill="#f8fafc")
    draw.text((32, 82), "Card title", fill="#172033")
    draw.text((40, 138), "Open", fill="#ffffff")
    image.save(path)
    graph = {
        "image": str(path),
        "image_w": 400,
        "image_h": 220,
        "route": "grounding",
        "containers": [
            {
                "id": "C1",
                "bbox": [0, 0, 400, 50],
                "role": "banner",
                "source": "grounding",
                "parent": None,
                "depth": 0,
            },
            {
                "id": "C2",
                "bbox": [20, 70, 160, 120],
                "role": "card",
                "source": "grounding",
                "parent": None,
                "depth": 0,
            },
        ],
        "elements": [
            {
                "id": 1,
                "bbox": [20, 13, 120, 28],
                "type": "text",
                "text": "Workspace",
                "role": "",
                "source": "grounding",
                "container": "C1",
            },
            {
                "id": 2,
                "bbox": [32, 82, 95, 24],
                "type": "text",
                "text": "Card title",
                "role": "",
                "source": "grounding",
                "container": "C2",
            },
            {
                "id": 3,
                "bbox": [32, 130, 80, 28],
                "type": "button",
                "text": "Open",
                "role": "",
                "source": "grounding",
                "container": "C2",
            },
            {
                "id": 4,
                "bbox": [210, 70, 60, 60],
                "type": "image",
                "text": "",
                "role": "",
                "source": "grounding",
                "container": None,
            },
        ],
        "provenance": {"route": "grounding", "fallbacks": [], "warnings": []},
    }
    strategy = {
        "requested": "auto",
        "selected": "grounding",
        "attempts": [{"strategy": "grounding", "status": "selected"}],
        "fallback_used": False,
        "policy": "grounding-default-cv-only-when-unavailable",
    }
    return path, graph, strategy


class ImageContractTests(unittest.TestCase):
    def test_reference_records_faithful_pixels_and_explicit_unknowns(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path, _graph, _strategy = _fixture(Path(raw_dir))
            expected_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            reference = inspect_image_reference(path, reference_id="IMG-MVP-01")

        self.assertEqual(reference["reference_id"], "IMG-MVP-01")
        self.assertEqual(reference["input"]["size"], [400, 220])
        self.assertEqual(
            reference["input"]["sha256"],
            expected_sha256,
        )
        self.assertEqual(reference["state"]["mode"], "faithful")
        self.assertEqual(reference["state"]["dpr"], "unknown")
        self.assertEqual(reference["state"]["viewport"], "unknown")
        self.assertEqual(reference["state"]["font_identity"], "unknown")
        self.assertIn("original-asset", reference["cannot_claim"])

    def test_design_samples_surfaces_and_never_uses_text_box_as_background(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path, graph, _strategy = _fixture(Path(raw_dir))
            reference = inspect_image_reference(path)
            design = build_image_design(graph, reference)

        by_id = {str(element["id"]): element for element in design["elements"]}
        self.assertEqual(by_id["C1"]["style"]["fillColor"], "#24324a")
        self.assertEqual(by_id["C2"]["style"]["fillColor"], "#ffffff")
        text_color = _rgb(by_id["1"]["style"]["textColor"])
        self.assertGreater(sum(text_color), 700)
        self.assertNotIn("fillColor", by_id["1"]["style"])
        button = by_id["3"]
        self.assertEqual(button["style"]["fillColor"], "#2f6fed")
        self.assertGreater(sum(_rgb(button["style"]["textColor"])), 700)
        self.assertEqual(
            design["_meta"]["imagePresentation"],
            "grounding-pixel-sampled-fixed-coordinate",
        )

    def test_image_element_keeps_reference_only_asset_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path, graph, _strategy = _fixture(Path(raw_dir))
            reference = inspect_image_reference(path)
            design = build_image_design(graph, reference)

        image = next(element for element in design["elements"] if element["id"] == "4")
        record = image["assetIdentity"]["asset_record"]
        self.assertTrue(image["imageBase64"])
        self.assertEqual(record["source_identity"]["status"], "unavailable")
        self.assertEqual(record["display_payload"]["kind"], "screenshot-crop")
        self.assertFalse(record["display_payload"]["original"])
        self.assertTrue(record["display_payload"]["reference_only"])
        self.assertFalse(image["sourceResolution"]["display"]["generated"])
        self.assertFalse(image["sourceResolution"]["identity"]["original"])

    def test_logo_display_includes_full_white_brand_container(self) -> None:
        image_path = Path(
            "tests/fixtures/image_to_slice_benchmark_2026-11-02/"
            "IMG-FLEXWEAVER-ADMIN.png"
        )
        graph = {
            "image": str(image_path),
            "image_w": 1920,
            "image_h": 826,
            "route": "grounding",
            "containers": [],
            "elements": [
                {
                    "id": 1,
                    "bbox": [15, 16, 215, 48],
                    "type": "image",
                    "text": "",
                    "assetName": "tetuo_auto_logo",
                    "assetKind": "logo",
                    "visibleCrop": {
                        "status": "available",
                        "display_box": [17, 18, 194, 30],
                        "source_rect": [17, 18, 194, 30],
                        "requested_bbox": [15, 16, 215, 48],
                    },
                }
            ],
            "imageEnrichment": {"mode": "apply"},
            "provenance": {"route": "grounding"},
        }

        design = build_image_design(graph, inspect_image_reference(image_path))

        logo = next(
            element
            for element in design["elements"]
            if element.get("assetName") == "tetuo_auto_logo"
        )
        self.assertEqual(
            [logo["x"], logo["y"], logo["width"], logo["height"]],
            [12, 11, 206, 50],
        )
        self.assertEqual(logo["assetIdentity"]["bbox"], [17, 18, 194, 30])

    def test_header_avatar_and_badge_use_visible_bounds(self) -> None:
        image_path = Path(
            "tests/fixtures/image_to_slice_benchmark_2026-11-02/"
            "IMG-FLEXWEAVER-ADMIN.png"
        )
        graph = {
            "image": str(image_path),
            "image_w": 1920,
            "image_h": 826,
            "route": "grounding",
            "containers": [],
            "elements": [
                {
                    "id": 1,
                    "bbox": [1713, 24, 61, 32],
                    "type": "avatar",
                    "text": "",
                    "assetName": "user_avatar_li_zhiqiang",
                    "assetKind": "avatar",
                    "visibleCrop": {
                        "display_box": [1713, 24, 61, 32],
                        "requested_bbox": [1713, 24, 61, 32],
                        "source_rect": [1713, 24, 61, 32],
                    },
                },
                {
                    "id": 2,
                    "bbox": [1597, 20, 47, 24],
                    "type": "image",
                    "text": "",
                    "assetName": "notification_badge_30",
                    "assetKind": "icon",
                    "visibleCrop": {
                        "display_box": [1599, 22, 20, 20],
                        "requested_bbox": [1597, 20, 47, 24],
                        "source_rect": [1599, 22, 20, 20],
                    },
                },
            ],
            "imageEnrichment": {"mode": "apply"},
            "provenance": {"route": "grounding"},
        }

        design = build_image_design(graph, inspect_image_reference(image_path))

        by_name = {
            element["assetName"]: element
            for element in design["elements"]
            if element.get("assetName")
        }
        avatar = by_name["user_avatar_li_zhiqiang"]
        self.assertEqual(
            [avatar["x"], avatar["y"], avatar["width"], avatar["height"]],
            [1710, 10, 39, 39],
        )
        self.assertEqual(avatar["assetIdentity"]["bbox"], [1713, 24, 61, 32])
        badge = by_name["notification_badge_30"]
        self.assertEqual(
            [badge["x"], badge["y"], badge["width"], badge["height"]],
            [1577, 9, 49, 42],
        )

    def test_image_ir_keeps_candidate_fields_and_fixed_flow(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path, graph, strategy = _fixture(Path(raw_dir))
            reference = inspect_image_reference(path)
            design = build_image_design(graph, reference)
            image_ir = build_image_ir(graph, design, reference, strategy)

        text_node = next(node for node in image_ir["nodes"] if node["node_id"] == "1")
        self.assertEqual(
            text_node["fields"]["text"]["authority"],
            "grounding-vlm-candidate",
        )
        self.assertEqual(text_node["fields"]["text"]["status"], "candidate")
        self.assertEqual(
            text_node["fields"]["flow"]["value"],
            "fixed-coordinate",
        )
        self.assertEqual(text_node["fields"]["flow"]["status"], "candidate")
        self.assertEqual(image_ir["strategy"]["selected"], "grounding")
        self.assertEqual(image_ir["input"]["reference_id"], reference["reference_id"])
        self.assertTrue(any(asset["reference_only"] for asset in image_ir["assets"]))
        self.assertEqual(image_ir["counts"]["image_candidates"], 1)

    def test_cv_candidates_keep_cv_authority_in_design_and_ir(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path, graph, _strategy = _fixture(Path(raw_dir))
            graph["route"] = "cv"
            graph["provenance"] = {
                "route": "cv",
                "fallbacks": [],
                "warnings": [],
            }
            graph["containers"][0]["source"] = "cv:v2.4"
            graph["elements"][0]["source"] = "cv:ocr"
            graph["elements"][3]["source"] = "cv:omniparser"
            reference = inspect_image_reference(path)
            strategy = {
                "requested": "auto",
                "selected": "cv",
                "attempts": [
                    {
                        "strategy": "grounding",
                        "status": "unavailable",
                        "reason": "grounding-config-missing",
                    },
                    {"strategy": "cv", "status": "selected"},
                ],
                "fallback_used": True,
                "policy": "grounding-default-cv-only-when-unavailable",
            }
            design = build_image_design(graph, reference)
            image_ir = build_image_ir(graph, design, reference, strategy)

        design_by_id = {str(element["id"]): element for element in design["elements"]}
        self.assertEqual(
            design_by_id["C1"]["imageMVP"]["source"],
            "cv-container-candidate",
        )
        self.assertEqual(
            design_by_id["1"]["imageMVP"]["source"],
            "cv-ocr-candidate",
        )
        self.assertEqual(
            design_by_id["4"]["imageMVP"]["source"],
            "cv-omniparser-candidate",
        )
        nodes = {node["node_id"]: node for node in image_ir["nodes"]}
        self.assertEqual(
            nodes["1"]["fields"]["text"]["authority"],
            "cv-ocr-candidate",
        )
        self.assertEqual(
            nodes["4"]["fields"]["role"]["authority"],
            "cv-omniparser-candidate",
        )
        self.assertTrue(
            all(
                "grounding" not in str(value)
                for value in (
                    design_by_id["C1"]["imageMVP"]["source"],
                    design_by_id["1"]["imageMVP"]["source"],
                    design_by_id["4"]["imageMVP"]["source"],
                    nodes["1"]["fields"]["text"]["authority"],
                    nodes["4"]["fields"]["role"]["authority"],
                )
            )
        )

    def test_image_candidate_is_refined_to_saturated_visible_region(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "panel.png"
            image = Image.new("RGB", (400, 220), "#ffffff")
            draw = ImageDraw.Draw(image)
            draw.rectangle((220, 90, 299, 149), fill="#2f6fed")
            image.save(path)
            graph = {
                "image": str(path),
                "image_w": 400,
                "image_h": 220,
                "route": "grounding",
                "containers": [],
                "elements": [
                    {
                        "id": 14,
                        "bbox": [200, 70, 140, 100],
                        "type": "image",
                        "source": "grounding",
                    }
                ],
                "provenance": {"route": "grounding"},
            }
            reference = inspect_image_reference(path)
            design = build_image_design(graph, reference)

        image_element = design["elements"][0]
        self.assertEqual(
            [
                image_element["x"],
                image_element["y"],
                image_element["width"],
                image_element["height"],
            ],
            [220, 90, 80, 60],
        )

    def test_multiline_text_uses_ink_band_not_total_box_height_for_font_size(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "paragraph.png"
            image = Image.new("RGB", (400, 220), "#ffffff")
            draw = ImageDraw.Draw(image)
            draw.text((40, 100), "First line", fill="#172033")
            draw.text((40, 118), "Second line", fill="#172033")
            image.save(path)
            graph = {
                "image": str(path),
                "image_w": 400,
                "image_h": 220,
                "route": "grounding",
                "containers": [],
                "elements": [
                    {
                        "id": 7,
                        "bbox": [40, 96, 180, 44],
                        "type": "text",
                        "text": "First line Second line",
                        "source": "grounding",
                    }
                ],
                "provenance": {"route": "grounding"},
            }
            reference = inspect_image_reference(path)
            design = build_image_design(graph, reference)

        self.assertLessEqual(design["elements"][0]["style"]["fontSize"], 18)

    def test_ocr_supplement_fills_only_missing_candidate_text(self) -> None:
        graph = {
            "image": "sample.png",
            "image_w": 1200,
            "image_h": 800,
            "route": "grounding",
            "containers": [],
            "elements": [
                {
                    "id": 1,
                    "bbox": [36, 16, 168, 32],
                    "type": "text",
                    "text": "Northstar Admin",
                    "source": "grounding",
                },
                {
                    "id": 2,
                    "bbox": [444, 256, 144, 16],
                    "type": "text",
                    "text": "New customers",
                    "source": "grounding",
                },
            ],
            "provenance": {"route": "grounding"},
        }
        observations = [
            {
                "text": "Northstar Admin",
                "bbox": [38, 20, 178, 24],
                "confidence": 0.99,
            },
            {
                "text": "Overview",
                "bbox": [239, 25, 66, 16],
                "confidence": 0.94,
            },
            {
                "text": "Start import",
                "bbox": [1051, 113, 90, 18],
                "confidence": 0.81,
            },
            {
                "text": "New customers",
                "bbox": [443, 259, 106, 16],
                "confidence": 0.98,
            },
            {
                "text": "today",
                "bbox": [549, 256, 44, 22],
                "confidence": 1.0,
            },
            {
                "text": "View details",
                "bbox": [367, 477, 84, 16],
                "confidence": 0.99,
            },
        ]

        merged, report = merge_ocr_candidates(graph, observations)

        texts = [item["text"] for item in merged["elements"]]
        self.assertEqual(texts.count("Northstar Admin"), 1)
        self.assertIn("Overview", texts)
        self.assertIn("Start import", texts)
        self.assertIn("View details", texts)
        self.assertIn("New customers today", texts)
        self.assertEqual(report["added_count"], 4)
        self.assertEqual(report["source"], "ocr-supplement:easyocr")
        added = [
            item
            for item in merged["elements"]
            if str(item.get("source", "")).startswith("ocr-supplement:")
        ]
        self.assertTrue(added)
        self.assertTrue(
            all(item["imageMVPTextStatus"] == "ocr-candidate" for item in added)
        )
        self.assertEqual(
            len({item["id"] for item in merged["elements"]}), len(merged["elements"])
        )

    def test_ocr_language_selection_is_explicit_for_cjk_and_latin(self) -> None:
        latin = {
            "elements": [{"text": "Northstar Admin"}],
        }
        mixed = {
            "elements": [{"text": "卡片一"}],
        }

        self.assertEqual(select_ocr_languages(latin), ["en"])
        self.assertEqual(select_ocr_languages(mixed), ["ch_sim", "en"])

    def test_ocr_line_merge_does_not_join_right_to_left_stat_regions(self) -> None:
        graph = {
            "image": "sample.png",
            "image_w": 1200,
            "image_h": 800,
            "route": "grounding",
            "containers": [],
            "elements": [],
            "provenance": {"route": "grounding"},
        }
        observations = [
            {
                "text": "Fulfillment completion",
                "bbox": [817, 254, 159, 25],
                "confidence": 0.88,
            },
            {
                "text": "Pending orders",
                "bbox": [63, 257, 106, 20],
                "confidence": 0.65,
            },
            {
                "text": "New customers",
                "bbox": [443, 259, 106, 16],
                "confidence": 0.98,
            },
            {
                "text": "today",
                "bbox": [549, 256, 45, 23],
                "confidence": 1.0,
            },
        ]

        merged, report = merge_ocr_candidates(graph, observations)

        texts = [item["text"] for item in merged["elements"]]
        self.assertIn("Fulfillment completion", texts)
        self.assertIn("Pending orders", texts)
        self.assertIn("New customers today", texts)
        self.assertEqual(report["added_count"], 3)

    def test_ocr_line_merge_joins_adjacent_fragments_with_small_y_drift(self) -> None:
        graph = {
            "image": "sample.png",
            "image_w": 900,
            "image_h": 700,
            "route": "grounding",
            "containers": [],
            "elements": [],
            "provenance": {"route": "grounding"},
        }
        observations = [
            {
                "text": "The page contains an image element;",
                "bbox": [7, 80, 240, 21],
                "confidence": 0.95,
            },
            {
                "text": "CSS background image;",
                "bbox": [258, 78, 158, 24],
                "confidence": 0.99,
            },
            {
                "text": "and an inline SVG_",
                "bbox": [419, 79, 122, 18],
                "confidence": 1.0,
            },
        ]

        merged, report = merge_ocr_candidates(graph, observations)

        texts = [item["text"] for item in merged["elements"]]
        self.assertEqual(
            texts,
            [
                "The page contains an image element; CSS background image; and an inline SVG_"
            ],
        )
        self.assertEqual(report["line_count"], 1)
        self.assertEqual(report["added_count"], 1)

    def test_ocr_short_unit_merges_into_adjacent_numeric_owner(self) -> None:
        graph = {
            "image": "sample.png",
            "image_w": 2544,
            "image_h": 1336,
            "route": "grounding",
            "containers": [],
            "elements": [],
            "provenance": {"route": "grounding"},
        }
        observations = [
            {
                "text": "5.8",
                "bbox": [1061, 660, 109, 74],
                "confidence": 0.91,
            },
            {
                "text": "折",
                "bbox": [1097, 725, 42, 40],
                "confidence": 0.99,
            },
        ]

        merged, report = merge_ocr_candidates(graph, observations)

        self.assertEqual(
            [item["text"] for item in merged["elements"]],
            ["5.8折"],
        )
        self.assertTrue(merged["elements"][0]["logicalText"])
        self.assertEqual(report["added_count"], 1)
        self.assertEqual(report["logical_merge_count"], 1)
        self.assertEqual(report["skipped_count"], 0)
        self.assertEqual(report["logical_merges"][0]["unit"], "折")

    def test_ocr_short_unit_does_not_merge_across_large_gap(self) -> None:
        graph = {
            "image": "sample.png",
            "image_w": 2544,
            "image_h": 1336,
            "route": "grounding",
            "containers": [],
            "elements": [],
            "provenance": {"route": "grounding"},
        }
        observations = [
            {
                "text": "5.8",
                "bbox": [1061, 660, 109, 74],
                "confidence": 0.91,
            },
            {
                "text": "折",
                "bbox": [1300, 725, 42, 40],
                "confidence": 0.99,
            },
        ]

        merged, report = merge_ocr_candidates(graph, observations)

        self.assertEqual(
            [item["text"] for item in merged["elements"]],
            ["5.8"],
        )
        self.assertEqual(report["logical_merge_count"], 0)
        self.assertEqual(
            report["skipped"], [{"text": "折", "reason": "text-too-short"}]
        )

    def test_ocr_similar_spatially_overlapping_text_is_suppressed(self) -> None:
        graph = {
            "image": "sample.png",
            "image_w": 900,
            "image_h": 700,
            "route": "grounding",
            "containers": [],
            "elements": [
                {
                    "id": 1,
                    "bbox": [7, 80, 534, 21],
                    "type": "text",
                    "text": "The page contains an image element, a CSS background image, and an inline SVG.",
                    "source": "grounding",
                }
            ],
            "provenance": {"route": "grounding"},
        }
        observations = [
            {
                "text": "The page contains an image element; CSS background image; and an inline SVG_",
                "bbox": [7, 78, 534, 24],
                "confidence": 0.99,
            }
        ]

        merged, report = merge_ocr_candidates(graph, observations)

        self.assertEqual(len(merged["elements"]), 1)
        self.assertEqual(report["added_count"], 0)
        self.assertEqual(report["skipped"][0]["reason"], "already-covered")

    def test_ocr_substring_duplicate_requires_spatial_overlap(self) -> None:
        graph = {
            "image": "sample.png",
            "image_w": 1200,
            "image_h": 800,
            "route": "grounding",
            "containers": [],
            "elements": [
                {
                    "id": 1,
                    "bbox": [63, 257, 106, 20],
                    "type": "text",
                    "text": "Pending orders",
                    "source": "grounding",
                }
            ],
            "provenance": {"route": "grounding"},
        }
        observations = [
            {
                "text": "Orders",
                "bbox": [325, 25, 50, 16],
                "confidence": 0.99,
            }
        ]

        merged, report = merge_ocr_candidates(graph, observations)

        self.assertIn("Orders", [item["text"] for item in merged["elements"]])
        self.assertEqual(report["added_count"], 1)

    def test_ocr_identical_text_at_another_type_scale_is_kept(self) -> None:
        """The nav label and the h1 may share a string; both must survive.

        dark-card-grid: ``模型广场`` is a 130x42 menu item at y=35 and a
        395x120 heading at y=251.  Suppressing the second instance by text
        alone silently removes the selected nav tab from the design -- and the
        critical-text gate stays green because the heading still matches.
        """
        graph = {
            "image": "sample.png",
            "image_w": 2544,
            "image_h": 1336,
            "route": "grounding",
            "containers": [],
            "elements": [
                {
                    "id": 1,
                    "bbox": [90, 251, 395, 120],
                    "type": "text",
                    "text": "模型广场",
                    "source": "grounding",
                }
            ],
            "provenance": {"route": "grounding"},
        }
        observations = [
            {"text": "模型广场", "bbox": [561, 35, 130, 42], "confidence": 0.96}
        ]

        merged, report = merge_ocr_candidates(graph, observations)

        texts = [item["text"] for item in merged["elements"]]
        self.assertEqual(texts.count("模型广场"), 2)
        self.assertEqual(report["added_count"], 1)

    def test_ocr_identical_text_same_scale_elsewhere_is_still_suppressed(self) -> None:
        """Per-row repeats keep one candidate: table/form synthesis owns them.

        light-table repeats ``(选填)`` in eight rows at the same 30-32 px size.
        Adding every instance here would double-emit what the table grid
        already produces, so identical text at one type scale stays a
        duplicate even when the boxes do not overlap.
        """
        graph = {
            "image": "sample.png",
            "image_w": 2544,
            "image_h": 1336,
            "route": "grounding",
            "containers": [],
            "elements": [
                {
                    "id": 1,
                    "bbox": [948, 846, 72, 30],
                    "type": "text",
                    "text": "(选填)",
                    "source": "grounding",
                }
            ],
            "provenance": {"route": "grounding"},
        }
        observations = [
            {"text": "(选填)", "bbox": [948, 926, 72, 32], "confidence": 0.97}
        ]

        merged, report = merge_ocr_candidates(graph, observations)

        self.assertEqual(len(merged["elements"]), 1)
        self.assertEqual(report["added_count"], 0)
        self.assertEqual(report["skipped"][0]["reason"], "already-covered")

    def test_ocr_identical_text_jittered_box_is_still_suppressed(self) -> None:
        """Same place, slightly different box: one physical label, not two.

        Partially overlapping boxes (not nested -- a nested one is handled by
        the full-line replacement branch) still describe one label; the centre
        distance is a fraction of the box width.
        """
        graph = {
            "image": "sample.png",
            "image_w": 2544,
            "image_h": 1336,
            "route": "grounding",
            "containers": [],
            "elements": [
                {
                    "id": 1,
                    "bbox": [200, 200, 60, 28],
                    "type": "text",
                    "text": "控制台",
                    "source": "grounding",
                }
            ],
            "provenance": {"route": "grounding"},
        }
        observations = [
            {"text": "控制台", "bbox": [215, 202, 60, 30], "confidence": 0.98}
        ]

        merged, report = merge_ocr_candidates(graph, observations)

        self.assertEqual(len(merged["elements"]), 1)
        self.assertEqual(report["added_count"], 0)

    def test_ocr_full_line_replaces_covered_cv_text_fragments(self) -> None:
        graph = {
            "image": "sample.png",
            "image_w": 1200,
            "image_h": 800,
            "route": "cv",
            "containers": [],
            "elements": [
                {
                    "bbox": [443, 259, 106, 16],
                    "type": "text",
                    "text": "New customers",
                    "source": "cv:ocr",
                },
                {
                    "bbox": [551, 256, 40, 22],
                    "type": "text",
                    "text": "today",
                    "source": "cv:ocr",
                },
                {
                    "bbox": [900, 400, 80, 20],
                    "type": "text",
                    "text": "Other text",
                    "source": "cv:ocr",
                },
            ],
            "provenance": {"route": "cv"},
        }
        observations = [
            {
                "text": "New customers today",
                "bbox": [443, 256, 151, 23],
                "confidence": 0.99,
            }
        ]

        merged, report = merge_ocr_candidates(graph, observations)

        texts = [item["text"] for item in merged["elements"]]
        self.assertEqual(set(texts), {"New customers today", "Other text"})
        self.assertEqual(report["added_count"], 1)
        self.assertEqual(report["replaced_covered_count"], 2)
        self.assertEqual(
            {item["text"] for item in report["replaced_covered"]},
            {"New customers", "today"},
        )

    def test_non_text_cv_rectangle_caption_is_not_rendered_as_text(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path, graph, _strategy = _fixture(Path(raw_dir))
            graph["route"] = "cv"
            graph["elements"].append(
                {
                    "id": 99,
                    "bbox": [210, 70, 60, 60],
                    "type": "rectangle",
                    "text": "A map or photo app.",
                    "role": "",
                    "source": "cv:omniparser",
                    "container": None,
                }
            )
            reference = inspect_image_reference(path)
            design = build_image_design(graph, reference)

        by_id = {str(element["id"]): element for element in design["elements"]}
        self.assertEqual(by_id["99"]["type"], "rectangle")
        self.assertEqual(by_id["99"]["text"], "")
        self.assertEqual(by_id["1"]["text"], "Workspace")

    def test_ocr_same_normalized_text_replaces_bad_cv_spacing(self) -> None:
        graph = {
            "image": "sample.png",
            "image_w": 1200,
            "image_h": 800,
            "route": "cv",
            "containers": [],
            "elements": [
                {
                    "bbox": [1051, 113, 90, 18],
                    "type": "text",
                    "text": "Startimport",
                    "source": "cv:ocr",
                }
            ],
            "provenance": {"route": "cv"},
        }
        observations = [
            {
                "text": "Start import",
                "bbox": [1051, 113, 90, 18],
                "confidence": 0.99,
            }
        ]

        merged, report = merge_ocr_candidates(graph, observations)

        self.assertEqual(
            [item["text"] for item in merged["elements"]], ["Start import"]
        )
        self.assertEqual(report["replaced_covered_count"], 1)
        self.assertEqual(report["added"][0]["source"], "ocr-supplement:easyocr")

    def test_ocr_merge_ignores_non_text_caption_as_text_evidence(self) -> None:
        graph = {
            "image": "sample.png",
            "image_w": 1200,
            "image_h": 800,
            "route": "cv",
            "containers": [],
            "elements": [
                {
                    "bbox": [1026, 96, 134, 44],
                    "type": "rectangle",
                    "text": "Start import",
                    "source": "cv:omniparser",
                }
            ],
            "provenance": {"route": "cv"},
        }
        observations = [
            {
                "text": "Start import",
                "bbox": [1051, 113, 90, 18],
                "confidence": 0.99,
            }
        ]

        merged, report = merge_ocr_candidates(graph, observations)

        self.assertEqual(report["added_count"], 1)
        self.assertEqual(report["skipped_count"], 0)
        self.assertEqual(
            [item["source"] for item in merged["elements"]],
            ["cv:omniparser", "ocr-supplement:easyocr"],
        )

    def test_ocr_precise_cells_replace_one_overlong_merged_row(self) -> None:
        graph = {
            "image": "sample.png",
            "image_w": 1200,
            "image_h": 800,
            "route": "cv",
            "containers": [],
            "elements": [
                {
                    "bbox": [300, 700, 800, 40],
                    "type": "text",
                    "text": "4 2026-10-29 03:30:00 30939 auto 2026-10-26 11:22:28 2",
                    "source": "cv:omniparser",
                }
            ],
            "provenance": {"route": "cv"},
        }
        observations = [
            {
                "text": "2026-10-29 03:30:00",
                "bbox": [400, 700, 160, 20],
                "confidence": 0.99,
            },
            {
                "text": "30939",
                "bbox": [650, 700, 60, 20],
                "confidence": 0.99,
            },
        ]

        merged, report = merge_ocr_candidates(graph, observations)

        self.assertEqual(
            [item["text"] for item in merged["elements"]],
            ["2026-10-29 03:30:00", "30939"],
        )
        self.assertEqual(report["replaced_covered_count"], 1)

    def test_image_region_recovery_finds_embedded_visual_but_not_header(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "dashboard.png"
            image = Image.new("RGB", (1200, 800), "#ffffff")
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 1199, 63), fill="#26364f")
            draw.rectangle((68, 352, 327, 571), fill="#2f6fed")
            draw.ellipse((220, 380, 280, 440), fill="#f2b84b")
            image.save(path)
            graph = {
                "image": str(path),
                "image_w": 1200,
                "image_h": 800,
                "route": "grounding",
                "containers": [
                    {
                        "id": "C1",
                        "bbox": [0, 0, 1200, 64],
                        "type": "container",
                        "source": "grounding",
                    }
                ],
                "elements": [],
                "provenance": {"route": "grounding"},
            }

            recovered, report = recover_image_region_candidates(graph, path)

        self.assertEqual(report["added_count"], 1)
        image_elements = [
            item for item in recovered["elements"] if item["type"] == "image"
        ]
        self.assertEqual(len(image_elements), 1)
        self.assertEqual(image_elements[0]["bbox"], [68, 352, 260, 220])

    def test_white_text_on_small_surface_becomes_button_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "button.png"
            image = Image.new("RGB", (500, 220), "#ffffff")
            draw = ImageDraw.Draw(image)
            draw.rectangle((40, 40, 179, 79), fill="#2f6fed")
            draw.text((60, 51), "Start", fill="#ffffff")
            image.save(path)
            graph = {
                "image": str(path),
                "image_w": 500,
                "image_h": 220,
                "route": "grounding",
                "containers": [],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [60, 51, 50, 16],
                        "type": "text",
                        "text": "Start",
                        "source": "ocr-supplement:easyocr",
                    }
                ],
                "provenance": {"route": "grounding"},
            }
            reference = inspect_image_reference(path)
            design = build_image_design(graph, reference)

        element = design["elements"][0]
        self.assertEqual(element["type"], "button")
        self.assertEqual(
            [element["x"], element["y"], element["width"], element["height"]],
            [40, 40, 140, 40],
        )
        self.assertEqual(element["style"]["fillColor"], "#2f6fed")

    def test_recovered_asset_becomes_figma_image_payload_and_underlay_is_skipped(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            path = root / "asset-map.png"
            image = Image.new("RGB", (400, 220), "#ffffff")
            draw = ImageDraw.Draw(image)
            draw.rectangle((220, 90, 299, 149), fill="#2f6fed")
            draw.text((50, 30), "Title", fill="#172033")
            draw.rectangle((50, 70, 129, 99), fill="#335577")
            image.save(path)
            graph = {
                "image": str(path),
                "image_w": 400,
                "image_h": 220,
                "route": "grounding",
                "containers": [],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [50, 30, 80, 20],
                        "type": "text",
                        "text": "Title",
                        "source": "grounding",
                    },
                    {
                        "id": 2,
                        "bbox": [50, 70, 80, 30],
                        "type": "button",
                        "text": "Save",
                        "source": "grounding",
                    },
                ],
                "imageEnrichment": {
                    "assets": [
                        {
                            "name": "blue_cover",
                            "kind": "illustration",
                            "bbox": [220, 90, 80, 60],
                            "critical": False,
                        },
                        {
                            "name": "full_page_underlay",
                            "kind": "screenshot",
                            "bbox": [0, 0, 400, 220],
                            "critical": False,
                        },
                    ]
                },
                "provenance": {"route": "grounding"},
            }
            recovered, report = recover_visible_assets(
                graph,
                path,
                work_dir=root / "work",
            )
            reference = inspect_image_reference(path)
            design = build_image_design(recovered, reference)

        images = [
            element for element in design["elements"] if element["type"] == "image"
        ]
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0]["imageBase64"])
        self.assertTrue(images[0]["imageMVP"]["reference_only"])
        self.assertFalse(images[0]["imageMVP"]["generated"])
        self.assertEqual(images[0]["assetName"], "blue_cover")
        self.assertEqual(images[0]["assetKind"], "illustration")
        self.assertEqual(
            images[0]["displayPayload"]["payload_sha256"],
            images[0]["visibleCrop"]["payload_sha256"],
        )
        self.assertEqual(report["underlay_count"], 1)
        self.assertEqual(
            design["_meta"]["imageMVP"]["referenceUnderlays"][0]["name"],
            "full_page_underlay",
        )

    def test_enriched_text_uses_script_specific_fonts_and_line_height(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "fonts.png"
            Image.new("RGB", (400, 200), "#ffffff").save(path)
            graph = {
                "image": str(path),
                "image_w": 400,
                "image_h": 200,
                "route": "grounding",
                "containers": [],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [20, 20, 120, 24],
                        "type": "text",
                        "text": "自动备份",
                    },
                    {
                        "id": 2,
                        "bbox": [20, 60, 120, 24],
                        "type": "text",
                        "text": "auto_backup",
                    },
                ],
                "imageEnrichment": {"mode": "apply"},
                "provenance": {"route": "grounding"},
            }

            design = build_image_design(graph, inspect_image_reference(path))

        by_text = {
            element["text"]: element
            for element in design["elements"]
            if element["type"] == "text"
        }
        self.assertIn("Noto Sans SC", by_text["自动备份"]["style"]["fontFamily"])
        self.assertIn("Arimo", by_text["auto_backup"]["style"]["fontFamily"])
        self.assertGreaterEqual(by_text["自动备份"]["style"]["lineHeight"], 24)

    def test_enriched_text_uses_visible_ink_origin(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "ink.png"
            image = Image.new("RGB", (320, 120), "#ffffff")
            draw = ImageDraw.Draw(image)
            draw.text((42, 30), "Backup", fill="#333333")
            image.save(path)
            graph = {
                "image": str(path),
                "image_w": 320,
                "image_h": 120,
                "route": "grounding",
                "containers": [],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [34, 20, 160, 24],
                        "type": "text",
                        "text": "Backup",
                    }
                ],
                "imageEnrichment": {"mode": "apply"},
                "provenance": {"route": "grounding"},
            }

            design = build_image_design(graph, inspect_image_reference(path))

        text = next(
            element for element in design["elements"] if element.get("text") == "Backup"
        )
        self.assertGreaterEqual(text["x"], 42)

    def test_enriched_status_text_recovers_green_ink_position(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "status.png"
            image = Image.new("RGB", (400, 260), "#ffffff")
            draw = ImageDraw.Draw(image)
            draw.text((120, 60), "SUCCESS", fill="#008000")
            image.save(path)
            graph = {
                "image": str(path),
                "image_w": 400,
                "image_h": 260,
                "route": "grounding",
                "containers": [],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [80, 120, 120, 24],
                        "type": "text",
                        "text": "SUCCESS",
                    }
                ],
                "imageEnrichment": {"mode": "apply"},
                "provenance": {"route": "grounding"},
            }

            design = build_image_design(graph, inspect_image_reference(path))

        text = next(
            element
            for element in design["elements"]
            if element.get("text") == "SUCCESS"
        )
        self.assertLess(text["y"], 80)
        self.assertLessEqual(text["style"]["fontSize"], 16)
        red, green, blue = _rgb(text["style"]["textColor"])
        self.assertGreater(green, red)
        self.assertGreater(green, blue)

    def test_enriched_design_preserves_container_child_hierarchy(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "hierarchy.png"
            Image.new("RGB", (400, 300), "#ffffff").save(path)
            graph = {
                "image": str(path),
                "image_w": 400,
                "image_h": 300,
                "route": "grounding",
                "containers": [
                    {
                        "id": "C1",
                        "bbox": [0, 0, 400, 300],
                        "role": "page",
                    },
                    {
                        "id": "C2",
                        "bbox": [20, 20, 180, 100],
                        "role": "panel",
                        "parent": "C1",
                    },
                ],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [30, 30, 100, 24],
                        "type": "text",
                        "text": "Inside",
                        "container": "C2",
                    },
                    {
                        "id": 2,
                        "bbox": [30, 200, 100, 24],
                        "type": "text",
                        "text": "Sibling",
                        "container": "C1",
                    },
                ],
                "imageEnrichment": {"mode": "apply"},
                "provenance": {"route": "grounding"},
            }

            design = build_image_design(graph, inspect_image_reference(path))

        by_id = {element["id"]: element for element in design["elements"]}
        self.assertIn("C2", {item["id"] for item in by_id["C1"]["layoutChildren"]})
        self.assertIn("2", {item["id"] for item in by_id["C1"]["layoutChildren"]})
        self.assertEqual(
            [item["id"] for item in by_id["C2"]["layoutChildren"]],
            ["1"],
        )

    def test_enriched_breadcrumb_uses_main_content_header_line(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "breadcrumb.png"
            Image.new("RGB", (320, 140), "#ffffff").save(path)
            graph = {
                "image": str(path),
                "image_w": 320,
                "image_h": 140,
                "route": "grounding",
                "containers": [
                    {
                        "id": "C1",
                        "bbox": [0, 0, 320, 80],
                        "role": "main-content",
                    }
                ],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [30, 50, 120, 24],
                        "type": "text",
                        "text": "自动备份",
                    }
                ],
                "imageEnrichment": {"mode": "apply"},
                "provenance": {"route": "grounding"},
            }

            design = build_image_design(graph, inspect_image_reference(path))

        text = next(
            element
            for element in design["elements"]
            if element.get("text") == "自动备份"
        )
        self.assertEqual(text["x"], 46)
        self.assertEqual(text["y"], 17)
        self.assertEqual(text["width"], 80)
        self.assertEqual(text["style"]["fontSize"], 18)

    def test_enriched_design_recovers_horizontal_surface_band(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "band.png"
            image = Image.new("RGB", (400, 200), "#ffffff")
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 40, 399, 89), fill="#eeeeee")
            draw.text((20, 55), "Section", fill="#333333")
            image.save(path)
            graph = {
                "image": str(path),
                "image_w": 400,
                "image_h": 200,
                "route": "grounding",
                "containers": [
                    {
                        "id": "C1",
                        "bbox": [0, 0, 400, 200],
                        "role": "main-content",
                    }
                ],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [20, 55, 80, 20],
                        "type": "text",
                        "text": "Section",
                    }
                ],
                "imageEnrichment": {"mode": "apply"},
                "provenance": {"route": "grounding"},
            }

            design = build_image_design(graph, inspect_image_reference(path))

        bands = [
            element
            for element in design["elements"]
            if element.get("role") == "surface-band"
        ]
        self.assertEqual(len(bands), 1)
        self.assertEqual(bands[0]["y"], 40)
        self.assertEqual(bands[0]["height"], 50)
        self.assertEqual(bands[0]["style"]["fillColor"].lower(), "#eeeeee")

    def test_enriched_design_recovers_table_search_field(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "search.png"
            image = Image.new("RGB", (420, 180), "#ffffff")
            draw = ImageDraw.Draw(image)
            draw.rectangle((171, 51, 337, 86), outline="#c2cad8")
            draw.text((187, 61), "表内搜索", fill="#999999")
            image.save(path)
            graph = {
                "image": str(path),
                "image_w": 420,
                "image_h": 180,
                "route": "grounding",
                "containers": [
                    {
                        "id": "C1",
                        "bbox": [0, 0, 420, 180],
                        "role": "main-content",
                    }
                ],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [187, 61, 62, 20],
                        "type": "text",
                        "text": "表内搜索",
                    }
                ],
                "imageEnrichment": {"mode": "apply"},
                "provenance": {"route": "grounding"},
            }

            design = build_image_design(graph, inspect_image_reference(path))

        search = next(
            element
            for element in design["elements"]
            if element.get("id") == "recovered-table-search"
        )
        self.assertEqual(search["type"], "input")
        self.assertEqual(
            [search["x"], search["y"], search["width"], search["height"]],
            [171, 51, 168, 36],
        )
        self.assertEqual(search["controlValue"], "")

    def test_enriched_design_keeps_one_owner_for_overlapping_same_text(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "owners.png"
            Image.new("RGB", (400, 200), "#ffffff").save(path)
            graph = {
                "image": str(path),
                "image_w": 400,
                "image_h": 200,
                "route": "grounding",
                "containers": [],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [20, 20, 240, 40],
                        "type": "button",
                        "text": "0 30 3 * * ?",
                    },
                    {
                        "id": 2,
                        "bbox": [20, 20, 240, 40],
                        "type": "input",
                        "text": "0 30 3 * * ?",
                        "controlType": "input",
                        "controlValue": "0 30 3 * * ?",
                    },
                    {
                        "id": 3,
                        "bbox": [20, 80, 80, 24],
                        "type": "text",
                        "text": "auto",
                    },
                    {
                        "id": 4,
                        "bbox": [20, 120, 80, 24],
                        "type": "text",
                        "text": "auto",
                    },
                ],
                "imageEnrichment": {"mode": "apply"},
                "provenance": {"route": "grounding"},
            }

            design = build_image_design(graph, inspect_image_reference(path))

        auto = [
            element
            for element in design["elements"]
            if (element.get("controlValue") or element.get("text")) == "auto"
        ]
        schedule = [
            element
            for element in design["elements"]
            if (element.get("controlValue") or element.get("text")) == "0 30 3 * * ?"
        ]
        self.assertEqual([element["type"] for element in schedule], ["input"])
        self.assertEqual(len(auto), 2)

    def test_enriched_input_places_value_from_text_box_origin(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "input.png"
            Image.new("RGB", (320, 120), "#ffffff").save(path)
            graph = {
                "image": str(path),
                "image_w": 320,
                "image_h": 120,
                "route": "grounding",
                "containers": [],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [20, 20, 200, 40],
                        "type": "input",
                        "text": "",
                        "controlType": "input",
                        "controlValue": "auto_backup",
                    },
                    {
                        "id": 2,
                        "bbox": [32, 30, 98, 20],
                        "type": "text",
                        "text": "auto_backup",
                    },
                ],
                "imageEnrichment": {"mode": "apply"},
                "provenance": {"route": "grounding"},
            }

            design = build_image_design(graph, inspect_image_reference(path))

        inputs = [
            element for element in design["elements"] if element.get("type") == "input"
        ]
        self.assertEqual(len(inputs), 1)
        self.assertEqual(inputs[0]["textBox"], [33, 31, 176, 20])

    def test_enriched_input_samples_visible_border_color(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "border.png"
            image = Image.new("RGB", (320, 120), "#ffffff")
            draw = ImageDraw.Draw(image)
            draw.rectangle((20, 20, 219, 59), fill="#ffffff", outline="#c2cad8")
            image.save(path)
            graph = {
                "image": str(path),
                "image_w": 320,
                "image_h": 120,
                "route": "grounding",
                "containers": [],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [20, 20, 200, 40],
                        "type": "input",
                        "text": "",
                        "controlType": "input",
                        "controlValue": "Value",
                    }
                ],
                "imageEnrichment": {"mode": "apply"},
                "provenance": {"route": "grounding"},
            }

            design = build_image_design(graph, inspect_image_reference(path))

        text_input = next(
            element for element in design["elements"] if element.get("type") == "input"
        )
        self.assertEqual(text_input["style"]["borderColor"], "#c2cad8")

    def test_enriched_input_uses_visible_value_ink_box(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "value.png"
            image = Image.new("RGB", (320, 120), "#ffffff")
            draw = ImageDraw.Draw(image)
            draw.rectangle((20, 20, 219, 59), fill="#ffffff", outline="#c2cad8")
            draw.text((42, 30), "Value", fill="#333333")
            image.save(path)
            graph = {
                "image": str(path),
                "image_w": 320,
                "image_h": 120,
                "route": "grounding",
                "containers": [],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [20, 20, 200, 40],
                        "type": "input",
                        "text": "",
                        "controlType": "input",
                        "controlValue": "Value",
                    }
                ],
                "imageEnrichment": {"mode": "apply"},
                "provenance": {"route": "grounding"},
            }

            design = build_image_design(graph, inspect_image_reference(path))

        text_input = next(
            element for element in design["elements"] if element.get("type") == "input"
        )
        self.assertTrue(40 <= text_input["textBox"][0] <= 43)
        self.assertTrue(27 <= text_input["textBox"][1] <= 30)

    def test_enriched_input_owns_near_duplicate_ocr_text(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "textarea.png"
            Image.new("RGB", (480, 160), "#ffffff").save(path)
            graph = {
                "image": str(path),
                "image_w": 480,
                "image_h": 160,
                "route": "grounding",
                "containers": [],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [20, 20, 400, 80],
                        "type": "input",
                        "text": "",
                        "controlType": "textarea",
                        "controlValue": "2023年12月16日：修改成凌晨3：30执行备份",
                    },
                    {
                        "id": 2,
                        "bbox": [32, 29, 340, 24],
                        "type": "text",
                        "text": "2023年12月16日: 修改成麦晨3: 30执行备份",
                    },
                ],
                "imageEnrichment": {"mode": "apply"},
                "provenance": {"route": "grounding"},
            }

            design = build_image_design(graph, inspect_image_reference(path))

        texts = [element for element in design["elements"] if element.get("text")]
        self.assertEqual([element["type"] for element in texts], ["input"])
        self.assertEqual(texts[0]["textBox"], [33, 30, 376, 24])

    def test_enriched_checkbox_prefers_adjacent_label_text(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "checkbox.png"
            Image.new("RGB", (240, 100), "#ffffff").save(path)
            graph = {
                "image": str(path),
                "image_w": 240,
                "image_h": 100,
                "route": "grounding",
                "containers": [],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [120, 30, 20, 20],
                        "type": "checkbox",
                        "text": "",
                        "controlType": "checkbox",
                        "controlValue": "以auto用户身份执行",
                        "controlState": "checked",
                    },
                    {
                        "id": 2,
                        "bbox": [20, 30, 92, 20],
                        "type": "text",
                        "text": "Wauto用户身份执行",
                    },
                ],
                "imageEnrichment": {"mode": "apply"},
                "provenance": {"route": "grounding"},
            }

            design = build_image_design(graph, inspect_image_reference(path))

        checkbox = next(
            element
            for element in design["elements"]
            if element.get("controlType") == "checkbox"
        )
        label = next(
            element
            for element in design["elements"]
            if element.get("text") == "以auto用户身份执行"
        )
        self.assertEqual(checkbox["text"], "")
        self.assertEqual(label["type"], "text")

    def test_checked_checkbox_creates_vector_and_standalone_label(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "checked.png"
            Image.new("RGB", (240, 100), "#ffffff").save(path)
            graph = {
                "image": str(path),
                "image_w": 240,
                "image_h": 100,
                "route": "grounding",
                "containers": [],
                "elements": [
                    {
                        "id": 1,
                        "bbox": [20, 30, 24, 21],
                        "type": "checkbox",
                        "text": "",
                        "controlType": "checkbox",
                        "controlValue": "执行成功",
                        "controlState": "checked",
                    }
                ],
                "imageEnrichment": {"mode": "apply"},
                "provenance": {"route": "grounding"},
            }

            design = build_image_design(graph, inspect_image_reference(path))

        checkbox = next(
            element
            for element in design["elements"]
            if element.get("controlType") == "checkbox"
        )
        label = next(
            element
            for element in design["elements"]
            if element.get("text") == "执行成功"
        )
        check = next(
            element
            for element in design["elements"]
            if element.get("assetName") == "check"
        )
        self.assertEqual(checkbox["text"], "")
        self.assertEqual(checkbox["style"]["borderWidth"], 0)
        self.assertEqual(label["x"], 49)
        self.assertTrue(check["vectorSvg"].startswith("<svg"))


if __name__ == "__main__":
    unittest.main()


def test_ocr_merge_keeps_a_long_paragraph_and_attaches_line_boxes() -> None:
    """A wrapped paragraph keeps the grounder's text and gains OCR line boxes.

    The paragraph was deleted by the "overlong" branch because one OCR line was
    a fragment of it, while the OCR line that could have rebuilt it had already
    been skipped as "already-covered".  Net result was a four-character stub.
    Text must stay authoritative; OCR only supplies the line geometry.
    """
    paragraph = "系统正在对当前内容进行安全审核，请保持页面开启。审核完成后，系统会更新处理状态。"
    graph = {
        "elements": [
            {
                "id": 7,
                "type": "text",
                "text": paragraph,
                "bbox": [238, 500, 1075, 65],
                "source": "grounding",
            }
        ],
        "containers": [],
    }
    observations = [
        {
            "text": "系统正在对当前内容进行安全审核。请保持页面开启。审核完成后。系统会更新",
            "bbox": [239, 499, 856, 36],
            "confidence": 0.91,
        },
        {"text": "处理状态。", "bbox": [239, 545, 116, 36], "confidence": 0.99},
    ]

    merged, report = merge_ocr_candidates(graph, observations)

    assert [item["text"] for item in merged["elements"]] == [paragraph]
    measured = merged["elements"][0]["measuredLines"]
    assert len(measured) == 2
    assert "".join(line["text"] for line in measured) == paragraph
    assert [line["box"] for line in measured] == [
        [239, 499, 856, 36],
        [239, 545, 116, 36],
    ]
    assert report["attached_line_group_count"] == 1
    assert report["replaced_covered_count"] == 0
    assert report["added_count"] == 0


def test_ocr_merge_never_deletes_a_paragraph_for_a_single_fragment() -> None:
    """One covering fragment is not a rebuild plan, so the paragraph stays."""
    paragraph = "系统正在对当前内容进行安全审核，请保持页面开启。审核完成后，系统会更新处理状态。"
    graph = {
        "elements": [
            {
                "id": 3,
                "type": "text",
                "text": paragraph,
                "bbox": [238, 500, 1075, 65],
                "source": "grounding",
            }
        ],
        "containers": [],
    }

    merged, report = merge_ocr_candidates(
        graph,
        [{"text": "处理状态。", "bbox": [239, 545, 116, 36], "confidence": 0.99}],
    )

    assert [item["text"] for item in merged["elements"]] == [paragraph]
    assert "measuredLines" not in merged["elements"][0]
    # The lone fragment is redundant with the paragraph text, so it is not
    # added either -- the paragraph keeps the content.
    assert report["added_count"] == 0
    assert report["replaced_covered_count"] == 0


def test_ocr_merge_attaches_lines_when_no_line_is_overlong() -> None:
    """Two short lines inside one element still describe a wrapped paragraph.

    The right-hand paragraph was never "overlong" against a single line, so the
    overlong branch never ran; both lines were then skipped as "already
    covered" and the element kept one flat 653x65 box.  The renderer drew that
    box as a single line that overflowed the column.  Line geometry must be
    attached whenever the stacked lines reproduce the element text, whatever
    their individual length.
    """
    paragraph = "我们会检查内容完整性、风险特征和访问环境，为页面提供稳定的安全保护。"
    graph = {
        "elements": [
            {
                "id": 11,
                "type": "text",
                "text": paragraph,
                "bbox": [1267, 439, 653, 65],
                "source": "grounding",
            }
        ],
        "containers": [],
    }
    observations = [
        {
            "text": "我们会检查内容完整性。风险特征和访问环",
            "bbox": [1266, 440, 412, 32],
            "confidence": 0.89,
        },
        {
            "text": "境;为页面提供稳定的安全保护。",
            "bbox": [1268, 478, 306, 30],
            "confidence": 0.65,
        },
    ]

    merged, report = merge_ocr_candidates(graph, observations)

    assert [item["text"] for item in merged["elements"]] == [paragraph]
    measured = merged["elements"][0]["measuredLines"]
    assert [line["box"] for line in measured] == [
        [1266, 440, 412, 32],
        [1268, 478, 306, 30],
    ]
    assert "".join(line["text"] for line in measured) == paragraph
    assert report["attached_line_group_count"] == 1
    assert report["added_count"] == 0


def test_ocr_merge_keeps_side_by_side_cells_out_of_line_geometry() -> None:
    """Cells on one row are not paragraph lines, even inside a wider box."""
    row = "工时管理个人信息展开查询我的工时看板"
    graph = {
        "elements": [
            {
                "id": 12,
                "type": "text",
                "text": row,
                "bbox": [100, 300, 900, 40],
                "source": "grounding",
            }
        ],
        "containers": [],
    }
    observations = [
        {"text": "工时管理", "bbox": [100, 302, 120, 36], "confidence": 0.93},
        {"text": "个人信息", "bbox": [300, 302, 120, 36], "confidence": 0.92},
        {"text": "展开查询", "bbox": [500, 302, 120, 36], "confidence": 0.91},
        {"text": "我的工时看板", "bbox": [700, 302, 160, 36], "confidence": 0.9},
    ]

    merged, report = merge_ocr_candidates(graph, observations)

    assert "measuredLines" not in merged["elements"][0]
    assert report["attached_line_group_count"] == 0
