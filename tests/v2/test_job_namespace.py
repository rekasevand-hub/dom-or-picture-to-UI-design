from __future__ import annotations

import unittest

from src.app.services.job_namespace import (
    JobNamespaceError,
    build_job_namespace,
    migrate_legacy_job_id,
    parse_job_namespace,
    validate_job_namespace,
)


class JobNamespaceContractTests(unittest.TestCase):
    def test_namespace_is_stable_and_round_trips_unicode_ids(self) -> None:
        first = build_job_namespace("client-甲", "job/one:42")
        second = build_job_namespace("client-甲", "job/one:42")

        self.assertEqual(first, second)
        self.assertEqual(
            first,
            "r5job:v1:Y2xpZW50LeeUsg:am9iL29uZTo0Mg",
        )
        parsed = parse_job_namespace(first)
        self.assertEqual(parsed.client_id, "client-甲")
        self.assertEqual(parsed.raw_job_id, "job/one:42")
        self.assertEqual(parsed.canonical, first)

    def test_namespace_keeps_same_raw_id_isolated_by_client(self) -> None:
        first = build_job_namespace("client-a", "same-job")
        second = build_job_namespace("client-b", "same-job")

        self.assertNotEqual(first, second)
        self.assertEqual(parse_job_namespace(first).raw_job_id, "same-job")
        self.assertEqual(parse_job_namespace(second).raw_job_id, "same-job")

    def test_namespace_rejects_client_mismatch(self) -> None:
        namespaced = build_job_namespace("client-a", "job-one")

        with self.assertRaises(JobNamespaceError):
            validate_job_namespace(namespaced, client_id="client-b")

    def test_namespace_rejects_legacy_and_tampered_values(self) -> None:
        for value in (
            "job-one",
            "r5job:v2:Y2xpZW50LWE:am9iLW9uZQ",
            "r5job:v1:not_base64:am9iLW9uZQ",
            "r5job:v1:Y2xpZW50LWE:am9iLW9uZQ=",
            "r5job:v1::am9iLW9uZQ",
        ):
            with self.subTest(value=value):
                with self.assertRaises(JobNamespaceError):
                    parse_job_namespace(value)

    def test_legacy_migration_is_explicit_and_deterministic(self) -> None:
        migrated = migrate_legacy_job_id("legacy-job", client_id="client-a")
        replayed = migrate_legacy_job_id(
            parse_job_namespace(migrated).canonical,
            client_id="client-a",
        )

        self.assertEqual(migrated, replayed)
        self.assertEqual(parse_job_namespace(migrated).raw_job_id, "legacy-job")
        self.assertEqual(parse_job_namespace(migrated).client_id, "client-a")

    def test_legacy_migration_rejects_unknown_namespace_version(self) -> None:
        with self.assertRaises(JobNamespaceError):
            migrate_legacy_job_id(
                "r5job:v2:Y2xpZW50LWE:am9iLW9uZQ",
                client_id="client-a",
            )


if __name__ == "__main__":
    unittest.main()
