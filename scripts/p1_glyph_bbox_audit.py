"""Generate canvas glyph truth and compare it with Tesseract glyph boxes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.evidence import (
    calibrate_glyph_boxes,
    compare_glyph_boxes,
    compare_glyph_boxes_trusted,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare Tesseract glyph boxes with browser canvas metrics."
    )
    parser.add_argument("--engine", choices=("chromium", "webkit"), required=True)
    parser.add_argument("--ocr-result", type=Path, required=True)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=_ROOT / "tests" / "fixtures" / "p1" / "ocr_canvas.html",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_ROOT / "output" / "_p1_evidence_shadow" / "glyph_bbox_audit.json",
    )
    args = parser.parse_args(argv)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser_type = getattr(p, args.engine)
        browser = browser_type.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(args.fixture.resolve().as_uri(), wait_until="load")
        page.wait_for_timeout(300)
        truth = page.evaluate(_TRUTH_JS)
        browser.close()

    ocr = json.loads(args.ocr_result.read_text(encoding="utf-8"))
    observed = ocr.get("glyph_observations") or []
    comparison = compare_glyph_boxes(truth, observed)
    calibration = calibrate_glyph_boxes(truth, observed)
    trusted = compare_glyph_boxes_trusted(truth, observed)
    result = {
        "schema_version": "p1-glyph-bbox-audit/1.0",
        "engine": args.engine,
        "fixture": str(args.fixture),
        "ocr_result": str(args.ocr_result),
        "truth_count": len(truth),
        "observed_count": len(observed),
        "comparison": comparison,
        "calibration": calibration,
        "trusted": trusted,
        "truth": truth,
        "observed": observed,
        "interpretation": (
            "Canvas actualBoundingBox metrics are browser-local ground truth; "
            "Tesseract boxes are OCR ink boxes and may use a different baseline convention."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "engine": args.engine,
        "sequence_match": comparison["sequence_match"],
        "truth_count": comparison["truth_count"],
        "observed_count": comparison["observed_count"],
        "max_delta": comparison["max_delta"],
        "p95_delta": comparison["p95_delta"],
        "calibrated_max_delta": calibration["calibrated"]["max_delta"],
        "calibrated_p95_delta": calibration["calibrated"]["p95_delta"],
        "calibrated_within_2px_count": calibration["calibrated"]["within_2px_count"],
        "trusted_count": trusted["trusted"]["compared_count"],
        "suspect_count": trusted["suspect_count"],
        "trusted_max_delta": trusted["trusted"]["max_delta"],
        "trusted_p95_delta": trusted["trusted"]["p95_delta"],
        "trusted_within_2px_count": trusted["trusted"]["within_2px_count"],
        "within_2px_count": comparison["within_2px_count"],
        "output": str(args.out),
    }, ensure_ascii=False))
    return 0


_TRUTH_JS = r"""
() => {
  const canvas = document.getElementById("ocr-canvas");
  const ctx = canvas.getContext("2d");
  const specs = [
    {text: "Invoice total: 128.50", x: 24, baseline: 54, font: "bold 26px sans-serif"},
    {text: "This sentence exists only as painted pixels.", x: 24, baseline: 86, font: "16px sans-serif"},
  ];
  const out = [];
  for (const spec of specs) {
    ctx.font = spec.font;
    let cursor = spec.x;
    for (const ch of spec.text) {
      const m = ctx.measureText(ch);
      if (/\s/.test(ch)) {
        cursor += m.width;
        continue;
      }
      const left = Math.max(0, m.actualBoundingBoxLeft || 0);
      const right = Math.max(0, m.actualBoundingBoxRight || m.width);
      const ascent = Math.max(1, m.actualBoundingBoxAscent || m.width * 0.7);
      const descent = Math.max(0, m.actualBoundingBoxDescent || 0);
      out.push({
        text: ch,
        bbox: [
          Math.round(cursor - left),
          Math.round(spec.baseline - ascent),
          Math.max(1, Math.round(left + right)),
          Math.max(1, Math.round(ascent + descent))
        ]
      });
      cursor += m.width;
    }
  }
  return out;
}
"""


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
