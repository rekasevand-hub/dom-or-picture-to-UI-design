from __future__ import annotations

import copy
import unittest

from src.app.services.structure.image_strategy import merge_hybrid_graph


def _graph(route: str, *, elements: list[dict], containers: list[dict] | None = None):
    return {
        "image": "sample.png",
        "image_w": 400,
        "image_h": 220,
        "route": route,
        "containers": containers or [],
        "elements": elements,
        "provenance": {"route": route, "fallbacks": [], "warnings": []},
    }


class ImageStrategyTests(unittest.TestCase):
    def test_hybrid_adds_missing_cv_text_and_skips_duplicate(self) -> None:
        grounding = _graph(
            "grounding",
            elements=[
                {
                    "id": 1,
                    "bbox": [20, 20, 120, 24],
                    "type": "text",
                    "text": "Workspace",
                    "source": "grounding",
                }
            ],
        )
        cv = _graph(
            "cv",
            elements=[
                {
                    "id": 7,
                    "bbox": [22, 21, 118, 24],
                    "type": "text",
                    "text": "Workspace",
                    "source": "cv:ocr",
                },
                {
                    "id": 8,
                    "bbox": [20, 60, 110, 22],
                    "type": "text",
                    "text": "Missing CTA",
                    "source": "cv:ocr",
                },
            ],
        )
        original = copy.deepcopy(grounding)

        merged, report = merge_hybrid_graph(grounding, cv)

        self.assertEqual(grounding, original)
        self.assertEqual(merged["route"], "hybrid")
        texts = [item["text"] for item in merged["elements"]]
        self.assertIn("Missing CTA", texts)
        self.assertEqual(texts.count("Workspace"), 1)
        added = next(
            item for item in merged["elements"] if item["text"] == "Missing CTA"
        )
        self.assertEqual(added["source"], "hybrid:cv:ocr")
        self.assertEqual(added["authority"], "hybrid-cv-candidate")
        self.assertFalse(added["verified"])
        self.assertEqual(report["text_added_count"], 1)
        self.assertEqual(report["skipped_count"], 1)
        self.assertEqual(report["skipped"][0]["reason"], "duplicate-text")

    def test_hybrid_adds_one_missing_visual_box_and_skips_overlap(self) -> None:
        grounding = _graph(
            "grounding",
            containers=[
                {
                    "id": "C1",
                    "bbox": [0, 0, 400, 50],
                    "role": "banner",
                    "source": "grounding",
                }
            ],
            elements=[],
        )
        cv = _graph(
            "cv",
            elements=[
                {
                    "id": 11,
                    "bbox": [20, 80, 100, 60],
                    "type": "rectangle",
                    "text": "",
                    "source": "cv:omniparser",
                },
                {
                    "id": 12,
                    "bbox": [0, 0, 400, 50],
                    "type": "rectangle",
                    "text": "",
                    "source": "cv:omniparser",
                },
            ],
        )

        merged, report = merge_hybrid_graph(grounding, cv)

        visual = [
            item for item in merged["elements"] if item.get("type") == "rectangle"
        ]
        self.assertEqual(len(visual), 1)
        self.assertEqual(visual[0]["bbox"], [20, 80, 100, 60])
        self.assertEqual(visual[0]["source"], "hybrid:cv:omniparser")
        self.assertEqual(visual[0]["authority"], "hybrid-cv-candidate")
        self.assertFalse(visual[0]["verified"])
        self.assertEqual(report["visual_added_count"], 1)
        self.assertEqual(report["skipped"][0]["reason"], "duplicate-visual")

    def test_hybrid_report_preserves_all_supplement_sources(self) -> None:
        grounding = _graph("grounding", elements=[])
        cv = _graph(
            "cv",
            elements=[
                {
                    "id": 1,
                    "bbox": [10, 10, 80, 20],
                    "type": "text",
                    "text": "OCR added",
                    "source": "cv:ocr",
                },
                {
                    "id": 2,
                    "bbox": [10, 50, 80, 40],
                    "type": "rectangle",
                    "text": "",
                    "source": "cv:omniparser",
                },
            ],
        )

        _merged, report = merge_hybrid_graph(grounding, cv)

        self.assertEqual(
            report["supplement_sources"],
            ["cv:ocr", "cv:omniparser"],
        )
        self.assertEqual(report["primary_source"], "grounding")
        self.assertEqual(report["authority"], "candidate")
        self.assertFalse(report["promoted_to_verified"])

    def test_omniparser_caption_does_not_turn_visual_box_into_text_node(self) -> None:
        grounding = _graph("grounding", elements=[])
        cv = _graph(
            "cv",
            elements=[
                {
                    "id": 9,
                    "bbox": [20, 80, 120, 60],
                    "type": "rectangle",
                    "text": "A map or photo app.",
                    "source": "cv:omniparser",
                }
            ],
        )

        merged, report = merge_hybrid_graph(grounding, cv)

        added = merged["elements"][0]
        self.assertEqual(added["type"], "rectangle")
        self.assertEqual(added["text"], "A map or photo app.")
        self.assertEqual(report["text_added_count"], 0)
        self.assertEqual(report["visual_added_count"], 1)

    def test_hybrid_suppresses_spatially_overlapping_text_fragments(self) -> None:
        grounding = _graph(
            "grounding",
            elements=[
                {
                    "id": 1,
                    "bbox": [443, 259, 151, 22],
                    "type": "text",
                    "text": "New customers today",
                    "source": "grounding",
                }
            ],
        )
        cv = _graph(
            "cv",
            elements=[
                {
                    "id": 2,
                    "bbox": [443, 259, 106, 16],
                    "type": "text",
                    "text": "New customers",
                    "source": "cv:ocr",
                },
                {
                    "id": 3,
                    "bbox": [551, 256, 40, 22],
                    "type": "text",
                    "text": "today",
                    "source": "cv:ocr",
                },
            ],
        )

        merged, report = merge_hybrid_graph(grounding, cv)

        self.assertEqual(len(merged["elements"]), 1)
        self.assertEqual(report["text_added_count"], 0)
        self.assertEqual(
            [item["reason"] for item in report["skipped"]],
            ["duplicate-text", "duplicate-text"],
        )


if __name__ == "__main__":
    unittest.main()
