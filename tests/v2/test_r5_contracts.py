from __future__ import annotations

import unittest
from dataclasses import replace

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - optional development dependency
    Draft202012Validator = None

from src.app.services.contracts import (
    AcceptanceCheck,
    AccessPolicy,
    Applicability,
    AssetRecord,
    CheckStatus,
    CoverageInput,
    CoverageState,
    Dimension,
    EvidenceAvailability,
    EvidenceRecord,
    ExecutionGraph,
    FieldAuthority,
    FieldDecision,
    FieldDecisionStatus,
    FieldObservation,
    FieldRecord,
    OrderMapping,
    Rect,
    ReferenceRecord,
    ReleaseStatus,
    ReplayInput,
    ReplayStatus,
    RetentionPolicy,
    RuntimeIR,
    Tombstone,
    UnknownRecord,
    audit_bundle_json_schema,
    audit_replay,
    build_audit_bundle,
    build_page_coverage,
    evaluate_release,
    fixed_denominator_diff,
    materialize_replay,
    migrate_runtime_ir,
    recapture_reconcile,
    rect_union_area,
    resume_after_send,
    runtime_ir_json_schema,
    text_decision_from_ocr,
    validate_audit_bundle,
    validate_runtime_ir,
)


def base_ir() -> RuntimeIR:
    evidence = (
        EvidenceRecord(
            evidence_id="ev-dom",
            kind="dom-json",
            sha256="a" * 64,
            locator="evidence/dom.json",
            availability=EvidenceAvailability.AVAILABLE,
            expires_at="2026-11-18T00:00:00+00:00",
        ),
        EvidenceRecord(
            evidence_id="ev-render",
            kind="render-json",
            sha256="b" * 64,
            locator="evidence/render.json",
            availability=EvidenceAvailability.AVAILABLE,
            expires_at="2026-11-18T00:00:00+00:00",
        ),
    )
    fields = (
        FieldRecord(
            field_id="field-title",
            node_id="node-title",
            field_type="text-content",
            observations=(
                FieldObservation(
                    source="dom",
                    evidence_id="ev-dom",
                    present=True,
                    value="R5",
                ),
                FieldObservation(
                    source="screenshot",
                    evidence_id="ev-render",
                    present=True,
                    value="R5",
                ),
            ),
            decision=FieldDecision(
                authority=FieldAuthority.DOM_AND_SCREENSHOT,
                status=FieldDecisionStatus.SELECTED,
                selected_value="R5",
                release_eligible=True,
                cannot_promote=("role", "editability", "asset-source"),
                reason="DOM and screenshot agree.",
                evidence_refs=("ev-dom", "ev-render"),
            ),
        ),
        FieldRecord(
            field_id="field-badge",
            node_id="node-badge",
            field_type="text-content",
            observations=(
                FieldObservation(
                    source="screenshot",
                    evidence_id="ev-render",
                    present=False,
                    value=None,
                    reason="not-seen",
                ),
            ),
            decision=FieldDecision(
                authority=FieldAuthority.NONE,
                status=FieldDecisionStatus.UNKNOWN,
                selected_value=None,
                release_eligible=False,
                reason="No value is invented.",
                evidence_refs=("ev-render",),
            ),
        ),
        FieldRecord(
            field_id="field-legacy",
            node_id="node-legacy",
            field_type="visibility",
            observations=(),
            decision=FieldDecision(
                authority=FieldAuthority.NONE,
                status=FieldDecisionStatus.TOMBSTONE,
                selected_value=None,
                release_eligible=False,
                reason="Authoritative tombstone.",
            ),
        ),
    )
    return RuntimeIR(
        job_id="job-1",
        schema_version="1.0",
        policy_version="policy-v1",
        capture_revision="capture-r1",
        plan_revision="plan-r1",
        output_revision="output-r1",
        capture_id="capture-r1",
        state_signature="state-1",
        fields=fields,
        evidence=evidence,
        assets=(
            AssetRecord(
                asset_id="asset-1",
                source_url="https://temporary.example/asset.png",
                url_expires_at="2026-10-10T00:00:00+00:00",
                local_sha256="c" * 64,
                local_bytes_present=True,
                local_expires_at="2027-01-17T00:00:00+00:00",
                mime="image/png",
            ),
        ),
        tombstones=(
            Tombstone(
                tombstone_id="tomb-1",
                object_key="legacy",
                scope="page",
                authority="user",
                authority_version=2,
                effective_at="2026-10-18T00:00:00+00:00",
            ),
        ),
        unknowns=(
            UnknownRecord(
                object_key="badge",
                field="text-content",
                status="unknown",
                reason="not-seen",
            ),
        ),
        order_mapping=OrderMapping(
            dom_order=("title", "badge"),
            screenshot_order=("title", "badge"),
            figma_child_order=("title", "badge"),
        ),
        references=(
            ReferenceRecord(
                reference_id="capture-ref",
                kind="capture",
                target="capture-r1",
            ),
        ),
        retention=RetentionPolicy(
            replay_evidence_days=30,
            audit_metadata_days=180,
            evidence_expires_at="2026-11-18T00:00:00+00:00",
            audit_metadata_expires_at="2027-04-17T00:00:00+00:00",
        ),
        access_policy=AccessPolicy(
            allow_evidence_read=True,
            allow_materialize=True,
            allow_audit_summary=True,
        ),
        execution_graph=ExecutionGraph(
            nodes=("contract", "capture", "fusion", "write", "publish"),
            edges=(
                ("contract", "capture"),
                ("capture", "fusion"),
                ("fusion", "write"),
                ("write", "publish"),
            ),
        ),
    )


