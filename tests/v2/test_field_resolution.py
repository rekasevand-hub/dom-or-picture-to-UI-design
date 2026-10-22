from __future__ import annotations

import unittest

from src.app.services.contracts import (
    FieldDecisionStatus,
    FieldObservation,
    Tombstone,
)
from src.app.services.delivery.conflicts import (
    REQUIRED_REPORT_FIELDS,
    build_conflict_report,
)
from src.app.services.delivery.field_resolution import (
    FieldClaim,
    resolve_fields,
)


PROFILE = "fixed-authored-chromium/1.0"


def observation(source: str, value, *, evidence_id: str | None = None):
    return FieldObservation(
        source=source,
        evidence_id=evidence_id or "ev-" + source,
        present=True,
        value=value,
    )


class FieldResolutionTests(unittest.TestCase):
    def test_text_conflict_keeps_winner_null_and_blocks_content(self) -> None:
        resolution = resolve_fields(
            (
                FieldClaim(
                    field_id="title",
                    node_id="node-title",
                    field_type="text-content",
                    observations=(
                        observation("dom", "限时特价 A"),
                        observation("screenshot-ocr", "限时特价 B"),
                    ),
                ),
            ),
            PROFILE,
        )

        field = resolution.fields[0]
        self.assertEqual(
            field.decision.status,
            FieldDecisionStatus.EXTERNAL_CONFLICT,
        )
        self.assertIsNone(field.winner)
        self.assertNotIn("text-content", resolution.content.get("node-title", {}))
        self.assertNotIn("限时特价 A", repr(resolution.content))
        self.assertNotIn("限时特价 B", repr(resolution.content))

    def test_unknown_deferred_skipped_and_authority_required_stay_distinct(self) -> None:
        resolution = resolve_fields(
            (
                FieldClaim(
                    field_id="color",
                    node_id="node-card",
                    field_type="color",
                    observations=(),
                ),
                FieldClaim(
                    field_id="visibility",
                    node_id="node-card",
                    field_type="visibility",
                    observations=(),
                    status_hint=FieldDecisionStatus.DEFERRED,
                ),
                FieldClaim(
                    field_id="promo-asset",
                    node_id="node-promo",
                    field_type="asset",
                    observations=(),
                    status_hint=FieldDecisionStatus.SKIPPED,
                    skip_reason="Asset is outside the authored pilot scope.",
                ),
                FieldClaim(
                    field_id="price",
                    node_id="node-price",
                    field_type="price",
                    observations=(observation("dom", "¥19.90"),),
                ),
            ),
            PROFILE,
        )

        states = {field.field_id: field.decision.status for field in resolution.fields}
        self.assertEqual(states["color"], FieldDecisionStatus.UNKNOWN)
        self.assertEqual(states["visibility"], FieldDecisionStatus.DEFERRED)
        self.assertEqual(states["promo-asset"], FieldDecisionStatus.SKIPPED)
        self.assertEqual(states["price"], FieldDecisionStatus.AUTHORITY_REQUIRED)
        self.assertEqual(resolution.content, {})

    def test_tombstone_remains_delete_pending(self) -> None:
        tombstone = Tombstone(
            tombstone_id="tomb-old-price",
            object_key="node-price",
            scope="field",
            authority="business",
            authority_version=3,
            effective_at="2026-10-22T00:00:00+00:00",
        )
        resolution = resolve_fields(
            (
                FieldClaim(
                    field_id="price",
                    node_id="node-price",
                    field_type="text-content",
                    observations=(observation("old-revision", "旧价格 ¥59.00"),),
                    tombstone=tombstone,
                ),
            ),
            PROFILE,
        )

        field = resolution.fields[0]
        self.assertEqual(
            field.decision.status,
            FieldDecisionStatus.DELETE_PENDING,
        )
        self.assertIsNone(field.winner)
        self.assertEqual(field.tombstone, tombstone)
        self.assertNotIn("旧价格", repr(resolution.content))

    def test_ocr_candidate_is_not_promoted_to_content(self) -> None:
        resolution = resolve_fields(
            (
                FieldClaim(
                    field_id="ocr-title",
                    node_id="node-ocr",
                    field_type="text-content",
                    observations=(
                        observation("screenshot-ocr", "OCR 候选", evidence_id="ev-ocr"),
                    ),
                    ocr_confident=True,
                ),
            ),
            PROFILE,
        )

        field = resolution.fields[0]
        self.assertEqual(field.decision.status, FieldDecisionStatus.CANDIDATE)
        self.assertIsNone(field.winner)
        self.assertEqual(field.candidate_value, "OCR 候选")
        self.assertNotIn("OCR 候选", repr(resolution.content))
        self.assertEqual(
            set(field.decision.cannot_promote),
            {"role", "editability", "asset-source"},
        )

    def test_single_dom_observation_is_written(self) -> None:
        resolution = resolve_fields(
            (
                FieldClaim(
                    field_id="title",
                    node_id="node-title",
                    field_type="text-content",
                    observations=(observation("dom", "限时特价 A"),),
                ),
            ),
            PROFILE,
        )

        field = resolution.fields[0]
        self.assertEqual(field.decision.status, FieldDecisionStatus.SELECTED)
        self.assertEqual(field.winner, "限时特价 A")
        self.assertEqual(
            resolution.content["node-title"]["text-content"],
            "限时特价 A",
        )


class ConflictReportTests(unittest.TestCase):
    def test_every_unresolved_field_has_complete_report_entry(self) -> None:
        resolution = resolve_fields(
            (
                FieldClaim(
                    field_id="title",
                    node_id="node-title",
                    field_type="text-content",
                    observations=(
                        observation("dom", "限时特价 A"),
                        observation("screenshot-ocr", "限时特价 B"),
                    ),
                ),
                FieldClaim(
                    field_id="color",
                    node_id="node-card",
                    field_type="color",
                    observations=(),
                ),
                FieldClaim(
                    field_id="price",
                    node_id="node-price",
                    field_type="price",
                    observations=(observation("dom", "¥19.90"),),
                ),
            ),
            PROFILE,
        )

        report = build_conflict_report(resolution)

        self.assertTrue(report.outside_business_flow)
        self.assertEqual(len(report.entries), 3)
        for entry in report.entries:
            self.assertEqual(
                set(REQUIRED_REPORT_FIELDS).issubset(entry.to_dict()),
                True,
            )
            self.assertIsNone(entry.winner)
            self.assertTrue(entry.authority_gap)
            self.assertTrue(entry.current_display)
            self.assertTrue(entry.blocked_actions)
            self.assertTrue(entry.next_step)
        self.assertNotIn("限时特价 A", repr(report.content))
        self.assertNotIn("限时特价 B", repr(report.content))


if __name__ == "__main__":
    unittest.main()
