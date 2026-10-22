"""Stable client-scoped namespace for owned Figma write jobs."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

JOB_NAMESPACE_VERSION = "v1"
JOB_NAMESPACE_PREFIX = f"r5job:{JOB_NAMESPACE_VERSION}:"
MAX_CLIENT_ID_LENGTH = 128
MAX_RAW_JOB_ID_LENGTH = 256


class JobNamespaceError(ValueError):
    """The ownership job id is not a valid client-scoped namespace."""


@dataclass(frozen=True, slots=True)
class ParsedJobNamespace:
    client_id: str
    raw_job_id: str
    canonical: str
    version: str = JOB_NAMESPACE_VERSION


def build_job_namespace(client_id: str, raw_job_id: str) -> str:
    client = _normalize_component(
        client_id,
        label="client_id",
        max_length=MAX_CLIENT_ID_LENGTH,
    )
    raw = _normalize_component(
        raw_job_id,
        label="raw_job_id",
        max_length=MAX_RAW_JOB_ID_LENGTH,
    )
    return (
        f"{JOB_NAMESPACE_PREFIX}"
        f"{_encode_component(client)}:"
        f"{_encode_component(raw)}"
    )


def parse_job_namespace(value: str) -> ParsedJobNamespace:
    text = str(value or "")
    if not text.startswith(JOB_NAMESPACE_PREFIX):
        raise JobNamespaceError(
            f"ownership job id must use {JOB_NAMESPACE_PREFIX}<client>:<raw>"
        )
    encoded_client, separator, encoded_raw = text[
        len(JOB_NAMESPACE_PREFIX) :
    ].partition(":")
    if not separator or ":" in encoded_raw:
        raise JobNamespaceError("ownership job namespace has invalid separators")
    client_id = _decode_component(encoded_client, label="client_id")
    raw_job_id = _decode_component(encoded_raw, label="raw_job_id")
    _normalize_component(
        client_id,
        label="client_id",
        max_length=MAX_CLIENT_ID_LENGTH,
    )
    _normalize_component(
        raw_job_id,
        label="raw_job_id",
        max_length=MAX_RAW_JOB_ID_LENGTH,
    )
    canonical = build_job_namespace(client_id, raw_job_id)
    if canonical != text:
        raise JobNamespaceError("ownership job namespace is not canonical")
    return ParsedJobNamespace(
        client_id=client_id,
        raw_job_id=raw_job_id,
        canonical=canonical,
    )


def validate_job_namespace(value: str, *, client_id: str) -> ParsedJobNamespace:
    parsed = parse_job_namespace(value)
    expected_client = _normalize_component(
        client_id,
        label="client_id",
        max_length=MAX_CLIENT_ID_LENGTH,
    )
    if parsed.client_id != expected_client:
        raise JobNamespaceError(
            "ownership job namespace belongs to a different client"
        )
    return parsed


def migrate_legacy_job_id(value: str, *, client_id: str) -> str:
    """Return a canonical id; raw legacy ids gain the caller's client scope."""
    text = str(value or "").strip()
    if text.startswith(JOB_NAMESPACE_PREFIX):
        return validate_job_namespace(value, client_id=client_id).canonical
    if text.startswith("r5job:"):
        raise JobNamespaceError("unsupported ownership job namespace version")
    return build_job_namespace(client_id, value)


def _normalize_component(
    value: str,
    *,
    label: str,
    max_length: int,
) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise JobNamespaceError(f"{label} is required")
    if len(normalized) > max_length:
        raise JobNamespaceError(f"{label} exceeds {max_length} characters")
    return normalized


def _encode_component(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_component(value: str, *, label: str) -> str:
    if not value:
        raise JobNamespaceError(f"{label} is required")
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        ).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise JobNamespaceError(f"{label} is not canonical base64url") from exc
    if _encode_component(decoded) != value:
        raise JobNamespaceError(f"{label} is not canonical base64url")
    return decoded
