from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts/image_figma_mvp.py"
    spec = importlib.util.spec_from_file_location("image_figma_mvp_cli", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_image_figma_mvp_cli_defaults_are_current_product_contract() -> None:
    module = _load_script()
    args = module._build_parser().parse_args(
        [
            "--image",
            "input.png",
            "--truth",
            "truth.json",
            "--out",
            "out",
        ]
    )

    assert args.acceptance_policy == "1.0"
    assert args.emission_contract == "repair"
    assert args.calibration_mode == "residual"


def test_image_figma_mvp_cli_keeps_legacy_calibration_fallback() -> None:
    module = _load_script()
    args = module._build_parser().parse_args(
        [
            "--image",
            "input.png",
            "--truth",
            "truth.json",
            "--out",
            "out",
            "--calibration-mode",
            "legacy",
        ]
    )

    assert args.calibration_mode == "legacy"