def complete_coverage():
    return build_page_coverage(
        area=CoverageInput(100, 100, unit="px"),
        objects=CoverageInput(4, 4, unit="count"),
        text=CoverageInput(20, 20, unit="characters"),
        critical=CoverageInput(2, 2, unit="count"),
    )


def passing_check(
    check_id: str,
    dimension: Dimension,
    *,
    critical: bool = False,
    status: CheckStatus = CheckStatus.PASS,
    partial_allowed: bool = False,
) -> AcceptanceCheck:
    return AcceptanceCheck(
        check_id=check_id,
        object_key=check_id,
        dimension=dimension,
        check_type="test",
        critical=critical,
        required=True,
        status=status,
        partial_allowed=partial_allowed,
        evidence_refs=("evidence",),
        threshold_source="contract-test",
    )


class FieldAuthorityTests(unittest.TestCase):
    def test_unknown_enum_fails_closed(self) -> None:
        document = base_ir().to_dict()
        document["fields"][1]["decision"]["status"] = "future-status"
        issues = validate_runtime_ir(document)
        self.assertIn("unknown-field-status", {item.code for item in issues})

    def test_unknown_cannot_carry_selected_value(self) -> None:
        document = base_ir().to_dict()
        document["fields"][1]["decision"]["selected_value"] = "invented"
        issues = validate_runtime_ir(document)
        self.assertIn("unresolved-has-value", {item.code for item in issues})

    def test_screenshot_cannot_own_semantic_field(self) -> None:
        document = base_ir().to_dict()
        document["fields"][0]["field_type"] = "role"
        document["fields"][0]["decision"]["authority"] = "screenshot"
        issues = validate_runtime_ir(document)
        self.assertIn("screenshot-semantic-authority", {item.code for item in issues})

    def test_ocr_requires_semantic_promotion_guard(self) -> None:
        decision = text_decision_from_ocr(
            value="Price",
            dom_evidence_id=None,
            screenshot_evidence_id="ev-render",
            confident=True,
        )
        self.assertEqual(decision.status, FieldDecisionStatus.CANDIDATE)
        self.assertFalse(decision.release_eligible)
        self.assertEqual(
            set(decision.cannot_promote),
            {"role", "editability", "asset-source"},
        )


class CoverageTests(unittest.TestCase):
    def test_union_area_not_hypotenuse_or_sum(self) -> None:
        area = rect_union_area(
            (
                Rect(0, 0, 10, 10),
                Rect(5, 0, 10, 10),
            )
        )
        self.assertEqual(area, 150)

    def test_fixed_denominator_is_enforced(self) -> None:
        result = fixed_denominator_diff(
            denominator_pixels=100,
            excluded_diagnostic_pixels=20,
            valid_compare_pixels=80,
            masked_diff_pixels=0,
        )
        self.assertTrue(result["denominator_unchanged"])
        self.assertEqual(result["denominator_after_mask"], 100)
        with self.assertRaises(ValueError):
            fixed_denominator_diff(
                denominator_pixels=100,
                excluded_diagnostic_pixels=20,
                valid_compare_pixels=81,
                masked_diff_pixels=0,
            )


