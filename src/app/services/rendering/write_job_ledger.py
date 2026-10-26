"""Pure R5 write-job state and resume contracts."""

from __future__ import annotations

import json
import hashlib
import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from src.app.services.contracts.models import jsonable
from src.app.services.job_namespace import (
    JOB_NAMESPACE_PREFIX,
    JOB_NAMESPACE_VERSION,
    JobNamespaceError,
    build_job_namespace,
    parse_job_namespace,
    validate_job_namespace,
)

logger = logging.getLogger(__name__)


class LedgerIntegrityError(ValueError):
    """The ledger cannot be compacted safely."""


class LegacyLedgerMigrationError(ValueError):
    """A legacy ledger migration is ambiguous or unsafe."""


class WriteJobState(str, Enum):
    PLANNED = "planned"
    INFLIGHT = "inflight"
    COMMITTED = "committed"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled-back"
    ROLLBACK_INCOMPLETE = "rollback-incomplete"
    UNKNOWN = "unknown"
    RESUME_REQUIRED = "resume-required"


class ResumeAction(str, Enum):
    NONE = "none"
    SAFE_RETRY = "safe-retry"
    RECONCILE_NO_RESEND = "reconcile-no-resend"
    CLEANUP_ONLY = "cleanup-only"
    MANUAL_REVIEW = "manual-review"


@dataclass(frozen=True, slots=True)
class WriteJobRecord:
    job_id: str
    transaction_id: str
    client_id: str
    request_id: str
    fingerprint: str
    expected_created_nodes: int
    state: WriteJobState
    node_ids: tuple[str, ...] = ()
    bridge_state: str = ""
    ownership_classification: str = ""
    resume_action: str = ""
    resume_requires_human: bool = False
    cleanup_status: str = ""
    cleanup_matched: int = 0
    cleanup_removed: int = 0
    cleanup_failed_count: int = 0
    reason: str = ""
    updated_at: float = 0.0
    raw_job_id: str = ""
    namespace_version: str = ""

    def __post_init__(self) -> None:
        if not self.job_id:
            raise ValueError("job_id is required")
        if self.expected_created_nodes < 0:
            raise ValueError("expected_created_nodes must be nonnegative")

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class ResumeDecision:
    action: ResumeAction
    resend_allowed: bool
    requires_human: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class CompensationScope:
    job_id: str
    region_id: str
    node_ids: tuple[str, ...]
    user_takeover_state: str

    def __post_init__(self) -> None:
        if not self.job_id or not self.region_id:
            raise ValueError("job_id and region_id are required")

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class LedgerCompactionResult:
    status: str
    source_events: int
    output_events: int
    removed_events: int
    compacted_jobs: int
    protected_jobs: int
    source_sha256: str
    output_sha256: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class LegacyLedgerMigrationResult:
    status: str
    dry_run: bool
    fields: tuple[str, ...]
    counts: dict[str, int]
    source_sha256: str
    candidate_sha256: str
    target_sha256: str

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "dry_run": self.dry_run,
            "fields": list(self.fields),
            "counts": dict(self.counts),
            "source_sha256": self.source_sha256,
            "candidate_sha256": self.candidate_sha256,
            "target_sha256": self.target_sha256,
        }
        payload["report_sha256"] = _content_hash(payload)
        return payload


_TERMINAL_STATES = {
    WriteJobState.COMMITTED,
    WriteJobState.REJECTED,
    WriteJobState.ROLLED_BACK,
}

_STATE_EVENT_FIELDS = (
    "bridge_state",
    "cleanup_failed_count",
    "cleanup_matched",
    "cleanup_removed",
    "cleanup_status",
    "client_id",
    "compacted",
    "compaction_version",
    "event",
    "expected_created_nodes",
    "fingerprint",
    "history_events",
    "job_id",
    "namespace_version",
    "node_ids",
    "ownership_classification",
    "ownershipReadback",
    "raw_job_id",
    "reason",
    "request_id",
    "resume_action",
    "resume_requires_human",
    "state",
    "transaction_id",
    "updated_at",
    "version",
)
_STATE_EVENT_FIELD_SET = set(_STATE_EVENT_FIELDS)


