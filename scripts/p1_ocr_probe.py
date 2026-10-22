"""Run an OCR engine against one P1 evidence image and compare expected phrases."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.evidence import (
    compare_glyph_text,
    compare_ocr_text,
    parse_tesseract_boxes,
    summarize_ocr_observations,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a P1 OCR evidence probe.")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--expected", nargs="+", default=[])
    parser.add_argument("--engine", choices=("easyocr", "tesseract"), default="easyocr")
    parser.add_argument("--lang", default="en")
    parser.add_argument("--crop", help="x,y,w,h")
    parser.add_argument("--gpu", action="store_true")
    parser.add_argument(
        "--out",
        type=Path,
        default=_ROOT / "output" / "_p1_evidence_shadow" / "ocr_probe.json",
    )
    args = parser.parse_args(argv)
    if not args.image.is_file():
        print(json.dumps({"status": "error", "error": "image not found"}, ensure_ascii=False))
        return 2

    import cv2

    image = cv2.imread(str(args.image))
    if image is None:
        print(json.dumps({"status": "error", "error": "image decode failed"}, ensure_ascii=False))
        return 2
    crop = _parse_crop(args.crop) if args.crop else None
    if crop is not None:
        x, y, w, h = crop
        image = image[y : y + h, x : x + w]
        if image.size == 0:
            print(json.dumps({"status": "error", "error": "crop is empty"}, ensure_ascii=False))
            return 2

    try:
        if args.engine == "easyocr":
            import easyocr

            started = time.perf_counter()
            reader = easyocr.Reader([args.lang], gpu=args.gpu)
            raw = reader.readtext(image, detail=1)
            observations = [
                {
                    "text": str(text),
                    "confidence": float(confidence),
                    "bbox": _json_bbox(bbox),
                }
                for bbox, text, confidence in raw
            ]
            observed = " ".join(item["text"] for item in observations).strip()
            observation_level = "line"
            glyph_observations: list[dict[str, object]] = []
            glyph_text = ""
        else:
            import pytesseract

            started = time.perf_counter()
            data = pytesseract.image_to_data(
                image,
                lang=args.lang,
                output_type=pytesseract.Output.DICT,
            )
            observations = []
            for index, text in enumerate(data.get("text") or []):
                text = str(text or "").strip()
                if not text:
                    continue
                try:
                    confidence = float(data["conf"][index])
                except (KeyError, TypeError, ValueError):
                    confidence = None
                observations.append(
                    {
                        "text": text,
                        "confidence": confidence,
                        "bbox": [
                            int(data["left"][index]),
                            int(data["top"][index]),
                            int(data["width"][index]),
                            int(data["height"][index]),
                        ],
                    }
                )
            observed = " ".join(item["text"] for item in observations).strip()
            observation_level = "word"
            glyph_text = pytesseract.image_to_boxes(image, lang=args.lang)
            glyph_observations = parse_tesseract_boxes(
                glyph_text,
                image_height=image.shape[0],
            )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    except Exception as exc:  # noqa: BLE001 - report engine availability as evidence
        print(json.dumps({
            "status": "error",
            "engine": args.engine,
            "error": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False))
        return 2

    comparison = compare_ocr_text(args.expected, observed)
    observation_summary = summarize_ocr_observations(observations)
    glyph_comparison = (
        compare_glyph_text("".join(args.expected), "".join(
            str(item["text"]) for item in glyph_observations
        ))
        if args.engine == "tesseract"
        else None
    )
    result = {
        "status": comparison["status"],
        "engine": args.engine,
        "language": args.lang,
        "image": str(args.image),
        "image_sha256": _sha256_bytes(args.image.read_bytes()),
        "crop": crop,
        "elapsed_ms": elapsed_ms,
        "recognized_text": observed,
        "observation_level": observation_level,
        "comparison": comparison,
        "observation_summary": observation_summary,
        "glyph_count": len(glyph_observations),
        "glyph_comparison": glyph_comparison,
        "glyph_observations": glyph_observations,
        "promotion": "candidate-only; not selected as final text",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": result["status"],
        "matched_count": comparison["matched_count"],
        "total_count": comparison["total_count"],
        "elapsed_ms": elapsed_ms,
        "output": str(args.out),
    }, ensure_ascii=False))
    return 0 if result["status"] == "matched" else 1


def _parse_crop(value: str) -> tuple[int, int, int, int]:
    parts = [int(item.strip()) for item in value.split(",")]
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        raise ValueError("crop must be x,y,w,h with positive width and height")
    return parts[0], parts[1], parts[2], parts[3]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bbox(bbox: object) -> list[list[int]]:
    return [
        [int(coord) for coord in point]
        for point in bbox
    ]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
