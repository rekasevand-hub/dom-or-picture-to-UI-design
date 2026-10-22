from __future__ import annotations

import base64
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from src.app.services.contracts import (
    FieldAuthority,
    FieldDecisionStatus,
    validate_audit_bundle,
    validate_runtime_ir,
)
from src.app.services.evidence import (
    DEFAULT_SAMPLE_SCOPE,
    EvidenceAdapterError,
    EvidenceStorePolicy,
    SampleSpec,
    evaluate_sample_markers,
    load_sample_registry,
    adapt_capture,
    validate_sample_scope,
    validate_sample_registry,
    write_evidence_sidecar,
)
from scripts.p1_evidence_shadow import main as shadow_main


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_CAPTURED_AT = datetime(2026, 10, 19, tzinfo=timezone.utc)


def _write_capture_fixture(root: Path, *, page_kind: str = "content") -> None:
    (root / "00_screenshot.png").write_bytes(_PNG_1X1)
    dom = [
        {
            "tag": "html",
            "text": "",
            "x": 0,
            "y": 0,
            "w": 320,
            "h": 200,
            "bg": "rgba(0, 0, 0, 0)",
            "color": "rgb(0, 0, 0)",
            "fontSize": "16px",
            "fontWeight": "400",
            "fontFamily": "",
            "position": "static",
            "zIndex": 0,
            "interactive": False,
        },
        {
            "tag": "h1",
            "role": "heading",
            "text": "Visible title",
            "x": 16,
            "y": 20,
            "w": 180,
            "h": 36,
            "bg": "rgba(0, 0, 0, 0)",
            "color": "rgb(17, 34, 51)",
            "fontSize": "32px",
            "fontWeight": "700",
            "fontFamily": "Arial",
            "lineHeight": "normal",
            "textAlign": "start",
            "textBox": [16, 20, 180, 36],
            "textEmBox": [16, 20, 180, 36],
            "textEmLines": 1,
            "position": "static",
            "zIndex": 0,
            "interactive": False,
            "pIdx": 0,
        },
        {
            "tag": "div",
            "text": "",
            "x": 16,
            "y": 70,
            "w": 120,
            "h": 80,
            "bg": "rgb(255, 255, 255)",
            "bgImage": True,
            "position": "relative",
            "zIndex": 2,
            "interactive": False,
            "pIdx": 0,
        },
    ]
    (root / "00_dom.json").write_text(
        json.dumps(dom, ensure_ascii=False),
        encoding="utf-8",
    )
    page_state = {
        "requested_url": "https://fixture.example/page",
        "final_url": "https://fixture.example/page",
        "kind": page_kind,
        "confidence": 0.99,
        "reason": "fixture",
        "signals": {"passwordInputs": 0, "hasCaptchaElement": False},
        "attempts": [
            {
                "label": "headless",
                "final_url": "https://fixture.example/page",
                "http_status": 200,
                "page_state": {"kind": page_kind},
                "image": "capture_attempts/headless.png",
                "dom": "capture_attempts/headless_dom.json",
                "diagnostics": "capture_attempts/headless_dom_diagnostics.json",
                "error": None,
            }
        ],
        "fallback_used": False,
        "screenshot_source": "headless",
        "screenshot_only": page_kind != "content",
        "requested_route": "auto",
    }
    (root / "00_page_state.json").write_text(
        json.dumps(page_state, ensure_ascii=False),
        encoding="utf-8",
    )
    diagnostics = {
        "schema": 1,
        "url": "https://fixture.example/page",
        "page": {},
        "captured": {"elements": 3},
        "capture_gaps": {"shadow": 2},
        "unsupported": {"grid": 1, "flex_wrap": 0, "gradient": 1, "pseudo": 1},
        "samples": {},
        "notes": {},
    }
    (root / "00_dom_diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False),
        encoding="utf-8",
    )


