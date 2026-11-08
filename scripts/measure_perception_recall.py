"""Measure layered perception recall for a screenshot-to-Figma run.

This is a read-only diagnostic.  It does not modify the design, the frozen
acceptance policy, or any production artefact.

Why three layers: a single "perception recall" number hides where content is
lost.  An OCR line can be seen by the detector, present in the content
inventory, but never emitted as a native TEXT node; or emitted as TEXT but not
registered as a gate owner.  Those are different defects and need different
repairs, so they are reported separately.

The OCR observations come from ``pipeline/ocr_supplement.json``.  They are
produced by an independent detector (easyocr / tesseract), not by the VLM
generation path, which makes them a usable recall lower bound.  They are NOT
ground truth: OCR itself misses text, low-confidence rows are noisy, and the
detector shares the same source image as the generator.

Usage:
    python scripts/measure_perception_recall.py --runs <run_dir> [<run_dir> ...]
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "perception-recall/1.0"
HIGH_CONFIDENCE = 0.60
FUZZY_THRESHOLD = 0.82
MIN_CONTAINED_LENGTH = 3

_FULLWIDTH_CHARS = (
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
    "０１２３４５６７８９"
)
_CANONICAL: dict[int, str] = {
    ord(char): chr(ord(char) - 0xFEE0) for char in _FULLWIDTH_CHARS
}
# OCR frequently renders the same middle dot as '.', and Chinese punctuation
# as ASCII.  Normalizing those variants avoids false "missing" reports such as
# '输入·峰时' vs '输入 .峰时'.  Deliberately conservative: no character
# substitution for content (e.g. no '半' -> '¥' guessing).
for _char, _replacement in (
    ("·", "."), ("・", "."), ("•", "."), ("．", "."),
    ("，", ","), ("：", ":"), ("（", "("), ("）", ")"), ("；", ";"),
    ("「", '"'), ("」", '"'), ("『", '"'), ("』", '"'),
):
    _CANONICAL[ord(_char)] = _replacement


def _normalize(text: str) -> str:
    value = str(text or "").translate(_CANONICAL).lower()
    return re.sub(r"[\s\u3000]+", "", value)


def _match_kind(reference: str, candidate: str) -> str | None:
    left = _normalize(reference)
    right = _normalize(candidate)
    if not left or not right:
        return None
    if left == right:
        return "exact"
    if len(left) >= MIN_CONTAINED_LENGTH and left in right:
        return "contained"
    if len(right) >= MIN_CONTAINED_LENGTH and right in left:
        return "partial"
    if SequenceMatcher(None, left, right).ratio() >= FUZZY_THRESHOLD:
        return "fuzzy"
    return None


def _best(reference: str, candidates: Sequence[str]) -> dict[str, Any] | None:
    ranked: list[tuple[int, str, str]] = []
    priority = {"exact": 0, "contained": 1, "fuzzy": 2, "partial": 3}
    for candidate in candidates:
        kind = _match_kind(reference, candidate)
        if kind is not None:
            ranked.append((priority[kind], kind, candidate))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    _score, kind, candidate = ranked[0]
    return {"kind": kind, "candidate": candidate}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _layer(name: str, references: Sequence[dict], candidates: Sequence[str]) -> dict:
    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    for item in references:
        result = _best(str(item.get("text") or ""), candidates)
        if result is None:
            missing.append(item)
        elif result["kind"] == "partial":
            partial.append({**item, "match": result})
            matched.append({**item, "match": result})
        else:
            matched.append({**item, "match": result})
    total = len(references)
    return {
        "layer": name,
        "referenceCount": total,
        "matchedCount": len(matched),
        "missingCount": len(missing),
        "partialCount": len(partial),
        "recall": round(len(matched) / total, 6) if total else None,
        "missing": missing,
        "partial": partial,
    }


def measure(run: Path) -> dict[str, Any]:
    pipeline = run / "pipeline"
    ocr = _read_json(pipeline / "ocr_supplement.json")
    inventory = _read_json(pipeline / "10_content_inventory.json")
    design = _read_json(run / "figma_design.json")
    quality = _read_json(run / "native_text_quality.json")
    acceptance = _read_json(run / "acceptance.json")
    reference = _read_json(pipeline / "image_reference.json")

    observations: list[dict[str, Any]] = []
    for row in ocr.get("observations") or []:
        if not isinstance(row, Mapping):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        observations.append(
            {
                "text": text,
                "bbox": row.get("bbox"),
                "confidence": row.get("confidence"),
                "engine": row.get("engine"),
            }
        )
    high_confidence = [
        item
        for item in observations
        if item["confidence"] is None
        or float(item["confidence"]) >= HIGH_CONFIDENCE
    ]

    inventory_texts: list[str] = []
    for item in inventory.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("kind") or "") not in {
            "text",
            "control",
            "table-cell",
        }:
            continue
        text = str(item.get("text") or "").strip()
        if text:
            inventory_texts.append(text)

    native_texts: list[str] = []
    for element in design.get("elements") or []:
        if not isinstance(element, Mapping):
            continue
        if str(element.get("type") or "") == "image":
            continue
        text = str(element.get("text") or "").strip()
        if text:
            native_texts.append(text)

    owner_texts: list[str] = []
    for owner in quality.get("owners") or []:
        if isinstance(owner, Mapping) and str(owner.get("text") or "").strip():
            owner_texts.append(str(owner["text"]).strip())

    gate = quality.get("gate") or {}
    critical = gate.get("criticalText") or {}
    layers = {
        "screenshot_to_inventory": _layer(
            "screenshot_to_inventory", high_confidence, inventory_texts
        ),
        "inventory_to_native": _layer(
            "inventory_to_native",
            [{"text": text} for text in inventory_texts],
            native_texts,
        ),
        "screenshot_to_native": _layer(
            "screenshot_to_native", high_confidence, native_texts
        ),
        "native_to_gate_owner": _layer(
            "native_to_gate_owner",
            [{"text": text} for text in native_texts],
            owner_texts,
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "run": str(run),
        "input": {
            "sha256": (reference.get("input") or {}).get("sha256"),
            "size": (reference.get("input") or {}).get("size"),
        },
        "acceptance": {
            "status": acceptance.get("status"),
            "criticalMatched": critical.get("matchedCount"),
            "criticalRequired": critical.get("requiredCount"),
            "criticalMissing": critical.get("missing"),
        },
        "counts": {
            "ocrObservations": len(observations),
            "ocrHighConfidence": len(high_confidence),
            "inventoryTextItems": len(inventory_texts),
            "nativeTextOwners": len(native_texts),
            "gateOwnerRecords": len(owner_texts),
        },
        "layers": layers,
        "limitations": [
            "Diagnostic only; not part of the frozen formal acceptance.",
            "OCR observations are a recall lower bound, not ground truth: OCR "
            "itself can miss or misread text, and it shares the source image "
            "with the generation path.",
            "Matching is normalized string similarity, not glyph-level or "
            "positional verification; 'partial' means the OCR row contained "
            "additional tokens not covered by a single candidate.",
            "Layer recalls are independent; they must not be multiplied or "
            "combined into one score.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    results = [measure(run.resolve()) for run in args.runs]
    report = {
        "schema_version": "perception-recall-batch/1.0",
        "highConfidenceThreshold": HIGH_CONFIDENCE,
        "fuzzyThreshold": FUZZY_THRESHOLD,
        "runs": results,
    }
    print(
        f"{'run':<58} {'R->I':>7} {'I->N':>7} {'R->N':>7} {'N->G':>7} "
        f"{'critical':>10}"
    )
    for result in results:
        layers = result["layers"]
        recalls = [
            layers[key]["recall"]
            for key in (
                "screenshot_to_inventory",
                "inventory_to_native",
                "screenshot_to_native",
                "native_to_gate_owner",
            )
        ]
        rendered = [
            "n/a" if value is None else f"{value * 100:.1f}%" for value in recalls
        ]
        acc = result["acceptance"]
        critical = (
            f"{acc['criticalMatched']}/{acc['criticalRequired']}"
            if acc["criticalMatched"] is not None
            else "n/a"
        )
        print(
            f"{Path(result['run']).name:<58} {rendered[0]:>7} {rendered[1]:>7} "
            f"{rendered[2]:>7} {rendered[3]:>7} {critical:>10}"
        )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
