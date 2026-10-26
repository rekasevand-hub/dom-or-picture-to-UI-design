from __future__ import annotations

import base64
import hashlib
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

from src.app.services.structure.capture import DOM_JS
from src.app.services.structure.asset_metadata import (
    AssetIdentity,
    attach_display_payload,
    attach_verified_source_identity,
    build_asset_record,
    deduplicate_asset_records,
    object_fit_source_rect,
    parse_data_uri_asset,
    resolve_asset_identity,
)
from src.app.services.structure.providers.dom import _asset_metadata_for_node
from src.app.services.som.direct_design import (
    _carry_asset_metadata,
    build_direct_design,
)


class AssetMetadataTests(unittest.TestCase):
    def test_svg_data_uri_records_identity_dimensions_and_bytes(self) -> None:
        source = (
            "data:image/svg+xml,"
            "%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='100'%3E"
            "%3Crect width='200' height='100' fill='%23e85d75'/%3E%3C/svg%3E"
        )

        asset = parse_data_uri_asset(source)

        self.assertEqual(asset["mime"], "image/svg+xml")
        self.assertEqual(asset["natural_size"], [200.0, 100.0])
        self.assertEqual(
            asset["sha256"],
            hashlib.sha256(asset["bytes"]).hexdigest(),
        )
        self.assertEqual(asset["byte_length"], len(asset["bytes"]))

    def test_svg_viewbox_supplies_intrinsic_dimensions(self) -> None:
        source = (
            "data:image/svg+xml,"
            "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 516 154'%3E"
            "%3C/svg%3E"
        )

        asset = parse_data_uri_asset(source)

        self.assertEqual(asset["mime"], "image/svg+xml")
        self.assertEqual(asset["natural_size"], [516.0, 154.0])

    def test_cover_object_position_right_crops_the_right_source_half(self) -> None:
        crop = object_fit_source_rect(
            display_size=[100, 100],
            natural_size=[200, 100],
            object_fit="cover",
            object_position="right center",
        )

        self.assertEqual(crop["source_rect"], [100.0, 0.0, 100.0, 100.0])
        self.assertEqual(crop["scale"], 1.0)
        self.assertEqual(crop["object_fit"], "cover")

    def test_dom_probe_records_natural_size_and_object_fit(self) -> None:
        fixture = (
            Path(__file__).resolve().parents[1]
            / "fixtures"
            / "p1"
            / "canonical"
            / "transparent_crop.html"
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 900, "height": 700})
                page.goto(fixture.resolve().as_uri(), wait_until="domcontentloaded")
                page.wait_for_timeout(200)
                nodes = page.evaluate(DOM_JS)
            finally:
                browser.close()

        image = next(item for item in nodes if item.get("tag") == "img")
        self.assertEqual(image["naturalWidth"], 200)
        self.assertEqual(image["naturalHeight"], 100)
        self.assertEqual(image["objectFit"], "cover")
        self.assertEqual(image["objectPosition"], "0% 50%")

    def test_image_node_produces_identity_and_source_crop(self) -> None:
        source = (
            "data:image/svg+xml,"
            "%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='100'%3E"
            "%3Crect width='200' height='100' fill='%23e85d75'/%3E%3C/svg%3E"
        )
        node = {
            "tag": "img",
            "assetSrc": source,
            "naturalWidth": 200,
            "naturalHeight": 100,
            "objectFit": "cover",
            "objectPosition": "100% 50%",
        }

        identity, crop = _asset_metadata_for_node(
            node,
            [40, 40, 100, 100],
        )

        self.assertEqual(identity["mime"], "image/svg+xml")
        self.assertEqual(identity["natural_size"], [200.0, 100.0])
        self.assertEqual(crop["source_rect"], [100.0, 0.0, 100.0, 100.0])
        record = identity["asset_record"]
        self.assertEqual(
            record["source_identity"]["status"],
            "verified-original",
        )
        self.assertTrue(record["replacement"]["allowed"])

    def test_design_carries_asset_identity_and_source_crop(self) -> None:
        element = {}
        item = {
            "assetIdentity": {
                "source_kind": "data-uri",
                "content_sha256": "abc",
            },
            "sourceCrop": {
                "source_rect": [100.0, 0.0, 100.0, 100.0],
                "object_fit": "cover",
            },
            "displayPayload": {
                "kind": "screenshot-crop",
                "payload_sha256": "c" * 64,
            },
            "replacement": {
                "allowed": True,
                "mode": "source-bytes",
            },
        }

        _carry_asset_metadata(element, item)

        self.assertEqual(element["assetIdentity"], item["assetIdentity"])
        self.assertEqual(element["sourceCrop"], item["sourceCrop"])
        self.assertEqual(element["displayPayload"], item["displayPayload"])
        self.assertEqual(element["replacement"], item["replacement"])

    def test_background_image_data_uri_uses_first_url_for_identity(self) -> None:
        source = (
            "data:image/svg+xml,"
            "%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='80'%3E"
            "%3Crect width='160' height='80' fill='%23f0a24b'/%3E%3C/svg%3E"
        )
        node = {
            "tag": "div",
            "bgUrls": [source],
            "objectFit": "fill",
            "objectPosition": "50% 50%",
        }

        identity, crop = _asset_metadata_for_node(
            node,
            [8, 182, 160, 80],
        )

        self.assertEqual(identity["mime"], "image/svg+xml")
        self.assertEqual(identity["natural_size"], [160.0, 80.0])
        self.assertEqual(crop["source_rect"], [0.0, 0.0, 160.0, 80.0])
        self.assertEqual(
            identity["asset_record"]["source_identity"]["source_kind"],
            "data-uri",
        )

    def test_remote_dom_node_keeps_reference_only_identity(self) -> None:
        node = {
            "tag": "img",
            "assetSrc": "https://cdn.example/hero.png",
            "naturalWidth": 640,
            "naturalHeight": 480,
            "objectFit": "cover",
            "objectPosition": "50% 50%",
        }

        identity, _crop = _asset_metadata_for_node(
            node,
            [0, 0, 320, 240],
        )

        record = identity["asset_record"]
        self.assertEqual(
            record["source_identity"]["status"],
            "reference-only",
        )
        self.assertFalse(record["replacement"]["allowed"])

    def test_truncated_data_uri_does_not_become_verified_original(self) -> None:
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100'>"
            "<!--" + "x" * 21000 + "--></svg>"
        ).encode("utf-8")
        source = ("data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii"))[
            :20000
        ]
        node = {
            "tag": "img",
            "assetSrc": source,
            "naturalWidth": 100,
            "naturalHeight": 100,
            "objectFit": "fill",
            "objectPosition": "50% 50%",
        }

        identity, _crop = _asset_metadata_for_node(
            node,
            [0, 0, 100, 100],
        )

        self.assertEqual(
            identity["asset_record"]["source_identity"]["status"],
            "blocked-incomplete-identity",
        )
        self.assertFalse(identity["asset_record"]["replacement"]["allowed"])

    def test_remote_url_alone_is_reference_only_and_not_replaceable(self) -> None:
        identity = resolve_asset_identity(
            source_url="https://cdn.example/hero.png",
        )

        self.assertIsInstance(identity, AssetIdentity)
        self.assertEqual(identity.status, "reference-only")
        self.assertEqual(identity.replacement_mode, "reference-only")
        self.assertFalse(identity.replacement_allowed)
        self.assertIsNone(identity.payload_sha256)
        self.assertIsNone(identity.natural_size)

    def test_stable_payload_hash_and_natural_size_authorize_replacement(self) -> None:
        identity = resolve_asset_identity(
            source_url="https://cdn.example/hero.png",
            payload_sha256="a" * 64,
            natural_size=(1200, 800),
        )

        self.assertEqual(identity.status, "ready")
        self.assertEqual(identity.replacement_mode, "original-bytes")
        self.assertTrue(identity.replacement_allowed)

    def test_expired_url_requires_retained_bytes_or_fails_closed(self) -> None:
        retained = resolve_asset_identity(
            source_url="https://cdn.example/expired.png",
            payload_sha256="b" * 64,
            natural_size=(640, 480),
            url_expired=True,
            retained_bytes_present=True,
        )
        blocked = resolve_asset_identity(
            source_url="https://cdn.example/expired.png",
            payload_sha256="b" * 64,
            natural_size=(640, 480),
            url_expired=True,
            retained_bytes_present=False,
        )

        self.assertEqual(retained.status, "retained-bytes")
        self.assertEqual(retained.replacement_mode, "retained-bytes")
        self.assertTrue(retained.replacement_allowed)
        self.assertEqual(blocked.status, "blocked-expired-url")
        self.assertFalse(blocked.replacement_allowed)

    def test_verified_source_and_screenshot_display_are_separate(self) -> None:
        source = (
            "data:image/svg+xml,"
            "%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='100'%3E"
            "%3Crect width='200' height='100' fill='%23e85d75'/%3E%3C/svg%3E"
        )
        parsed = parse_data_uri_asset(source)

        record = build_asset_record(
            sample_id="DQ-T01",
            node_index=7,
            source_kind="img",
            source=source,
            natural_size=(200, 100),
            source_payload_sha256=parsed["sha256"],
            mime=parsed["mime"],
            source_bytes_present=True,
            source_provenance="data-uri",
            display_box=(40, 50, 100, 100),
            display_payload_sha256="c" * 64,
            screenshot_sha256="d" * 64,
            source_rect=(100, 0, 100, 100),
            object_fit="cover",
        )

        self.assertEqual(
            record["source_identity"]["status"],
            "verified-original",
        )
        self.assertEqual(
            record["display_payload"]["kind"],
            "screenshot-crop",
        )
        self.assertFalse(record["display_payload"]["original"])
        self.assertTrue(record["display_payload"]["reference_only"])
        self.assertTrue(record["replacement"]["allowed"])
        self.assertEqual(record["replacement"]["mode"], "source-bytes")
        self.assertEqual(record["use"]["use_id"], "DQ-T01:7:img")

    def test_remote_url_alone_is_reference_only(self) -> None:
        record = build_asset_record(
            sample_id="DQ-T02",
            node_index=8,
            source_kind="img",
            source="https://cdn.example/hero.png",
            natural_size=(640, 480),
            display_box=(0, 0, 320, 240),
            display_payload_sha256="e" * 64,
        )

        self.assertEqual(record["source_identity"]["status"], "reference-only")
        self.assertFalse(record["source_identity"]["bytes_present"])
        self.assertFalse(record["display_payload"]["original"])
        self.assertFalse(record["replacement"]["allowed"])
        self.assertEqual(record["replacement"]["mode"], "none")

    def test_screenshot_crop_hash_never_becomes_original(self) -> None:
        record = build_asset_record(
            sample_id="DQ-T03",
            node_index=9,
            source_kind="bg-0",
            source=None,
            natural_size=None,
            display_box=(12, 16, 80, 60),
            display_payload_sha256="f" * 64,
            screenshot_sha256="a" * 64,
        )

        self.assertEqual(record["display_payload"]["status"], "available")
        self.assertEqual(record["display_payload"]["kind"], "screenshot-crop")
        self.assertEqual(
            record["source_identity"]["status"],
            "unavailable",
        )
        self.assertFalse(record["replacement"]["allowed"])

    def test_incomplete_source_identity_fails_closed(self) -> None:
        record = build_asset_record(
            sample_id="DQ-T04",
            node_index=10,
            source_kind="img",
            source="https://cdn.example/incomplete.png",
            natural_size=(100, 50),
            source_payload_sha256="b" * 64,
            mime=None,
            source_bytes_present=True,
            source_provenance="network-response",
        )

        self.assertEqual(
            record["source_identity"]["status"],
            "blocked-incomplete-identity",
        )
        self.assertFalse(record["replacement"]["allowed"])
        self.assertIn("mime", record["source_identity"]["reason"])

    def test_missing_asset_remains_partial_not_pass(self) -> None:
        record = build_asset_record(
            sample_id="DQ-T05",
            node_index=11,
            source_kind="img",
            source="https://cdn.example/missing.png",
            natural_size=(0, 0),
            load_status="missing",
        )

        self.assertTrue(record["missing"]["is_missing"])
        self.assertEqual(record["missing"]["status"], "missing-source")
        self.assertEqual(record["missing"]["outcome"], "partial-not-pass")
        self.assertFalse(record["replacement"]["allowed"])

    def test_shared_source_has_one_asset_and_two_uses(self) -> None:
        source = "https://cdn.example/shared.png"
        first = build_asset_record(
            sample_id="DQ-T06",
            node_index=20,
            source_kind="img",
            source=source,
            natural_size=(80, 80),
            source_payload_sha256="1" * 64,
            mime="image/png",
            source_bytes_present=True,
            source_provenance="network-response",
            display_box=(10, 10, 40, 40),
            display_payload_sha256="2" * 64,
        )
        second = build_asset_record(
            sample_id="DQ-T06",
            node_index=21,
            source_kind="img",
            source=source,
            natural_size=(80, 80),
            source_payload_sha256="1" * 64,
            mime="image/png",
            source_bytes_present=True,
            source_provenance="network-response",
            display_box=(60, 10, 40, 40),
            display_payload_sha256="3" * 64,
        )

        ledger = deduplicate_asset_records([first, second])

        self.assertEqual(len(ledger["assets"]), 1)
        self.assertEqual(len(ledger["uses"]), 2)
        self.assertEqual(ledger["uses"][0]["asset_id"], ledger["uses"][1]["asset_id"])
        self.assertNotEqual(ledger["uses"][0]["use_id"], ledger["uses"][1]["use_id"])

    def test_attach_display_payload_keeps_crop_non_original(self) -> None:
        record = build_asset_record(
            sample_id="DQ-T07",
            node_index=30,
            source_kind="img",
            source="https://cdn.example/hero.png",
            natural_size=(100, 50),
            display_box=(5, 6, 100, 50),
        )

        enriched = attach_display_payload(
            record,
            payload_sha256="9" * 64,
            screenshot_sha256="8" * 64,
            display_box=(5, 6, 100, 50),
        )

        self.assertEqual(
            enriched["display_payload"]["payload_sha256"],
            "9" * 64,
        )
        self.assertEqual(enriched["display_payload"]["kind"], "screenshot-crop")
        self.assertFalse(enriched["display_payload"]["original"])
        self.assertFalse(enriched["replacement"]["allowed"])

    def test_display_box_alone_does_not_claim_a_display_payload(self) -> None:
        record = build_asset_record(
            sample_id="DQ-T08",
            node_index=31,
            source_kind="img",
            source=None,
            natural_size=None,
            display_box=(5, 6, 100, 50),
        )

        self.assertEqual(record["display_payload"]["status"], "missing")
        self.assertEqual(record["display_payload"]["kind"], "none")
        self.assertTrue(record["missing"]["is_missing"])

    def test_verified_source_upgrade_preserves_display_and_enables_replacement(
        self,
    ) -> None:
        record = build_asset_record(
            sample_id="DQ-T08",
            node_index=30,
            source_kind="img",
            source="https://cdn.example/photo.png",
            natural_size=(100, 50),
            display_box=(5, 6, 100, 50),
            display_payload_sha256="9" * 64,
            screenshot_sha256="8" * 64,
        )

        upgraded = attach_verified_source_identity(
            record,
            payload_sha256="a" * 64,
            mime="image/png",
            natural_size=(100, 50),
            provenance="network-response",
        )

        self.assertEqual(
            upgraded["source_identity"]["status"],
            "verified-original",
        )
        self.assertEqual(upgraded["asset_id"], "asset:sha256:" + "a" * 64)
        self.assertTrue(upgraded["replacement"]["allowed"])
        self.assertEqual(
            upgraded["display_payload"]["payload_sha256"],
            "9" * 64,
        )
        self.assertFalse(upgraded["display_payload"]["original"])
        self.assertEqual(upgraded["use"], record["use"])

    def test_direct_design_hashes_the_actual_screenshot_crop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screenshot = root / "page.png"
            Image.new("RGB", (100, 80), (250, 250, 250)).save(screenshot)
            record = build_asset_record(
                sample_id="DQ-T09",
                node_index=32,
                source_kind="img",
                source="https://cdn.example/photo.png",
                natural_size=(100, 80),
                display_box=(0, 0, 100, 80),
            )
            som = {
                "size": [100, 80],
                "image": str(screenshot),
                "containers": [],
                "elements": [
                    {
                        "id": "photo",
                        "type": "image",
                        "bbox": [0, 0, 100, 80],
                        "assetIdentity": {"asset_record": record},
                        "sourceCrop": {
                            "source_rect": [0, 0, 100, 80],
                            "object_fit": "fill",
                        },
                    }
                ],
                "provenance": {
                    "route": "dom",
                    "capture": {
                        "device_scale_factor": 1,
                        "viewport": {"width": 100, "height": 80},
                    },
                },
            }

            design = build_direct_design(som)
            expected_screenshot_sha = hashlib.sha256(
                screenshot.read_bytes()
            ).hexdigest()

        element = design["elements"][0]
        payload = base64.b64decode(element["imageBase64"])
        self.assertEqual(
            element["displayPayload"]["payload_sha256"],
            hashlib.sha256(payload).hexdigest(),
        )
        self.assertEqual(
            element["displayPayload"]["screenshot_sha256"],
            expected_screenshot_sha,
        )
        self.assertFalse(element["displayPayload"]["original"])
        self.assertFalse(element["replacement"]["allowed"])
        self.assertEqual(
            element["sourceResolution"]["display"]["selected"],
            "screenshot-crop",
        )
        self.assertEqual(
            element["sourceResolution"]["status"],
            "partial-unresolved-identity",
        )

    def test_direct_design_records_missing_display_without_screenshot(self) -> None:
        record = build_asset_record(
            sample_id="DQ-T10",
            node_index=33,
            source_kind="img",
            source="https://cdn.example/unavailable.png",
            natural_size=(100, 80),
            display_box=(0, 0, 100, 80),
        )
        som = {
            "size": [100, 80],
            "image": None,
            "containers": [],
            "elements": [
                {
                    "id": "missing-photo",
                    "type": "image",
                    "bbox": [0, 0, 100, 80],
                    "assetIdentity": {"asset_record": record},
                }
            ],
            "provenance": {
                "route": "dom",
                "capture": {
                    "device_scale_factor": 1,
                    "viewport": {"width": 100, "height": 80},
                },
            },
        }

        design = build_direct_design(som)

        element = design["elements"][0]
        self.assertNotIn("imageBase64", element)
        self.assertEqual(
            element["sourceResolution"]["display"]["selected"],
            "missing",
        )
        self.assertEqual(
            element["sourceResolution"]["status"],
            "partial-missing-display",
        )

    def test_direct_design_records_missing_display_without_asset_identity(self) -> None:
        som = {
            "size": [100, 80],
            "image": None,
            "containers": [],
            "elements": [
                {
                    "id": "icon-placeholder",
                    "type": "image",
                    "bbox": [0, 0, 14, 14],
                }
            ],
            "provenance": {
                "route": "dom",
                "capture": {
                    "device_scale_factor": 1,
                    "viewport": {"width": 100, "height": 80},
                },
            },
        }

        design = build_direct_design(som)

        element = design["elements"][0]
        self.assertEqual(
            element["sourceResolution"]["identity"]["selected"],
            "unavailable",
        )
        self.assertEqual(
            element["sourceResolution"]["display"]["selected"],
            "missing",
        )
        self.assertEqual(
            element["sourceResolution"]["status"],
            "partial-missing-display",
        )


if __name__ == "__main__":
    unittest.main()