class SampleScopeTests(unittest.TestCase):
    def test_default_scope_covers_p1_required_capture_boundaries(self) -> None:
        categories = {scenario.category for scenario in DEFAULT_SAMPLE_SCOPE.scenarios}
        self.assertEqual(
            categories,
            {
                "iframe",
                "shadow-dom",
                "canvas",
                "dynamic-state",
                "ocr",
                "assets",
                "capture-fallback",
            },
        )

    def test_scope_rejects_duplicate_scenario_ids(self) -> None:
        broken = DEFAULT_SAMPLE_SCOPE.__class__(
            scope_version=DEFAULT_SAMPLE_SCOPE.scope_version,
            browser_scope=DEFAULT_SAMPLE_SCOPE.browser_scope,
            required_page_states=DEFAULT_SAMPLE_SCOPE.required_page_states,
            scenarios=(
                DEFAULT_SAMPLE_SCOPE.scenarios[0],
                DEFAULT_SAMPLE_SCOPE.scenarios[0],
            ),
        )
        self.assertTrue(
            any("duplicate scenario id" in item for item in validate_sample_scope(broken))
        )

    def test_default_registry_has_two_runs_and_a_real_source_per_scenario(self) -> None:
        registry = load_sample_registry(
            Path("docs/v2_mentor/p1_sample_registry.json")
        )
        self.assertEqual(validate_sample_registry(registry), ())
        self.assertEqual(len(registry.samples), 14)
        for scenario in DEFAULT_SAMPLE_SCOPE.scenarios:
            samples = [
                item for item in registry.samples
                if item.scenario_id == scenario.scenario_id
            ]
            self.assertGreaterEqual(len(samples), 2)
            self.assertTrue(any(item.source_kind == "real" for item in samples))
            if scenario.category != "capture-fallback":
                self.assertTrue(
                    all(item.expected_markers for item in samples),
                    f"{scenario.scenario_id} samples need structural markers",
                )

    def test_marker_evaluation_rejects_content_page_without_declared_structure(self) -> None:
        sample = SampleSpec(
            sample_id="test",
            scenario_id="P1-S01",
            source_kind="controlled",
            locator="fixture.html",
            expected_page_state="content",
            expected_markers={"iframe": 2},
        )
        result = evaluate_sample_markers(
            sample,
            [{"tag": "iframe"}, {"tag": "div"}],
            {"kind": "content"},
        )
        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["markers"]["iframe"]["pass"])


class RetentionPolicyTests(unittest.TestCase):
    def test_default_policy_sets_replay_and_audit_expiries(self) -> None:
        policy = EvidenceStorePolicy()
        contract = policy.to_contract(
            datetime(2026, 10, 19, tzinfo=timezone.utc)
        )
        self.assertEqual(contract.replay_evidence_days, 30)
        self.assertEqual(contract.audit_metadata_days, 180)
        self.assertEqual(contract.evidence_expires_at, "2026-11-18T00:00:00+00:00")
        self.assertEqual(contract.audit_metadata_expires_at, "2027-04-17T00:00:00+00:00")

    def test_policy_rejects_audit_shorter_than_replay(self) -> None:
        with self.assertRaises(ValueError):
            EvidenceStorePolicy(replay_evidence_days=30, audit_metadata_days=29)


