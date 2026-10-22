from __future__ import annotations

import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.app.controllers.rendering_controller import RenderingController
from src.app.agents.precise_agent import PreciseAgent
from src.app.services.contracts import ExecutionGraph
from src.app.services.delivery.runtime_delivery import DeliveryContractError
from src.config.settings import Config
from tests.v2._delivery_fixture import (
    RecordingAdapter,
    delivery_acceptance,
    delivery_design,
    delivery_sidecar,
)


def _serialized_actions(actions: list[dict]) -> bytes:
    return json.dumps(
        actions,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class ContractDeliveryIntegrationTests(unittest.TestCase):
    def test_legacy_and_contract_profile_dispatch_identical_design(self) -> None:
        design = delivery_design()
        legacy_adapter = RecordingAdapter(actions=[])
        contract_adapter = RecordingAdapter(actions=[])
        sidecar = delivery_sidecar()
        acceptance = delivery_acceptance()

        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            with patch(
                "src.app.controllers.rendering_controller.build_adapter",
                side_effect=[legacy_adapter, contract_adapter],
            ):
                legacy_result = RenderingController(
                    Config(output_dir=output, delivery_profile="legacy")
                ).render(design, "svg")
                contract_result = RenderingController(
                    Config(output_dir=output, delivery_profile="contract-v2")
                ).render(
                    design,
                    "svg",
                    capture_sidecar=sidecar,
                    acceptance=acceptance,
                )

            self.assertIsNone(legacy_result)
            self.assertIsNotNone(contract_result)
            self.assertEqual(
                _serialized_actions(legacy_adapter.actions),
                _serialized_actions(contract_adapter.actions),
            )
            self.assertTrue((output / "runtime_ir.json").is_file())
            self.assertTrue((output / "audit_bundle.json").is_file())
            delivery_manifest = json.loads(
                (output / "delivery_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(delivery_manifest["delivery_profile"], "contract-v2")
            self.assertEqual(
                delivery_manifest["trace_id"],
                contract_result.trace_id,
            )

    def test_contract_validation_failure_stops_before_adapter_dispatch(self) -> None:
        invalid_ir = replace(
            delivery_sidecar().runtime_ir,
            execution_graph=ExecutionGraph(nodes=(), edges=()),
        )
        invalid_sidecar = replace(delivery_sidecar(), runtime_ir=invalid_ir)

        with tempfile.TemporaryDirectory() as raw_dir:
            with patch(
                "src.app.controllers.rendering_controller.build_adapter"
            ) as build_adapter:
                with self.assertRaises(DeliveryContractError):
                    RenderingController(
                        Config(
                            output_dir=Path(raw_dir),
                            delivery_profile="contract-v2",
                        )
                    ).render(
                        delivery_design(),
                        "svg",
                        capture_sidecar=invalid_sidecar,
                        acceptance=delivery_acceptance(),
                    )
                build_adapter.assert_not_called()

    def test_legacy_ignores_contract_inputs_and_remains_unchanged(self) -> None:
        invalid_ir = replace(
            delivery_sidecar().runtime_ir,
            execution_graph=ExecutionGraph(nodes=(), edges=()),
        )
        invalid_sidecar = replace(delivery_sidecar(), runtime_ir=invalid_ir)
        adapter = RecordingAdapter(actions=[])

        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            with patch(
                "src.app.controllers.rendering_controller.build_adapter",
                return_value=adapter,
            ):
                result = RenderingController(
                    Config(output_dir=output, delivery_profile="legacy")
                ).render(
                    delivery_design(),
                    "svg",
                    capture_sidecar=invalid_sidecar,
                    acceptance=delivery_acceptance(),
                )

            self.assertIsNone(result)
            self.assertEqual(adapter.actions[0], {"operation": "connect"})
            self.assertEqual(adapter.actions[-1], {"operation": "disconnect"})
            self.assertFalse((output / "runtime_ir.json").exists())

    def test_precise_agent_records_contract_profile_and_trace_in_manifest(self) -> None:
        design = delivery_design()
        sidecar = delivery_sidecar()
        acceptance = delivery_acceptance()
        bundle = SimpleNamespace(trace_id="trace-precise-agent")

        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            config = Config(
                output_dir=output,
                delivery_profile="contract-v2",
                text_align=False,
            )
            with (
                patch(
                    "src.app.services.evidence.adapter.adapt_capture",
                    return_value=sidecar,
                ),
                patch(
                    "src.app.services.som.direct_design.try_build_direct_design",
                    return_value=design,
                ),
                patch(
                    "src.app.services.som.direct_design.build_direct_design",
                    return_value=design,
                ),
                patch(
                    "src.app.services.som.design_crops.apply_crops_to_design",
                    return_value=0,
                ),
                patch(
                    "src.app.services.som.design_crops.backfill_design_image_crops"
                ),
                patch(
                    "src.app.controllers.rendering_controller.RenderingController.render",
                    return_value=bundle,
                ) as render_mock,
            ):
                PreciseAgent(config)._design_and_render(
                    {"provenance": {}},
                    image=str(output / "00_screenshot.png"),
                    url=None,
                    tool="svg",
                    out=output,
                    t0=time.time(),
                    route="dom",
                    counts={"containers": 1, "elements": 2},
                    fallbacks=[],
                    delivery_acceptance=acceptance,
                )

            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["delivery"]["profile"], "contract-v2")
            self.assertEqual(
                manifest["delivery"]["trace_id"],
                "trace-precise-agent",
            )
            render_mock.assert_called_once()
            self.assertIs(
                render_mock.call_args.kwargs["capture_sidecar"],
                sidecar,
            )
            self.assertIs(render_mock.call_args.kwargs["acceptance"], acceptance)


if __name__ == "__main__":
    unittest.main()
