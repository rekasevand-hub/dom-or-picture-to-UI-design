from __future__ import annotations

import unittest
from dataclasses import replace

from src.app.services.contracts import (
    AcceptanceCheck,
    Applicability,
    CheckStatus,
    CoverageInput,
    CoverageRegion,
    CoverageState,
    Dimension,
    Rect,
    ReleaseStatus,
    build_page_coverage,
    fixed_denominator_diff,
    assert_release_invariants,
)
from src.app.services.delivery.partial_report import build_partial_report
from src.app.services.delivery.release_gate import (
    ExportNotAllowed,
    ReleaseGateProfile,
    assert_export_allowed,
    release_decision,
)


def check(
    check_id: str,
    dimension: Dimension,
    status: CheckStatus,
    *,
    critical: bool = False,
    partial_allowed: bool = False,
) -> AcceptanceCheck:
    return AcceptanceCheck(
        check_id=check_id,
        object_key=check_id,
        dimension=dimension,
        check_type="release-gate-fixture",
        critical=critical,
        required=True,
        status=status,
        partial_allowed=partial_allowed,
        applicability=Applicability.REQUIRED,
    )


def complete_checks() -> tuple[AcceptanceCheck, ...]:
    return (
        check("visual", Dimension.VISUAL, CheckStatus.PASS),
        check("structure", Dimension.STRUCTURE, CheckStatus.PASS),
        check("edit", Dimension.EDIT, CheckStatus.PASS),
        check("asset", Dimension.ASSET, CheckStatus.PASS),
    )


def partial_coverage(*, unknown: bool = False, high_area: bool = False):
    return build_page_coverage(
        area=CoverageInput(
            1000,
            999 if high_area else 900,
            missing=0 if high_area else 100,
            unknown=1 if high_area and unknown else 0,
        ),
        objects=CoverageInput(12, 11, missing=1),
        text=CoverageInput(120, 111, missing=9),
        critical=CoverageInput(2, 1, missing=1),
    )


def region(
    region_id: str,
    state: CoverageState,
    *,
    object_key: str = "price-panel",
) -> CoverageRegion:
    return CoverageRegion(
        region_id=region_id,
        object_keys=(object_key,),
        source_rect=Rect(600, 290, 500, 120),
        output_rect=Rect(600, 290, 500, 120),
        coverage_state=state,
        reason=f"fixture state {state.value}",
        evidence_refs=(f"evidence:{region_id}",),
        affected_dimensions=(Dimension.VISUAL, Dimension.STRUCTURE),
        blocked_actions=("cannot-export-as-complete",),
    )


