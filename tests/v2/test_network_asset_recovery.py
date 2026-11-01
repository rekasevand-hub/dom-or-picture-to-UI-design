from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.app.services.structure.asset_metadata import build_asset_record
from src.app.services.structure.network_asset_recovery import (
    recover_network_assets,
)


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (4, 3), (30, 80, 160)).save(output, format="PNG")
    return output.getvalue()


def _design_with_urls(*urls: str) -> dict:
    elements = []
    for index, url in enumerate(urls):
        record = build_asset_record(
            sample_id="dom",
            node_index=index,
            source_kind="img",
            source=url,
            natural_size=(4, 3),
            display_box=(index, 0, 4, 3),
            display_payload_sha256=str(index + 1) * 64,
            screenshot_sha256="f" * 64,
        )
        elements.append(
            {
                "id": str(index + 1),
                "type": "image",
                "x": index,
                "y": 0,
                "width": 4,
                "height": 3,
                "assetIdentity": {
                    "source": url,
                    "asset_record": record,
                },
                "displayPayload": record["display_payload"],
                "replacement": record["replacement"],
            }
        )
    return {"canvas": {"width": 100, "height": 100}, "elements": elements}


class NetworkAssetRecoveryTests(unittest.TestCase):
    def test_recovers_responsive_variant_with_same_aspect_ratio(self) -> None:
        url = "https://img.example/photo.png"
        output = io.BytesIO()
        Image.new("RGB", (8, 6), (30, 80, 160)).save(output, format="WEBP")
        payload = output.getvalue()

        def request_get(source_url, *, referer, timeout_ms):
            return {
                "status": 200,
                "headers": {"content-type": "image/webp"},
                "body": payload,
            }

        with tempfile.TemporaryDirectory() as tmp:
            result = recover_network_assets(
                _design_with_urls(url),
                page_url="https://www.example/",
                output_dir=tmp,
                request_get=request_get,
            )

        self.assertEqual(result["status_counts"]["verified-original"], 1)
        self.assertEqual(result["rows"][0]["natural_size"], [8.0, 6.0])
        self.assertEqual(
            result["design"]["elements"][0]["assetIdentity"]["asset_record"][
                "source_identity"
            ]["status"],
            "verified-original",
        )
        self.assertTrue(
            result["design"]["elements"][0]["imageBase64"].startswith("iVBOR")
        )

    def test_recovers_and_deduplicates_browser_response_bytes(self) -> None:
        url = "https://img.example/photo.png"
        payload = _png_bytes()
        calls = []

        def request_get(source_url, *, referer, timeout_ms):
            calls.append((source_url, referer, timeout_ms))
            return {
                "status": 200,
                "headers": {"content-type": "image/png"},
                "body": payload,
            }

        with tempfile.TemporaryDirectory() as tmp:
            result = recover_network_assets(
                _design_with_urls(url, url),
                page_url="https://www.example/",
                output_dir=tmp,
                request_get=request_get,
            )
            retained = list((Path(tmp) / "assets").iterdir())

        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status_counts"]["verified-original"], 1)
        self.assertEqual(len(retained), 1)
        digest = hashlib.sha256(payload).hexdigest()
        self.assertEqual(retained[0].name, digest + ".png")
        upgraded = result["design"]["elements"]
        self.assertTrue(
            all(
                item["assetIdentity"]["asset_record"]["source_identity"]["status"]
                == "verified-original"
                for item in upgraded
            )
        )
        self.assertTrue(
            all(
                item["assetIdentity"]["asset_record"]["display_payload"]["kind"]
                == "screenshot-crop"
                for item in upgraded
            )
        )

    def test_size_limit_keeps_reference_only_and_retains_no_bytes(self) -> None:
        url = "https://img.example/photo.png"

        def request_get(source_url, *, referer, timeout_ms):
            return {
                "status": 200,
                "headers": {"content-type": "image/png"},
                "body": _png_bytes(),
            }

        with tempfile.TemporaryDirectory() as tmp:
            result = recover_network_assets(
                _design_with_urls(url),
                page_url="https://www.example/",
                output_dir=tmp,
                request_get=request_get,
                max_bytes_per_asset=10,
            )
            retained = list((Path(tmp) / "assets").iterdir())

        self.assertEqual(result["status_counts"]["verified-original"], 0)
        self.assertEqual(result["status_counts"]["reference-only"], 1)
        self.assertEqual(retained, [])
        self.assertEqual(
            result["design"]["elements"][0]["assetIdentity"]["asset_record"][
                "source_identity"
            ]["status"],
            "reference-only",
        )

    def test_non_image_response_is_not_upgraded(self) -> None:
        url = "https://img.example/photo.png"

        def request_get(source_url, *, referer, timeout_ms):
            return {
                "status": 200,
                "headers": {"content-type": "text/html"},
                "body": b"<html>blocked</html>",
            }

        with tempfile.TemporaryDirectory() as tmp:
            result = recover_network_assets(
                _design_with_urls(url),
                page_url="https://www.example/",
                output_dir=tmp,
                request_get=request_get,
            )

        self.assertEqual(result["status_counts"]["reference-only"], 1)
        self.assertEqual(
            result["rows"][0]["error_code"],
            "non-image-content-type",
        )


if __name__ == "__main__":
    unittest.main()