class AcceptanceTests(unittest.TestCase):
    def test_complete_requires_all_required_checks_and_coverage(self) -> None:
        checks = [
            passing_check("visual", Dimension.VISUAL),
            passing_check("structure", Dimension.STRUCTURE),
            passing_check("edit", Dimension.EDIT),
            passing_check("asset", Dimension.ASSET),
        ]
        decision = evaluate_release(
            checks=checks,
            coverage=complete_coverage(),
            preflight_passed=True,
            user_allowed_partial=False,
            noncritical_gap_isolatable=False,
        )
        self.assertEqual(decision.status, ReleaseStatus.DELIVERABLE_COMPLETE)
        self.assertTrue(decision.complete_export_allowed)
        self.assertEqual(decision.production_status, "production-not-eligible")

    def test_visual_pass_does_not_offset_edit_failure(self) -> None:
        checks = [
            passing_check("visual", Dimension.VISUAL),
            passing_check("edit", Dimension.EDIT, critical=True, status=CheckStatus.FAIL),
        ]
        decision = evaluate_release(
            checks=checks,
            coverage=complete_coverage(),
            preflight_passed=True,
            user_allowed_partial=False,
            noncritical_gap_isolatable=False,
        )
        self.assertEqual(decision.dimensions["visual"], "pass")
        self.assertEqual(decision.dimensions["edit"], "fail")
        self.assertEqual(decision.status, ReleaseStatus.BLOCKED_CRITICAL)
        self.assertFalse(decision.complete_export_allowed)

    def test_noncritical_isolated_gap_can_be_partial(self) -> None:
        checks = [
            passing_check("visual", Dimension.VISUAL, status=CheckStatus.PARTIAL),
            passing_check("structure", Dimension.STRUCTURE),
            passing_check("edit", Dimension.EDIT),
            passing_check("asset", Dimension.ASSET),
        ]
        partial_coverage = build_page_coverage(
            area=CoverageInput(100, 80, 20, unit="px"),
            objects=CoverageInput(4, 3, 1, unit="count"),
            text=CoverageInput(20, 18, 2, unit="characters"),
            critical=CoverageInput(2, 2, unit="count"),
        )
        decision = evaluate_release(
            checks=checks,
            coverage=partial_coverage,
            preflight_passed=True,
            user_allowed_partial=True,
            noncritical_gap_isolatable=True,
        )
        self.assertEqual(decision.status, ReleaseStatus.DELIVERABLE_PARTIAL)
        self.assertEqual(decision.allowed_export_mode, "explicit-partial")

    def test_reference_only_is_not_complete(self) -> None:
        decision = evaluate_release(
            checks=[passing_check("visual", Dimension.VISUAL)],
            coverage=complete_coverage(),
            required_dimensions=(Dimension.VISUAL,),
            preflight_passed=True,
            user_allowed_partial=False,
            noncritical_gap_isolatable=False,
            reference_only=True,
        )
        self.assertEqual(decision.status, ReleaseStatus.REFERENCE_ONLY)
        self.assertFalse(decision.complete_export_allowed)

    def test_explicitly_allowed_critical_partial_requires_partial_release(self) -> None:
        checks = [
            passing_check(
                "price",
                Dimension.VISUAL,
                critical=True,
                status=CheckStatus.PARTIAL,
                partial_allowed=True,
            ),
        ]
        partial_coverage = build_page_coverage(
            area=CoverageInput(100, 90, 10, unit="px"),
            objects=CoverageInput(2, 2, unit="count"),
            text=CoverageInput(10, 9, 1, unit="characters"),
            critical=CoverageInput(1, 1, unit="count"),
        )
        decision = evaluate_release(
            checks=checks,
            coverage=partial_coverage,
            required_dimensions=(Dimension.VISUAL,),
            preflight_passed=True,
            user_allowed_partial=True,
            noncritical_gap_isolatable=True,
        )
        self.assertEqual(decision.status, ReleaseStatus.DELIVERABLE_PARTIAL)
        self.assertNotIn("price", decision.critical_blockers)


