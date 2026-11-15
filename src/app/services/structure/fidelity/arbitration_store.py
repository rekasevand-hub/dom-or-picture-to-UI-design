"""Where an arbitrated design is kept, and how a re-export finds it again.

`12_design.json` is the compiler's output and the cache key for everything
downstream: its SHA decides whether a frozen ticket file still applies.  So the
arbiter must never write to it.  The design that was actually rendered — after
text calibration, after the tickets, after the pixel patches — goes to
`12_design_arbitrated.json` next to it, stamped with the SHA of the file it was
derived from.

On the next build the same compiler produces the same `12_design.json`, the SHA
matches, and the SVG / Figma export loads the arbitrated file instead of the raw
one.  That is the whole point: a re-export used to lose every ticket fix,
because the fixes lived only in the copy that happened to be rendered.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

DESIGN_NAME = "12_design.json"
ARBITRATED_NAME = "12_design_arbitrated.json"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_arbitrated(
    design: Mapping[str, Any],
    out_dir: str | Path,
    *,
    tickets: Sequence[str] = (),
    stages: Sequence[str] = (),
) -> Path:
    """Write the rendered design, stamped with the SHA of the compiler output."""
    out = Path(out_dir)
    source = out / DESIGN_NAME
    payload = dict(design)
    meta = dict(payload.get("_meta") or {})
    meta["arbitration"] = {
        "source": DESIGN_NAME,
        "sourceSha": sha256_file(source) if source.is_file() else "",
        "tickets": list(tickets),
        "stages": list(stages),
    }
    payload["_meta"] = meta
    path = out / ARBITRATED_NAME
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_arbitrated(out_dir: str | Path) -> dict[str, Any] | None:
    """The arbitrated design, but only if it still describes *this* build."""
    out = Path(out_dir)
    path = out / ARBITRATED_NAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or not payload.get("elements"):
        return None
    stamp = str(((payload.get("_meta") or {}).get("arbitration") or {}).get("sourceSha") or "")
    source = out / DESIGN_NAME
    if not stamp or not source.is_file():
        return None
    if stamp != sha256_file(source):
        return None
    return payload


def resolve_design(out_dir: str | Path, name: str = DESIGN_NAME) -> Path:
    """The file an exporter should draw: arbitrated when it is still valid."""
    out = Path(out_dir)
    if name == DESIGN_NAME and load_arbitrated(out) is not None:
        return out / ARBITRATED_NAME
    return out / name