class EvidenceAdapterTests(unittest.TestCase):
    def test_adapter_builds_runtime_ir_and_audit_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            capture_dir = Path(tmp) / "capture"
            capture_dir.mkdir()
            _write_capture_fixture(capture_dir)

            sidecar = adapt_capture(
                capture_dir,
                captured_at=_CAPTURED_AT,
                job_id="job-p1",
            )

        self.assertEqual(sidecar.runtime_ir.job_id, "job-p1")
        self.assertEqual(validate_runtime_ir(sidecar.runtime_ir), [])
        self.assertEqual(validate_audit_bundle(sidecar.audit_bundle), [])
        self.assertTrue(sidecar.runtime_ir.capture_id.startswith("capture-"))
        self.assertEqual(
            {item.kind for item in sidecar.runtime_ir.evidence},
            {"screenshot", "dom-json", "page-state-json", "dom-diagnostics-json"},
        )
        field_types = {item.field_type for item in sidecar.runtime_ir.fields}
        self.assertIn("text-content", field_types)
        self.assertIn("geometry", field_types)
        self.assertIn("role", field_types)
        self.assertIn("asset-hint", field_types)
        self.assertTrue(sidecar.runtime_ir.fields)
        self.assertTrue(
            all(
                item.decision.status is FieldDecisionStatus.OBSERVED
                and item.decision.release_eligible is False
                for item in sidecar.runtime_ir.fields
            )
        )
        self.assertTrue(
            all(
                item.decision.authority
                in {FieldAuthority.DOM, FieldAuthority.NONE}
                for item in sidecar.runtime_ir.fields
            )
        )
        unknown_fields = {item.field for item in sidecar.runtime_ir.unknowns}
        self.assertIn("shadow-capture", unknown_fields)
        self.assertIn("layout.grid", unknown_fields)
        self.assertTrue(sidecar.manifest["shadow_mode"])
        self.assertFalse(sidecar.manifest["default_path_changed"])
        self.assertFalse(sidecar.manifest["figma_write"])

    def test_manifest_retains_frame_scope_and_opaque_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            capture_dir = Path(tmp) / "capture"
            capture_dir.mkdir()
            _write_capture_fixture(capture_dir)
            page_state_path = capture_dir / "00_page_state.json"
            page_state = json.loads(page_state_path.read_text(encoding="utf-8"))
            page_state["navigation"] = {
                "status": "ok",
                "requested_url": page_state["requested_url"],
                "final_url": page_state["final_url"],
            }
            page_state["frame_inventory"] = [
                {
                    "path": "root/0",
                    "scope_path": "root/v0",
                    "depth": 1,
                    "url": "https://fixture.example/child",
                    "same_origin": True,
                    "accessible": True,
                    "opaque_frame": False,
                    "rendered": True,
                },
                {
                    "path": "root/1",
                    "scope_path": "root/v1",
                    "depth": 1,
                    "url": "https://opaque.example/frame",
                    "same_origin": False,
                    "accessible": False,
                    "opaque_frame": True,
                    "opaque_reason": "cross-origin",
                    "rendered": True,
                },
            ]
            page_state["frame_summary"] = {
                "frame_count": 2,
                "rendered_frame_count": 2,
                "accessible_frame_count": 1,
                "opaque_frame_count": 1,
            }
            page_state["capture_profile"] = "first-party-frame-strict/1.0"
            page_state["frame_request_policy"] = {
                "block_cross_origin_frame_documents": True,
                "blocked_document_count": 1,
            }
            page_state_path.write_text(
                json.dumps(page_state, ensure_ascii=False),
                encoding="utf-8",
            )

            sidecar = adapt_capture(
                capture_dir,
                captured_at=_CAPTURED_AT,
                job_id="job-frame-scope",
            )

        self.assertEqual(sidecar.manifest["frames"]["summary"]["frame_count"], 2)
        self.assertEqual(
            sidecar.manifest["frames"]["inventory_source"],
            "evidence/page_state.json",
        )
        self.assertEqual(sidecar.manifest["navigation"]["status"], "ok")
        self.assertEqual(
            sidecar.manifest["capture_profile"],
            "first-party-frame-strict/1.0",
        )
        self.assertEqual(
            sidecar.manifest["frame_request_policy"]["blocked_document_count"],
            1,
        )
        unknown_fields = {item.field for item in sidecar.runtime_ir.unknowns}
        self.assertIn("frame-content", unknown_fields)

    def test_writer_copies_evidence_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_dir = root / "capture"
            output_dir = root / "sidecar"
            capture_dir.mkdir()
            _write_capture_fixture(capture_dir)

            first = write_evidence_sidecar(
                capture_dir,
                output_dir,
                captured_at=_CAPTURED_AT,
                overwrite=False,
            )
            first_ir = (output_dir / "runtime_ir.json").read_bytes()
            second = write_evidence_sidecar(
                capture_dir,
                output_dir,
                captured_at=_CAPTURED_AT,
                overwrite=True,
            )
            second_ir = (output_dir / "runtime_ir.json").read_bytes()

            self.assertEqual(
                (output_dir / "evidence" / "screenshot.png").read_bytes(),
                _PNG_1X1,
            )
            self.assertTrue((output_dir / "audit_bundle.json").is_file())
            self.assertTrue((output_dir / "manifest.json").is_file())
            self.assertEqual(first.manifest["content_hash"], second.manifest["content_hash"])
            self.assertEqual(first_ir, second_ir)

    def test_adapter_hashes_data_uri_assets_and_marks_remote_reference_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_dir = root / "capture"
            output_dir = root / "sidecar"
            capture_dir.mkdir()
            _write_capture_fixture(capture_dir)
            dom_path = capture_dir / "00_dom.json"
            dom = json.loads(dom_path.read_text(encoding="utf-8"))
            dom[2]["tag"] = "img"
            dom[2]["assetSrc"] = (
                "data:image/png;base64,"
                + base64.b64encode(_PNG_1X1).decode("ascii")
            )
            dom.append(
                {
                    "tag": "div",
                    "x": 16,
                    "y": 180,
                    "w": 80,
                    "h": 40,
                    "bgUrls": ["https://assets.example/remote.png"],
                    "position": "static",
                    "zIndex": 0,
                }
            )
            dom_path.write_text(json.dumps(dom), encoding="utf-8")

            sidecar = adapt_capture(capture_dir, captured_at=_CAPTURED_AT)
            written = write_evidence_sidecar(
                capture_dir,
                output_dir,
                captured_at=_CAPTURED_AT,
            )
            assets = {item.asset_id: item for item in sidecar.runtime_ir.assets}
            local = assets["asset-0002-img"]
            remote = assets["asset-0003-bg-0"]
            self.assertTrue(local.local_bytes_present)
            self.assertEqual(local.local_sha256, next(
                item.sha256 for item in sidecar.runtime_ir.evidence
                if item.evidence_id == "ev-asset-0002-img"
            ))
            self.assertFalse(remote.local_bytes_present)
            self.assertEqual(remote.source_url, "https://assets.example/remote.png")
            asset_record = next(
                item for item in sidecar.runtime_ir.evidence
                if item.evidence_id == "ev-asset-0002-img"
            )
            self.assertTrue((output_dir / asset_record.locator).is_file())
            self.assertEqual(
                json.loads(
                    (output_dir / "manifest.json").read_text(encoding="utf-8")
                )["assets"][0]["status"],
                "local-bytes",
            )

    def test_missing_screenshot_fails_closed_without_partial_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_dir = root / "capture"
            output_dir = root / "sidecar"
            capture_dir.mkdir()
            _write_capture_fixture(capture_dir)
            (capture_dir / "00_screenshot.png").unlink()

            with self.assertRaises(EvidenceAdapterError):
                write_evidence_sidecar(
                    capture_dir,
                    output_dir,
                    captured_at=_CAPTURED_AT,
                )

            self.assertFalse(output_dir.exists() and any(output_dir.iterdir()))

    def test_adapter_rejects_evidence_over_size_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            capture_dir = Path(tmp) / "capture"
            capture_dir.mkdir()
            _write_capture_fixture(capture_dir)
            policy = EvidenceStorePolicy(max_total_bytes=16)

            with self.assertRaises(EvidenceAdapterError):
                adapt_capture(
                    capture_dir,
                    captured_at=_CAPTURED_AT,
                    policy=policy,
                )

    def test_soft_block_preserves_evidence_without_inventing_content_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            capture_dir = Path(tmp) / "capture"
            capture_dir.mkdir()
            _write_capture_fixture(capture_dir, page_kind="soft_block")

            sidecar = adapt_capture(capture_dir, captured_at=_CAPTURED_AT)

        self.assertFalse(
            any(item.field_type in {"text-content", "role", "asset-hint"}
                for item in sidecar.runtime_ir.fields)
        )
        unknown = {(item.field, item.status) for item in sidecar.runtime_ir.unknowns}
        self.assertIn(("page-content", "soft_block"), unknown)

    def test_screenshot_only_content_keeps_dom_as_evidence_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            capture_dir = Path(tmp) / "capture"
            capture_dir.mkdir()
            _write_capture_fixture(capture_dir)
            page_state_path = capture_dir / "00_page_state.json"
            page_state = json.loads(page_state_path.read_text(encoding="utf-8"))
            page_state["screenshot_only"] = True
            page_state_path.write_text(
                json.dumps(page_state, ensure_ascii=False),
                encoding="utf-8",
            )

            sidecar = adapt_capture(capture_dir, captured_at=_CAPTURED_AT)

        self.assertFalse(
            any(item.field_type in {"text-content", "role", "asset-hint"}
                for item in sidecar.runtime_ir.fields)
        )
        self.assertIn(
            ("dom-content", "screenshot-only"),
            {(item.field, item.status) for item in sidecar.runtime_ir.unknowns},
        )

    def test_shadow_cli_writes_sidecar_and_reports_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_dir = root / "capture"
            output_dir = root / "sidecar"
            capture_dir.mkdir()
            _write_capture_fixture(capture_dir)
            output = StringIO()
            with redirect_stdout(output):
                status = shadow_main(
                    [
                        str(capture_dir),
                        "--out",
                        str(output_dir),
                        "--captured-at",
                        "2026-10-19T00:00:00+00:00",
                        "--job-id",
                        "job-cli",
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(status, 0)
            self.assertEqual(payload["job_id"], "job-cli")
            self.assertTrue(payload["shadow_mode"])
            self.assertTrue((output_dir / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
