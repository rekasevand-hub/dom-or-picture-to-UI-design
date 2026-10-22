from __future__ import annotations

import base64
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.app.services.contracts import validate_audit_bundle, validate_runtime_ir
from src.app.services.evidence import (
    materialize_downloaded_assets,
    write_evidence_sidecar,
)


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_CAPTURED_AT = datetime(2026, 10, 19, tzinfo=timezone.utc)


def _write_remote_asset_capture(root: Path) -> None:
    (root / "00_screenshot.png").write_bytes(_PNG_1X1)
    dom = [
        {
            "tag": "html",
            "x": 0,
            "y": 0,
            "w": 100,
            "h": 100,
            "bg": "rgba(0, 0, 0, 0)",
            "position": "static",
            "zIndex": 0,
        },
        {
            "tag": "img",
            "assetSrc": "https://assets.example/image.png",
            "x": 10,
            "y": 10,
            "w": 32,
            "h": 32,
            "position": "static",
            "zIndex": 0,
        },
    ]
    (root / "00_dom.json").write_text(json.dumps(dom), encoding="utf-8")
    (root / "00_page_state.json").write_text(
        json.dumps(
            {
                "requested_url": "https://example.test/",
                "final_url": "https://example.test/",
                "kind": "content",
                "confidence": 0.99,
                "reason": "fixture",
                "signals": {},
                "attempts": [],
                "fallback_used": False,
                "screenshot_only": False,
                "requested_route": "auto",
            }
        ),
        encoding="utf-8",
    )
    (root / "00_dom_diagnostics.json").write_text(
        json.dumps({"capture_gaps": {"shadow": 0}, "unsupported": {}}),
        encoding="utf-8",
    )


class AssetMaterializeTests(unittest.TestCase):
    def test_materialized_sidecar_updates_assets_and_audit_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_dir = root / "capture"
            sidecar_dir = root / "sidecar"
            downloads_dir = root / "downloads"
            output_dir = root / "materialized"
            capture_dir.mkdir()
            _write_remote_asset_capture(capture_dir)
            sidecar = write_evidence_sidecar(
                capture_dir,
                sidecar_dir,
                captured_at=_CAPTURED_AT,
            )
            asset_id = "asset-0001-img"
            assets_dir = downloads_dir / "evidence" / "assets"
            assets_dir.mkdir(parents=True)
            (assets_dir / f"{asset_id}.png").write_bytes(_PNG_1X1)
            sha = __import__("hashlib").sha256(_PNG_1X1).hexdigest()
            (downloads_dir / "asset_downloads.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "rows": [
                            {
                                "asset_id": asset_id,
                                "status": "downloaded",
                                "source_url": "https://assets.example/image.png",
                                "mime": "image/png",
                                "sha256": sha,
                                "size_bytes": len(_PNG_1X1),
                                "locator": f"evidence/assets/{asset_id}.png",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = materialize_downloaded_assets(
                sidecar_dir,
                downloads_dir,
                output_dir,
            )
            ir = json.loads((output_dir / "runtime_ir.json").read_text(encoding="utf-8"))
            audit = json.loads((output_dir / "audit_bundle.json").read_text(encoding="utf-8"))
            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(validate_runtime_ir(ir), [])
            self.assertEqual(validate_audit_bundle(audit), [])
            asset = next(item for item in ir["assets"] if item["asset_id"] == asset_id)
            self.assertTrue(asset["local_bytes_present"])
            self.assertEqual(asset["local_sha256"], sha)
            self.assertIn("ev-asset-0001-img", audit["ordered_evidence"])
            self.assertIn("ev-asset-download-report", audit["ordered_evidence"])
            self.assertTrue((output_dir / "evidence" / "assets" / f"{asset_id}.png").is_file())
            self.assertEqual(manifest["materialization"]["downloaded_count"], 1)
            self.assertEqual(result.manifest["materialization"]["downloaded_bytes"], len(_PNG_1X1))
            self.assertEqual(
                ir["fields"],
                sidecar.runtime_ir.to_dict()["fields"],
            )


if __name__ == "__main__":
    unittest.main()
