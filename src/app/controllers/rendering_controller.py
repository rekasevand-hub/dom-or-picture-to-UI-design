"""渲染控制器：把 DesignSpec 输出到目标原型工具。"""
from __future__ import annotations

from typing import Any

from src.app.services.contracts import DeliveryProfile
from src.app.services.delivery.runtime_delivery import (
    ContractDeliveryBundle,
    DeliveryAcceptance,
    DeliveryContractError,
    build_runtime_delivery,
    emit_runtime_delivery,
)
from src.app.services.rendering import build_adapter
from src.config import Config


class RenderingController:
    """负责把 DesignSpec 渲染到具体原型工具。"""

    def __init__(self, config: Config) -> None:
        self.config = config

    def render(
        self,
        design: dict[str, Any],
        tool: str,
        *,
        capture_sidecar: Any = None,
        acceptance: DeliveryAcceptance | None = None,
    ) -> ContractDeliveryBundle | None:
        delivery_profile: DeliveryProfile = self.config.delivery_profile
        bundle: ContractDeliveryBundle | None = None
        if delivery_profile == "contract-v2":
            if capture_sidecar is None or acceptance is None:
                missing = []
                if capture_sidecar is None:
                    missing.append("capture_sidecar")
                if acceptance is None:
                    missing.append("acceptance")
                raise DeliveryContractError(
                    (
                        _delivery_input_issue(
                            "missing-delivery-input",
                            ",".join(missing),
                            "contract-v2 requires validated capture evidence and acceptance input",
                        ),
                    )
                )
            bundle = build_runtime_delivery(
                capture_sidecar,
                design,
                acceptance,
                delivery_profile=delivery_profile,
            )
            emit_runtime_delivery(bundle, self.config.output_dir)

        adapter = build_adapter(tool, self.config)
        adapter.connect()
        try:
            adapter.render_design(design)
        finally:
            adapter.disconnect()
        return bundle


def _delivery_input_issue(code: str, path: str, message: str):
    from src.app.services.contracts import ValidationIssue

    return ValidationIssue(code=code, path=path, message=message)