class IRAndReplayTests(unittest.TestCase):
    def test_base_runtime_ir_validates(self) -> None:
        self.assertEqual(validate_runtime_ir(base_ir()), [])

    def test_runtime_graph_cycle_fails(self) -> None:
        ir = base_ir()
        cyclic = replace(
            ir,
            execution_graph=ExecutionGraph(
                nodes=("a", "b"),
                edges=(("a", "b"), ("b", "a")),
            ),
        )
        issues = validate_runtime_ir(cyclic)
        self.assertIn("cyclic-runtime-dag", {item.code for item in issues})

    def test_audit_bundle_has_no_runtime_dag(self) -> None:
        bundle = build_audit_bundle(base_ir())
        self.assertIsNone(bundle.execution_graph)
        self.assertEqual(bundle.sequence_semantics, "ordered-audit-only")
        self.assertEqual(validate_audit_bundle(bundle), [])

    def test_audit_bundle_rejects_runtime_graph(self) -> None:
        document = build_audit_bundle(base_ir()).to_dict()
        document["execution_graph"] = {"nodes": ["contract"]}
        issues = validate_audit_bundle(document)
        self.assertIn("audit-has-runtime-graph", {item.code for item in issues})

    def test_migration_preserves_critical_state(self) -> None:
        migrated, result = migrate_runtime_ir(
            base_ir(),
            migrated_at="2026-10-19T00:00:00+00:00",
        )
        self.assertEqual(migrated.schema_version, "2.0")
        self.assertTrue(result.all_preserved)
        self.assertNotEqual(result.source_hash, result.migrated_hash)
        self.assertEqual(migrated.tombstones, base_ir().tombstones)
        self.assertEqual(migrated.unknowns, base_ir().unknowns)

    def test_replay_modes_are_distinct(self) -> None:
        unavailable = ReplayInput(
            evidence_available=False,
            permission_granted=True,
            local_asset_present=True,
            local_hash_matches=True,
            environment_changed=False,
            decision_trace_hash="d" * 64,
            materialized_hash="e" * 64,
        )
        audit = audit_replay(unavailable)
        materialize = materialize_replay(unavailable)
        self.assertEqual(audit.status, ReplayStatus.SUMMARY_ONLY)
        self.assertFalse(audit.exact_replay)
        self.assertEqual(
            materialize.status,
            ReplayStatus.BLOCKED_EVIDENCE_UNAVAILABLE,
        )
        recapture = recapture_reconcile(
            old_capture_id="capture-r1",
            new_capture_id="capture-r2",
            old_revision=1,
            new_revision=2,
            permission_granted=True,
            recaptured_hash="f" * 64,
        )
        self.assertEqual(recapture.status, ReplayStatus.NEW_CAPTURE_CREATED)
        self.assertFalse(recapture.exact_replay)

    def test_resume_duplicate_blocks(self) -> None:
        result = resume_after_send(side_effect_count=2, duplicate_create_count=1)
        self.assertEqual(result.mode.value, "resume")
        self.assertNotEqual(
            result.status,
            ReplayStatus.COMMITTED_AFTER_RECONCILE,
        )

    def test_schema_documents_expose_fixed_layer_ids(self) -> None:
        self.assertEqual(runtime_ir_json_schema()["properties"]["outer_schema"]["const"], "runtime-ir/1.0")
        self.assertEqual(
            audit_bundle_json_schema()["properties"]["outer_schema"]["const"],
            "audit-bundle/1.0",
        )

    @unittest.skipUnless(Draft202012Validator is not None, "jsonschema is not installed")
    def test_json_schemas_accept_golden_examples(self) -> None:
        Draft202012Validator(runtime_ir_json_schema()).validate(base_ir().to_dict())
        Draft202012Validator(audit_bundle_json_schema()).validate(
            build_audit_bundle(base_ir()).to_dict()
        )


if __name__ == "__main__":
    unittest.main()
