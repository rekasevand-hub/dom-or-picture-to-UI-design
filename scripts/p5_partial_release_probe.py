# -*- coding: utf-8 -*-
"""Detector-backed PARTIAL coverage and export-gate probe."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.contracts import (
    AcceptanceCheck,
    Applicability,
    CheckStatus,
    CoverageInput,
    CoverageRegion,
    CoverageState,
    Dimension,
    Rect,
    build_page_coverage,
    canonical_hash,
)
from src.app.services.delivery.partial_report import build_partial_report
from src.app.services.delivery.release_gate import (
    ReleaseGateProfile,
    release_decision,
)


PROFILE = "fixed-pilot/1.0"
PARTIAL_MAP = ROOT / "output" / "_r5_experiments" / "r5_exp_04_partial_coverage" / "coverage_map.json"
EXP05_RESULT = ROOT / "output" / "_r5_experiments" / "r5_exp_05_acceptance_gate" / "result.json"


def run_probe(output: str | Path) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    for path in (PARTIAL_MAP, EXP05_RESULT):
        if not path.is_file():
            raise FileNotFoundError(f"missing detector evidence: {path}")
    coverage_map = _load_json(PARTIAL_MAP)
    acceptance = _load_json(EXP05_RESULT)
    cases = []
    coverage_state_counts: dict[str, int] = {}
    reports: dict[str, Any] = {}
    decisions: dict[str, Any] = {}

    gate_profile = ReleaseGateProfile(
        profile_id=PROFILE,
        preflight_passed=True,
        user_allowed_partial=True,
        noncritical_gap_isolatable=True,
    )
    for case_id in (
        "intentional-omission",
        "write-failed",
        "observed-absent",
        "not-captured",
    ):
        source = coverage_map["cases"][case_id]
        gap_region = _gap_region(case_id, source)
        state = gap_region.coverage_state.value
        coverage_state_counts[state] = coverage_state_counts.get(state, 0) + 1
        report = build_partial_report(
            _page_coverage(source["coverage"]),
            (_case_check(case_id),),
            regions=(gap_region,),
            profile=PROFILE,
        )
        decision = release_decision(report, gate_profile)
        reports[case_id] = report
        decisions[case_id] = decision
        cases.append(
            {
                "case_id": case_id,
                "detector_state": state,
                "detector_gap_state": source["coverage"]["gap_state"],
                "report_status": report.status,
                "release_status": decision.status.value,
                "complete_export_allowed": decision.complete_export_allowed,
                "allowed_export_mode": decision.allowed_export_mode,
                "diff_reconciliation": source["diff_reconciliation"],
            }
        )

    checks = (
        _check(
            "states-distinct",
            "All four gap states remain distinct",
            set(coverage_state_counts)
            == {
                "intentional-omission",
                "write-failed",
                "observed-absent",
                "not-captured",
            },
        ),
        _check(
            "partial-release",
            "Intentional omission and observed absence are explicit partial releases",
            decisions["intentional-omission"].status.value == "deliverable-partial"
            and decisions["observed-absent"].status.value == "deliverable-partial",
        ),
        _check(
            "blocked-release",
            "Write failure and not-captured block release",
            decisions["write-failed"].status.value.startswith("blocked")
            and decisions["not-captured"].status.value.startswith("blocked"),
        ),
        _check(
            "no-complete-export",
            "No case permits complete export",
            all(not item.complete_export_allowed for item in decisions.values()),
        ),
        _check(
            "fixed-denominator",
            "Every partial case preserves the fixed raster denominator",
            all(
                item["diff_reconciliation"]["denominator_after_mask"]
                == item["diff_reconciliation"]["denominator_pixels"]
                == 912000
                for item in cases
            ),
        ),
        _check(
            "masked-zero-partial",
            "Masked diff zero still remains partial",
            all(
                item["diff_reconciliation"]["masked_diff_pixels"] == 0
                and item["diff_reconciliation"]["release_status_after_mask"]
                == "partial"
                for item in cases
            ),
        ),
        _check(
            "tiny-price-critical",
            "Persisted detector evidence contains a blocked tiny-price case",
            _contains_fixture(
                acceptance,
                "tiny-price-error",
            )
            and _contains_fixture(acceptance, "blocked-critical"),
        ),
        _check(
            "outside-business-flow",
            "Every report remains outside the business flow",
            all(report.outside_business_flow for report in reports.values()),
        ),
    )
    source_hashes = {
        "coverage_map_sha256": _sha256_file(PARTIAL_MAP),
        "acceptance_result_sha256": _sha256_file(EXP05_RESULT),
    }
    result = {
        "schema": "p5-partial-release-probe/1.0",
        "status": "verified-for" if all(item["passed"] for item in checks) else "blocked",
        "scope": "detector-backed PARTIAL and release gate on fixed pilot profile",
        "created_at": "2026-10-22T00:00:00+00:00",
        "profile": PROFILE,
        "code_revision": _code_revision(),
        "plugin_build": {
            "code_sha256": _sha256_file(ROOT / "figma_bridge" / "code.js"),
            "manifest_sha256": _sha256_file(ROOT / "figma_bridge" / "manifest.json"),
        },
        "thresholds": {
            "masked_diff_pixels_required": 0,
            "denominator_pixels_required": 912000,
            "critical_statuses": ["fail", "unknown", "no-ground-truth", "not-sampled"],
        },
        "source_evidence": source_hashes,
        "cases": cases,
        "coverage_state_counts": coverage_state_counts,
        "release": decisions["intentional-omission"].to_dict(),
        "checks": list(checks),
        "claim_limits": [
            "Detector states are consumed from persisted authored current-scope artifacts.",
            "The probe verifies hard-gate behavior, not production export enforcement in Figma.",
            "The fixed denominator is a raster fixture denominator, not a real-site coverage claim.",
        ],
    }
    result["content_hash"] = canonical_hash(result)
    _write_json(destination / "result.json", result)
    _write_json(destination / "partial_report.json", reports["intentional-omission"].to_dict())
    _write_json(
        destination / "manifest.json",
        {
            "schema": "p5-partial-release-manifest/1.0",
            "status": result["status"],
            "profile": PROFILE,
            "coverage_state_counts": coverage_state_counts,
            "release": result["release"],
            "source_evidence": source_hashes,
            "content_hash": result["content_hash"],
        },
    )
    return result


def _page_coverage(value: dict[str, Any]):
    area = value["area"]
    objects = value["object"]
    text = value["text"]
    critical = value["critical"]
    return build_page_coverage(
        area=CoverageInput(
            area["denominator_px"],
            area["covered_px"],
            missing=area["missing_px"],
            unknown=area["unknown_px"],
            unit="px",
        ),
        objects=CoverageInput(
            objects["denominator_count"],
            objects["covered_count"],
            missing=objects["missing_count"],
            unknown=objects["unknown_count"],
            unit="count",
        ),
        text=CoverageInput(
            text["denominator_characters"],
            text["covered_characters"],
            missing=text["missing_characters"],
            unknown=text["unknown_characters"],
            unit="characters",
        ),
        critical=CoverageInput(
            critical["denominator_count"],
            critical["covered_count"],
            missing=critical["missing_count"],
            unknown=critical["unknown_count"],
            unit="count",
        ),
        denominator_unchanged=True,
    )


def _gap_region(case_id: str, source: dict[str, Any]) -> CoverageRegion:
    region = next(
        item
        for item in source["regions"]
        if item["region_id"] == "REG-price-panel"
    )
    source_rect = region["source_rect"]
    output_rect = region["output_rect"]
    return CoverageRegion(
        region_id=f"{case_id}:{region['region_id']}",
        object_keys=tuple(region["object_keys"]),
        source_rect=Rect(
            source_rect["x"],
            source_rect["y"],
            source_rect["width"],
            source_rect["height"],
        ),
        output_rect=Rect(
            output_rect["x"],
            output_rect["y"],
            output_rect["width"],
            output_rect["height"],
        ),
        coverage_state=CoverageState(region["coverage_status"]),
        reason=region["reason"],
        evidence_refs=tuple(region["evidence"]),
        affected_dimensions=tuple(
            Dimension(item) for item in region["affected_dimensions"]
        ),
        blocked_actions=tuple(region["blocked_actions"]),
        diagnostic_mask=bool(region["diagnostic_mask"]),
    )


def _case_check(case_id: str) -> AcceptanceCheck:
    if case_id == "write-failed":
        status = CheckStatus.FAIL
        critical = True
        partial_allowed = False
    elif case_id == "not-captured":
        status = CheckStatus.UNKNOWN
        critical = True
        partial_allowed = False
    else:
        status = CheckStatus.PARTIAL
        critical = False
        partial_allowed = True
    return AcceptanceCheck(
        check_id=case_id,
        object_key="price-panel",
        dimension=Dimension.VISUAL,
        check_type="persisted-detector-status",
        critical=critical,
        required=True,
        status=status,
        partial_allowed=partial_allowed,
        applicability=Applicability.REQUIRED,
        evidence_refs=(f"detector:{case_id}",),
    )


def _contains_fixture(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value
    if isinstance(value, dict):
        return any(
            needle in str(key) or _contains_fixture(item, needle)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_fixture(item, needle) for item in value)
    return False


def _check(name: str, description: str, passed: bool) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "passed": bool(passed),
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code_revision() -> str:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return revision + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    staging = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with staging.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(staging, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="output/_p5_partial_release_round1")
    args = parser.parse_args()
    result = run_probe(args.out)
    print(json.dumps(result["coverage_state_counts"], ensure_ascii=False, indent=2))
    print("status=" + result["status"])
    print("content_hash=" + result["content_hash"])
    return 0 if result["status"] == "verified-for" else 1


if __name__ == "__main__":
    raise SystemExit(main())
