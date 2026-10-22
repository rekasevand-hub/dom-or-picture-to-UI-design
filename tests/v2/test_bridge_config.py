from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.app.services.bridge_config import (
    BridgeConfigError,
    DEFAULT_BRIDGE_CONFIG_PATH,
    load_bridge_config,
)
from src.app.services.bridge_server import _hub_from_server_config
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter
from src.config.settings import Config


def _config_payload() -> dict:
    return {
        "schema_version": "figma-bridge-config/1.0",
        "allow_env_overrides": False,
        "ledger": {
            "path": "state/write-jobs.jsonl",
            "max_events": 128,
            "terminal_retention_days": 14,
            "compact_min_events": 16,
            "allow_legacy_read": False,
        },
        "security": {
            "require_secret_references": False,
            "require_secure_file_permissions": False,
        },
        "server": {
            "host": "127.0.0.1",
            "port": 9876,
            "timeout": 12.5,
            "idempotency_ttl": 30,
            "journal_path": "state/bridge.jsonl",
            "max_inflight": 8,
            "max_message_bytes": 4096,
            "max_params_depth": 6,
            "max_cache_entries": 32,
            "max_journal_events": 64,
            "exclusive_journal_lock": True,
            "auth_token": "shared-secret",
            "plugin_token": "plugin-secret",
            "plugin_token_recheck_seconds": 0.5,
            "client_tokens": {"client-a": "client-secret-a"},
            "allow_legacy_job_ids": False,
            "client_write_defaults": {
                "max_inflight": 3,
                "burst": 2,
                "min_interval_ms": 10,
            },
            "client_write_limits": {
                "client-a": {
                    "max_inflight": 1,
                    "burst": 1,
                    "min_interval_ms": 25,
                }
            },
            "tls": {
                "enabled": False,
                "certfile": "",
                "keyfile": "",
                "ca_file": "",
                "require_client_cert": False,
            },
            "write_pacing": {
                "min_interval_ms": 25,
                "queue_timeout_seconds": 2.5,
                "max_queue": 4,
            },
        },
        "client": {
            "url": "ws://127.0.0.1:9876",
            "timeout": 5,
            "client_id": "client-a",
            "client_token": "client-secret-a",
            "auth_token": "shared-secret",
            "allow_legacy_job_ids": False,
            "tls": {
                "enabled": False,
                "verify": True,
                "ca_file": "",
                "certfile": "",
                "keyfile": "",
            },
        },
    }


