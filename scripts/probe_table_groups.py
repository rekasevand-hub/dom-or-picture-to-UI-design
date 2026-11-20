"""Would a group of row bands qualify as a table?  Measure before wiring it.

Reads each page's OCR boxes (frozen), re-runs only the separator probe on the
image, and prints per-group evidence: band count, stable columns, spans, header
fill.  No perception run, no compile, no Figma — this only answers whether the
thresholds separate a table from a list on the pages we actually have.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from src.app.services.structure.physical_perception import (  # noqa: E402
    column_clusters,
    probe_separators,
    row_bands,
)
from sample_sources import locate  # noqa: E402

PAGES = {
    "AtomGit": "output/_v2_fit_AtomGit/pipeline",
    "FluxWeaver": "output/_phys_FluxWeaver/pipeline",
    "inventory": "output/_v2_fit_inventory/pipeline",
    "inventory2": "output/_v2_fit_inventory2/pipeline",
    "marketplace": "output/_v2_fit_marketplace/pipeline",
    "review": "output/_v2_fit_review/pipeline",
    "wecom-modal": "output/_v2_fit_wecom-modal/pipeline",
    "gmail": "output/_v2_fit_gmail/pipeline",
    "erp": "output/_v2_fit_erp/pipeline",
    "worklog": "output/_v2_fit_worklog/pipeline",
}
MIN_ROWS = 3
MIN_COLUMNS = 3
SUPPORT = 0.8


def _boxes(run: Path) -> list[list[int]]:
    path = run / "ocr_supplement.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        [int(v) for v in item["bbox"][:4]]
        for item in (data.get("observations") or [])
        if len(item.get("bbox") or []) >= 4
    ]


def _source(run: Path, tag: str) -> Path | None:
    path = run / "image_reference.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        return locate(tag, data["input"]["path"])
    except Exception:  # noqa: BLE001 - a missing sample is not a finding
        return None


def _median(patch) -> tuple[float, float, float] | None:
    if patch.size == 0:
        return None
    flat = patch.reshape(-1, 3).astype(np.float32)
    return tuple(float(v) for v in np.median(flat, axis=0))


def probe(tag: str, run: Path) -> None:
    picture = _source(run, tag)
    boxes = _boxes(run)
    if picture is None or not boxes:
        print(f"{tag:<12} skipped (no picture or OCR)")
        return
    image = np.asarray(Image.open(picture).convert("RGB"), dtype=np.int16)
    height, width = image.shape[:2]
    groups = probe_separators(image, width, height)
    bands = row_bands(groups)
    print(f"{tag:<12} {width}x{height} groups={len(groups)} bands={len(bands)}")
    for group in groups:
        mine = [b for b in bands if b.get("group") == (int(group["x0"]), int(group["x1"]))]
        if not mine:
            continue
        clusters = column_clusters(boxes, mine)
        support = max(2, int(round(len(mine) * SUPPORT)))
        strong = [c for c in clusters if c["rows"] >= support]
        verdict = (
            "TABLE"
            if len(mine) >= MIN_ROWS and len(strong) >= MIN_COLUMNS
            else "-"
        )
        fills = [
            _median(image[b["bbox"][1] : b["bbox"][1] + b["bbox"][3], b["bbox"][0] : b["bbox"][0] + b["bbox"][2]])
            for b in mine
        ]
        spread = 0.0
        if fills and fills[0] is not None:
            for other in fills[1:]:
                if other is None:
                    continue
                spread = max(spread, max(abs(a - b) for a, b in zip(fills[0], other)))
        print(
            f"   span x={group['x0']}..{group['x1']} rows={len(mine)} "
            f"cluster={len(clusters)} strong={len(strong)} headerΔ={spread:.0f} -> {verdict}"
        )
        for c in clusters:
            print(
                f"      col left={c['left']:>5} right={c['right']:>5} rows={c['rows']}/{len(mine)} "
                f"align={c['align']} {'*' if c in strong else ''}"
            )


def main() -> int:
    for tag, run in PAGES.items():
        probe(tag, ROOT / run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