class WriteJobLedger:
    """Append-only business job index referencing bridge transactions."""

    def __init__(
        self,
        path: str | Path,
        *,
        allow_legacy_job_ids: bool = False,
        max_events: int = 4096,
        terminal_retention_days: float = 30.0,
        compact_min_events: int = 256,
    ) -> None:
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        if terminal_retention_days < 0:
            raise ValueError("terminal_retention_days must be non-negative")
        if compact_min_events <= 0:
            raise ValueError("compact_min_events must be positive")
        if compact_min_events > max_events:
            raise ValueError("compact_min_events must be <= max_events")
        self.path = Path(path).expanduser().resolve()
        self.allow_legacy_job_ids = allow_legacy_job_ids
        self.max_events = max_events
        self.terminal_retention_days = float(terminal_retention_days)
        self.compact_min_events = compact_min_events
        self._lock = threading.RLock()
        self._event_count = self._count_valid_events()

    @classmethod
    def from_bridge_config(cls, config: Any) -> "WriteJobLedger":
        ledger_config = getattr(config, "ledger", None)
        if ledger_config is None:
            raise ValueError("bridge config has no ledger section")
        return cls(
            ledger_config.path,
            allow_legacy_job_ids=ledger_config.allow_legacy_read,
            max_events=ledger_config.max_events,
            terminal_retention_days=ledger_config.terminal_retention_days,
            compact_min_events=ledger_config.compact_min_events,
        )

    def begin_job(
        self,
        *,
        job_id: str,
        transaction_id: str,
        client_id: str,
        request_id: str,
        expected_created_nodes: int,
        fingerprint: str,
    ) -> WriteJobRecord:
        job_id, raw_job_id, namespace_version = self._validate_identity(
            job_id,
            client_id=client_id,
            transaction_id=transaction_id,
        )
        existing = self.load(job_id)
        if existing is not None:
            if (
                existing.fingerprint != fingerprint
                or existing.transaction_id != transaction_id
                or existing.client_id != client_id
            ):
                raise ValueError(
                    f"job id {job_id!r} was already used with another intent"
                )
            return existing
        record = WriteJobRecord(
            job_id=job_id,
            transaction_id=transaction_id,
            client_id=client_id,
            request_id=request_id,
            fingerprint=fingerprint,
            expected_created_nodes=expected_created_nodes,
            state=WriteJobState.PLANNED,
            updated_at=time.time(),
            raw_job_id=raw_job_id,
            namespace_version=namespace_version,
        )
        self._append(record)
        return record

    def mark_inflight(self, job_id: str) -> WriteJobRecord:
        record = self._require(job_id)
        updated = self._replace(record, state=WriteJobState.INFLIGHT)
        self._append(updated)
        return updated

    def record_bridge_outcome(
        self,
        job_id: str,
        bridge_state: str,
        response: dict[str, Any] | None = None,
    ) -> WriteJobRecord:
        record = self._require(job_id)
        state = self._bridge_state_to_job_state(bridge_state)
        node_ids = record.node_ids
        if response is not None:
            extracted = self._created_node_ids(response)
            if extracted:
                node_ids = extracted
        updated = self._replace(
            record,
            state=state,
            bridge_state=str(bridge_state),
            node_ids=node_ids,
        )
        self._append(updated)
        return updated

    def record_ownership(
        self,
        job_id: str,
        ownership_readback: dict[str, Any],
        classification: str,
    ) -> WriteJobRecord:
        allowed = {
            "matches-intended",
            "partial-match",
            "does-not-match-intended",
            "indeterminate",
        }
        if classification not in allowed:
            raise ValueError(f"unsupported ownership classification: {classification}")
        record = self._require(job_id)
        updated = self._replace(
            record,
            ownership_classification=classification,
            reason=str(ownership_readback.get("status") or ""),
        )
        self._append(
            updated,
            extra={
                "ownershipReadback": {
                    "status": ownership_readback.get("status"),
                    "jobId": ownership_readback.get("jobId"),
                    "owner": ownership_readback.get("owner"),
                    "matched": ownership_readback.get("matched"),
                }
            },
        )
        return updated

    def record_resume_decision(
        self,
        job_id: str,
        decision: ResumeDecision,
    ) -> WriteJobRecord:
        record = self._require(job_id)
        updated = self._replace(
            record,
            state=(
                WriteJobState.RESUME_REQUIRED
                if decision.action is ResumeAction.MANUAL_REVIEW
                else record.state
            ),
            resume_action=decision.action.value,
            resume_requires_human=decision.requires_human,
            reason=decision.reason,
        )
        self._append(updated)
        return updated

    def record_cleanup(
        self,
        job_id: str,
        cleanup_result: dict[str, Any],
    ) -> WriteJobRecord:
        record = self._require(job_id)
        if str(cleanup_result.get("jobId") or "") != job_id:
            raise ValueError("cleanup result job id mismatch")
        failed = cleanup_result.get("failed")
        failed_count = len(failed) if isinstance(failed, list) else 0
        cleanup_status = str(cleanup_result.get("status") or "")
        updated = self._replace(
            record,
            state=(
                WriteJobState.RESUME_REQUIRED
                if cleanup_status == "partial" or failed_count > 0
                else record.state
            ),
            cleanup_status=cleanup_status,
            cleanup_matched=int(cleanup_result.get("matched") or 0),
            cleanup_removed=int(cleanup_result.get("removed") or 0),
            cleanup_failed_count=failed_count,
        )
        self._append(updated)
        return updated

    def compact(
        self,
        *,
        now: float | None = None,
        force: bool = False,
    ) -> LedgerCompactionResult:
        """Collapse expired terminal history while preserving its latest state."""
        with self._lock:
            source_hash = _file_sha256(self.path)
            events, repaired_tail = self._scan_event_lines(
                strict_interior=True,
                allow_torn_tail=True,
            )
            source_events = len(events)
            if source_events < self.compact_min_events and not force:
                return LedgerCompactionResult(
                    status="skipped",
                    source_events=source_events,
                    output_events=source_events,
                    removed_events=0,
                    compacted_jobs=0,
                    protected_jobs=0,
                    source_sha256=source_hash,
                    output_sha256=source_hash,
                    reason="below-compact-minimum",
                )

            grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
            fingerprints: dict[str, str] = {}
            for index, event in enumerate(events):
                job_id = str(event.get("job_id") or "").strip()
                fingerprint = str(event.get("fingerprint") or "")
                if not job_id:
                    raise LedgerIntegrityError("state event is missing job_id")
                prior = fingerprints.setdefault(job_id, fingerprint)
                if prior != fingerprint:
                    raise LedgerIntegrityError(
                        "state events for one job have conflicting fingerprints"
                    )
                grouped.setdefault(job_id, []).append((index, event))

            cutoff = float(time.time() if now is None else now) - (
                self.terminal_retention_days * 86_400.0
            )
            output: list[tuple[int, dict[str, Any]]] = []
            compacted_jobs = 0
            protected_jobs = 0
            expected_states: dict[str, str] = {}
            expected_latest: dict[str, dict[str, Any]] = {}
            for job_id, history in grouped.items():
                latest_index, latest = history[-1]
                state_value = str(latest.get("state") or "")
                try:
                    state = WriteJobState(state_value)
                except ValueError as exc:
                    raise LedgerIntegrityError(
                        "state event has an unsupported state"
                    ) from exc
                expected_states[job_id] = state.value
                updated_at = _event_updated_at(latest)
                if (
                    state in _TERMINAL_STATES
                    and len(history) > 1
                    and updated_at is not None
                    and updated_at <= cutoff
                ):
                    replacement = _sanitize_event(latest)
                    replacement["compacted"] = True
                    replacement["compaction_version"] = 1
                    replacement["history_events"] = len(history)
                    output.append((latest_index, replacement))
                    expected_latest[job_id] = replacement
                    compacted_jobs += 1
                else:
                    output.extend(history)
                    expected_latest[job_id] = _sanitize_event(latest)
                    if state not in _TERMINAL_STATES:
                        protected_jobs += 1

            output.sort(key=lambda item: item[0])
            output_events = [event for _, event in output]
            removed_events = source_events - len(output_events)
            if removed_events == 0 and not repaired_tail:
                return LedgerCompactionResult(
                    status="unchanged",
                    source_events=source_events,
                    output_events=source_events,
                    removed_events=0,
                    compacted_jobs=0,
                    protected_jobs=protected_jobs,
                    source_sha256=source_hash,
                    output_sha256=source_hash,
                    reason="no-expired-terminal-history",
                )

            candidate = _serialize_events(output_events)
            candidate_hash = hashlib.sha256(candidate).hexdigest()
            temporary = self._write_compaction_candidate(
                candidate,
                expected_states=expected_states,
                expected_latest=expected_latest,
                expected_events=len(output_events),
            )
            try:
                os.replace(temporary, self.path)
            except BaseException:
                _unlink_quietly(temporary)
                raise
            _fsync_directory(self.path.parent)
            self._event_count = len(output_events)
            return LedgerCompactionResult(
                status="compacted",
                source_events=source_events,
                output_events=len(output_events),
                removed_events=removed_events,
                compacted_jobs=compacted_jobs,
                protected_jobs=protected_jobs,
                source_sha256=source_hash,
                output_sha256=candidate_hash,
                reason=(
                    "expired-terminal-history-collapsed"
                    if compacted_jobs
                    else "repaired-torn-tail"
                ),
            )

    def maybe_compact(self, *, now: float | None = None) -> LedgerCompactionResult | None:
        if self._event_count <= self.max_events:
            return None
        try:
            return self.compact(now=now)
        except (OSError, LedgerIntegrityError) as exc:
            logger.error("write job ledger compaction failed: %s", exc)
            return None

    def load(self, job_id: str) -> WriteJobRecord | None:
        normalized = str(job_id or "").strip()
        if not self.allow_legacy_job_ids and not normalized.startswith(
            JOB_NAMESPACE_PREFIX
        ):
            return None
        try:
            if normalized.startswith(JOB_NAMESPACE_PREFIX):
                parsed = parse_job_namespace(normalized)
                normalized = parsed.canonical
        except JobNamespaceError:
            logger.warning("忽略非法 ownership job namespace")
            return None
        latest: dict[str, Any] | None = None
        for event in self._events():
            if str(event.get("job_id") or "") == normalized:
                latest = event
        if latest is None:
            return None
        try:
            state = WriteJobState(str(latest["state"]))
        except (KeyError, ValueError):
            return None
        node_ids = latest.get("node_ids")
        client_id = str(latest.get("client_id") or "")
        raw_job_id = str(latest.get("raw_job_id") or "")
        namespace_version = str(latest.get("namespace_version") or "")
        if normalized.startswith(JOB_NAMESPACE_PREFIX):
            parsed = parse_job_namespace(normalized)
            if client_id != parsed.client_id:
                logger.warning("忽略 client 不匹配的 ownership job ledger 记录")
                return None
            raw_job_id = raw_job_id or parsed.raw_job_id
            namespace_version = namespace_version or JOB_NAMESPACE_VERSION
        elif self.allow_legacy_job_ids:
            raw_job_id = raw_job_id or normalized
            namespace_version = namespace_version or "legacy"
        return WriteJobRecord(
            job_id=normalized,
            transaction_id=str(latest.get("transaction_id") or ""),
            client_id=client_id,
            request_id=str(latest.get("request_id") or ""),
            fingerprint=str(latest.get("fingerprint") or ""),
            expected_created_nodes=int(latest.get("expected_created_nodes") or 0),
            state=state,
            node_ids=tuple(str(value) for value in node_ids or [] if str(value)),
            bridge_state=str(latest.get("bridge_state") or ""),
            ownership_classification=str(
                latest.get("ownership_classification") or ""
            ),
            resume_action=str(latest.get("resume_action") or ""),
            resume_requires_human=bool(
                latest.get("resume_requires_human", False)
            ),
            cleanup_status=str(latest.get("cleanup_status") or ""),
            cleanup_matched=int(latest.get("cleanup_matched") or 0),
            cleanup_removed=int(latest.get("cleanup_removed") or 0),
            cleanup_failed_count=int(latest.get("cleanup_failed_count") or 0),
            reason=str(latest.get("reason") or ""),
            updated_at=float(latest.get("updated_at") or 0),
            raw_job_id=raw_job_id,
            namespace_version=namespace_version,
        )

    def _require(self, job_id: str) -> WriteJobRecord:
        record = self.load(job_id)
        if record is None:
            raise KeyError(f"unknown write job: {job_id}")
        return record

    def _append(
        self,
        record: WriteJobRecord,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            event = _sanitize_event(
                {
                    "version": 2,
                    "event": "state",
                    **record.to_dict(),
                    **(extra or {}),
                }
            )
            line = json.dumps(
                event,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._event_count += 1
        self.maybe_compact()

    def _count_valid_events(self) -> int:
        try:
            events, _ = self._scan_event_lines(
                strict_interior=False,
                allow_torn_tail=True,
            )
        except OSError:
            return 0
        return len(events)

    def _scan_event_lines(
        self,
        *,
        strict_interior: bool,
        allow_torn_tail: bool,
    ) -> tuple[list[dict[str, Any]], bool]:
        if not self.path.exists():
            return [], False
        text = self.path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        events: list[dict[str, Any]] = []
        malformed: list[int] = []
        nonempty: list[int] = []
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            nonempty.append(index)
            try:
                event = json.loads(line)
            except (TypeError, ValueError):
                malformed.append(index)
                continue
            if not _is_supported_state_event(event):
                malformed.append(index)
                continue
            events.append(event)
        if not malformed:
            return events, False
        if not strict_interior:
            return events, True
        first_malformed = malformed[0]
        trailing_is_malformed = not any(
            index > first_malformed
            for index in nonempty
            if index not in malformed
        )
        if allow_torn_tail and all(
            index >= first_malformed for index in malformed
        ) and trailing_is_malformed:
            return events, True
        raise LedgerIntegrityError(
            "write job ledger has corrupt content before its trailing tail"
        )

    def _write_compaction_candidate(
        self,
        candidate: bytes,
        *,
        expected_states: Mapping[str, str],
        expected_latest: Mapping[str, Mapping[str, Any]],
        expected_events: int,
    ) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        temporary = Path(raw_path)
        try:
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(candidate)
                handle.flush()
                os.fsync(handle.fileno())
            self._validate_compaction_candidate(
                temporary,
                expected_states=expected_states,
                expected_latest=expected_latest,
                expected_events=expected_events,
            )
            return temporary
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            _unlink_quietly(temporary)
            raise

    def _validate_compaction_candidate(
        self,
        path: Path,
        *,
        expected_states: Mapping[str, str],
        expected_latest: Mapping[str, Mapping[str, Any]],
        expected_events: int,
    ) -> None:
        text = path.read_text(encoding="utf-8")
        if text and not text.endswith("\n"):
            raise LedgerIntegrityError("compaction candidate lacks a final newline")
        events: list[dict[str, Any]] = []
        for line in text.splitlines():
            if not line.strip():
                raise LedgerIntegrityError("compaction candidate contains a blank line")
            try:
                event = json.loads(line)
            except (TypeError, ValueError) as exc:
                raise LedgerIntegrityError(
                    "compaction candidate is not valid JSONL"
                ) from exc
            if not _is_supported_state_event(event):
                raise LedgerIntegrityError(
                    "compaction candidate contains an unsupported event"
                )
            events.append(event)
        if len(events) != expected_events:
            raise LedgerIntegrityError(
                "compaction candidate event count does not match"
            )
        latest: dict[str, dict[str, Any]] = {}
        fingerprints: dict[str, str] = {}
        for event in events:
            job_id = str(event["job_id"])
            fingerprint = str(event.get("fingerprint") or "")
            prior = fingerprints.setdefault(job_id, fingerprint)
            if prior != fingerprint:
                raise LedgerIntegrityError(
                    "compaction candidate has a fingerprint conflict"
                )
            latest[job_id] = event
        observed_states = {
            job_id: str(event.get("state") or "")
            for job_id, event in latest.items()
        }
        if observed_states != dict(expected_states):
            raise LedgerIntegrityError(
                "compaction candidate changed reconstructed job states"
            )
        if latest != {
            job_id: dict(event)
            for job_id, event in expected_latest.items()
        }:
            raise LedgerIntegrityError(
                "compaction candidate changed a latest job snapshot"
            )

    def _events(self) -> list[dict[str, Any]]:
        try:
            events, _ = self._scan_event_lines(
                strict_interior=False,
                allow_torn_tail=True,
            )
        except OSError:
            raise
        return events

    def _validate_identity(
        self,
        job_id: str,
        *,
        client_id: str,
        transaction_id: str,
    ) -> tuple[str, str, str]:
        normalized = str(job_id or "").strip()
        normalized_transaction = str(transaction_id or "").strip()
        if normalized_transaction != normalized:
            raise ValueError("owned job transaction_id must equal job_id")
        if normalized.startswith(JOB_NAMESPACE_PREFIX):
            parsed = validate_job_namespace(normalized, client_id=client_id)
            return parsed.canonical, parsed.raw_job_id, JOB_NAMESPACE_VERSION
        if normalized.startswith("r5job:"):
            parse_job_namespace(normalized)
        if not self.allow_legacy_job_ids:
            raise JobNamespaceError(
                "legacy ownership job ids require allow_legacy_job_ids=True"
            )
        if not normalized or not str(client_id or "").strip():
            raise JobNamespaceError("legacy job_id and client_id are required")
        return normalized, normalized, "legacy"

    @staticmethod
    def _replace(record: WriteJobRecord, **changes: Any) -> WriteJobRecord:
        values = {
            field: getattr(record, field)
            for field in WriteJobRecord.__dataclass_fields__
        }
        values.update(changes)
        values["updated_at"] = time.time()
        return WriteJobRecord(**values)

    @staticmethod
    def _bridge_state_to_job_state(bridge_state: str) -> WriteJobState:
        mapping = {
            "planned": WriteJobState.PLANNED,
            "inflight": WriteJobState.INFLIGHT,
            "committed": WriteJobState.COMMITTED,
            "rejected": WriteJobState.REJECTED,
            "rolled-back": WriteJobState.ROLLED_BACK,
            "rollback-incomplete": WriteJobState.ROLLBACK_INCOMPLETE,
            "unknown": WriteJobState.UNKNOWN,
        }
        return mapping.get(str(bridge_state), WriteJobState.RESUME_REQUIRED)

    @staticmethod
    def _created_node_ids(response: dict[str, Any]) -> tuple[str, ...]:
        result = response.get("result")
        if not isinstance(result, dict):
            result = response
        committed = result.get("committed")
        if not isinstance(committed, list):
            return ()
        return tuple(
            str(item["result"])
            for item in committed
            if isinstance(item, dict)
            and isinstance(item.get("result"), str)
            and item["result"]
        )


class OwnedBatchCoordinator:
    """Write-ahead coordinator for a single owned Figma create batch."""

    def __init__(
        self,
        adapter: Any,
        ledger: Any,
        *,
        allow_legacy_job_ids: bool = False,
    ) -> None:
        self.adapter = adapter
        self.ledger = ledger
        self.allow_legacy_job_ids = allow_legacy_job_ids

    def create_owned_batch(
        self,
        job_id: str,
        actions: list[dict[str, Any]],
        *,
        request_id: str | None = None,
    ) -> WriteJobRecord:
        raw_job_id = str(job_id).strip()
        if not raw_job_id:
            raise ValueError("job_id is required")
        if not isinstance(actions, list) or not actions:
            raise ValueError("owned batch actions must be a non-empty list")
        client_id = str(getattr(self.adapter, "client_id", "")).strip()
        if not client_id:
            raise ValueError("adapter client_id is required for owned jobs")
        normalized_job_id = build_job_namespace(client_id, raw_job_id)
        request_id = request_id or uuid.uuid4().hex
        fingerprint = self._fingerprint(normalized_job_id, actions)
        record = self.ledger.begin_job(
            job_id=normalized_job_id,
            transaction_id=normalized_job_id,
            client_id=client_id,
            request_id=request_id,
            expected_created_nodes=self._expected_created_nodes(actions),
            fingerprint=fingerprint,
        )
        if record.state is not WriteJobState.PLANNED:
            return record
        self.ledger.mark_inflight(normalized_job_id)
        try:
            response = self.adapter.apply_batch(
                actions,
                transaction_id=normalized_job_id,
            )
        except Exception:  # noqa: BLE001 - outcome is reconciled below
            bridge_state = "unknown"
            try:
                status = self.adapter.transaction_status(normalized_job_id)
                if isinstance(status, dict):
                    bridge_state = str(status.get("state") or "unknown")
            except Exception:  # noqa: BLE001 - bridge may be unavailable
                bridge_state = "unknown"
            return self.ledger.record_bridge_outcome(
                normalized_job_id,
                bridge_state,
            )
        bridge_state = (
            str(response.get("status") or "unknown")
            if isinstance(response, dict)
            else "unknown"
        )
        return self.ledger.record_bridge_outcome(
            normalized_job_id,
            bridge_state,
            response,
        )

    def resume_job(self, job_id: str) -> ResumeDecision:
        job_id = self._validated_job_id(job_id)
        record = self.ledger.load(job_id)
        if record is None:
            raise KeyError(f"unknown write job: {job_id}")
        status: dict[str, Any] = {}
        try:
            raw_status = self.adapter.transaction_status(job_id)
            if isinstance(raw_status, dict):
                nested = raw_status.get("transaction")
                status = nested if isinstance(nested, dict) else raw_status
                bridge_state = str(status.get("state") or "")
                if bridge_state:
                    record = self.ledger.record_bridge_outcome(
                        job_id,
                        bridge_state,
                    )
        except Exception:  # noqa: BLE001 - preserve unknown/manual state
            status = {}

        ownership: dict[str, Any] | None = None
        if record.state is WriteJobState.UNKNOWN:
            raw_ownership = status.get("ownershipReadback")
            if isinstance(raw_ownership, dict):
                ownership = raw_ownership
            elif record.expected_created_nodes > 0:
                try:
                    candidate = self.adapter.ownership_report(job_id)
                    if isinstance(candidate, dict):
                        ownership = candidate
                except Exception:  # noqa: BLE001 - manual review remains
                    ownership = None
            if ownership is not None:
                reconciliation = status.get("ownershipReconciliation")
                classification = (
                    str(reconciliation.get("classification") or "")
                    if isinstance(reconciliation, dict)
                    else ""
                )
                if not classification:
                    classification = self._classify_ownership(
                        record.expected_created_nodes,
                        ownership,
                    )
                record = self.ledger.record_ownership(
                    job_id,
                    ownership,
                    classification,
                )
        decision = plan_resume(record, ownership)
        self.ledger.record_resume_decision(job_id, decision)
        return decision

    def plan_cleanup(self, job_id: str) -> dict[str, Any]:
        normalized = str(job_id).strip()
        if not normalized:
            return {
                "allowed": False,
                "jobId": "",
                "reason": "job_id is required",
            }
        normalized = self._validated_job_id(normalized)
        record = self.ledger.load(normalized)
        if record is None:
            return {
                "allowed": False,
                "jobId": normalized,
                "reason": "unknown write job",
            }
        if record.state not in _TERMINAL_STATES:
            return {
                "allowed": False,
                "jobId": normalized,
                "reason": "cleanup-requires-manual-review",
            }
        return {
            "allowed": True,
            "jobId": normalized,
            "reason": "cleanup uses exact owner and job markers",
        }

    def cleanup_job(self, job_id: str) -> WriteJobRecord:
        plan = self.plan_cleanup(job_id)
        if not plan["allowed"]:
            raise ValueError(plan["reason"])
        normalized = str(plan["jobId"])
        result = self.adapter.cleanup_owned_job(normalized)
        if not isinstance(result, dict):
            raise RuntimeError("cleanup result must be an object")
        return self.ledger.record_cleanup(normalized, result)

    def _validated_job_id(self, job_id: str) -> str:
        normalized = str(job_id or "").strip()
        if normalized.startswith(JOB_NAMESPACE_PREFIX):
            return validate_job_namespace(
                normalized,
                client_id=str(getattr(self.adapter, "client_id", "")),
            ).canonical
        if self.allow_legacy_job_ids:
            if not normalized:
                raise JobNamespaceError("legacy job_id is required")
            return normalized
        return parse_job_namespace(normalized).canonical

    @staticmethod
    def _expected_created_nodes(actions: list[dict[str, Any]]) -> int:
        create_actions = {
            "create_frame",
            "create_rectangle",
            "create_ellipse",
            "create_text",
            "create_image",
        }
        return sum(
            1
            for item in actions
            if isinstance(item, dict)
            and str(item.get("action") or "") in create_actions
        )

    @staticmethod
    def _fingerprint(job_id: str, actions: list[dict[str, Any]]) -> str:
        payload = json.dumps(
            {"jobId": job_id, "actions": actions},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _classify_ownership(
        expected: int,
        ownership: dict[str, Any],
    ) -> str:
        if ownership.get("status") != "reported":
            return "indeterminate"
        try:
            matched = int(ownership.get("matched") or 0)
        except (TypeError, ValueError):
            return "indeterminate"
        if expected > 0 and matched == expected:
            return "matches-intended"
        if matched == 0:
            return "does-not-match-intended"
        if 0 < matched < expected:
            return "partial-match"
        return "indeterminate"


def plan_resume(
    record: WriteJobRecord,
    ownership: dict[str, Any] | None,
) -> ResumeDecision:
    if record.state is WriteJobState.PLANNED:
        return ResumeDecision(
            action=ResumeAction.SAFE_RETRY,
            resend_allowed=True,
            requires_human=False,
            reason="The write was not dispatched.",
        )
    if record.state in {
        WriteJobState.COMMITTED,
        WriteJobState.REJECTED,
        WriteJobState.ROLLED_BACK,
    }:
        return ResumeDecision(
            action=ResumeAction.NONE,
            resend_allowed=False,
            requires_human=False,
            reason="The write job already has a terminal outcome.",
        )
    if record.state is WriteJobState.UNKNOWN:
        return _plan_unknown_resume(record, ownership)
    return ResumeDecision(
        action=ResumeAction.MANUAL_REVIEW,
        resend_allowed=False,
        requires_human=True,
        reason=f"State {record.state.value} requires manual reconciliation.",
    )


def _plan_unknown_resume(
    record: WriteJobRecord,
    ownership: dict[str, Any] | None,
) -> ResumeDecision:
    if not isinstance(ownership, dict) or ownership.get("status") != "reported":
        return ResumeDecision(
            action=ResumeAction.MANUAL_REVIEW,
            resend_allowed=False,
            requires_human=True,
            reason="Ownership readback is unavailable for an unknown write.",
        )
    try:
        matched = int(ownership.get("matched") or 0)
    except (TypeError, ValueError):
        matched = 0
    expected = record.expected_created_nodes
    if expected > 0 and matched == expected:
        return ResumeDecision(
            action=ResumeAction.RECONCILE_NO_RESEND,
            resend_allowed=False,
            requires_human=False,
            reason="All expected owned nodes are present; reconcile without resend.",
        )
    return ResumeDecision(
        action=ResumeAction.MANUAL_REVIEW,
        resend_allowed=False,
        requires_human=True,
        reason=(
            f"Owned marker count {matched} does not match expected {expected}; "
            "manual reconciliation is required."
        ),
    )


def migrate_legacy_write_job_ledger(
    source_path: str | Path,
    target_path: str | Path,
    *,
    client_mapping: Mapping[str, str],
    dry_run: bool = True,
    overwrite: bool = False,
) -> LegacyLedgerMigrationResult:
    """Migrate bare state events into explicit client namespaces.

    Mapping keys are legacy source ``client_id`` values. The target value is
    the client id used for the canonical namespace. Reports intentionally omit
    source ids, job ids, event text, action payloads, and secrets.
    """
    source = Path(source_path).expanduser().resolve()
    target = Path(target_path).expanduser().resolve()
    if source == target:
        raise LegacyLedgerMigrationError(
            "legacy migration requires a distinct source and target"
        )
    if not source.exists():
        raise LegacyLedgerMigrationError("legacy source ledger does not exist")
    mapping = {
        str(key or "").strip(): str(value or "").strip()
        for key, value in client_mapping.items()
    }
    if not mapping or any(not key or not value for key, value in mapping.items()):
        raise LegacyLedgerMigrationError(
            "explicit client mapping entries must be non-empty"
        )

    source_bytes = source.read_bytes()
    source_events = _read_strict_state_events(source_bytes)
    grouped: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = {}
    group_fingerprints: dict[tuple[str, str], str] = {}
    source_clients: set[str] = set()
    for index, event in enumerate(source_events):
        legacy_job_id = str(event.get("job_id") or "").strip()
        source_client = str(event.get("client_id") or "").strip()
        if not legacy_job_id or legacy_job_id.startswith("r5job:"):
            raise LegacyLedgerMigrationError(
                "legacy ledger contains a missing or already namespaced job"
            )
        if not source_client:
            raise LegacyLedgerMigrationError(
                "legacy ledger event has no client identity to map"
            )
        if source_client not in mapping:
            raise LegacyLedgerMigrationError(
                "legacy ledger client identity has no explicit mapping"
            )
        transaction_id = str(
            event.get("transaction_id") or legacy_job_id
        ).strip()
        if transaction_id != legacy_job_id:
            raise LegacyLedgerMigrationError(
                "legacy ledger transaction id does not match its job id"
            )
        try:
            WriteJobState(str(event.get("state") or ""))
        except ValueError as exc:
            raise LegacyLedgerMigrationError(
                "legacy ledger contains an unsupported job state"
            ) from exc
        key = (source_client, legacy_job_id)
        fingerprint = str(event.get("fingerprint") or "")
        prior = group_fingerprints.setdefault(key, fingerprint)
        if prior != fingerprint:
            raise LegacyLedgerMigrationError(
                "legacy ledger job has conflicting fingerprints"
            )
        source_clients.add(source_client)
        grouped.setdefault(key, []).append((index, event))

    target_to_source: dict[str, tuple[str, str]] = {}
    migrated_groups: list[tuple[str, list[tuple[int, dict[str, Any]]]]] = []
    for key, history in grouped.items():
        source_client, legacy_job_id = key
        target_client = mapping[source_client]
        namespaced = build_job_namespace(target_client, legacy_job_id)
        previous = target_to_source.get(namespaced)
        if previous is not None and previous != key:
            raise LegacyLedgerMigrationError(
                "legacy client mapping collides on a namespaced job"
            )
        target_to_source[namespaced] = key
        migrated_groups.append((namespaced, history))

    migrated_events: list[tuple[str, int, dict[str, Any]]] = []
    terminal_jobs = 0
    protected_jobs = 0
    for namespaced, history in migrated_groups:
        latest_state = WriteJobState(str(history[-1][1]["state"]))
        if latest_state in _TERMINAL_STATES:
            terminal_jobs += 1
        else:
            protected_jobs += 1
        target_client = parse_job_namespace(namespaced).client_id
        for ordinal, event in history:
            migrated = _sanitize_event(event)
            migrated.update(
                {
                    "version": 2,
                    "job_id": namespaced,
                    "transaction_id": namespaced,
                    "client_id": target_client,
                    "raw_job_id": parse_job_namespace(namespaced).raw_job_id,
                    "namespace_version": JOB_NAMESPACE_VERSION,
                }
            )
            migrated_events.append((namespaced, ordinal, migrated))
    migrated_events.sort(key=lambda item: (item[0], item[1]))
    output_events = [event for _, _, event in migrated_events]
    expected_states = {
        namespaced: str(history[-1][1]["state"])
        for namespaced, history in migrated_groups
    }
    _validate_sanitized_events(output_events, expected_states=expected_states)
    candidate = _serialize_events(output_events)
    candidate_hash = hashlib.sha256(candidate).hexdigest()
    source_hash = hashlib.sha256(source_bytes).hexdigest()

    if not dry_run:
        if target.exists() and not overwrite:
            raise LegacyLedgerMigrationError(
                "legacy migration target exists; overwrite is not enabled"
            )
        _atomic_replace_with_validation(
            target,
            candidate,
            validate=lambda path: _validate_sanitized_file(
                path,
                expected_states=expected_states,
                expected_events=len(output_events),
            ),
        )

    counts = {
        "source_events": len(source_events),
        "source_jobs": len(grouped),
        "source_clients": len(source_clients),
        "mapping_entries": len(mapping),
        "output_events": len(output_events),
        "output_jobs": len(migrated_groups),
        "terminal_jobs": terminal_jobs,
        "protected_jobs": protected_jobs,
        "conflicts": 0,
    }
    return LegacyLedgerMigrationResult(
        status="dry-run" if dry_run else "applied",
        dry_run=dry_run,
        fields=tuple(sorted(_STATE_EVENT_FIELD_SET)),
        counts=counts,
        source_sha256=source_hash,
        candidate_sha256=candidate_hash,
        target_sha256=candidate_hash,
    )


def _read_strict_state_events(source: bytes) -> list[dict[str, Any]]:
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LegacyLedgerMigrationError(
            "legacy ledger is not valid UTF-8"
        ) from exc
    if text and not text.endswith("\n"):
        raise LegacyLedgerMigrationError(
            "legacy ledger has a torn tail; repair or replay it before migration"
        )
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            raise LegacyLedgerMigrationError("legacy ledger contains a blank line")
        try:
            event = json.loads(line)
        except (TypeError, ValueError) as exc:
            raise LegacyLedgerMigrationError(
                "legacy ledger contains invalid JSONL"
            ) from exc
        if not _is_supported_state_event(event):
            raise LegacyLedgerMigrationError(
                "legacy ledger contains an unsupported state event"
            )
        events.append(event)
    return events


def _validate_sanitized_events(
    events: list[dict[str, Any]],
    *,
    expected_states: Mapping[str, str],
) -> None:
    latest: dict[str, dict[str, Any]] = {}
    fingerprints: dict[str, str] = {}
    for event in events:
        if not _is_supported_state_event(event):
            raise LegacyLedgerMigrationError(
                "migration candidate contains an unsupported event"
            )
        job_id = str(event["job_id"])
        fingerprint = str(event.get("fingerprint") or "")
        prior = fingerprints.setdefault(job_id, fingerprint)
        if prior != fingerprint:
            raise LegacyLedgerMigrationError(
                "migration candidate contains conflicting fingerprints"
            )
        latest[job_id] = event
    observed = {
        job_id: str(event.get("state") or "")
        for job_id, event in latest.items()
    }
    if observed != dict(expected_states):
        raise LegacyLedgerMigrationError(
            "migration candidate changed reconstructed job states"
        )


def _validate_sanitized_file(
    path: Path,
    *,
    expected_states: Mapping[str, str],
    expected_events: int,
) -> None:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise LegacyLedgerMigrationError(
            "migration candidate cannot be read for validation"
        ) from exc
    events = _read_strict_state_events(content)
    if len(events) != expected_events:
        raise LegacyLedgerMigrationError(
            "migration candidate event count changed"
        )
    _validate_sanitized_events(events, expected_states=expected_states)


def _is_supported_state_event(event: Any) -> bool:
    return (
        isinstance(event, dict)
        and event.get("version") in {1, 2}
        and event.get("event") == "state"
        and bool(str(event.get("job_id") or "").strip())
    )


def _sanitize_event(event: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = {
        key: event[key]
        for key in _STATE_EVENT_FIELDS
        if key in event
    }
    ownership = sanitized.get("ownershipReadback")
    if isinstance(ownership, Mapping):
        sanitized["ownershipReadback"] = {
            key: ownership[key]
            for key in ("jobId", "matched", "owner", "status")
            if key in ownership
        }
    return sanitized


def _serialize_events(events: list[dict[str, Any]]) -> bytes:
    if not events:
        return b""
    text = "\n".join(
        json.dumps(
            event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for event in events
    )
    return (text + "\n").encode("utf-8")


def _event_updated_at(event: Mapping[str, Any]) -> float | None:
    try:
        return float(event.get("updated_at"))
    except (TypeError, ValueError):
        return None


def _content_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return hashlib.sha256(b"").hexdigest()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_replace_with_validation(
    path: Path,
    payload: bytes,
    *,
    validate: Any,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw_path)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        validate(temporary)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        _unlink_quietly(temporary)
        raise


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        logger.warning("could not remove temporary ledger file: %s", path)
