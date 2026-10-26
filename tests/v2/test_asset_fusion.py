from __future__ import annotations

import unittest

from src.app.services.structure.asset_fusion import fuse_asset_record


def _record(
    *,
    source_status: str = "verified-original",
    source_kind: str = "data-uri",
    provenance: str = "data-uri",
    display_status: str = "available",
    replaceable: bool | None = None,
) -> dict:
    verified = source_status == "verified-original"
    if replaceable is None:
        replaceable = verified
    return {
        "asset_id": "asset:sha256:" + "a" * 64 if verified else "asset:ref:" + "b" * 64,
        "source_identity": {
            "status": source_status,
            "source_kind": source_kind,
            "payload_sha256": "a" * 64 if verified else None,
            "mime": "image/png" if verified else None,
            "natural_size": [100.0, 80.0],
            "bytes_present": verified,
            "provenance": provenance,
        },
        "display_payload": {
            "status": display_status,
            "kind": "screenshot-crop" if display_status == "available" else "none",
            "payload_sha256": "c" * 64 if display_status == "available" else None,
            "screenshot_sha256": "d" * 64,
            "display_box": [0, 0, 100, 80],
            "source_rect": [0, 0, 100, 80],
            "object_fit": "fill",
            "original": False,
            "reference_only": True,
        },
        "replacement": {
            "allowed": replaceable,
            "mode": "source-bytes" if replaceable else "none",
            "figma_runtime": "not-evaluated",
        },
        "missing": {
            "is_missing": source_status == "missing" or display_status != "available",
            "status": "missing-source"
            if source_status == "missing"
            else "loaded"
            if display_status == "available"
            else "missing-display",
            "outcome": "partial-not-pass"
            if source_status == "missing" or display_status != "available"
            else "pass",
        },
        "use": {
            "use_id": "DQ-T:1:img",
            "node_index": 1,
            "source_kind": "img",
            "display_box": [0, 0, 100, 80],
        },
    }


def _generated(**overrides) -> dict:
    candidate = {
        "payload_sha256": "e" * 64,
        "bytes_present": True,
        "generator": "fixture-generator",
        "model": "fixture-model",
        "input_reference": "DQ-T:1:img",
        "prompt": "reconstruct the missing image",
        "prompt_version": "1",
        "review_status": "unreviewed",
    }
    candidate.update(overrides)
    return candidate


