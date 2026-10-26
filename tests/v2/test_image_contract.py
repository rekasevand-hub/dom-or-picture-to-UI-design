from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.structure.image_contract import (
    build_image_design,
    build_image_ir,
    inspect_image_reference,
    merge_ocr_candidates,
    recover_image_region_candidates,
    select_ocr_languages,
)


def _rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))


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


if __name__ == "__main__":
    unittest.main()