class PartialReportTests(unittest.TestCase):
    def test_four_gap_states_remain_distinct(self) -> None:
        states = (
            CoverageState.INTENTIONAL_OMISSION,
            CoverageState.WRITE_FAILED,
            CoverageState.OBSERVED_ABSENT,
            CoverageState.NOT_CAPTURED,
        )
        report = build_partial_report(
            partial_coverage(unknown=True),
            (
                check(
                    "visual-gap",
                    Dimension.VISUAL,
                    CheckStatus.PARTIAL,
                    partial_allowed=True,
                ),
            ),
            regions=tuple(
                region(f"region-{state.value}", state) for state in states
            ),
        )

        self.assertEqual(report.status, "blocked")
        self.assertEqual(
            {state.value: report.coverage_state_counts[state.value] for state in states},
            {
                "intentional-omission": 1,
                "write-failed": 1,
                "observed-absent": 1,
                "not-captured": 1,
            },
        )
        self.assertEqual(
            {item.coverage_state for item in report.regions},
            set(states),
        )
        self.assertNotEqual(
            CoverageState.NOT_CAPTURED,
            CoverageState.OBSERVED_ABSENT,
        )
        self.assertIn("not-captured", report.reason)

    def test_intentional_noncritical_gap_can_be_partial(self) -> None:
        report = build_partial_report(
            partial_coverage(),
            (
                check(
                    "visual-gap",
                    Dimension.VISUAL,
                    CheckStatus.PARTIAL,
                    partial_allowed=True,
                ),
                check("structure", Dimension.STRUCTURE, CheckStatus.PASS),
                check("edit", Dimension.EDIT, CheckStatus.PASS),
                check("asset", Dimension.ASSET, CheckStatus.PASS),
            ),
            regions=(
                region(
                    "price-panel",
                    CoverageState.INTENTIONAL_OMISSION,
                ),
            ),
        )

        self.assertEqual(report.status, "partial")
        self.assertTrue(report.root_name.startswith("[PARTIAL]"))
        self.assertTrue(report.outside_business_flow)

    def test_write_failure_and_critical_unknown_block(self) -> None:
        write_failed = build_partial_report(
            partial_coverage(),
            (
                check(
                    "write",
                    Dimension.STRUCTURE,
                    CheckStatus.FAIL,
                    critical=True,
                ),
            ),
        )
        unknown = build_partial_report(
            partial_coverage(unknown=True),
            (
                check(
                    "capture",
                    Dimension.VISUAL,
                    CheckStatus.UNKNOWN,
                    critical=True,
                ),
            ),
            regions=(region("not-captured", CoverageState.NOT_CAPTURED),),
        )

        self.assertEqual(write_failed.status, "blocked")
        self.assertIn("write", write_failed.critical_blockers)
        self.assertEqual(unknown.status, "blocked")
        self.assertIn("capture", unknown.critical_blockers)

    def test_tiny_price_failure_blocks_high_area_pass(self) -> None:
        report = build_partial_report(
            partial_coverage(high_area=True),
            (
                check("visual-background", Dimension.VISUAL, CheckStatus.PASS),
                check(
                    "price-value",
                    Dimension.STRUCTURE,
                    CheckStatus.FAIL,
                    critical=True,
                ),
            ),
        )

        self.assertEqual(report.status, "blocked")
        self.assertIn("price-value", report.critical_blockers)
        self.assertGreater(report.coverage["area"]["ratio"], 0.99)

    def test_mask_does_not_shrink_contract_denominator(self) -> None:
        reconciliation = fixed_denominator_diff(
            denominator_pixels=912000,
            excluded_diagnostic_pixels=60000,
            valid_compare_pixels=852000,
            masked_diff_pixels=0,
        )
        report = build_partial_report(
            partial_coverage(),
            (
                check(
                    "visual-gap",
                    Dimension.VISUAL,
                    CheckStatus.PARTIAL,
                    partial_allowed=True,
                ),
            ),
        )

        self.assertTrue(reconciliation["denominator_unchanged"])
        self.assertEqual(reconciliation["denominator_after_mask"], 912000)
        self.assertTrue(report.denominator_unchanged)


class ReleaseGateTests(unittest.TestCase):
    def test_partial_and_blocked_never_allow_complete_export(self) -> None:
        profile = ReleaseGateProfile(
            profile_id="p5-pilot/1.0",
            preflight_passed=True,
            user_allowed_partial=True,
            noncritical_gap_isolatable=True,
        )
        partial_report = build_partial_report(
            partial_coverage(),
            (
                check(
                    "visual-gap",
                    Dimension.VISUAL,
                    CheckStatus.PARTIAL,
                    partial_allowed=True,
                ),
            ),
        )
        partial_decision = release_decision(partial_report, profile)
        blocked_report = build_partial_report(
            partial_coverage(),
            (
                check(
                    "price",
                    Dimension.STRUCTURE,
                    CheckStatus.FAIL,
                    critical=True,
                ),
            ),
        )
        blocked_decision = release_decision(blocked_report, profile)

        self.assertFalse(partial_decision.complete_export_allowed)
        self.assertEqual(partial_decision.allowed_export_mode, "explicit-partial")
        self.assertFalse(blocked_decision.complete_export_allowed)
        self.assertEqual(blocked_decision.allowed_export_mode, "none")
        with self.assertRaises(ExportNotAllowed):
            assert_export_allowed(partial_decision)
        with self.assertRaises(ExportNotAllowed):
            assert_export_allowed(blocked_decision)

    def test_tampered_complete_export_flag_fails_invariant_validation(self) -> None:
        report = build_partial_report(
            partial_coverage(),
            (
                check(
                    "visual-gap",
                    Dimension.VISUAL,
                    CheckStatus.PARTIAL,
                    partial_allowed=True,
                ),
            ),
        )
        decision = release_decision(
            report,
            ReleaseGateProfile(
                profile_id="p5-pilot/1.0",
                preflight_passed=True,
                user_allowed_partial=True,
                noncritical_gap_isolatable=True,
            ),
        )
        tampered = replace(
            decision,
            complete_export_allowed=True,
            allowed_export_mode="complete",
        )

        with self.assertRaises(ValueError):
            assert_release_invariants(tampered)


if __name__ == "__main__":
    unittest.main()
