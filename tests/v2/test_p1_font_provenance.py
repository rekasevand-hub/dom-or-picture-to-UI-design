from __future__ import annotations

import unittest

from src.app.services.structure.font_provenance import (
    FontFaceIdentity,
    PlatformFontProbe,
    apply_platform_font_provenance,
    collect_platform_font_rows,
    evaluate_font_face,
    is_generic_font_stack,
)
from src.app.services.structure.frames import _summarize_font_resolution


class PlatformFontProvenanceTests(unittest.TestCase):
    def test_frame_font_summary_preserves_nested_probe_errors(self) -> None:
        summary = _summarize_font_resolution(
            [
                {
                    "path": "root/0",
                    "generic_node_count": 1,
                    "resolved_count": 0,
                    "ambiguous_count": 0,
                    "missing_count": 1,
                    "status": "partial",
                    "errors": ["DOM.describeNode failed"],
                }
            ],
            [],
        )

        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["errors"][0]["path"], "root/0")
        self.assertIn("DOM.describeNode", summary["errors"][0]["error"])

    def test_generic_font_stack_detection_excludes_explicit_families(self) -> None:
        self.assertTrue(is_generic_font_stack("sans-serif"))
        self.assertTrue(is_generic_font_stack("ui-sans-serif, sans-serif"))
        self.assertFalse(is_generic_font_stack("Arial, sans-serif"))
        self.assertFalse(is_generic_font_stack('"Times New Roman"'))

    def test_cdp_rows_are_collected_only_for_exact_marker(self) -> None:
        class FakeCDP:
            def __init__(self) -> None:
                self.calls = []

            def send(self, method, params=None):
                self.calls.append((method, params))
                if method == "DOM.performSearch":
                    return {"searchId": "s1", "resultCount": 2}
                if method == "DOM.getSearchResults":
                    return {"nodeIds": [10, 11]}
                if method == "DOM.describeNode":
                    marker = "root-2" if params["nodeId"] == 10 else "other-marker"
                    return {
                        "node": {
                            "nodeId": params["nodeId"],
                            "attributes": [
                                "data-p1-font-probe-id",
                                marker,
                            ],
                        },
                    }
                if method == "CSS.getPlatformFontsForNode":
                    return {
                        "fonts": [
                            {
                                "familyName": "Microsoft YaHei",
                                "glyphCount": 4,
                            }
                        ],
                    }
                return {}

        cdp = FakeCDP()
        rows = collect_platform_font_rows(
            cdp,
            [{"fontProbeId": "root-2"}],
        )

        self.assertEqual(rows["root-2"][0]["familyName"], "Microsoft YaHei")
        self.assertIn(
            ("DOM.discardSearchResults", {"searchId": "s1"}),
            cdp.calls,
        )

    def test_probe_resolves_nodes_and_removes_temporary_markers(self) -> None:
        class FakeCDP:
            def __init__(self) -> None:
                self.calls = []

            def send(self, method, params=None):
                self.calls.append((method, params))
                if method == "DOM.performSearch":
                    return {"searchId": "s2", "resultCount": 1}
                if method == "DOM.getSearchResults":
                    return {"nodeIds": [20]}
                if method == "DOM.describeNode":
                    return {
                        "node": {
                            "nodeId": 20,
                            "attributes": [
                                "data-p1-font-probe-id",
                                "root-2",
                            ],
                        },
                    }
                if method == "CSS.getPlatformFontsForNode":
                    return {
                        "fonts": [
                            {
                                "familyName": "Microsoft YaHei",
                                "glyphCount": 4,
                            }
                        ],
                    }
                return {}

        class FakeContext:
            def __init__(self, cdp) -> None:
                self.cdp = cdp

            def new_cdp_session(self, page):
                return self.cdp

        class FakePage:
            def __init__(self, cdp) -> None:
                self.context = FakeContext(cdp)

        class FakeFrame:
            def __init__(self) -> None:
                self.cleanup = []

            def evaluate(self, script, prefix):
                self.cleanup.append(prefix)
                return 0

        cdp = FakeCDP()
        frame = FakeFrame()
        nodes = [
            {
                "fontFamily": "sans-serif",
                "fontProbeId": "root-2",
            }
        ]
        probe = PlatformFontProbe(FakePage(cdp))

        summary = probe(frame, "root", nodes)

        self.assertEqual(nodes[0]["fontFamily"], "Microsoft YaHei")
        self.assertEqual(summary["resolved_count"], 1)
        self.assertEqual(frame.cleanup, ["root"])
        self.assertIn(("DOM.enable", None), cdp.calls)
        self.assertIn(("CSS.enable", None), cdp.calls)

    def test_single_platform_font_resolves_generic_family(self) -> None:
        nodes = [
            {
                "text": "Holdout accessible child",
                "fontFamily": "sans-serif",
                "fontProbeId": "root-7",
            }
        ]

        summary = apply_platform_font_provenance(
            nodes,
            {
                "root-7": [
                    {
                        "familyName": "Microsoft YaHei",
                        "postScriptName": "MicrosoftYaHei",
                        "glyphCount": 24,
                    }
                ],
            },
        )

        node = nodes[0]
        self.assertEqual(node["fontFamilyRequested"], "sans-serif")
        self.assertEqual(node["fontFamily"], "Microsoft YaHei")
        self.assertEqual(
            node["fontFamilyResolution"],
            "browser-platform-font",
        )
        self.assertEqual(
            node["platformFonts"][0]["familyName"],
            "Microsoft YaHei",
        )
        self.assertNotIn("fontProbeId", node)
        self.assertEqual(summary["resolved_count"], 1)

    def test_multiple_platform_fonts_remain_ambiguous(self) -> None:
        nodes = [
            {
                "text": "Latin 中文",
                "fontFamily": "sans-serif",
                "fontProbeId": "root-8",
            }
        ]

        summary = apply_platform_font_provenance(
            nodes,
            {
                "root-8": [
                    {"familyName": "Segoe UI", "glyphCount": 5},
                    {"familyName": "Microsoft YaHei", "glyphCount": 2},
                ],
            },
        )

        node = nodes[0]
        self.assertEqual(node["fontFamily"], "sans-serif")
        self.assertEqual(
            node["fontFamilyResolution"],
            "ambiguous-platform-font",
        )
        self.assertNotIn("fontFamilyRequested", node)
        self.assertEqual(summary["ambiguous_count"], 1)

    def test_missing_platform_evidence_keeps_requested_family(self) -> None:
        nodes = [
            {
                "text": "No font evidence",
                "fontFamily": "serif",
                "fontProbeId": "root-9",
            }
        ]

        summary = apply_platform_font_provenance(nodes, {})

        node = nodes[0]
        self.assertEqual(node["fontFamily"], "serif")
        self.assertEqual(node["fontFamilyResolution"], "font-evidence-missing")
        self.assertNotIn("fontProbeId", node)
        self.assertEqual(summary["missing_count"], 1)

    def test_missing_or_ambiguous_fonts_become_blocked_font_partial(self) -> None:
        missing = evaluate_font_face(
            declared_family="sans-serif",
            resolved_family="sans-serif",
            actual_family=None,
            resolution="font-evidence-missing",
        )
        ambiguous = evaluate_font_face(
            declared_family="sans-serif",
            resolved_family="sans-serif",
            actual_family="Segoe UI + Microsoft YaHei",
            resolution="ambiguous-platform-font",
        )
        resolved = evaluate_font_face(
            declared_family="sans-serif",
            resolved_family="Microsoft YaHei",
            actual_family="Microsoft YaHei",
            resolution="browser-platform-font",
        )

        self.assertIsInstance(missing, FontFaceIdentity)
        self.assertEqual(missing.gate_status, "blocked-font/partial")
        self.assertEqual(ambiguous.gate_status, "blocked-font/partial")
        self.assertEqual(resolved.gate_status, "pass")

    def test_declared_resolved_and_actual_faces_remain_separate(self) -> None:
        face = evaluate_font_face(
            declared_family="sans-serif",
            resolved_family="Microsoft YaHei",
            actual_family="Microsoft YaHei",
            resolution="browser-platform-font",
        )

        self.assertEqual(face.declared_family, "sans-serif")
        self.assertEqual(face.resolved_family, "Microsoft YaHei")
        self.assertEqual(face.actual_family, "Microsoft YaHei")
        self.assertNotEqual(face.declared_family, face.actual_family)

    def test_legacy_design_family_ignores_css_quotes_for_gate_match(self) -> None:
        face = evaluate_font_face(
            declared_family='"Times New Roman"',
            resolved_family='"Times New Roman"',
            actual_family="Times New Roman",
            resolution="legacy-design-family",
        )

        self.assertEqual(face.gate_status, "pass")


if __name__ == "__main__":
    unittest.main()
