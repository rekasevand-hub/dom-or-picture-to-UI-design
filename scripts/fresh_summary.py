"""Read the acceptance files the high-fidelity runs leave behind, one row per page.

A run writes a dozen artefacts; the only four numbers worth comparing across
pages are visual fidelity, the frame count it landed on, how many elements it
needed to say it, and which gate it failed.  Everything else belongs to the page
it came from.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TAGS = ["AtomGit", "FluxWeaver", "inventory", "inventory2", "marketplace", "review", "wecom-modal"]
FROZEN = {"AtomGit": 13, "FluxWeaver": 6, "inventory": 10, "inventory2": 14,
          "marketplace": 9, "review": 3, "wecom-modal": 6}


def read(tag: str) -> dict | None:
    out = ROOT / "output" / f"_fresh_{tag}"
    path = out / "acceptance.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    visual = data.get("visual") or {}
    design = out / "figma_design.json"
    frames = elements = None
    if design.is_file():
        tree = json.loads(design.read_text(encoding="utf-8"))
        items = tree.get("elements") or []
        elements = len(items)
        frames = sum(1 for item in items if item.get("layoutChildren"))
    return {
        "tag": tag,
        "status": data.get("status"),
        "within30": round(float(visual.get("within30_pct") or 0), 2),
        "mean": round(float(visual.get("mean") or 0), 3),
        "ink": round(float(visual.get("ink_mean") or 0), 2),
        "over30": round(float(visual.get("over30_pct") or 0), 2),
        "frames": frames,
        "frozen": FROZEN[tag],
        "elements": elements,
        "blockers": ",".join(data.get("blockers") or [])[:70],
    }


def main() -> int:
    rows = [row for row in (read(tag) for tag in TAGS) if row]
    print(f"{'page':<13}{'within30':>9}{'mean':>7}{'ink':>8}{'>30%':>7}{'帧':>4}{'冻结':>5}{'元素':>6}")
    for row in rows:
        print(
            f"{row['tag']:<13}{row['within30']:>9.2f}{row['mean']:>7.2f}{row['ink']:>8.2f}"
            f"{row['over30']:>7.2f}{row['frames'] or 0:>4}{row['frozen']:>5}{row['elements'] or 0:>6}"
        )
    if len(sys.argv) > 1:
        for row in rows:
            print(f"  {row['tag']}: {row['status']} | {row['blockers']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
