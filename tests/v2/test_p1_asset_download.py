from __future__ import annotations

import base64
import unittest

from src.app.services.evidence import (
    AssetDownloadError,
    AssetDownloadPolicy,
    inspect_asset_payload,
    validate_remote_asset_url,
)


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class AssetDownloadTests(unittest.TestCase):
    def test_private_and_non_http_urls_fail_closed(self) -> None:
        policy = AssetDownloadPolicy()
        with self.assertRaises(AssetDownloadError):
            validate_remote_asset_url("http://127.0.0.1/asset.png", policy)
        with self.assertRaises(AssetDownloadError):
            validate_remote_asset_url("file:///tmp/asset.png", policy)

    def test_png_signature_is_hashed_and_extended(self) -> None:
        result = inspect_asset_payload(
            _PNG_1X1,
            content_type="image/png",
            policy=AssetDownloadPolicy(),
        )
        self.assertEqual(result["mime"], "image/png")
        self.assertEqual(result["extension"], ".png")
        self.assertEqual(result["size_bytes"], len(_PNG_1X1))
        self.assertEqual(len(result["sha256"]), 64)

    def test_mime_signature_mismatch_fails_closed(self) -> None:
        with self.assertRaises(AssetDownloadError):
            inspect_asset_payload(
                _PNG_1X1,
                content_type="text/html",
                policy=AssetDownloadPolicy(),
            )

    def test_size_limit_fails_closed(self) -> None:
        with self.assertRaises(AssetDownloadError):
            inspect_asset_payload(
                _PNG_1X1,
                content_type="image/png",
                policy=AssetDownloadPolicy(max_bytes_per_asset=8),
            )


if __name__ == "__main__":
    unittest.main()
