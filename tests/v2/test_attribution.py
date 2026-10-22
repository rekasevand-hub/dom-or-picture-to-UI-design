from __future__ import annotations

import unittest

from src.app.services.attribution import (
    AttributionEvidence,
    UnavailableAttributionProvider,
)
from src.app.services.bridge_server import BridgeHub, TransactionRecord


def _transaction() -> TransactionRecord:
    return TransactionRecord(
        client_id="client-a",
        requested_id="request-a",
        transaction_id="tx-a",
        state="unknown",
        fingerprint="a" * 64,
        action="apply_edit_batch",
        updated_at=1.0,
    )


class AttributionStubTests(unittest.TestCase):
    def test_default_provider_returns_unavailable_evidence(self) -> None:
        evidence = UnavailableAttributionProvider().resolve(_transaction())

        self.assertEqual(evidence.status, "unavailable")
        self.assertEqual(evidence.actor, "unknown")
        self.assertEqual(evidence.revision, "unknown")
        self.assertEqual(evidence.source, "figma-plugin-api")

    def test_bridge_accepts_future_attribution_provider(self) -> None:
        class FakeProvider:
            def resolve(self, transaction):
                self.transaction = transaction
                return AttributionEvidence(
                    status="available",
                    actor="collaborator@example.test",
                    revision="revision-42",
                    source="external-audit",
                    reason="test provider",
                )

        provider = FakeProvider()
        hub = BridgeHub(timeout=1, attribution_provider=provider)
        payload = hub._transaction_payload(_transaction())

        self.assertEqual(payload["attribution"]["status"], "available")
        self.assertEqual(
            payload["attribution"]["actor"],
            "collaborator@example.test",
        )
        self.assertEqual(payload["attribution"]["source"], "external-audit")
        self.assertEqual(provider.transaction.transaction_id, "tx-a")

    def test_bridge_fails_closed_when_provider_raises(self) -> None:
        class FailingProvider:
            def resolve(self, transaction):
                raise RuntimeError("audit unavailable")

        hub = BridgeHub(timeout=1, attribution_provider=FailingProvider())
        payload = hub._transaction_payload(_transaction())

        self.assertEqual(payload["attribution"]["status"], "unavailable")
        self.assertEqual(payload["attribution"]["actor"], "unknown")
        self.assertIn("audit unavailable", payload["attribution"]["reason"])


if __name__ == "__main__":
    unittest.main()
