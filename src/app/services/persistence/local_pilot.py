"""Bounded local filesystem store for the P5 pilot."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from src.app.services.contracts import (
    DeliveryRecord,
    canonical_hash,
    jsonable,
)
from src.app.services.evidence.retention import contract_retention_deadlines
from src.app.services.persistence.store import (
    DeliveryStore,
    IdempotencyConflict,
    PersistenceCommitError,
    PersistenceValidationError,
    validate_delivery_bundle,
)


@dataclass(frozen=True, slots=True)
class LocalPilotPurgeResult:
    purged_count: int
    protected_count: int
    tombstone_archives: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "purged_count": self.purged_count,
            "protected_count": self.protected_count,
            "tombstone_archives": list(self.tombstone_archives),
        }


class LocalPilotStore(DeliveryStore):
    storage_profile = "local-pilot"
    production_eligible = False

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], float] | None = None,
        before_commit: Callable[[str], None] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.deliveries = self.root / "deliveries"
        self.tombstones = self.root / "tombstones"
        self.root.mkdir(parents=True, exist_ok=True)
        self.deliveries.mkdir(parents=True, exist_ok=True)
        self._clock = clock or time.time
        self._before_commit = before_commit

    def put(self, bundle: Any, idempotency_key: str) -> DeliveryRecord:
        key = str(idempotency_key or "").strip()
        if not key:
            raise PersistenceValidationError("idempotency_key is required")
        validated = validate_delivery_bundle(bundle)
        content_hash = canonical_hash(
            {
                "trace_id": validated.trace_id,
                "runtime_ir": _mapping(validated.runtime_ir),
                "audit_bundle": _mapping(validated.audit_bundle),
            }
        )
        existing = self._find_by_idempotency(key)
        if existing is not None:
            if existing.content_hash == content_hash:
                return existing
            raise IdempotencyConflict(
                f"idempotency key {key!r} is already bound to different content"
            )
        target = self.deliveries / validated.trace_id
        if target.exists():
            raise IdempotencyConflict(
                f"trace id already exists with different idempotency key: {validated.trace_id}"
            )
        now = datetime.fromtimestamp(self._clock(), tz=timezone.utc)
        runtime_mapping = _mapping(validated.runtime_ir)
        retention = runtime_mapping.get("retention") or {}
        from src.app.services.contracts import RetentionPolicy

        policy = RetentionPolicy(
            replay_evidence_days=int(retention["replay_evidence_days"]),
            audit_metadata_days=int(retention["audit_metadata_days"]),
            evidence_expires_at=retention.get("evidence_expires_at"),
            audit_metadata_expires_at=retention.get("audit_metadata_expires_at"),
        )
        expires_at = contract_retention_deadlines(policy, now=now)[
            "audit_metadata_expires_at"
        ].isoformat()
        record = DeliveryRecord(
            trace_id=validated.trace_id,
            idempotency_key=key,
            stored_at=now.isoformat(),
            expires_at=expires_at,
            runtime_ir=runtime_mapping,
            audit_bundle=_mapping(validated.audit_bundle),
            release_decision=(
                jsonable(validated.release_decision)
                if validated.release_decision is not None
                else None
            ),
            storage_profile=self.storage_profile,
            production_eligible=False,
            content_hash=content_hash,
            purge_protected=bool(runtime_mapping.get("unknowns")),
        )
        self._commit_record(record, target)
        return record

    def get(self, trace_id: str) -> DeliveryRecord | None:
        path = self.deliveries / str(trace_id) / "record.json"
        if not path.is_file():
            return None
        return _record_from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_expired(self, now: Any) -> list[DeliveryRecord]:
        cutoff = _parse_time(now)
        expired: list[DeliveryRecord] = []
        for path in self.deliveries.glob("*/record.json"):
            record = _record_from_dict(json.loads(path.read_text(encoding="utf-8")))
            if _parse_time(record.expires_at) <= cutoff:
                expired.append(record)
        return sorted(expired, key=lambda item: item.trace_id)

    def purge(self, expired: Iterable[DeliveryRecord]) -> LocalPilotPurgeResult:
        purged = 0
        protected = 0
        archives = []
        for item in expired:
            if item.purge_protected:
                protected += 1
                continue
            target = (self.deliveries / item.trace_id).resolve()
            if target.parent != self.deliveries.resolve():
                raise PersistenceValidationError(
                    f"refusing to purge outside deliveries root: {target}"
                )
            tombstones = item.runtime_ir.get("tombstones") or []
            if tombstones:
                archive = self.tombstones / f"{item.trace_id}.json"
                _atomic_write_json(
                    archive,
                    {
                        "trace_id": item.trace_id,
                        "job_id": item.runtime_ir.get("job_id"),
                        "tombstones": tombstones,
                        "archived_at": item.expires_at,
                    },
                )
                archives.append(str(archive))
            if target.exists():
                shutil.rmtree(target)
                purged += 1
        return LocalPilotPurgeResult(
            purged_count=purged,
            protected_count=protected,
            tombstone_archives=tuple(archives),
        )

    def _find_by_idempotency(self, key: str) -> DeliveryRecord | None:
        for path in self.deliveries.glob("*/record.json"):
            record = _record_from_dict(json.loads(path.read_text(encoding="utf-8")))
            if record.idempotency_key == key:
                return record
        return None

    def _commit_record(self, record: DeliveryRecord, target: Path) -> None:
        staging = self.root / f".staging-{os.getpid()}-{uuid.uuid4().hex}"
        staging.mkdir(parents=True, exist_ok=False)
        try:
            if self._before_commit is not None:
                self._before_commit("before-commit")
            _write_json(staging / "record.json", record.to_dict())
            if self._before_commit is not None:
                self._before_commit("before-replace")
            os.replace(staging, target)
        except OSError as exc:
            raise PersistenceCommitError(f"cannot commit pilot record: {exc}") from exc
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return jsonable(value)
    return jsonable(value)


def _record_from_dict(value: dict[str, Any]) -> DeliveryRecord:
    return DeliveryRecord(
        trace_id=str(value["trace_id"]),
        idempotency_key=str(value["idempotency_key"]),
        stored_at=str(value["stored_at"]),
        expires_at=str(value["expires_at"]),
        runtime_ir=value["runtime_ir"],
        audit_bundle=value["audit_bundle"],
        release_decision=value.get("release_decision"),
        storage_profile=str(value["storage_profile"]),
        production_eligible=bool(value["production_eligible"]),
        content_hash=str(value["content_hash"]),
        purge_protected=bool(value.get("purge_protected")),
    )


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("expiration timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _write_json(path: Path, value: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        _write_json(staging, value)
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)
