"""File-backed configuration for the Figma bridge and its Python client."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

BRIDGE_CONFIG_SCHEMA_VERSION = "figma-bridge-config/1.0"
DEFAULT_BRIDGE_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "figma_bridge.config.json"
)


class BridgeConfigError(ValueError):
    """The bridge configuration file is missing or invalid."""


@dataclass(frozen=True, slots=True)
class BridgeWritePacingConfig:
    min_interval_ms: float
    queue_timeout_seconds: float
    max_queue: int


@dataclass(frozen=True, slots=True)
class BridgeWriterLeaseConfig:
    enabled: bool
    path: Path | None
    ttl_seconds: float
    owner_id: str


@dataclass(frozen=True, slots=True)
class BridgeSecurityConfig:
    require_secret_references: bool
    require_secure_file_permissions: bool


@dataclass(frozen=True, slots=True)
class ClientWriteLimitConfig:
    max_inflight: int
    burst: int
    min_interval_ms: float


@dataclass(frozen=True, slots=True)
class BridgeLedgerConfig:
    path: Path
    max_events: int
    terminal_retention_days: float
    compact_min_events: int
    allow_legacy_read: bool


@dataclass(frozen=True, slots=True)
class BridgeTlsServerConfig:
    enabled: bool
    certfile: Path | None
    keyfile: Path | None
    ca_file: Path | None
    require_client_cert: bool


@dataclass(frozen=True, slots=True)
class BridgeTlsClientConfig:
    enabled: bool
    verify: bool
    ca_file: Path | None
    certfile: Path | None
    keyfile: Path | None


@dataclass(frozen=True, slots=True)
class BridgeServerConfig:
    host: str
    port: int
    timeout: float
    idempotency_ttl: float
    journal_path: Path | None
    max_inflight: int
    max_message_bytes: int
    max_params_depth: int
    max_cache_entries: int
    max_journal_events: int
    exclusive_journal_lock: bool
    auth_token: str | None
    plugin_token: str | None
    plugin_token_recheck_seconds: float
    client_tokens: Mapping[str, str]
    allow_legacy_job_ids: bool
    client_write_defaults: ClientWriteLimitConfig
    client_write_limits: Mapping[str, ClientWriteLimitConfig]
    write_pacing: BridgeWritePacingConfig
    writer_lease: BridgeWriterLeaseConfig
    tls: BridgeTlsServerConfig


@dataclass(frozen=True, slots=True)
class BridgeClientConfig:
    url: str
    timeout: float
    client_id: str | None
    client_token: str | None
    auth_token: str | None
    allow_legacy_job_ids: bool
    tls: BridgeTlsClientConfig


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    schema_version: str
    allow_env_overrides: bool
    security: BridgeSecurityConfig
    ledger: BridgeLedgerConfig
    config_path: Path
    server: BridgeServerConfig
    client: BridgeClientConfig


def load_bridge_config(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> BridgeConfig:
    values = os.environ if environ is None else environ
    configured_path = str(values.get("FIGMA_BRIDGE_CONFIG", "")).strip()
    resolved_path = Path(
        path or configured_path or DEFAULT_BRIDGE_CONFIG_PATH
    ).expanduser().resolve()
    if not resolved_path.exists():
        raise BridgeConfigError(
            f"bridge config file does not exist: {resolved_path}"
        )
    try:
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise BridgeConfigError(
            f"cannot read bridge config file {resolved_path}: {exc}"
        ) from exc
    root = _object(payload, "config")
    _keys(
        root,
        "config",
        required={
            "schema_version",
            "allow_env_overrides",
            "security",
            "ledger",
            "server",
            "client",
        },
        allowed={
            "schema_version",
            "allow_env_overrides",
            "security",
            "ledger",
            "server",
            "client",
        },
    )
    schema_version = _string(root["schema_version"], "schema_version")
    if schema_version != BRIDGE_CONFIG_SCHEMA_VERSION:
        raise BridgeConfigError(
            f"unsupported bridge config schema: {schema_version!r}"
        )
    security_payload = _object(root["security"], "security")
    security_keys = {
        "require_secret_references",
        "require_secure_file_permissions",
    }
    _keys(
        security_payload,
        "security",
        required=security_keys,
        allowed=security_keys,
    )
    security = BridgeSecurityConfig(
        require_secret_references=_boolean(
            security_payload["require_secret_references"],
            "security.require_secret_references",
        ),
        require_secure_file_permissions=_boolean(
            security_payload["require_secure_file_permissions"],
            "security.require_secure_file_permissions",
        ),
    )
    ledger = _ledger_config(
        root["ledger"],
        base_dir=resolved_path.parent,
    )
    direct_secret_used = [False]
    server = _server_config(
        root["server"],
        base_dir=resolved_path.parent,
        environ=values,
        security=security,
        direct_secret_used=direct_secret_used,
    )
    client = _client_config(
        root["client"],
        base_dir=resolved_path.parent,
        environ=values,
        security=security,
        direct_secret_used=direct_secret_used,
    )
    if (
        direct_secret_used[0]
        and security.require_secure_file_permissions
        and not _secret_file_is_private(resolved_path)
    ):
        raise BridgeConfigError(
            "config file containing direct secrets must have private permissions"
        )
    return BridgeConfig(
        schema_version=schema_version,
        allow_env_overrides=_boolean(
            root["allow_env_overrides"],
            "allow_env_overrides",
        ),
        security=security,
        ledger=ledger,
        config_path=resolved_path,
        server=server,
        client=client,
    )


def _ledger_config(value: Any, *, base_dir: Path) -> BridgeLedgerConfig:
    payload = _object(value, "ledger")
    required = {
        "path",
        "max_events",
        "terminal_retention_days",
        "compact_min_events",
        "allow_legacy_read",
    }
    _keys(payload, "ledger", required=required, allowed=required)
    raw_path = Path(_string(payload["path"], "ledger.path")).expanduser()
    if not raw_path.is_absolute():
        raw_path = base_dir / raw_path
    path = raw_path.resolve()
    max_events = _integer(
        payload["max_events"],
        "ledger.max_events",
        minimum=1,
    )
    compact_min_events = _integer(
        payload["compact_min_events"],
        "ledger.compact_min_events",
        minimum=1,
    )
    if compact_min_events > max_events:
        raise BridgeConfigError(
            "ledger.compact_min_events must be <= ledger.max_events"
        )
    return BridgeLedgerConfig(
        path=path,
        max_events=max_events,
        terminal_retention_days=_number(
            payload["terminal_retention_days"],
            "ledger.terminal_retention_days",
            minimum=0,
        ),
        compact_min_events=compact_min_events,
        allow_legacy_read=_boolean(
            payload["allow_legacy_read"],
            "ledger.allow_legacy_read",
        ),
    )


def _server_config(
    value: Any,
    *,
    base_dir: Path,
    environ: Mapping[str, str],
    security: BridgeSecurityConfig,
    direct_secret_used: list[bool],
) -> BridgeServerConfig:
    payload = _object(value, "server")
    required = {
        "host",
        "port",
        "timeout",
        "idempotency_ttl",
        "journal_path",
        "max_inflight",
        "max_message_bytes",
        "max_params_depth",
        "max_cache_entries",
        "max_journal_events",
        "exclusive_journal_lock",
        "auth_token",
        "plugin_token",
        "plugin_token_recheck_seconds",
        "client_tokens",
        "allow_legacy_job_ids",
        "client_write_defaults",
        "client_write_limits",
        "write_pacing",
        "tls",
    }
    _keys(
        payload,
        "server",
        required=required,
        allowed=required | {"writer_lease"},
    )
    port = _integer(payload["port"], "server.port", minimum=1, maximum=65535)
    journal_value = payload["journal_path"]
    journal_path: Path | None
    if journal_value is None or str(journal_value).strip() == "":
        journal_path = None
    else:
        journal_path = Path(_string(journal_value, "server.journal_path"))
        if not journal_path.is_absolute():
            journal_path = base_dir / journal_path
        journal_path = journal_path.resolve()
    pacing = _object(payload["write_pacing"], "server.write_pacing")
    pacing_keys = {
        "min_interval_ms",
        "queue_timeout_seconds",
        "max_queue",
    }
    _keys(
        pacing,
        "server.write_pacing",
        required=pacing_keys,
        allowed=pacing_keys,
    )
    return BridgeServerConfig(
        host=_string(payload["host"], "server.host"),
        port=port,
        timeout=_number(payload["timeout"], "server.timeout", positive=True),
        idempotency_ttl=_number(
            payload["idempotency_ttl"],
            "server.idempotency_ttl",
            positive=True,
        ),
        journal_path=journal_path,
        max_inflight=_integer(
            payload["max_inflight"],
            "server.max_inflight",
            minimum=1,
        ),
        max_message_bytes=_integer(
            payload["max_message_bytes"],
            "server.max_message_bytes",
            minimum=1,
        ),
        max_params_depth=_integer(
            payload["max_params_depth"],
            "server.max_params_depth",
            minimum=1,
        ),
        max_cache_entries=_integer(
            payload["max_cache_entries"],
            "server.max_cache_entries",
            minimum=1,
        ),
        max_journal_events=_integer(
            payload["max_journal_events"],
            "server.max_journal_events",
            minimum=1,
        ),
        exclusive_journal_lock=_boolean(
            payload["exclusive_journal_lock"],
            "server.exclusive_journal_lock",
        ),
        auth_token=_optional_secret(
            payload["auth_token"],
            "server.auth_token",
            environ=environ,
            base_dir=base_dir,
            security=security,
            direct_secret_used=direct_secret_used,
        ),
        plugin_token=_optional_secret(
            payload["plugin_token"],
            "server.plugin_token",
            environ=environ,
            base_dir=base_dir,
            security=security,
            direct_secret_used=direct_secret_used,
        ),
        plugin_token_recheck_seconds=_number(
            payload["plugin_token_recheck_seconds"],
            "server.plugin_token_recheck_seconds",
            positive=True,
        ),
        client_tokens=MappingProxyType(
            _token_mapping(
                payload["client_tokens"],
                "server.client_tokens",
                environ=environ,
                base_dir=base_dir,
                security=security,
                direct_secret_used=direct_secret_used,
            )
        ),
        allow_legacy_job_ids=_boolean(
            payload["allow_legacy_job_ids"],
            "server.allow_legacy_job_ids",
        ),
        client_write_defaults=_client_write_limit(
            payload["client_write_defaults"],
            "server.client_write_defaults",
        ),
        client_write_limits=MappingProxyType(
            _client_write_limits(payload["client_write_limits"])
        ),
        write_pacing=BridgeWritePacingConfig(
            min_interval_ms=_number(
                pacing["min_interval_ms"],
                "server.write_pacing.min_interval_ms",
                minimum=0,
            ),
            queue_timeout_seconds=_number(
                pacing["queue_timeout_seconds"],
                "server.write_pacing.queue_timeout_seconds",
                positive=True,
            ),
            max_queue=_integer(
                pacing["max_queue"],
                "server.write_pacing.max_queue",
                minimum=1,
            ),
        ),
        writer_lease=_writer_lease_config(
            payload.get("writer_lease"),
            base_dir=base_dir,
        ),
        tls=_server_tls_config(
            payload["tls"],
            base_dir=base_dir,
        ),
    )


def _writer_lease_config(
    value: Any,
    *,
    base_dir: Path,
) -> BridgeWriterLeaseConfig:
    if value is None:
        return BridgeWriterLeaseConfig(
            enabled=False,
            path=None,
            ttl_seconds=300.0,
            owner_id="bridge-local",
        )
    payload = _object(value, "server.writer_lease")
    required = {"enabled", "path", "ttl_seconds", "owner_id"}
    _keys(payload, "server.writer_lease", required=required, allowed=required)
    enabled = _boolean(payload["enabled"], "server.writer_lease.enabled")
    raw_path = _optional_string(payload["path"], "server.writer_lease.path")
    path = None
    if raw_path is not None:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        path = path.resolve()
    if enabled and path is None:
        raise BridgeConfigError(
            "server.writer_lease.path is required when enabled"
        )
    return BridgeWriterLeaseConfig(
        enabled=enabled,
        path=path,
        ttl_seconds=_number(
            payload["ttl_seconds"],
            "server.writer_lease.ttl_seconds",
            positive=True,
        ),
        owner_id=_string(
            payload["owner_id"],
            "server.writer_lease.owner_id",
        ),
    )


def _client_config(
    value: Any,
    *,
    base_dir: Path,
    environ: Mapping[str, str],
    security: BridgeSecurityConfig,
    direct_secret_used: list[bool],
) -> BridgeClientConfig:
    payload = _object(value, "client")
    required = {
        "url",
        "timeout",
        "client_id",
        "client_token",
        "auth_token",
        "allow_legacy_job_ids",
        "tls",
    }
    _keys(payload, "client", required=required, allowed=required)
    url = _string(payload["url"], "client.url")
    if not url.startswith(("ws://", "wss://")):
        raise BridgeConfigError("client.url must start with ws:// or wss://")
    client_id = _optional_string(payload["client_id"], "client.client_id")
    if client_id is not None and len(client_id) > 128:
        raise BridgeConfigError("client.client_id exceeds 128 characters")
    client_token = _optional_secret(
        payload["client_token"],
        "client.client_token",
        environ=environ,
        base_dir=base_dir,
        security=security,
        direct_secret_used=direct_secret_used,
    )
    if client_token and client_id is None:
        raise BridgeConfigError(
            "client.client_id is required when client.client_token is set"
        )
    tls = _client_tls_config(payload["tls"], base_dir=base_dir)
    if tls.enabled and not url.startswith("wss://"):
        raise BridgeConfigError("client.url must use wss:// when TLS is enabled")
    return BridgeClientConfig(
        url=url.rstrip("/"),
        timeout=_number(payload["timeout"], "client.timeout", positive=True),
        client_id=client_id,
        client_token=client_token,
        auth_token=_optional_secret(
            payload["auth_token"],
            "client.auth_token",
            environ=environ,
            base_dir=base_dir,
            security=security,
            direct_secret_used=direct_secret_used,
        ),
        allow_legacy_job_ids=_boolean(
            payload["allow_legacy_job_ids"],
            "client.allow_legacy_job_ids",
        ),
        tls=tls,
    )


def _server_tls_config(value: Any, *, base_dir: Path) -> BridgeTlsServerConfig:
    payload = _object(value, "server.tls")
    required = {
        "enabled",
        "certfile",
        "keyfile",
        "ca_file",
        "require_client_cert",
    }
    _keys(payload, "server.tls", required=required, allowed=required)
    enabled = _boolean(payload["enabled"], "server.tls.enabled")
    certfile = _config_path(
        payload["certfile"],
        "server.tls.certfile",
        base_dir,
    )
    keyfile = _config_path(
        payload["keyfile"],
        "server.tls.keyfile",
        base_dir,
    )
    ca_file = _config_path(
        payload["ca_file"],
        "server.tls.ca_file",
        base_dir,
    )
    if enabled and (certfile is None or keyfile is None):
        raise BridgeConfigError(
            "server TLS requires certfile and keyfile"
        )
    require_client_cert = _boolean(
        payload["require_client_cert"],
        "server.tls.require_client_cert",
    )
    if require_client_cert and ca_file is None:
        raise BridgeConfigError(
            "server TLS require_client_cert requires ca_file"
        )
    return BridgeTlsServerConfig(
        enabled=enabled,
        certfile=certfile,
        keyfile=keyfile,
        ca_file=ca_file,
        require_client_cert=require_client_cert,
    )


def _client_tls_config(value: Any, *, base_dir: Path | None) -> BridgeTlsClientConfig:
    payload = _object(value, "client.tls")
    required = {"enabled", "verify", "ca_file", "certfile", "keyfile"}
    _keys(payload, "client.tls", required=required, allowed=required)
    certfile = _config_path(
        payload["certfile"],
        "client.tls.certfile",
        base_dir,
    )
    keyfile = _config_path(
        payload["keyfile"],
        "client.tls.keyfile",
        base_dir,
    )
    if (certfile is None) != (keyfile is None):
        raise BridgeConfigError(
            "client TLS certfile and keyfile must be provided together"
        )
    return BridgeTlsClientConfig(
        enabled=_boolean(payload["enabled"], "client.tls.enabled"),
        verify=_boolean(payload["verify"], "client.tls.verify"),
        ca_file=_config_path(
            payload["ca_file"],
            "client.tls.ca_file",
            base_dir,
        ),
        certfile=certfile,
        keyfile=keyfile,
    )


def _config_path(
    value: Any,
    path: str,
    base_dir: Path | None,
) -> Path | None:
    raw = _optional_string(value, path)
    if raw is None:
        return None
    resolved = Path(raw).expanduser()
    if not resolved.is_absolute():
        if base_dir is None:
            resolved = Path.cwd() / resolved
        else:
            resolved = base_dir / resolved
    resolved = resolved.resolve()
    if not resolved.exists():
        raise BridgeConfigError(f"{path} does not exist: {resolved}")
    return resolved


def _client_write_limits(value: Any) -> dict[str, ClientWriteLimitConfig]:
    payload = _object(value, "server.client_write_limits")
    limits: dict[str, ClientWriteLimitConfig] = {}
    for raw_client_id, raw_limit in payload.items():
        client_id = str(raw_client_id or "").strip()
        if not client_id or len(client_id) > 128:
            raise BridgeConfigError(
                "server.client_write_limits clientId must be 1..128 characters"
            )
        limits[client_id] = _client_write_limit(
            raw_limit,
            f"server.client_write_limits.{client_id}",
        )
    return limits


def _client_write_limit(value: Any, path: str) -> ClientWriteLimitConfig:
    payload = _object(value, path)
    required = {"max_inflight", "burst", "min_interval_ms"}
    _keys(payload, path, required=required, allowed=required)
    return ClientWriteLimitConfig(
        max_inflight=_integer(
            payload["max_inflight"],
            f"{path}.max_inflight",
            minimum=1,
        ),
        burst=_integer(
            payload["burst"],
            f"{path}.burst",
            minimum=1,
        ),
        min_interval_ms=_number(
            payload["min_interval_ms"],
            f"{path}.min_interval_ms",
            minimum=0,
        ),
    )


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BridgeConfigError(f"{path} must be an object")
    return value


def _keys(
    value: Mapping[str, Any],
    path: str,
    *,
    required: set[str],
    allowed: set[str],
) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        raise BridgeConfigError(f"{path} missing keys: {', '.join(missing)}")
    if unknown:
        raise BridgeConfigError(f"{path} unknown keys: {', '.join(unknown)}")


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BridgeConfigError(f"{path} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise BridgeConfigError(f"{path} must be a string or null")
    normalized = value.strip()
    return normalized or None


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise BridgeConfigError(f"{path} must be a boolean")
    return value


def _integer(
    value: Any,
    path: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BridgeConfigError(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise BridgeConfigError(f"{path} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise BridgeConfigError(f"{path} must be <= {maximum}")
    return value


def _number(
    value: Any,
    path: str,
    *,
    minimum: float | None = None,
    positive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeConfigError(f"{path} must be a number")
    number = float(value)
    if positive and number <= 0:
        raise BridgeConfigError(f"{path} must be positive")
    if minimum is not None and number < minimum:
        raise BridgeConfigError(f"{path} must be >= {minimum}")
    return number


def _token_mapping(
    value: Any,
    path: str,
    *,
    environ: Mapping[str, str],
    base_dir: Path,
    security: BridgeSecurityConfig,
    direct_secret_used: list[bool],
) -> dict[str, str]:
    payload = _object(value, path)
    normalized: dict[str, str] = {}
    for raw_client_id, raw_token in payload.items():
        client_id = str(raw_client_id or "").strip()
        token = _optional_secret(
            raw_token,
            f"{path}.{client_id}",
            environ=environ,
            base_dir=base_dir,
            security=security,
            direct_secret_used=direct_secret_used,
        )
        if not client_id or len(client_id) > 128:
            raise BridgeConfigError(
                f"{path} clientId must be 1..128 characters"
            )
        if not token:
            raise BridgeConfigError(f"{path}.{client_id} must not be empty")
        normalized[client_id] = token
    return normalized


def _optional_secret(
    value: Any,
    path: str,
    *,
    environ: Mapping[str, str],
    base_dir: Path,
    security: BridgeSecurityConfig,
    direct_secret_used: list[bool],
) -> str | None:
    raw = _optional_string(value, path)
    if raw is None:
        return None
    if raw.startswith("env:"):
        name = raw[4:].strip()
        resolved = str(environ.get(name, "")).strip()
        if not name or not resolved:
            raise BridgeConfigError(
                f"{path} references missing environment secret {name!r}"
            )
        return resolved
    if raw.startswith("file:"):
        path_value = raw[5:].strip()
        if not path_value:
            raise BridgeConfigError(f"{path} secret file path is empty")
        secret_path = Path(path_value).expanduser()
        if not secret_path.is_absolute():
            secret_path = base_dir / secret_path
        try:
            resolved = secret_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise BridgeConfigError(
                f"{path} cannot read secret file {secret_path}: {exc}"
            ) from exc
        if not resolved:
            raise BridgeConfigError(f"{path} secret file is empty")
        if (
            security.require_secure_file_permissions
            and not _secret_file_is_private(secret_path)
        ):
            raise BridgeConfigError(
                f"{path} secret file must have private permissions: {secret_path}"
            )
        return resolved
    if security.require_secret_references:
        raise BridgeConfigError(
            f"{path} must use env: or file: when secret references are required"
        )
    direct_secret_used[0] = True
    return raw


def _secret_file_is_private(path: Path) -> bool:
    if os.name != "nt":
        mode = stat.S_IMODE(path.stat().st_mode)
        return mode & 0o077 == 0
    try:
        result = subprocess.run(
            ["icacls", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    output = result.stdout + result.stderr
    broad_identities = (
        "Authenticated Users",
        "BUILTIN\\Users",
        "Everyone",
    )
    return not any(identity.lower() in output.lower() for identity in broad_identities)
