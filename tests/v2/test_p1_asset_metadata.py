from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.app.services.structure.capture import DOM_JS
from src.app.services.structure.asset_metadata import (
    AssetIdentity,
    object_fit_source_rect,
    parse_data_uri_asset,
    resolve_asset_identity,
)
from src.app.services.structure.providers.dom import _asset_metadata_for_node
from src.app.services.som.direct_design import _carry_asset_metadata


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
        }

        _carry_asset_metadata(element, item)

        self.assertEqual(element["assetIdentity"], item["assetIdentity"])
        self.assertEqual(element["sourceCrop"], item["sourceCrop"])

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


if __name__ == "__main__":
    unittest.main()
