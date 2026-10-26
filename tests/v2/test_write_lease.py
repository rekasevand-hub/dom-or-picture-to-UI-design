from __future__ import annotations

import multiprocessing
import time
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from src.app.services.write_lease import (
    WriterLeaseCommitError,
    WriterLeaseConflict,
    WriterLeaseLost,
    WriterLeaseStore,
    acquire_writer_lease,
    release_writer_lease,
)


class MutableClock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = float(value)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)


def _hold_lease_process(path: str, ready: str, duration: float) -> None:
    store = WriterLeaseStore(
        Path(path),
        owner_id="process-holder",
        ttl_seconds=30,
    )
    lease = store.acquire()
    Path(ready).write_text(str(lease.generation), encoding="utf-8")
    time.sleep(duration)
    store.release(lease)


class WriterLeaseTests(unittest.TestCase):
    def test_active_owner_blocks_stale_owner_and_generation_increments(self) -> None:
        with TemporaryDirectory() as raw_dir:
            clock = MutableClock()
            path = Path(raw_dir) / "writer-lease.json"
            first_store = WriterLeaseStore(
                path,
                owner_id="writer-a",
                ttl_seconds=10,
                clock=clock,
            )
            second_store = WriterLeaseStore(
                path,
                owner_id="writer-b",
                ttl_seconds=10,
                clock=clock,
            )
            self.addCleanup(first_store.close)
            self.addCleanup(second_store.close)
            first = first_store.acquire()

            self.assertEqual(first.generation, 1)
            self.assertEqual(first.owner_id, "writer-a")
            self.assertEqual(first_store.assert_current(first), first)
            with self.assertRaises(WriterLeaseConflict):
                second_store.acquire()

            first_store.release(first)
            second = second_store.acquire()
            self.assertEqual(second.generation, 2)
            self.assertEqual(second.owner_id, "writer-b")
            second_store.close()

    def test_expired_and_wrong_generation_tokens_are_lost(self) -> None:
        with TemporaryDirectory() as raw_dir:
            clock = MutableClock()
            store = WriterLeaseStore(
                Path(raw_dir) / "writer-lease.json",
                owner_id="writer-a",
                ttl_seconds=5,
                clock=clock,
            )
            self.addCleanup(store.close)
            lease = store.acquire()

            with self.assertRaises(WriterLeaseLost):
                store.assert_current(replace(lease, generation=lease.generation + 1))

            clock.advance(6)
            with self.assertRaises(WriterLeaseLost):
                store.assert_current(lease)

            resumed = store.acquire()
            self.assertEqual(resumed.generation, 2)
            self.assertEqual(store.assert_current(resumed), resumed)
            store.close()

    def test_pause_resume_reacquires_only_after_expiry(self) -> None:
        with TemporaryDirectory() as raw_dir:
            clock = MutableClock()
            store = WriterLeaseStore(
                Path(raw_dir) / "writer-lease.json",
                owner_id="writer-a",
                ttl_seconds=2,
                clock=clock,
            )
            self.addCleanup(store.close)
            lease = store.acquire()
            clock.advance(1.5)
            self.assertEqual(store.assert_current(lease), lease)
            clock.advance(1)

            with self.assertRaises(WriterLeaseLost):
                store.assert_current(lease)
            renewed = store.acquire()
            self.assertGreater(renewed.generation, lease.generation)
            store.close()

    def test_failed_commit_preserves_the_current_lease(self) -> None:
        with TemporaryDirectory() as raw_dir:
            clock = MutableClock()
            path = Path(raw_dir) / "writer-lease.json"

            def fail_commit(stage: str) -> None:
                if stage == "before-commit":
                    raise OSError("simulated partition during commit")

            store = WriterLeaseStore(
                path,
                owner_id="writer-a",
                ttl_seconds=10,
                clock=clock,
            )
            current = store.acquire()
            before_failure = path.read_bytes()
            clock.advance(11)
            store.close()
            partitioned = WriterLeaseStore(
                path,
                owner_id="writer-b",
                ttl_seconds=10,
                clock=clock,
                before_commit=fail_commit,
            )
            self.addCleanup(partitioned.close)

            with self.assertRaises(WriterLeaseCommitError):
                partitioned.acquire()

            self.assertEqual(path.read_bytes(), before_failure)
            recovered_store = WriterLeaseStore(
                path,
                owner_id="writer-c",
                ttl_seconds=10,
                clock=clock,
            )
            self.addCleanup(recovered_store.close)
            recovered = recovered_store.acquire()
            self.assertEqual(recovered.generation, current.generation + 1)
            recovered_store.close()

    def test_two_local_processes_cannot_hold_the_same_lease(self) -> None:
        with TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "writer-lease.json"
            ready = Path(raw_dir) / "ready.txt"
            context = multiprocessing.get_context("spawn")
            process = context.Process(
                target=_hold_lease_process,
                args=(str(path), str(ready), 2.0),
            )
            process.start()
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(ready.exists())
                contender = WriterLeaseStore(
                    path,
                    owner_id="contender",
                    ttl_seconds=10,
                )
                with self.assertRaises(WriterLeaseConflict):
                    contender.acquire()
            finally:
                process.join(timeout=5)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)

    def test_dead_same_owner_process_lease_is_recoverable_before_ttl(
        self,
    ) -> None:
        with TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "writer-lease.json"
            ready = Path(raw_dir) / "ready.txt"
            context = multiprocessing.get_context("spawn")
            process = context.Process(
                target=_hold_lease_process,
                args=(str(path), str(ready), 30.0),
            )
            process.start()
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(ready.exists())
            finally:
                process.terminate()
                process.join(timeout=5)

            recovered_store = WriterLeaseStore(
                path,
                owner_id="process-holder",
                ttl_seconds=30,
            )
            self.addCleanup(recovered_store.close)
            recovered = recovered_store.acquire()

            self.assertEqual(recovered.owner_id, "process-holder")
            self.assertEqual(recovered.generation, 2)
            recovered_store.close()

    def test_convenience_acquire_retains_process_ownership_until_release(
        self,
    ) -> None:
        with TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "writer-lease.json"
            lease = acquire_writer_lease(
                path,
                owner_id="helper-owner",
                ttl_seconds=30,
            )

            with self.assertRaises(WriterLeaseConflict):
                acquire_writer_lease(
                    path,
                    owner_id="helper-contender",
                    ttl_seconds=30,
                )

            release_writer_lease(path, lease)
            contender = acquire_writer_lease(
                path,
                owner_id="helper-contender",
                ttl_seconds=30,
            )
            self.assertEqual(contender.generation, lease.generation + 1)
            release_writer_lease(path, contender)


if __name__ == "__main__":
    unittest.main()
