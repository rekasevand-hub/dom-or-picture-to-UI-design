"""OCR backend selection: RapidOCR by default, EasyOCR as the fallback.

The contract is the observation shape, not the engine, so these tests only pin
the routing: configured backend first, the other one when a backend is absent,
and never an exception when neither is installed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.structure import image_contract  # noqa: E402


def _obs(engine: str) -> list[dict]:
    return [
        {
            "text": "内容正在审核中",
            "bbox": [244, 343, 291, 44],
            "confidence": 0.9,
            "engine": engine,
        }
    ]


def test_rapidocr_is_the_default_backend(monkeypatch) -> None:
    monkeypatch.setattr(image_contract, "OCR_BACKEND", "rapidocr")
    monkeypatch.setattr(image_contract, "_rapidocr", lambda path: _obs("rapidocr"))
    calls: list[str] = []
    monkeypatch.setattr(
        image_contract,
        "extract_easyocr_observations",
        lambda path, languages=None: calls.append("easyocr") or _obs("easyocr"),
    )

    observations = image_contract.extract_ocr_observations("unused.png")

    assert observations[0]["engine"] == "rapidocr"
    assert calls == []


def test_a_missing_backend_falls_back_to_the_other(monkeypatch) -> None:
    monkeypatch.setattr(image_contract, "OCR_BACKEND", "rapidocr")
    monkeypatch.setattr(image_contract, "_rapidocr", lambda path: None)
    monkeypatch.setattr(
        image_contract,
        "extract_easyocr_observations",
        lambda path, languages=None: _obs("easyocr"),
    )

    observations = image_contract.extract_ocr_observations("unused.png")

    assert observations[0]["engine"] == "easyocr"


def test_the_configured_backend_wins(monkeypatch) -> None:
    monkeypatch.setattr(image_contract, "OCR_BACKEND", "easyocr")
    monkeypatch.setattr(image_contract, "_rapidocr", lambda path: _obs("rapidocr"))
    monkeypatch.setattr(
        image_contract,
        "extract_easyocr_observations",
        lambda path, languages=None: _obs("easyocr"),
    )

    assert image_contract.extract_ocr_observations("unused.png")[0]["engine"] == "easyocr"


def test_no_backend_at_all_returns_empty_instead_of_raising(monkeypatch) -> None:
    monkeypatch.setattr(image_contract, "OCR_BACKEND", "rapidocr")
    monkeypatch.setattr(image_contract, "_rapidocr", lambda path: None)

    def boom(path, languages=None):
        raise ImportError("easyocr is not installed")

    monkeypatch.setattr(image_contract, "extract_easyocr_observations", boom)

    assert image_contract.extract_ocr_observations("unused.png") == []