class AssetFusionTests(unittest.TestCase):
    def test_verified_source_selects_dom_identity_and_capture_display(self) -> None:
        result = fuse_asset_record(_record())

        self.assertEqual(result["identity"]["selected"], "verified-source")
        self.assertEqual(result["identity"]["source_tier"], "dom-source")
        self.assertTrue(result["identity"]["original"])
        self.assertTrue(result["identity"]["replaceable"])
        self.assertEqual(result["display"]["selected"], "screenshot-crop")
        self.assertFalse(result["display"]["original"])
        self.assertTrue(result["display"]["reference_only"])
        self.assertFalse(result["display"]["fallback_used"])
        self.assertEqual(
            result["fallback_chain"],
            ["dom-source", "screenshot-crop"],
        )
        self.assertEqual(result["status"], "resolved-source-and-capture")

    def test_recovered_network_source_is_second_identity_tier(self) -> None:
        result = fuse_asset_record(
            _record(source_kind="network-response", provenance="network-response")
        )

        self.assertEqual(result["identity"]["source_tier"], "recovered-network")
        self.assertTrue(result["identity"]["replaceable"])
        self.assertEqual(result["fallback_chain"][0], "recovered-network")

    def test_reference_or_missing_identity_does_not_block_available_crop(self) -> None:
        for status in ("reference-only", "missing"):
            with self.subTest(status=status):
                result = fuse_asset_record(_record(source_status=status))
                self.assertEqual(result["identity"]["selected"], status)
                self.assertFalse(result["identity"]["original"])
                self.assertFalse(result["identity"]["replaceable"])
                self.assertEqual(result["display"]["selected"], "screenshot-crop")
                self.assertEqual(result["status"], "partial-unresolved-identity")

    def test_generated_candidate_is_used_only_when_capture_is_missing(self) -> None:
        result = fuse_asset_record(
            _record(source_status="unavailable", display_status="missing"),
            generated_candidates=[_generated()],
        )

        self.assertEqual(result["display"]["selected"], "generated-approximation")
        self.assertTrue(result["display"]["generated"])
        self.assertFalse(result["display"]["original"])
        self.assertFalse(result["display"]["reference_only"])
        self.assertTrue(result["display"]["fallback_used"])
        self.assertFalse(result["identity"]["original"])
        self.assertFalse(result["identity"]["replaceable"])
        self.assertEqual(result["status"], "partial-generated-display")
        self.assertEqual(
            result["display"]["provenance"],
            {
                "generator": "fixture-generator",
                "model": "fixture-model",
                "input_reference": "DQ-T:1:img",
                "prompt": "reconstruct the missing image",
                "prompt_version": "1",
                "review_status": "unreviewed",
                "payload_sha256": "e" * 64,
            },
        )

    def test_capture_outranks_generated_candidate(self) -> None:
        result = fuse_asset_record(
            _record(),
            generated_candidates=[_generated()],
        )

        self.assertEqual(result["display"]["selected"], "screenshot-crop")
        generated = next(
            row
            for row in result["candidates"]
            if row["kind"] == "generated-approximation"
        )
        self.assertEqual(generated["status"], "rejected")
        self.assertEqual(
            generated["reason"],
            "higher-priority-capture-available",
        )

    def test_icon_policy_can_prefer_generated_candidate_over_capture(self) -> None:
        record = _record(source_status="unavailable")
        record["use"]["source_kind"] = "icon-crop"
        result = fuse_asset_record(
            record,
            generated_candidates=[_generated(use_class="icon-crop")],
            prefer_generated_for_icon_crop=True,
        )

        self.assertEqual(result["display"]["selected"], "generated-approximation")
        self.assertTrue(result["display"]["generated"])
        self.assertEqual(result["status"], "generated-icon-display")
        capture = next(
            row for row in result["candidates"] if row["kind"] == "screenshot-crop"
        )
        self.assertEqual(capture["status"], "rejected")
        self.assertEqual(capture["reason"], "generated-icon-policy")
        generated = next(
            row
            for row in result["candidates"]
            if row["kind"] == "generated-approximation"
        )
        self.assertEqual(generated["reason"], "policy-prefers-generated-icon")

    def test_generated_provenance_is_complete_or_rejected(self) -> None:
        result = fuse_asset_record(
            _record(source_status="unavailable", display_status="missing"),
            generated_candidates=[_generated(model="")],
        )

        self.assertEqual(result["display"]["selected"], "missing")
        self.assertFalse(result["display"]["generated"])
        self.assertEqual(result["status"], "blocked-generated-provenance")
        generated = next(
            row
            for row in result["candidates"]
            if row["kind"] == "generated-approximation"
        )
        self.assertEqual(generated["status"], "blocked")
        self.assertIn("model", generated["reason"])

    def test_verified_identity_and_generated_display_remain_independent(self) -> None:
        result = fuse_asset_record(
            _record(display_status="missing"),
            generated_candidates=[_generated()],
        )

        self.assertEqual(result["identity"]["selected"], "verified-source")
        self.assertTrue(result["identity"]["replaceable"])
        self.assertEqual(result["display"]["selected"], "generated-approximation")
        self.assertFalse(result["display"]["original"])
        self.assertEqual(result["status"], "partial-generated-display")

    def test_missing_display_without_generated_candidate_is_visible(self) -> None:
        result = fuse_asset_record(
            _record(display_status="missing"),
        )

        self.assertEqual(result["display"]["selected"], "missing")
        self.assertEqual(result["status"], "partial-missing-display")
        self.assertEqual(result["fallback_chain"][-1], "missing")

    def test_candidate_order_is_deterministic(self) -> None:
        first = fuse_asset_record(
            _record(display_status="missing"),
            generated_candidates=[_generated(), _generated(payload_sha256="f" * 64)],
        )
        second = fuse_asset_record(
            _record(display_status="missing"),
            generated_candidates=[_generated(), _generated(payload_sha256="f" * 64)],
        )

        self.assertEqual(first, second)
        self.assertEqual(
            [row["kind"] for row in first["candidates"]],
            [
                "verified-source",
                "screenshot-crop",
                "generated-approximation",
                "generated-approximation",
            ],
        )


if __name__ == "__main__":
    unittest.main()