class BridgeConfigTests(unittest.TestCase):
    def test_default_config_file_is_available(self) -> None:
        config = load_bridge_config()

        self.assertTrue(DEFAULT_BRIDGE_CONFIG_PATH.exists())
        self.assertEqual(config.schema_version, "figma-bridge-config/1.0")
        self.assertFalse(config.allow_env_overrides)
        self.assertEqual(config.server.port, 8765)
        self.assertEqual(Config().figma_bridge_url, config.client.url)
        self.assertEqual(config.ledger.max_events, 4096)
        self.assertEqual(config.ledger.terminal_retention_days, 30)
        self.assertEqual(config.ledger.compact_min_events, 256)
        self.assertFalse(config.ledger.allow_legacy_read)
        self.assertFalse(config.server.writer_lease.enabled)
        self.assertEqual(
            config.server.writer_lease.path,
            (
                DEFAULT_BRIDGE_CONFIG_PATH.parent
                / "output/_bridge_state/writer-lease.json"
            ).resolve(),
        )
        self.assertEqual(config.server.writer_lease.ttl_seconds, 300)

    def test_loads_all_server_and_client_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "figma_bridge.config.json"
            path.write_text(json.dumps(_config_payload()), encoding="utf-8")

            config = load_bridge_config(path, environ={})

            self.assertEqual(config.server.host, "127.0.0.1")
            self.assertEqual(config.server.port, 9876)
            self.assertEqual(config.server.timeout, 12.5)
            self.assertEqual(config.server.client_tokens["client-a"], "client-secret-a")
            self.assertEqual(config.server.plugin_token, "plugin-secret")
            self.assertEqual(config.server.plugin_token_recheck_seconds, 0.5)
            self.assertEqual(config.ledger.max_events, 128)
            self.assertEqual(config.ledger.terminal_retention_days, 14)
            self.assertEqual(config.ledger.compact_min_events, 16)
            self.assertFalse(config.ledger.allow_legacy_read)
            self.assertEqual(
                config.ledger.path,
                (path.parent / "state/write-jobs.jsonl").resolve(),
            )
            self.assertEqual(config.server.write_pacing.min_interval_ms, 25)
            self.assertEqual(
                config.server.client_write_defaults.max_inflight,
                3,
            )
            self.assertEqual(
                config.server.client_write_limits["client-a"].burst,
                1,
            )
            self.assertFalse(config.server.tls.enabled)
            self.assertTrue(config.client.tls.verify)
            self.assertEqual(
                config.server.journal_path,
                (path.parent / "state/bridge.jsonl").resolve(),
            )
            self.assertEqual(config.client.url, "ws://127.0.0.1:9876")
            self.assertEqual(config.client.client_id, "client-a")
            self.assertEqual(config.client.client_token, "client-secret-a")

    def test_config_path_can_be_selected_by_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "custom.json"
            path.write_text(json.dumps(_config_payload()), encoding="utf-8")

            config = load_bridge_config(
                environ={"FIGMA_BRIDGE_CONFIG": str(path)}
            )

            self.assertEqual(config.server.port, 9876)

    def test_adapter_uses_client_section_from_config_file(self) -> None:
        calls = []

        class FakeWebSocketModule:
            @staticmethod
            def create_connection(url, **options):
                calls.append((url, options))
                return object()

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "figma_bridge.config.json"
            path.write_text(json.dumps(_config_payload()), encoding="utf-8")
            adapter = FigmaBridgeAdapter(config_path=path)
            adapter._websocket = FakeWebSocketModule

            adapter.connect()

            self.assertEqual(calls[0][0], "ws://127.0.0.1:9876/command")
            headers = calls[0][1]["header"]
            self.assertEqual(headers["Authorization"], "Bearer shared-secret")
            self.assertEqual(headers["X-Figma-Client-Id"], "client-a")
            self.assertEqual(headers["X-Figma-Client-Token"], "client-secret-a")

    def test_config_file_ignores_environment_unless_explicitly_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "figma_bridge.config.json"
            path.write_text(json.dumps(_config_payload()), encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "FIGMA_BRIDGE_URL": "ws://env-host:9999",
                    "FIGMA_BRIDGE_CLIENT_TOKEN": "env-token",
                },
            ):
                adapter = FigmaBridgeAdapter(config_path=path)

            self.assertEqual(adapter.bridge_url, "ws://127.0.0.1:9876")
            self.assertEqual(adapter.client_token, "client-secret-a")

    def test_server_section_builds_hub_with_file_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "figma_bridge.config.json"
            path.write_text(json.dumps(_config_payload()), encoding="utf-8")
            config = load_bridge_config(path, environ={})

            hub = _hub_from_server_config(
                config.server,
                environ={"FIGMA_BRIDGE_TIMEOUT": "99"},
                allow_env_overrides=config.allow_env_overrides,
            )
            try:
                self.assertEqual(hub.timeout, 12.5)
                self.assertEqual(hub.idempotency_ttl, 30)
                self.assertEqual(hub.max_inflight, 8)
                self.assertEqual(
                    hub.journal_path,
                    (path.parent / "state/bridge.jsonl").resolve(),
                )
                self.assertEqual(hub.auth_token, "shared-secret")
                self.assertEqual(hub.plugin_token, "plugin-secret")
                self.assertEqual(
                    hub.client_tokens,
                    {"client-a": "client-secret-a"},
                )
                self.assertEqual(hub.write_min_interval, 0.025)
                self.assertEqual(hub.write_queue_timeout, 2.5)
                self.assertEqual(hub.max_write_queue, 4)
                self.assertEqual(
                    hub.client_write_limits["client-a"].max_inflight,
                    1,
                )
            finally:
                hub.close()

    def test_environment_overrides_require_explicit_config_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "figma_bridge.config.json"
            path.write_text(json.dumps(_config_payload()), encoding="utf-8")
            config = load_bridge_config(path, environ={})

            file_hub = _hub_from_server_config(
                config.server,
                environ={"FIGMA_BRIDGE_TIMEOUT": "99"},
                allow_env_overrides=False,
            )
            file_timeout = file_hub.timeout
            file_hub.close()
            override_hub = _hub_from_server_config(
                config.server,
                environ={"FIGMA_BRIDGE_TIMEOUT": "99"},
                allow_env_overrides=True,
            )
            try:
                self.assertEqual(file_timeout, 12.5)
                self.assertEqual(override_hub.timeout, 99)
            finally:
                override_hub.close()

    def test_server_plugin_token_provider_reads_rotated_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "figma_bridge.config.json"
            payload = _config_payload()
            path.write_text(json.dumps(payload), encoding="utf-8")
            config = load_bridge_config(path, environ={})
            hub = _hub_from_server_config(
                config.server,
                environ={},
                allow_env_overrides=False,
                config_path=path,
            )
            try:
                self.assertEqual(
                    hub.plugin_token_provider(),
                    "plugin-secret",
                )
                payload["server"]["plugin_token"] = "rotated-secret"
                path.write_text(json.dumps(payload), encoding="utf-8")
                self.assertEqual(
                    hub.plugin_token_provider(),
                    "rotated-secret",
                )
            finally:
                hub.close()

    def test_unknown_or_invalid_values_fail_closed(self) -> None:
        invalid_values = (
            ("server", "unknown", True),
            ("server", "port", 0),
            ("server", "client_tokens", {"client-a": ""}),
            ("client", "url", ""),
            ("ledger", "path", ""),
            ("ledger", "max_events", 0),
            ("ledger", "terminal_retention_days", -1),
            ("ledger", "compact_min_events", 0),
            ("ledger", "allow_legacy_read", "false"),
            ("ledger", "unknown", True),
        )
        for section, key, value in invalid_values:
            with self.subTest(section=section, key=key):
                payload = _config_payload()
                payload[section][key] = value
                with tempfile.TemporaryDirectory() as temp_dir:
                    path = Path(temp_dir) / "invalid.json"
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(BridgeConfigError):
                        load_bridge_config(path, environ={})

    def test_tls_requires_matching_server_and_client_settings(self) -> None:
        invalid_values = (
            ("server.tls", {"enabled": True}),
            ("client.tls", {"enabled": True}),
        )
        for key, override in invalid_values:
            payload = _config_payload()
            section, nested = key.split(".")
            payload[section][nested].update(override)
            with tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "invalid.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(BridgeConfigError):
                    load_bridge_config(path, environ={})


if __name__ == "__main__":
    unittest.main()
