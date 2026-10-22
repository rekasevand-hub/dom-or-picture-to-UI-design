from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.rotate_figma_bridge_config import rotate_bridge_config
from src.app.services.bridge_config import (
    BridgeConfigError,
    load_bridge_config,
)
from tests.v2.test_bridge_config import _config_payload


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class SecretLifecycleTests(unittest.TestCase):
    def test_env_and_file_secret_references_are_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payload = copy.deepcopy(_config_payload())
            plugin_secret = root / "plugin.secret"
            plugin_secret.write_text("file-plugin-token\n", encoding="utf-8")
            payload["server"]["auth_token"] = "env:SHARED_TOKEN"
            payload["server"]["plugin_token"] = "file:plugin.secret"
            payload["server"]["client_tokens"] = {
                "client-a": "env:CLIENT_TOKEN",
            }
            payload["client"]["auth_token"] = "env:SHARED_TOKEN"
            payload["client"]["client_token"] = "env:CLIENT_TOKEN"
            path = root / "figma_bridge.config.json"
            _write_config(path, payload)

            config = load_bridge_config(
                path,
                environ={
                    "SHARED_TOKEN": "shared-secret",
                    "CLIENT_TOKEN": "client-secret",
                },
            )

            self.assertEqual(config.server.auth_token, "shared-secret")
            self.assertEqual(config.server.plugin_token, "file-plugin-token")
            self.assertEqual(
                config.server.client_tokens["client-a"],
                "client-secret",
            )
            self.assertEqual(config.client.client_token, "client-secret")

    def test_missing_secret_reference_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "figma_bridge.config.json"
            payload = copy.deepcopy(_config_payload())
            payload["server"]["plugin_token"] = "env:MISSING_PLUGIN_TOKEN"
            _write_config(path, payload)

            with self.assertRaises(BridgeConfigError):
                load_bridge_config(path, environ={})

    def test_direct_secret_can_be_forbidden_or_require_private_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "figma_bridge.config.json"
            payload = copy.deepcopy(_config_payload())
            payload["security"]["require_secret_references"] = True
            _write_config(path, payload)
            with self.assertRaises(BridgeConfigError):
                load_bridge_config(path, environ={})

            payload["security"]["require_secret_references"] = False
            payload["security"]["require_secure_file_permissions"] = True
            _write_config(path, payload)
            with patch(
                "src.app.services.bridge_config._secret_file_is_private",
                return_value=False,
            ):
                with self.assertRaises(BridgeConfigError):
                    load_bridge_config(path, environ={})

    def test_file_secret_requires_private_permissions_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            secret_path = root / "plugin.secret"
            secret_path.write_text("file-secret\n", encoding="utf-8")
            payload = copy.deepcopy(_config_payload())
            payload["server"]["plugin_token"] = "file:plugin.secret"
            payload["security"]["require_secure_file_permissions"] = True
            path = root / "figma_bridge.config.json"
            _write_config(path, payload)

            with patch(
                "src.app.services.bridge_config._secret_file_is_private",
                return_value=False,
            ):
                with self.assertRaises(BridgeConfigError):
                    load_bridge_config(path, environ={})

    def test_atomic_rotation_preserves_file_on_validation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "figma_bridge.config.json"
            payload = copy.deepcopy(_config_payload())
            _write_config(path, payload)
            original = path.read_bytes()

            with self.assertRaises(BridgeConfigError):
                rotate_bridge_config(
                    path,
                    {"server.tls.certfile": "missing.crt"},
                    environ={},
                )

            self.assertEqual(path.read_bytes(), original)

    def test_rotation_updates_plugin_token_without_echoing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "figma_bridge.config.json"
            payload = copy.deepcopy(_config_payload())
            payload["server"]["plugin_token"] = ""
            _write_config(path, payload)

            report = rotate_bridge_config(
                path,
                {"server.plugin_token": "rotated-secret"},
                environ={},
            )

            self.assertEqual(
                load_bridge_config(path, environ={}).server.plugin_token,
                "rotated-secret",
            )
            self.assertIn("server.plugin_token", report["updated_fields"])
            self.assertNotIn("rotated-secret", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
