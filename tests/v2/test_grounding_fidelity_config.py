from __future__ import annotations

from dataclasses import replace

import pytest

from src.config.settings import Config


def test_high_fidelity_defaults(monkeypatch) -> None:
    monkeypatch.setenv("GROUNDING_FIDELITY_MODE", "high")
    monkeypatch.setenv("IMAGE_ENRICHMENT_MODE", "apply")
    cfg = Config()

    assert cfg.grounding_fidelity_mode == "high"
    assert cfg.grounding_repair_max_rounds == 3
    assert cfg.grounding_repair_max_extra_calls == 6
    assert cfg.grounding_repair_min_region_gain == pytest.approx(0.5)
    assert cfg.grounding_region_regression_tolerance == pytest.approx(0.2)


def test_high_fidelity_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("GROUNDING_FIDELITY_MODE", raising=False)
    monkeypatch.delenv("IMAGE_ENRICHMENT_MODE", raising=False)

    cfg = Config()

    assert cfg.grounding_fidelity_mode == "off"
    assert cfg.image_enrichment_mode == "off"


def test_high_fidelity_requires_image_enrichment_apply() -> None:
    with pytest.raises(ValueError, match="IMAGE_ENRICHMENT_MODE=apply"):
        Config(
            grounding_fidelity_mode="high",
            image_enrichment_mode="analyze",
        )


def test_high_fidelity_accepts_apply() -> None:
    cfg = Config(
        grounding_fidelity_mode="high",
        image_enrichment_mode="apply",
    )

    assert cfg.grounding_fidelity_mode == "high"


@pytest.mark.parametrize("mode", ["mystery", "HIGH!", ""])
def test_high_fidelity_mode_fails_closed(mode: str) -> None:
    with pytest.raises(ValueError, match="GROUNDING_FIDELITY_MODE"):
        Config(
            grounding_fidelity_mode=mode,
            image_enrichment_mode="apply",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("grounding_repair_max_rounds", 0),
        ("grounding_repair_max_extra_calls", 0),
        ("grounding_repair_min_region_gain", 0.0),
        ("grounding_region_regression_tolerance", -0.01),
    ],
)
def test_high_fidelity_rejects_non_positive_or_negative_budgets(
    field: str,
    value: float,
) -> None:
    cfg = Config(
        grounding_fidelity_mode="high",
        image_enrichment_mode="apply",
    )

    with pytest.raises(ValueError, match=field):
        replace(cfg, **{field: value})


def test_high_fidelity_controller_clamps_to_contract_budgets() -> None:
    cfg = Config(
        grounding_fidelity_mode="high",
        image_enrichment_mode="apply",
        grounding_repair_max_rounds=9,
        grounding_repair_max_extra_calls=20,
    )

    assert cfg.repair_round_budget() == 3
    assert cfg.repair_call_budget() == 6


def test_fidelity_mode_rejects_whitespace_padded_value() -> None:
    with pytest.raises(ValueError, match="GROUNDING_FIDELITY_MODE"):
        Config(
            grounding_fidelity_mode=" high ",
            image_enrichment_mode="apply",
        )
