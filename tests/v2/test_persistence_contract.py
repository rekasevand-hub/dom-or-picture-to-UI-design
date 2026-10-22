from __future__ import annotations

import unittest
from dataclasses import replace

from src.app.services.contracts import (
    RetentionPolicy,
    Tombstone,
    UnknownRecord,
    build_audit_bundle,
)
from src.app.services.persistence.store import (
    PersistenceValidationError,
    validate_delivery_bundle,
)
from tests.v2._delivery_fixture import delivery_sidecar


def _runtime_with_records():
    source = delivery_sidecar().runtime_ir
    return replace(
        source,
        tombstones=(
            Tombstone(
                tombstone_id="tomb-1",
                object_key="legacy",
                scope="field",
                authority="business",
                authority_version=2,
                effective_at="2026-10-22T00:00:00+00:00",
            ),
        ),
        unknowns=(
            UnknownRecord(
                object_key="badge",
                field="text-content",
                status="unknown",
                reason="not observed",
            ),
        ),
        retention=RetentionPolicy(
            replay_evidence_days=30,
            audit_metadata_days=180,
            evidence_expires_at="2027-01-01T00:00:00+00:00",
            audit_metadata_expires_at="2027-04-01T00:00:00+00:00",
        ),
    )


class PersistenceContractTests(unittest.TestCase):
    def test_runtime_and_audit_remain_separate(self) -> None:
        runtime = _runtime_with_records()
        audit = build_audit_bundle(runtime)

        normalized = validate_delivery_bundle(
            {
                "trace_id": "trace-1",
                "runtime_ir": runtime,
                "audit_bundle": audit,
            }
        )

        self.assertEqual(normalized.trace_id, "trace-1")
        self.assertEqual(normalized.runtime_ir, runtime)
        self.assertEqual(normalized.audit_bundle, audit)
        self.assertEqual(normalized.audit_bundle.sequence_semantics, "ordered-audit-only")

    def test_unknown_enum_fails_before_persistence(self) -> None:
        runtime = _runtime_with_records().to_dict()
        runtime["fields"][0]["decision"]["status"] = "future-status"
        audit = build_audit_bundle(_runtime_with_records()).to_dict()

        with self.assertRaises(PersistenceValidationError):
            validate_delivery_bundle(
                {
                    "trace_id": "trace-invalid",
                    "runtime_ir": runtime,
                    "audit_bundle": audit,
                }
            )

    def test_unknown_and_tombstone_records_survive_bundle_validation(self) -> None:
        runtime = _runtime_with_records()
        normalized = validate_delivery_bundle(
            {
                "trace_id": "trace-records",
                "runtime_ir": runtime,
                "audit_bundle": build_audit_bundle(runtime),
            }
        )

        self.assertEqual(normalized.runtime_ir.tombstones, runtime.tombstones)
        self.assertEqual(normalized.runtime_ir.unknowns, runtime.unknowns)
        self.assertEqual(
            normalized.runtime_ir.retention.audit_metadata_expires_at,
            "2027-04-01T00:00:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
