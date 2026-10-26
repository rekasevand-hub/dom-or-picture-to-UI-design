"""Strict local single-writer leases with monotonic generations."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Callable


class WriterLeaseError(RuntimeError):
    """Base class for writer-lease failures."""


class WriterLeaseConflict(WriterLeaseError):
    """Another writer still owns an active lease."""


class WriterLeaseLost(WriterLeaseError):
    """The presented token is stale, wrong or expired."""


class WriterLeaseCommitError(WriterLeaseError):
    """The lease state could not be committed safely."""


class WriterLeaseIntegrityError(WriterLeaseError):
    """The persisted lease state is malformed."""


@dataclass(frozen=True, slots=True)
class WriterLease:
    owner_id: str
    generation: int
    expires_at: float

    def __post_init__(self) -> None:
        if not str(self.owner_id or "").strip():
            raise ValueError("owner_id is required")
        if self.generation < 1:
            raise ValueError("generation must be positive")
        if self.expires_at <= 0:
            raise ValueError("expires_at must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "generation": self.generation,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WriterLease":
        return cls(
            owner_id=str(value["owner_id"]),
            generation=int(value["generation"]),
            expires_at=float(value["expires_at"]),
        )


class WriterLeaseStore:
    """File-backed lease for one local bridge writer."""

    def __init__(
        self,
        path: str | Path,
        *,
        owner_id: str,
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] | None = None,
        before_commit: Callable[[str], None] | None = None,
    ) -> None:
        if not str(owner_id or "").strip():
            raise ValueError("owner_id is required")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.path = Path(path).expanduser().resolve()
        self.owner_id = str(owner_id).strip()
        self.ttl_seconds = float(ttl_seconds)
        self._clock = clock or time.time
        self._before_commit = before_commit
        self._lock_path = self.path.with_name(self.path.name + ".lock")
        # Held for the writer's lifetime so process death is distinguishable
        # from an unexpired lease left behind by a crashed local writer.
        self._owner_lock = _FileLock(
            self.path.with_name(self.path.name + ".owner")
        )

    def acquire(self) -> WriterLease:
        acquired_owner_lock = False
        if not self._owner_lock.held:
            self._owner_lock.acquire()
            acquired_owner_lock = True
        try:
            with _FileLock(self._lock_path):
                now = self._clock()
                previous = self._read_state()
                if (
                    previous is not None
                    and previous.get("status") == "active"
                    and float(previous["expires_at"]) > now
                    and not acquired_owner_lock
                ):
                    raise WriterLeaseConflict(
                        f"write lease is owned by {previous.get('owner_id')!r} "
                        f"until {previous.get('expires_at')}"
                    )
                generation = int((previous or {}).get("generation") or 0) + 1
                lease = WriterLease(
                    owner_id=self.owner_id,
                    generation=generation,
                    expires_at=now + self.ttl_seconds,
                )
                self._commit(
                    {
                        **lease.to_dict(),
                        "status": "active",
                        "updated_at": now,
                    }
                )
                return lease
        except Exception:
            if acquired_owner_lock:
                self._owner_lock.release()
            raise

    def assert_current(self, token: WriterLease) -> WriterLease:
        with _FileLock(self._lock_path):
            now = self._clock()
            current = self._current_lease(now)
            if current != token:
                raise WriterLeaseLost(
                    "writer lease token does not match the current generation"
                )
            return token

    def renew(self, token: WriterLease) -> WriterLease:
        with _FileLock(self._lock_path):
            now = self._clock()
            current = self._current_lease(now)
            if current != token:
                raise WriterLeaseLost("cannot renew a stale writer lease")
            renewed = WriterLease(
                owner_id=token.owner_id,
                generation=token.generation,
                expires_at=now + self.ttl_seconds,
            )
            self._commit(
                {
                    **renewed.to_dict(),
                    "status": "active",
                    "updated_at": now,
                }
            )
            return renewed

    def release(self, token: WriterLease) -> None:
        try:
            with _FileLock(self._lock_path):
                now = self._clock()
                current = self._current_lease(now)
                if current != token:
                    raise WriterLeaseLost("cannot release a stale writer lease")
                self._commit(
                    {
                        **token.to_dict(),
                        "status": "released",
                        "updated_at": now,
                    }
                )
        finally:
            self._owner_lock.release()

    def close(self) -> None:
        self._owner_lock.release()

    def _current_lease(self, now: float) -> WriterLease:
        state = self._read_state()
        if state is None:
            raise WriterLeaseLost("writer lease does not exist")
        if state.get("status") != "active":
            raise WriterLeaseLost("writer lease is not active")
        lease = WriterLease.from_dict(state)
        if lease.expires_at <= now:
            raise WriterLeaseLost("writer lease has expired")
        return lease

    def _read_state(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise WriterLeaseIntegrityError(
                f"cannot read writer lease state {self.path}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise WriterLeaseIntegrityError("writer lease state must be an object")
        return value

    def _commit(self, state: dict[str, Any]) -> None:
        if self._before_commit is not None:
            try:
                self._before_commit("before-commit")
            except OSError as exc:
                raise WriterLeaseCommitError(
                    f"writer lease commit hook failed: {exc}"
                ) from exc
        self.path.parent.mkdir(parents=True, exist_ok=True)
        staging = self.path.with_name(f".{self.path.name}.tmp-{os.getpid()}")
        try:
            with staging.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    state,
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staging, self.path)
        except OSError as exc:
            raise WriterLeaseCommitError(
                f"cannot commit writer lease state: {exc}"
            ) from exc
        finally:
            staging.unlink(missing_ok=True)


class _FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any | None = None

    @property
    def held(self) -> bool:
        return self.handle is not None

    def acquire(self) -> "_FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise WriterLeaseConflict(
                f"writer lease lock is busy: {self.path}"
            ) from exc
        self.handle = handle
        return self

    def release(self) -> None:
        handle = self.handle
        self.handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> "_FileLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


_RETAINED_LEASE_STORES: dict[str, WriterLeaseStore] = {}
_RETAINED_LEASE_STORES_LOCK = Lock()


def acquire_writer_lease(
    path: str | Path,
    *,
    owner_id: str,
    ttl_seconds: float = 300.0,
    clock: Callable[[], float] | None = None,
) -> WriterLease:
    resolved_path = Path(path).expanduser().resolve()
    key = str(resolved_path)
    with _RETAINED_LEASE_STORES_LOCK:
        store = _RETAINED_LEASE_STORES.get(key)
        if store is None:
            store = WriterLeaseStore(
                resolved_path,
                owner_id=owner_id,
                ttl_seconds=ttl_seconds,
                clock=clock,
            )
        lease = store.acquire()
        _RETAINED_LEASE_STORES[key] = store
        return lease


def release_writer_lease(path: str | Path, token: WriterLease) -> None:
    key = str(Path(path).expanduser().resolve())
    with _RETAINED_LEASE_STORES_LOCK:
        store = _RETAINED_LEASE_STORES.get(key)
        if store is None:
            raise WriterLeaseLost("writer lease has no retained local owner")
        try:
            store.release(token)
        finally:
            _RETAINED_LEASE_STORES.pop(key, None)


def assert_current_lease(
    path: str | Path,
    token: WriterLease,
    *,
    clock: Callable[[], float] | None = None,
) -> WriterLease:
    return WriterLeaseStore(
        path,
        owner_id=token.owner_id,
        ttl_seconds=1,
        clock=clock,
    ).assert_current(token)
