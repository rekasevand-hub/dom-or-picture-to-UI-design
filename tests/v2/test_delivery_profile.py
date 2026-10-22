from __future__ import annotations

import os
import unittest
from dataclasses import replace
from unittest.mock import patch

from src.app.services.contracts import ExecutionGraph, validate_runtime_ir
from src.app.services.delivery.runtime_delivery import (
    DeliveryContractError,
    build_runtime_delivery,
)
from src.config.settings import Config
from tests.v2._delivery_fixture import (
    delivery_acceptance,
    delivery_design,
    delivery_sidecar,
)


class DeliveryProfileTests(unittest.TestCase):
    def test_delivery_profile_defaults_to_legacy(self) -> None:
        with patch.dict(os.environ, {"DELIVERY_PROFILE": ""}):
            self.assertEqual(Config().delivery_profile, "legacy")

    def test_delivery_profile_is_explicit_and_fail_closed(self) -> None:
        with patch.dict(os.environ, {"DELIVERY_PROFILE": "contract-v2"}):
            self.assertEqual(Config().delivery_profile, "contract-v2")
        with patch.dict(os.environ, {"DELIVERY_PROFILE": "unsafe-profile"}):
            with self.assertRaisesRegex(ValueError, "DELIVERY_PROFILE"):
                Config()

    def test_contract_bundle_is_deterministic_and_valid(self) -> None:
        sidecar = delivery_sidecar()
        design = delivery_design()
        acceptance = delivery_acceptance()

        first = build_runtime_delivery(sidecar, design, acceptance)
        second = build_runtime_delivery(sidecar, design, acceptance)

        self.assertEqual(first.trace_id, second.trace_id)
        self.assertEqual(first.runtime_ir, second.runtime_ir)
        self.assertEqual(first.audit_bundle, second.audit_bundle)
        self.assertEqual(first.runtime_ir.job_id, sidecar.runtime_ir.job_id)
        self.assertTrue(first.runtime_ir.plan_revision.startswith("plan-"))
        self.assertTrue(first.runtime_ir.output_revision.startswith("output-"))
        self.assertEqual(
            first.release_decision.status.value,
            "deliverable-complete",
        )
        self.assertTrue(first.release_decision.complete_export_allowed)
        self.assertEqual(validate_runtime_ir(first.runtime_ir), [])

    def test_invalid_runtime_contract_stops_bundle_creation(self) -> None:
        invalid_ir = replace(
            delivery_sidecar().runtime_ir,
            execution_graph=ExecutionGraph(nodes=(), edges=()),
        )
        sidecar = replace(delivery_sidecar(), runtime_ir=invalid_ir)

        with self.assertRaises(DeliveryContractError) as caught:
            build_runtime_delivery(
                sidecar,
                delivery_design(),
                delivery_acceptance(),
            )

        self.assertIn(
            "empty-runtime-dag",
            {issue.code for issue in caught.exception.issues},
        )


if __name__ == "__main__":
    unittest.main()
