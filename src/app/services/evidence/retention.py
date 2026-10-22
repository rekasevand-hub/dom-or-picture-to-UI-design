"""Retention policy for local P1 evidence sidecars."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.app.services.contracts import RetentionPolicy, jsonable


@dataclass(frozen=True, slots=True)
class EvidenceStorePolicy:
    policy_version: str = "p1-evidence-store/1.0"
    replay_evidence_days: int = 30
    audit_metadata_days: int = 180
    storage_mode: str = "local-sidecar"
    external_url_policy: str = "not-persisted"
    copy_evidence_bytes: bool = True
    max_total_bytes: int = 512 * 1024 * 1024
    redact_keys: tuple[str, ...] = (
        "authorization",
        "cookie",
        "cookies",
        "csrf",
        "password",
        "secret",
        "session",
        "storage_state",
        "token",
    )

    def __post_init__(self) -> None:
        if self.replay_evidence_days <= 0:
            raise ValueError("replay_evidence_days must be positive")
        if self.audit_metadata_days < self.replay_evidence_days:
            raise ValueError("audit_metadata_days cannot be shorter than replay evidence")
        if self.max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")

    def to_contract(self, captured_at: datetime) -> RetentionPolicy:
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        captured_at = captured_at.astimezone(timezone.utc)
        return RetentionPolicy(
            replay_evidence_days=self.replay_evidence_days,
            audit_metadata_days=self.audit_metadata_days,
            evidence_expires_at=_isoformat(
                captured_at + timedelta(days=self.replay_evidence_days)
            ),
            audit_metadata_expires_at=_isoformat(
                captured_at + timedelta(days=self.audit_metadata_days)
            ),
            external_url_separate=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "+00:00")


def contract_retention_deadlines(
    policy: RetentionPolicy,
    *,
    now: datetime | None = None,
) -> dict[str, datetime]:
    """Return evidence/audit deadlines, deriving them only when absent."""
    base = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    evidence = _parse_deadline(policy.evidence_expires_at) or (
        base + timedelta(days=policy.replay_evidence_days)
    )
    audit = _parse_deadline(policy.audit_metadata_expires_at) or (
        base + timedelta(days=policy.audit_metadata_days)
    )
    return {
        "evidence_expires_at": evidence,
        "audit_metadata_expires_at": audit,
    }


def _parse_deadline(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("retention deadlines must be timezone-aware")
    return parsed.astimezone(timezone.utc)
