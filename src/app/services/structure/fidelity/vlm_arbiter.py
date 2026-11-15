"""A referee for the last few defects, with no authority over geometry.

The rules in this pipeline are measurements: a threshold, a projection, a
stroke width.  What they cannot do is *name* something.  A run of pixels that no
node explains is either a word the OCR never read or a chip the plan never had,
and only a picture model can say which.  So the model is given exactly that job
and nothing else:

* it never invents coordinates.  The candidates are numbered blocks we measured
  (``residual_regions``: diff > 40, 14x14..240x120, under 65% text), each shown
  as ``[picture | current render]`` side by side, and it picks an index;
* it may only file two kinds of ticket — ``MISSING_OR_FADED_TEXT`` and
  ``STYLE_MISMATCH`` — because those are the two where a name is the missing
  piece of information;
* every ticket is frozen to disk, keyed by the picture and render it was derived
  from.  A replay reads the frozen file instead of calling the model, so the
  same inputs produce the same output whether or not there is a key in the
  environment;
* and every ticket has to pass four gates, measured after a real re-render.  A
  ticket that improves its own block but costs the page a fifth of a point is
  rolled back, ticket by ticket.

The model is therefore a classifier over candidates, and the gates decide
whether its opinion is worth keeping.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

SCHEMA_VERSION = "image-arbiter-tickets/1.0"

#: The only two questions the model is asked.
TICKET_TYPES = ("MISSING_OR_FADED_TEXT", "STYLE_MISMATCH")

#: ``STYLE_MISMATCH`` may ask for these three repairs, no others.
STYLE_FIXES = ("bold", "pill_bg", "border")

#: A ticket is worth keeping when the whole page does not lose this much.
GLOBAL_TOLERANCE = 0.02
#: Patch budget: a ticket may never be the reason the canvas becomes a mosaic.
PATCH_BUDGET_SHARE = 0.08
MAX_TICKETS = 8


class ArbiterUnavailable(RuntimeError):
    """No vision model is configured; frozen tickets are the only way in."""


@dataclass
class Candidate:
    """A measured region the plan does not explain, in page coordinates."""

    index: int
    box: tuple[int, int, int, int]
    error: float

    def as_dict(self) -> dict[str, Any]:
        return {"index": self.index, "bbox": list(self.box), "error": round(self.error, 1)}


@dataclass
class Ticket:
    """One instruction, expressed only in terms of a candidate or a node."""

    type: str
    candidate: int | None = None
    node_id: str = ""
    expected_text: str = ""
    fix: str = ""
    roi_bbox: list[int] = field(default_factory=list)
    reason: str = ""

    def validate(self) -> None:
        if self.type not in TICKET_TYPES:
            raise ValueError(f"unknown ticket type: {self.type}")
        if self.type == "MISSING_OR_FADED_TEXT":
            if not self.expected_text.strip():
                raise ValueError("MISSING_OR_FADED_TEXT needs expected_text")
            if len(self.roi_bbox) != 4:
                raise ValueError("MISSING_OR_FADED_TEXT needs a measured roi_bbox")
        if self.type == "STYLE_MISMATCH":
            if not self.node_id:
                raise ValueError("STYLE_MISMATCH needs node_id")
            if self.fix not in STYLE_FIXES:
                raise ValueError(f"unknown style fix: {self.fix!r}")


@dataclass
class TicketFile:
    """The frozen result of one arbitration, replayable without the model."""

    key: str
    tickets: list[Ticket] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "key": self.key,
            "tickets": [asdict(ticket) for ticket in self.tickets],
        }

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return path

    @classmethod
    def load(cls, path: Path, key: str) -> "TicketFile":
        if not path.is_file():
            return cls(key=key)
        data = json.loads(path.read_text(encoding="utf-8"))
        if str(data.get("key")) != key:
            # Different picture or different render: the instructions were about
            # a drawing that no longer exists.
            return cls(key=key)
        tickets = [Ticket(**ticket) for ticket in data.get("tickets") or []]
        return cls(key=key, tickets=tickets)


def render_key(image_sha: str, render_path: str | Path) -> str:
    """Identity of one arbitration: the picture plus the render it looked at."""
    render_bytes = Path(render_path).read_bytes() if Path(render_path).is_file() else b""
    digest = hashlib.sha1(render_bytes).hexdigest()[:16]
    return f"{image_sha[:16]}-{digest}"


def build_candidates(
    truth,
    drawn,
    regions: Sequence[Sequence[int]],
) -> list[Candidate]:
    """Number the blocks worth asking about, worst error first."""
    import numpy as np

    if not regions:
        return []
    candidates: list[Candidate] = []
    height, width = truth.shape[:2]
    for index, region in enumerate(regions):
        # ``residual_regions`` carries a paint level as a fifth value; the
        # candidate only needs the block.
        x, y, w, h = (int(value) for value in list(region)[:4])
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + w), min(height, y + h)
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        block = np.abs(truth[y0:y1, x0:x1] - drawn[y0:y1, x0:x1]).max(axis=2)
        candidates.append(
            Candidate(index=index, box=(x0, y0, x1 - x0, y1 - y0), error=float(block.mean()))
        )
    candidates.sort(key=lambda candidate: candidate.error, reverse=True)
    candidates = candidates[:MAX_TICKETS]
    # The number the model sees is the position of the strip it was shown, not
    # the region's original index: "candidate 1" has to mean "the second image",
    # or every answer lands on a block the model never looked at.
    for position, candidate in enumerate(candidates):
        candidate.index = position
    return candidates


def side_by_side(
    truth,
    drawn,
    candidate: Candidate,
    pad: int = 6,
) -> Any:
    """One candidate, picture on the left and render on the right, at 1:1.

    No scaling: the whole point of a candidate is small text, and a downsized
    strip turns a glyph into a smudge the model cannot read.
    """
    import numpy as np

    x, y, w, h = candidate.box
    height, width = truth.shape[:2]
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(width, x + w + pad), min(height, y + h + pad)
    gap = np.full((y1 - y0, 8, 3), 255, dtype=np.uint8)
    pair = np.concatenate(
        [truth[y0:y1, x0:x1].astype(np.uint8), gap, drawn[y0:y1, x0:x1].astype(np.uint8)],
        axis=1,
    )
    return pair


def propose(
    candidates: Sequence[Candidate],
    strips: Sequence[Any],
    *,
    prompt_builder: Callable[[Sequence[Candidate]], str] | None = None,
    vision: Any = None,
) -> TicketFile:
    """Ask the model which candidates it can name.

    ``vision`` is a callable ``(prompt, images) -> dict``.  When it is missing
    the arbitration simply cannot happen; that is a configuration problem, not a
    reason to guess, so it raises instead of returning an empty list that would
    look like "nothing wrong".
    """
    if vision is None:
        raise ArbiterUnavailable(
            "VISION_API_KEY is not configured: the arbiter can replay frozen "
            "tickets (15_arbiter_tickets.json) but cannot run live"
        )
    prompt = (prompt_builder or default_prompt)(candidates)
    payload = vision(prompt, strips) or {}
    by_index = {candidate.index: candidate for candidate in candidates}
    tickets: list[Ticket] = []
    for raw in (payload.get("tickets") or [])[:MAX_TICKETS]:
        try:
            chosen = raw.get("candidate")
            chosen = int(chosen) if chosen is not None else None
            ticket = Ticket(
                type=str(raw.get("type") or ""),
                candidate=chosen,
                node_id=str(raw.get("node_id") or ""),
                expected_text=str(raw.get("expected_text") or ""),
                fix=str(raw.get("fix") or ""),
                roi_bbox=[],
                reason=str(raw.get("reason") or ""),
            )
            # The model does not get to say where.  A candidate was measured, so
            # its box *is* the region; anything the model wrote there is a guess
            # at best and a hallucination at worst.
            if ticket.type == "MISSING_OR_FADED_TEXT":
                candidate = by_index.get(ticket.candidate) if ticket.candidate is not None else None
                if candidate is None:
                    continue
                ticket.roi_bbox = [int(value) for value in candidate.box]
            ticket.validate()
        except (TypeError, ValueError):
            continue
        tickets.append(ticket)
    return TicketFile(key="", tickets=tickets)


def default_prompt(candidates: Sequence[Candidate]) -> str:
    """The question, kept short enough that the answer stays a schema."""
    listing = json.dumps([candidate.as_dict() for candidate in candidates], ensure_ascii=False)
    return (
        "下面按顺序给出 N 张并排对照图，第 i 张对应候选 i：左边是原图，右边是当前渲染。\n"
        f"候选清单（编号、页面坐标、平均误差）：{listing}\n"
        "只回答 JSON，不要解释。格式：\n"
        '{"tickets":[{"type":"MISSING_OR_FADED_TEXT","candidate":0,'
        '"expected_text":"图上真实可见的文字","reason":"..."},'
        '{"type":"STYLE_MISMATCH","candidate":1,"fix":"bold|pill_bg|border","reason":"..."}]}\n'
        "坐标由系统按候选补齐，你不要写 bbox，也不要编造节点 id。\n"
        f"最多 {MAX_TICKETS} 条；只在能确定时回答，看不清就少答。"
    )


def execute(
    ticket: Ticket,
    elements: list[dict[str, Any]],
    truth,
    drawn,
) -> dict[str, Any] | None:
    """Carry out one ticket with deterministic operations, or refuse.

    Returns the number of elements changed.  Refusing is a normal outcome: a
    ticket that points at nothing, or names a node that is gone, is dropped here
    rather than turned into a guess.
    """
    ticket.validate()
    if ticket.type == "STYLE_MISMATCH":
        return _execute_style(ticket, elements)
    return _execute_text(ticket, elements, truth)


def _find(elements: Sequence[dict[str, Any]], node_id: str) -> dict[str, Any] | None:
    for element in elements:
        if str(element.get("id") or "") == node_id:
            return element
    return None


def _execute_style(ticket: Ticket, elements: list[dict[str, Any]]) -> dict[str, Any] | None:
    element = _find(elements, ticket.node_id)
    if element is None:
        return None
    style = element.setdefault("style", {})
    if ticket.fix == "bold":
        style["fontWeight"] = "bold"
        style["fontWeightValue"] = 700
    elif ticket.fix == "pill_bg":
        if not style.get("fillColor"):
            return None
        style["borderRadius"] = float(style.get("borderRadius") or 12)
    elif ticket.fix == "border":
        if not style.get("borderColor"):
            return None
        style["borderWidth"] = max(1, int(style.get("borderWidth") or 1))
    else:  # pragma: no cover - validate() already rejected these
        return None
    element["arbiterEvidence"] = {"ticket": ticket.type, "fix": ticket.fix}
    return {"node": ticket.node_id, "fix": ticket.fix}


def _execute_text(
    ticket: Ticket, elements: list[dict[str, Any]], truth
) -> dict[str, Any] | None:
    """Build the missing words as a text node, styled from the pixels there."""
    import numpy as np

    x, y, w, h = (int(value) for value in ticket.roi_bbox)
    height, width = truth.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    crop = truth[y0:y1, x0:x1]
    ink = np.abs(crop - np.median(crop.reshape(-1, 3), axis=0)).max(axis=2) >= 40
    if not ink.any():
        return None
    background = np.median(
        np.concatenate([crop[0:1].reshape(-1, 3), crop[-1:].reshape(-1, 3)]), axis=0
    )
    foreground = np.median(crop[ink], axis=0)
    rows = np.where(ink.any(axis=1))[0]
    columns = np.where(ink.any(axis=0))[0]
    if rows.size == 0 or columns.size == 0:
        return None
    ink_height = float(rows[-1] - rows[0] + 1)
    size = max(8.0, round(ink_height * 0.95 * 2) / 2)

    def hexed(colour) -> str:
        return "#{:02x}{:02x}{:02x}".format(*(int(value) for value in colour))

    digest = hashlib.sha1(
        f"arbiter:{x0}:{y0}:{x1}:{y1}:{ticket.expected_text}".encode("utf-8")
    ).hexdigest()[:16]
    element = {
        "id": f"arbiter-text:{digest}",
        "type": "text",
        "x": x0 + int(columns[0]),
        "y": y0 + int(rows[0]),
        "width": float(columns[-1] - columns[0] + 1),
        "height": ink_height,
        "text": ticket.expected_text,
        "style": {
            "fontSize": size,
            "fontFamily": "Noto Sans SC",
            "textColor": hexed(foreground),
            "textAlign": "left",
            "fontWeight": "normal",
            "fontWeightValue": 400,
        },
        "role": "text",
        "name": "Arbiter text",
        "contentRef": f"arbiter-text:{digest}",
        "arbiterEvidence": {
            "ticket": ticket.type,
            "background": hexed(background),
            "reason": ticket.reason,
        },
    }
    elements.append(element)
    return {"node": element["id"], "text": ticket.expected_text}


@dataclass
class GateResult:
    """The four checks, and the one that failed."""

    roi_before: float
    roi_after: float
    global_before: float
    global_after: float
    frames: int
    frames_floor: int
    written_equals_accepted: bool
    patch_share: float

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def failures(self) -> list[str]:
        failed = []
        if self.roi_after < self.roi_before:
            failed.append("roi-worse")
        if self.global_after < self.global_before - GLOBAL_TOLERANCE:
            failed.append("page-worse")
        if self.frames < self.frames_floor:
            failed.append("frames-lost")
        if not self.written_equals_accepted:
            failed.append("frames-disagree")
        if self.patch_share > PATCH_BUDGET_SHARE * 100:
            failed.append("patch-budget")
        return failed
