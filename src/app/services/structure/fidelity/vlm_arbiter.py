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
    frames_before: int = 0

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
        if self.frames < self.frames_floor or (self.frames_before and self.frames < self.frames_before):
            failed.append("frames-lost")
        if not self.written_equals_accepted:
            failed.append("frames-disagree")
        if self.patch_share > PATCH_BUDGET_SHARE * 100:
            failed.append("patch-budget")
        return failed


# --------------------------------------------------------------------------
# 设计神似口径（宏观仲裁）
#
# 上一版按 diff>40 的碎片逐块问模型、再用 ROI 的像素相似度否决工单，结果是
# 模型看得见"哪块像素不对"，却看不见"这一页该怎么排"，而像素门禁又会否掉一切
# 让字形发生 0.5px 变化的修复。这一层换成宏观口径：
#
#   * 输入是整页 + 上/中/下三段横带的并排图，外加当前页面的容器与文本清单；
#   * 工单只回答"设计上哪里不对"，五类，全部由确定性算子执行；
#   * 门禁不再看像素，只看结构红线、几何防撞，以及修复后的并排复核。
# --------------------------------------------------------------------------

DESIGN_TICKETS = (
    "MISSING_TEXT_BLOCK",
    "TEXT_COLLISION_OR_DRIFT",
    "INCOMPLETE_GRAPHIC_OR_WIDGET",
    "TYPOGRAPHY_HIERARCHY",
    "CONTAINER_CROWDING",
    "BORDER_OR_SEPARATION",
)
#: 边界类工单能派发的执行动作。
BORDER_FIXES = ("border", "gap", "inset")
#: 两个文本框重叠超过较小者面积的这个比例，就算 A 压 B。
COLLISION_SHARE = 0.45
#: 整页图缩到这个宽度再送模型：它要看排版，不需要数清每一个像素。
MACRO_WIDTH = 1440
#: 整页最多几条；上/中/下每一带最多几条。之前是"全页 6 条"，结果四条被字重
#: 字号吃掉，卡片粘连连一条都没剩下。
WHOLE_PAGE_QUOTA = 3
BAND_QUOTA = 3
#: 局部裁片放大倍数：1px 描边在 0.56× 的整页图里小于一个像素，2× 才看得见。
CROP_ZOOM = 2
#: 候选裁片最多几张，以及每张裁片向外留多少上下文。
CROP_LIMIT = 5
#: 同色容器互相压住多少比例，才提名为"缝隙"候选。
GAP_MIN_OVERLAP = 0.02
#: 相邻容器之间的缺口到这么近才算"该有缝却没有"。
GAP_MAX_PX = 24
#: 内圈 1px 与填充色的差达到这个值，算看得见的边；四边里三边一致即可。
EDGE_RIM_MIN_DELTA = 8
EDGE_RIM_MAX_SPREAD = 16
CROP_PAD = 12
#: 目标端修复时把文字抬到这一层：比页面上任何内容都高。
TARGET_TEXT_Z = 9999


@dataclass
class ProbeCandidate:
    """一处"几何上可疑"的地方，由确定性探针提出、交给模型确认。"""

    kind: str
    ref: str
    box: list[int]
    note: str = ""


@dataclass
class DesignTicket:
    """一条"设计上不对"的意见，用能落地的东西表达。"""

    type: str
    ref: str = ""
    text: str = ""
    roi_bbox: list[int] = field(default_factory=list)
    dx: float = 0.0
    dy: float = 0.0
    fix: str = ""
    note: str = ""
    #: 模型回答的第几个候选（1 起）。真机回环靠它绑定，不靠 note 里的中文序号。
    candidate: int = 0

    def validate(self) -> None:
        if self.type not in DESIGN_TICKETS:
            raise ValueError(f"unknown design ticket: {self.type}")
        if self.type == "MISSING_TEXT_BLOCK" and len(self.roi_bbox) != 4:
            raise ValueError("MISSING_TEXT_BLOCK needs roi_bbox")
        if self.type in ("TEXT_COLLISION_OR_DRIFT", "TYPOGRAPHY_HIERARCHY", "BORDER_OR_SEPARATION") and not self.ref:
            raise ValueError(f"{self.type} needs ref")
        if self.type == "BORDER_OR_SEPARATION" and not self.fix:
            raise ValueError("BORDER_OR_SEPARATION needs a fix")
        if self.fix and self.fix not in BORDER_FIXES and self.type == "BORDER_OR_SEPARATION":
            raise ValueError(f"unknown border fix: {self.fix}")


@dataclass
class DesignFile:
    key: str
    tickets: list[DesignTicket] = field(default_factory=list)
    schema_version: str = "image-design-tickets/1.0"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "key": self.key,
            "tickets": [asdict(ticket) for ticket in self.tickets],
        }

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path, key: str) -> "DesignFile":
        if not path.is_file():
            return cls(key=key)
        data = json.loads(path.read_text(encoding="utf-8"))
        if str(data.get("key")) != key:
            return cls(key=key)
        return cls(key=key, tickets=[DesignTicket(**t) for t in data.get("tickets") or []])


def scene_digest(elements: Sequence[Mapping[str, Any]], limit: int = 48) -> str:
    """当前页面的骨架清单：容器与文字，带 contentRef 和坐标。

    模型需要能"指着"某个节点说话，所以引用必须是稳定 id（contentRef），坐标只
    用来让它对上号。
    """
    containers = []
    texts = []
    for element in elements:
        ref = str(element.get("contentRef") or element.get("id") or "")
        box = [
            int(float(element.get("x") or 0)),
            int(float(element.get("y") or 0)),
            int(float(element.get("width") or 0)),
            int(float(element.get("height") or 0)),
        ]
        if element.get("type") == "container" and not element.get("imageBase64"):
            role = str(element.get("role") or "")
            if role in ("patch", "mark", "text-backdrop"):
                continue
            containers.append({"ref": ref, "role": role, "bbox": box})
        elif element.get("type") == "text" and str(element.get("text") or "").strip():
            style = element.get("style") or {}
            texts.append(
                {
                    "ref": ref,
                    "bbox": box,
                    "text": str(element.get("text"))[:20],
                    "size": style.get("fontSize"),
                    "weight": style.get("fontWeightValue") or style.get("fontWeight"),
                }
            )
    containers.sort(key=lambda item: -(item["bbox"][2] * item["bbox"][3]))
    texts.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return json.dumps(
        {"containers": containers[:limit], "texts": texts[:limit]},
        ensure_ascii=False,
    )


def macro_panels(truth, drawn, bands: int = 3) -> list[Any]:
    """整页 + 上/中/下三段，左右并排，干净无标注。

    整页缩到 ``MACRO_WIDTH`` 是为了让模型看清排版关系；三段按 1:1 给，是因为
    标题、价格这类"层级感"的判断需要原尺寸的字。
    """
    import numpy as np

    height, width = truth.shape[:2]
    rows = []
    for index in range(bands):
        top = height * index // bands
        bottom = height * (index + 1) // bands
        gap = np.full((bottom - top, 10, 3), 255, dtype=np.uint8)
        rows.append(
            np.concatenate(
                [truth[top:bottom].astype(np.uint8), gap, drawn[top:bottom].astype(np.uint8)],
                axis=1,
            )
        )
    scale = min(1.0, MACRO_WIDTH / max(1, width))
    if scale < 1.0:
        whole = []
        for image in (truth, drawn):
            small = _resize(image, scale)
            whole.append(small)
        gap = np.full((whole[0].shape[0], 10, 3), 255, dtype=np.uint8)
        rows.insert(0, np.concatenate([whole[0], gap, whole[1]], axis=1))
    return rows


def _resize(image, scale: float):
    import numpy as np
    from PIL import Image

    height, width = image.shape[:2]
    size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    resized = Image.fromarray(image.astype(np.uint8)).resize(size, Image.LANCZOS)
    return np.asarray(resized)


def _edge_rim(image, box: Sequence[int], fill: str) -> str:
    """A visible 1-2px rim that `detect_border` refuses, read from the inside.

    `detect_border` wants four sides to agree on one colour and to be clearly
    different from the page.  A card whose border sits on a shadow, or whose
    stroke is blended with a gradient, fails that test while the eye still sees
    an edge.  This reads the innermost pixel row/column of each side against the
    fill: three agreeing sides are enough.
    """
    import numpy as np

    from src.app.services.structure.fidelity.pixel_probe import hex_to_rgb

    x, y, w, h = (int(value) for value in box)
    height, width = image.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return ""
    crop = np.asarray(image[y0:y1, x0:x1], dtype=np.int16)
    base = np.asarray(hex_to_rgb(fill), dtype=np.int16)
    sides = {
        "top": crop[0:1, 2:-2].reshape(-1, 3),
        "bottom": crop[-1:, 2:-2].reshape(-1, 3),
        "left": crop[2:-2, 0:1].reshape(-1, 3),
        "right": crop[2:-2, -1:].reshape(-1, 3),
    }
    colours = []
    for sample in sides.values():
        if sample.size == 0:
            continue
        median = np.median(sample, axis=0)
        if int(np.abs(median - base).max()) < EDGE_RIM_MIN_DELTA:
            continue
        colours.append(median)
    if len(colours) < 3:
        return ""
    stack = np.stack(colours)
    if int(np.abs(stack.max(axis=0) - stack.min(axis=0)).max()) > EDGE_RIM_MAX_SPREAD:
        return ""
    colour = np.median(stack, axis=0)
    return "#{:02x}{:02x}{:02x}".format(*(int(value) for value in colour))


def _rect(element: Mapping[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(float(element.get("x") or 0)),
        int(float(element.get("y") or 0)),
        int(float(element.get("width") or 0)),
        int(float(element.get("height") or 0)),
    )


def _share(inner: Sequence[int], outer: Sequence[int]) -> float:
    """Share of ``inner`` covered by ``outer``."""
    width = min(inner[0] + inner[2], outer[0] + outer[2]) - max(inner[0], outer[0])
    height = min(inner[1] + inner[3], outer[1] + outer[3]) - max(inner[1], outer[1])
    if width <= 0 or height <= 0:
        return 0.0
    return (width * height) / max(1, inner[2] * inner[3])


def probe_candidates(
    elements: Sequence[Mapping[str, Any]],
    truth,
    background: str,
    *,
    limit: int = CROP_LIMIT,
) -> list[ProbeCandidate]:
    """Deterministic suspects for the two-stage judge.

    The whole-page view is the wrong instrument for a 1px stroke: at 0.56× a
    hairline is half a pixel, and the model — any model — reads it as noise.  So
    the pixels nominate, and the model only confirms: same-colour surfaces that
    overlap, a border the picture draws and the design does not, and a control
    painted on top of its own label.

    Every candidate is a *question*, never a ticket.  A false nomination costs
    one crop in the prompt; a false ticket costs a wrong edit on the page.
    """
    from src.app.services.structure.fidelity import pixel_probe

    height, width = truth.shape[:2]
    canvas = max(1, width * height)
    # 卡片吸附之后，卡自己已经不画底色了（真盒由它下面那张 paint 面板负责）。
    # 探针要问的是"这张盒子的**画**在哪、是什么颜色"，所以透明容器一律换成它的
    # 面板：否则每张卡都在第一行 continue 掉，候选永远是 0。
    panels = {
        str(element.get("id") or "")[len("paint:") :]: element
        for element in elements
        if str(element.get("id") or "").startswith("paint:")
    }
    surfaces: list[tuple[str, tuple[int, int, int, int], str, Mapping[str, Any]]] = []
    for element in elements:
        if element.get("type") != "container":
            continue
        if str(element.get("role") or "") not in (
            "card",
            "panel",
            "header",
            "sidebar",
            "main-content",
        ):
            continue
        style = element.get("style") or {}
        fill = str(style.get("fillColor") or "")
        box = _rect(element)
        painted = panels.get(str(element.get("id") or ""))
        if fill in ("", "transparent", "none") and painted is not None:
            box = _rect(painted)
            fill = str((painted.get("style") or {}).get("fillColor") or "")
        if not fill or fill in ("", "transparent", "none"):
            continue
        if box[2] * box[3] < canvas * 0.01:
            continue
        surfaces.append(
            (str(element.get("contentRef") or element.get("id") or ""), box, fill.lower(), element)
        )
    candidates: list[ProbeCandidate] = []
    for ref, box, fill, element in surfaces:
        style = element.get("style") or {}
        painted = panels.get(str(element.get("id") or ""))
        border_width = int(style.get("borderWidth") or 0) or int(
            ((painted or {}).get("style") or {}).get("borderWidth") or 0
        )
        if border_width:
            continue
        found = pixel_probe.detect_border(truth, box, fill)
        method = "border"
        if not found:
            rim = _edge_rim(truth, box, fill)
            if not rim:
                continue
            found = {"color": rim, "width": 1}
            method = "rim"
        candidates.append(
            ProbeCandidate(
                kind="border",
                ref=ref,
                box=list(box),
                note=(
                    f"原图有 {found['color']} 的 {found['width']}px 轮廓，方案里没有"
                    if method == "border"
                    else f"原图内圈有一圈 {found['color']} 的边（底差），方案里没有"
                ),
            )
        )
    # 同色互叠：两张卡共用一种填充，盒又压在一起，看上去就是一块。
    for index, (ref_a, a, fa, _first) in enumerate(surfaces):
        for ref_b, b, fb, _second in surfaces[index + 1 :]:
            if fa != fb:
                continue
            # 任意方向压住对方 2% 就足够可疑：marketplace 那两张卡只互叠
            # 61/1243（4.9%），阈值定 25% 就永远看不见它们。
            overlap = max(_share(a, b), _share(b, a))
            if overlap >= GAP_MIN_OVERLAP:
                box = [
                    max(a[0], b[0]),
                    max(a[1], b[1]),
                    min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]),
                    min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]),
                ]
                if box[2] < 8 or box[3] < 8:
                    continue
                candidates.append(
                    ProbeCandidate(
                        kind="gap",
                        ref=ref_a,
                        box=box,
                        note=f"与 {ref_b} 同色互叠 {box[2]}x{box[3]}",
                    )
                )
                continue
            # 不重叠也可能缺缝：两块同色容器紧挨着，而原图在这条缝里是页色。
            # 这正是"底色差 + 间距缺口"那类边界，1px 描边探针看不见它。
            horizontal = abs((a[0] + a[2]) - b[0]) if a[0] <= b[0] else abs((b[0] + b[2]) - a[0])
            vertical = abs((a[1] + a[3]) - b[1]) if a[1] <= b[1] else abs((b[1] + b[3]) - a[1])
            if min(horizontal, vertical) > GAP_MAX_PX:
                continue
            if not pixel_probe.separated_by_page(truth, background, a, b, min_width=2):
                continue
            if horizontal <= vertical:
                low = a[0] + a[2] if a[0] <= b[0] else b[0] + b[2]
                box = [int(low), max(a[1], b[1]), max(2, int(min(horizontal, GAP_MAX_PX))),
                       min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])]
            else:
                low = a[1] + a[3] if a[1] <= b[1] else b[1] + b[3]
                box = [max(a[0], b[0]), int(low), min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]),
                       max(2, int(min(vertical, GAP_MAX_PX)))]
            if box[2] < 2 or box[3] < 2:
                continue
            candidates.append(
                ProbeCandidate(
                    kind="gap",
                    ref=ref_a,
                    box=box,
                    note=f"与 {ref_b} 同色相邻，原图这条缝是页色",
                )
            )
    # 控件压字：画在文字之后、又没有 OCR 支撑的按钮/输入框。
    for order, element in enumerate(elements):
        if element.get("type") not in ("button", "input"):
            continue
        box = _rect(element)
        for other_order, other in enumerate(elements):
            if other_order >= order or other.get("type") != "text":
                continue
            if not str(other.get("text") or "").strip():
                continue
            if _share(_rect(other), box) >= 0.6:
                candidates.append(
                    ProbeCandidate(
                        kind="occlusion",
                        ref=str(element.get("contentRef") or element.get("id") or ""),
                        box=list(box),
                        note=f"控件画在「{str(other.get('text'))[:8]}」之上",
                    )
                )
                break
    candidates.sort(key=lambda item: item.box[2] * item.box[3], reverse=True)
    seen: set[tuple[str, str]] = set()
    unique: list[ProbeCandidate] = []
    for candidate in candidates:
        key = (candidate.kind, candidate.ref)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
        if len(unique) >= limit:
            break
    return unique


def candidate_panels(truth, drawn, candidates: Sequence[ProbeCandidate], zoom: int = CROP_ZOOM):
    """One 2× side-by-side strip per candidate, in the order they are numbered."""
    import numpy as np

    height, width = truth.shape[:2]
    panels = []
    for candidate in candidates:
        x, y, w, h = candidate.box
        x0 = max(0, x - CROP_PAD)
        y0 = max(0, y - CROP_PAD)
        x1 = min(width, x + w + CROP_PAD)
        y1 = min(height, y + h + CROP_PAD)
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        left = _resize(truth[y0:y1, x0:x1], zoom)
        right = _resize(drawn[y0:y1, x0:x1], zoom)
        gap = np.full((left.shape[0], 10, 3), 255, dtype=np.uint8)
        panels.append(np.concatenate([left, gap, right], axis=1))
    return panels


def probe_target_candidates(
    elements: Sequence[Mapping[str, Any]],
    truth,
    target,
    background: str,
    *,
    limit: int = CROP_LIMIT,
) -> list[ProbeCandidate]:
    """Differences that exist **only** in the export.

    A whole-page judge that compares the SVG to the picture can never see these:
    the words are in the design, the stroke is in the design, and the target
    renderer is what loses them.  So the second stage compares the picture to the
    *export* and nominates exactly two kinds — a label whose ink is gone, and a
    hairline the export did not draw.
    """
    import numpy as np

    from src.app.services.structure.fidelity import pixel_probe

    height, width = truth.shape[:2]
    candidates: list[ProbeCandidate] = []

    def ink_share(image, box) -> float:
        x, y, w, h = box
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + w), min(height, y + h)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return 0.0
        crop = np.asarray(image[y0:y1, x0:x1], dtype=np.int16)
        surface = np.median(
            np.concatenate([crop[:1].reshape(-1, 3), crop[-1:].reshape(-1, 3)]), axis=0
        )
        return float((np.abs(crop - surface).max(axis=2) >= 40).mean())

    for element in elements:
        if element.get("type") != "text" or not str(element.get("text") or "").strip():
            continue
        if element.get("rotation"):
            continue
        box = _rect(element)
        if box[2] < 8 or box[3] < 8:
            continue
        before = ink_share(truth, box)
        after = ink_share(target, box)
        if before < 0.02 or after >= before * 0.4:
            continue
        candidates.append(
            ProbeCandidate(
                kind="target-text",
                ref=str(element.get("contentRef") or element.get("id") or ""),
                box=list(box),
                note=f"原图有字（墨迹 {before:.0%}），导出图只剩 {after:.0%}",
            )
        )
    for element in elements:
        if element.get("type") != "container":
            continue
        style = element.get("style") or {}
        fill = str(style.get("fillColor") or "")
        if not fill or fill in ("transparent", "none"):
            continue
        box = _rect(element)
        if box[2] < 24 or box[3] < 16:
            continue
        if not pixel_probe.detect_border(truth, box, fill):
            continue
        if pixel_probe.detect_border(target, box, fill):
            continue
        candidates.append(
            ProbeCandidate(
                kind="target-border",
                ref=str(element.get("contentRef") or element.get("id") or ""),
                box=list(box),
                note="原图有 1px 轮廓，导出图没有",
            )
        )
    candidates.sort(key=lambda item: item.box[2] * item.box[3], reverse=True)
    return candidates[:limit]


def execute_target(
    ticket: DesignTicket,
    elements: list[dict[str, Any]],
    truth,
) -> dict[str, Any] | None:
    """One round of repair for a target-only difference, and nothing clever.

    Only two operations are allowed: lift the label above what covers it, and
    draw the hairline the export dropped.  Both are paint-order or style, so no
    member moves and no frame is re-vetted.
    """
    from src.app.services.structure.fidelity import pixel_probe

    element = _by_ref(elements, ticket.ref)
    if element is None:
        return None
    box = _rect(element)
    if ticket.type == "BORDER_OR_SEPARATION" or element.get("type") == "container":
        fill = str((element.get("style") or {}).get("fillColor") or "")
        found = pixel_probe.detect_border(truth, box, fill) if fill else None
        if not found:
            return None
        style = element.setdefault("style", {})
        style["borderColor"] = found["color"]
        style["borderWidth"] = max(1, int(found["width"]))
        return {"ref": ticket.ref, "action": "border"}
    # 文字：抬到最上面，并把颜色校准成原图墨色。
    element["zIndex"] = TARGET_TEXT_Z
    style = element.setdefault("style", {})
    style["textColor"] = _ink_colour(truth, box) or style.get("textColor")
    return {"ref": ticket.ref, "action": "lifted"}


def _ink_colour(truth, box: tuple[int, int, int, int]) -> str:
    import numpy as np

    x, y, w, h = box
    height, width = truth.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return ""
    crop = np.asarray(truth[y0:y1, x0:x1], dtype=np.int16)
    surface = np.median(
        np.concatenate([crop[:1].reshape(-1, 3), crop[-1:].reshape(-1, 3)]), axis=0
    )
    ink = np.abs(crop - surface).max(axis=2) >= 40
    if not ink.any():
        return ""
    colour = np.median(crop[ink], axis=0)
    return "#{:02x}{:02x}{:02x}".format(*(int(value) for value in colour))


def target_prompt(candidates: Sequence[ProbeCandidate]) -> str:
    """Second-stage prompt: original vs the real Figma export, 2× crops only."""
    return (
        f"图 1..{len(candidates)} 是**原图**与**真机 Figma 导出图**的 2× 局部对照"
        "（每张左半是原图，右半是导出图）。这些差异只在导出端出现——"
        "设计文件里字和线都在，是目标端把它们吞掉了。\n"
        f"候选清单：\n{candidate_digest(candidates)}\n"
        "逐条判断候选是否成立，只输出 JSON：\n"
        '{"tickets":[\n'
        '{"type":"TEXT_COLLISION_OR_DRIFT","candidate":1,"ref":"<文字的 contentRef>",'
        '"fix":"nudge","dx":0,"dy":0,"note":"导出图把这段字吞了/盖住了"},\n'
        '{"type":"BORDER_OR_SEPARATION","candidate":2,"ref":"<容器的 contentRef>",'
        '"fix":"border","note":"导出图没画这圈 1px 轮廓"}\n'
        "]}\n"
        "candidate 填这张图是候选清单里的第几个（1 起），ref 可留空由它绑定；"
        "不成立就不要报；ref 若填，必须从下面这几个字符串里原样挑一个，"
        "不要写 None、不要写 null、不要自己编：\n"
        + "\n".join(f"- {candidate.ref}" for candidate in candidates)
        + f"\n最多 {BAND_QUOTA} 条。"
    )


def candidate_digest(candidates: Sequence[ProbeCandidate]) -> str:
    lines = []
    for index, candidate in enumerate(candidates, start=1):
        lines.append(
            f"{index}. [{candidate.kind}] ref={candidate.ref} bbox={candidate.box} {candidate.note}"
        )
def design_prompt(digest: str, candidates: Sequence[ProbeCandidate] = ()) -> str:
    """The one prompt.  Whole page for layout, 2x crops for hairlines.

    图 1 是整页，图 2/3/4 是三段，图 5 起是探针挑出来的局部 2× 对照。分开给是
    因为两种判断需要两种尺度：排版关系要退后看，1px 描边要贴着看。整页图缩到
    1440 宽以后，1px 只剩 0.57px，任何模型都只能当噪声。
    """
    scenes = (
        "图 1 是整页对比（左原图、右当前渲染），图 2/3/4 分别是上/中/下三段。"
    )
    if candidates:
        scenes += (
            f"图 5 起是 {len(candidates)} 张**局部 2× 放大**对照（左原图、右渲染），"
            "顺序对应下面的候选清单。\n"
            f"候选清单（确定性探针提出，只等你确认，不是结论）：\n{candidate_digest(candidates)}\n"
        )
    return (
        scenes
        + "判断标准是**设计神似**，不是逐像素相等：排版、间距、容器完整、图标、字重字号层级、"
        "整体风格要还原。允许字形有细微差别，但下面七类观感问题必须指出：\n"
        "1 漏掉明显的文字块或副标题；2 文字明显偏移或互相重叠（A 压 B、同文双影）；"
        "3 图标/Logo/印章不完整；4 悬浮小窗结构或零件残缺；"
        "5 标题/价格/导航的字重字号层级不对；6 容器大小异常或同层互相挤占越界；"
        "7 **相邻同色容器之间没有可见边界**——两张卡同色相接、看起来是一块，"
        "或卡片/胶囊缺了那一圈 1px 轮廓、缺了该有的间距。\n"
        f"当前页面骨架（容器的 ref/bbox，文字的 ref/bbox/内容/字号/字重）：\n{digest}\n"
        "只输出 JSON，不要解释：\n"
        '{"tickets":[\n'
        '{"type":"BORDER_OR_SEPARATION","ref":"<容器的 contentRef>","fix":"border|gap|inset",'
        '"note":"第几个候选；边界缺什么"},\n'
        '{"type":"MISSING_TEXT_BLOCK","roi_bbox":[x,y,w,h],"text":"应该出现的文字","note":"依据"},\n'
        '{"type":"TEXT_COLLISION_OR_DRIFT","ref":"<文字的 contentRef>","fix":"remove|nudge","dx":0,"dy":0,"note":"..."},\n'
        '{"type":"INCOMPLETE_GRAPHIC_OR_WIDGET","roi_bbox":[x,y,w,h],"fix":"pill|border","note":"..."},\n'
        '{"type":"TYPOGRAPHY_HIERARCHY","ref":"<文字的 contentRef>","fix":"bold|bigger|both","note":"..."},\n'
        '{"type":"CONTAINER_CROWDING","ref":"<容器的 contentRef>","fix":"clamp","note":"..."}\n'
        "]}\n"
        f"配额：整页最多 {WHOLE_PAGE_QUOTA} 条，上/中/下每一段最多 {BAND_QUOTA} 条；"
        "同一个节点只能派一种工单（说它缺字就不要再同时说它压字）。"
        "坐标用原图像素，ref 必须来自上面的清单；有候选时优先回答候选，"
        "候选都不成立就只报整页的排版问题。"
    )


def parse_design_tickets(payload: Mapping[str, Any]) -> list[DesignTicket]:
    tickets: list[DesignTicket] = []
    limit = WHOLE_PAGE_QUOTA + BAND_QUOTA * 3
    for raw in (payload.get("tickets") or [])[:limit]:
        try:
            ticket = DesignTicket(
                type=str(raw.get("type") or ""),
                ref=str(raw.get("ref") or ""),
                text=str(raw.get("text") or ""),
                roi_bbox=[int(value) for value in raw.get("roi_bbox") or []],
                dx=float(raw.get("dx") or 0.0),
                dy=float(raw.get("dy") or 0.0),
                fix=str(raw.get("fix") or ""),
                note=str(raw.get("note") or ""),
                candidate=int(raw.get("candidate") or raw.get("candidate_id") or 0),
            )
            ticket.validate()
        except (TypeError, ValueError):
            continue
        tickets.append(ticket)
    return tickets


#: 同节点互斥时的优先级：越靠前越可信。MISSING_TEXT_BLOCK 最弱——它是对"这一带
#: 看不见字"的解释，而碰撞/边界是对"这一带怎么错了"的直接观察。
TICKET_PRIORITY = {
    "BORDER_OR_SEPARATION": 0,
    "TEXT_COLLISION_OR_DRIFT": 1,
    "TYPOGRAPHY_HIERARCHY": 2,
    "INCOMPLETE_GRAPHIC_OR_WIDGET": 3,
    "CONTAINER_CROWDING": 4,
    "MISSING_TEXT_BLOCK": 5,
}


def _ticket_box(ticket: DesignTicket, elements: Sequence[Mapping[str, Any]]):
    if len(ticket.roi_bbox) == 4:
        return list(ticket.roi_bbox)
    element = _by_ref(elements, ticket.ref)
    if element is None:
        return None
    return list(_rect(element))


def cap_design_tickets(
    tickets: Sequence[DesignTicket],
    elements: Sequence[Mapping[str, Any]],
    canvas: tuple[int, int],
    *,
    whole: int = WHOLE_PAGE_QUOTA,
    per_band: int = BAND_QUOTA,
) -> list[DesignTicket]:
    """One ticket per node, and a budget per band.

    The quota used to be "six for the page", which the typography tickets ate:
    of six live tickets for marketplace, two were "this should be bold" and the
    merged cards never got one.  Three for the page plus three per band keeps a
    structural finding from being crowded out by a font weight.
    """
    by_node: dict[str, DesignTicket] = {}
    loose: list[DesignTicket] = []
    for ticket in tickets:
        node = ticket.ref or (ticket.text.strip() if ticket.type == "MISSING_TEXT_BLOCK" else "")
        if not node:
            loose.append(ticket)
            continue
        current = by_node.get(node)
        if current is None or TICKET_PRIORITY.get(ticket.type, 9) < TICKET_PRIORITY.get(
            current.type, 9
        ):
            by_node[node] = ticket
    ordered = sorted(
        by_node.values(), key=lambda item: TICKET_PRIORITY.get(item.type, 9)
    ) + loose
    height = max(1, int(canvas[1]))
    used_whole = 0
    used_band = [0, 0, 0]
    kept: list[DesignTicket] = []
    for ticket in ordered:
        box = _ticket_box(ticket, elements)
        if box is None or box[3] >= height * 0.5:
            if used_whole >= whole:
                continue
            used_whole += 1
            kept.append(ticket)
            continue
        band = min(2, max(0, int((box[1] + box[3] / 2) * 3 // height)))
        if used_band[band] >= per_band:
            continue
        used_band[band] += 1
        kept.append(ticket)
    return kept


def _by_ref(elements: Sequence[dict[str, Any]], ref: str) -> dict[str, Any] | None:
    for element in elements:
        if ref and ref in (str(element.get("contentRef") or ""), str(element.get("id") or "")):
            return element
    return None


def count_collisions(elements: Sequence[Mapping[str, Any]]) -> int:
    """Two text nodes covering the same place: the A-presses-B the user can see."""
    texts = [
        (int(e.get("x") or 0), int(e.get("y") or 0), int(e.get("width") or 0), int(e.get("height") or 0))
        for e in elements
        if e.get("type") == "text" and str(e.get("text") or "").strip()
    ]
    clashes = 0
    for index, first in enumerate(texts):
        for second in texts[index + 1 :]:
            overlap_w = min(first[0] + first[2], second[0] + second[2]) - max(first[0], second[0])
            overlap_h = min(first[1] + first[3], second[1] + second[3]) - max(first[1], second[1])
            if overlap_w <= 0 or overlap_h <= 0:
                continue
            smaller = min(max(1, first[2] * first[3]), max(1, second[2] * second[3]))
            if (overlap_w * overlap_h) / smaller > COLLISION_SHARE:
                clashes += 1
    return clashes


def execute_design(
    ticket: DesignTicket,
    elements: list[dict[str, Any]],
    truth,
    canvas: tuple[int, int],
) -> dict[str, Any] | None:
    """把一条"设计意见"落成确定性操作。做不到就返回 None，不猜。"""
    import numpy as np

    if ticket.type == "MISSING_TEXT_BLOCK":
        return _design_missing_text(ticket, elements, truth)
    if ticket.type in ("TEXT_COLLISION_OR_DRIFT", "TYPOGRAPHY_HIERARCHY", "CONTAINER_CROWDING"):
        element = _by_ref(elements, ticket.ref)
        if element is None:
            return None
        if ticket.type == "TEXT_COLLISION_OR_DRIFT":
            if ticket.fix == "remove":
                elements.remove(element)
                return {"ref": ticket.ref, "action": "removed"}
            element["x"] = round(float(element.get("x") or 0) + ticket.dx, 1)
            element["y"] = round(float(element.get("y") or 0) + ticket.dy, 1)
            return {"ref": ticket.ref, "action": f"nudged {ticket.dx:+.0f},{ticket.dy:+.0f}"}
        if ticket.type == "TYPOGRAPHY_HIERARCHY":
            style = element.setdefault("style", {})
            current = int(style.get("fontWeightValue") or 400)
            if ticket.fix in ("bold", "both"):
                style["fontWeightValue"] = 800 if current >= 700 else 700
                style["fontWeight"] = "bold"
            if ticket.fix in ("bigger", "both"):
                size = float(style.get("fontSize") or 14)
                style["fontSize"] = round(size * 1.15 * 2) / 2
            return {"ref": ticket.ref, "action": ticket.fix}
        # CONTAINER_CROWDING: keep it on the canvas; nothing clever.
        x, y = float(element.get("x") or 0), float(element.get("y") or 0)
        w, h = float(element.get("width") or 0), float(element.get("height") or 0)
        new_x = max(0.0, min(x, canvas[0] - w))
        new_y = max(0.0, min(y, canvas[1] - h))
        element["x"], element["y"] = round(new_x, 1), round(new_y, 1)
        return {"ref": ticket.ref, "action": "clamped"}
    if ticket.type == "INCOMPLETE_GRAPHIC_OR_WIDGET":
        return _design_widget(ticket, elements, truth)
    if ticket.type == "BORDER_OR_SEPARATION":
        return _design_border(ticket, elements, truth, canvas)
    return None


def _median_fill(truth, box: tuple[int, int, int, int]) -> str:
    """The colour inside a box, ignoring its 2px rim."""
    import numpy as np

    x, y, w, h = box
    height, width = truth.shape[:2]
    x0, y0 = max(0, x + 2), max(0, y + 2)
    x1, y1 = min(width, x + w - 2), min(height, y + h - 2)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return ""
    crop = truth[y0:y1, x0:x1]
    colour = np.median(crop.reshape(-1, 3), axis=0)
    return "#{:02x}{:02x}{:02x}".format(*(int(value) for value in colour))


def _design_border(
    ticket: DesignTicket,
    elements: list[dict[str, Any]],
    truth,
    canvas: tuple[int, int],
) -> dict[str, Any] | None:
    """Give a surface the edge the picture draws around it.

    A border is a *style*, not a new node: it paints inside the box the element
    already owns, so no member moves and no frame is re-vetted.  `gap` and
    `inset` land on the same operation on purpose — two same-colour cards are
    separated by drawing the hairline each of them has in the picture, and
    Figma's `inset` stroke is the same 1px ring drawn inside the bounds.
    """
    from src.app.services.structure.fidelity import pixel_probe

    element = _by_ref(elements, ticket.ref)
    if element is None:
        return None
    box = _rect(element)
    style = element.setdefault("style", {})
    fill = str(style.get("fillColor") or "")
    # 卡片吸附之后，卡本身是透明的，真正的盒子与底色在它下面那张 paint 面板上。
    panel = None
    for other in elements:
        if str(other.get("id") or "") == f"paint:{element.get('id')}":
            panel = other
            break
    if panel is not None:
        box = _rect(panel)
        panel_style = panel.get("style") or {}
        fill = str(panel_style.get("fillColor") or fill)
        if int(panel_style.get("borderWidth") or 0):
            # 这条工单要的东西已经在画面上了（吸附阶段补过），不用再画一遍。
            return {"ref": ticket.ref, "action": "already-bordered"}
    if box[2] < 8 or box[3] < 8:
        return None
    if fill in ("", "transparent", "none"):
        fill = _median_fill(truth, box)
    if not fill:
        return None
    if int(style.get("borderWidth") or 0):
        return {"ref": ticket.ref, "action": "already-bordered"}
    found = pixel_probe.detect_border(truth, box, fill)
    if not found:
        # 没有独立 1px 描边，但有"底差边"：卡片压在阴影上、或描边被渐变压掉时
        # 就是这种情形。规则要求支持底差与间距缺口，这里补上底差这一半。
        rim = _edge_rim(truth, box, fill)
        if not rim:
            return None
        found = {"color": rim, "width": 1}
    style["borderColor"] = found["color"]
    style["borderWidth"] = max(1, int(found["width"]))
    radius = pixel_probe.estimate_corner_radius(truth, box, fill=fill)
    if radius:
        style["borderRadius"] = int(radius)
    if ticket.fix == "inset":
        style["borderStyle"] = "inset"
    siblings = []
    for other in elements:
        if other is element or other.get("type") != "container":
            continue
        other_fill = str((other.get("style") or {}).get("fillColor") or "")
        if other_fill.lower() != fill.lower():
            continue
        if _share(_rect(other), box) > 0.05:
            siblings.append(str(other.get("id") or ""))
    element.setdefault("designEvidence", {})["borderRepair"] = {
        "ticket": ticket.fix,
        "colour": found["color"],
        "siblings": siblings[:4],
    }
    return {
        "ref": ticket.ref,
        "action": f"border {found['color']} {found['width']}px",
        "separated": siblings[:4],
    }


#: 不透明块盖住目标这么多，才算"被埋了"。
OCCLUSION_COVER = 0.5


def paint_ranks(elements: Sequence[dict[str, Any]]) -> dict[int, int]:
    """Flat paint rank per element, by the renderer's own ordering rule."""
    from src.app.services.rendering.adapter_base import paint_order

    return {index: rank for rank, (index, _item) in enumerate(paint_order(elements))}


def _cover_share(outer: Sequence[float], inner: Sequence[float]) -> float:
    width = min(outer[0] + outer[2], inner[0] + inner[2]) - max(outer[0], inner[0])
    height = min(outer[1] + outer[3], inner[1] + inner[3]) - max(outer[1], inner[1])
    if width <= 0 or height <= 0:
        return 0.0
    return (width * height) / max(1.0, inner[2] * inner[3])


def _is_opaque(element: Mapping[str, Any]) -> bool:
    if element.get("imageBase64"):
        return True
    style = element.get("style") or {}
    fill = str(style.get("fillColor") or "")
    if element.get("transparent") or fill.lower() in ("", "transparent", "none"):
        return False
    return True


def occluders_above(
    elements: Sequence[dict[str, Any]],
    box: Sequence[float],
    host: dict[str, Any] | None = None,
    share: float = OCCLUSION_COVER,
) -> list[dict[str, Any]]:
    """Opaque nodes painted after this box that cover half of it or more.

    This is the question the arbiter was missing.  "Is there a node at these
    coordinates" answered yes, and the ticket was closed as a false positive —
    while the words were sitting under a duplicated panel or a pixel patch.
    """
    ranks = paint_ranks(list(elements))
    text_rank = None
    if host is not None:
        for index, element in enumerate(elements):
            if element is host:
                text_rank = ranks.get(index)
                break
    if text_rank is None:
        for index, element in enumerate(elements):
            rect = _rect(element)
            if [int(value) for value in rect] == [int(value) for value in box]:
                text_rank = ranks.get(index)
                break
    found: list[dict[str, Any]] = []
    for index, element in enumerate(elements):
        if str(element.get("type") or "") == "text" or not _is_opaque(element):
            continue
        rect = _rect(element)
        if _cover_share(rect, box) < share:
            continue
        rank = ranks.get(index, 0)
        if text_rank is not None and rank <= text_rank:
            continue
        found.append(
            {
                "index": index,
                "element": element,
                "ref": str(element.get("contentRef") or element.get("id") or ""),
                "z": int(element.get("zIndex") or 0),
                "rank": rank,
                "cover": round(_cover_share(rect, box), 3),
            }
        )
    found.sort(key=lambda item: item["cover"], reverse=True)
    return found


def _drop_element(elements: list[dict[str, Any]], target: dict[str, Any]) -> None:
    """Remove one element, and its id from any frame that lists it."""
    target_id = str(target.get("id") or "")
    elements[:] = [element for element in elements if element is not target]
    if not target_id:
        return
    for element in elements:
        children = element.get("layoutChildren")
        if not children:
            continue
        kept = [
            child
            for child in children
            if not (isinstance(child, dict) and str(child.get("id") or "") == target_id)
        ]
        if len(kept) != len(children):
            element["layoutChildren"] = kept


def _duplicate_background(
    elements: Sequence[dict[str, Any]],
    entry: Mapping[str, Any],
    ranks: Mapping[int, int],
) -> bool:
    """A panel that paints the same area twice — safe to delete, not to demote.

    Demoting a duplicate panel just moves the double paint one layer down.  It
    only counts as duplicate when another container with the same fill covers
    it almost completely and paints below it: that is a second copy, not a
    legitimate overlay.
    """
    element = entry["element"]
    role = str(element.get("role") or "")
    if role in ("page", "page-ground", "page-background"):
        return True
    style = element.get("style") or {}
    fill = str(style.get("fillColor") or "").lower()
    if not fill or fill in ("transparent", "none"):
        return False
    own = _rect(element)
    own_rank = ranks.get(int(entry.get("index") or 0))
    for index, other in enumerate(elements):
        if other is element or str(other.get("type") or "") != "container":
            continue
        other_fill = str((other.get("style") or {}).get("fillColor") or "").lower()
        if other_fill != fill:
            continue
        rect = _rect(other)
        if _cover_share(rect, own) < 0.85:
            continue
        rank = ranks.get(index)
        if own_rank is None or rank is None or rank < own_rank:
            return True
    return False


def _uncover_text(
    elements: list[dict[str, Any]],
    host: dict[str, Any],
    box: Sequence[float],
) -> dict[str, Any] | None:
    """Make a buried node visible: drop the duplicate, or lift the words.

    Deleting is only for a genuine second copy of the same background.  Anything
    else — a patch, a real overlay — is left alone and the word is lifted above
    it, because the pixels there are carrying something the vector tree does not
    have.  Ranks are recomputed after every deletion: an index into a list that
    just got shorter is a wrong answer waiting for the next ticket.
    """
    if not occluders_above(elements, box, host):
        return None
    removed: list[str] = []
    for _round in range(3):
        entries = occluders_above(elements, box, host)
        if not entries:
            break
        ranks = paint_ranks(list(elements))
        target = next(
            (
                entry
                for entry in entries
                if _duplicate_background(elements, entry, ranks)
            ),
            None,
        )
        if target is None:
            break
        _drop_element(elements, target["element"])
        removed.append(target["ref"])
    if removed:
        host.setdefault("designEvidence", {})["occlusionRepair"] = {
            "action": "removed-duplicate",
            "removed": removed,
        }
        return {
            "ref": str(host.get("contentRef") or host.get("id") or ""),
            "action": "uncovered:removed-duplicate",
            "detail": ",".join(removed),
        }
    entries = occluders_above(elements, box, host)
    if not entries:
        return None
    top = max(entry["z"] for entry in entries)
    word_z = int(host.get("zIndex") or 0)
    if word_z > top:
        return None
    host["zIndex"] = top + 1
    host.setdefault("designEvidence", {})["occlusionRepair"] = {
        "action": "lifted",
        "above": [entry["ref"] for entry in entries],
    }
    return {
        "ref": str(host.get("contentRef") or host.get("id") or ""),
        "action": "uncovered:lifted",
        "detail": ",".join(entry["ref"] for entry in entries),
    }


def _design_missing_text(ticket: DesignTicket, elements: list[dict[str, Any]], truth):
    """Make the words appear where the model says they are missing.

    The first thing to check is that they are not already there.  Three of the
    live tickets were refused for `new-collision` because the node existed and
    was simply invisible or too small — its colour sat within a few channels of
    the surface behind it, or the type had been measured at 8px.  Adding a second
    print of the same words is the one thing a design reviewer would notice
    immediately, so the search comes first and the new node is the fallback.
    """
    import numpy as np

    x, y, w, h = (int(value) for value in ticket.roi_bbox)
    height, width = truth.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 6 or y1 - y0 < 6:
        return None
    crop = truth[y0:y1, x0:x1]
    background = np.median(
        np.concatenate([crop[0:1].reshape(-1, 3), crop[-1:].reshape(-1, 3)]), axis=0
    )
    ink = np.abs(crop - background).max(axis=2) >= 40
    if not ink.any():
        return None
    foreground = np.median(crop[ink], axis=0)
    rows = np.where(ink.any(axis=1))[0]
    columns = np.where(ink.any(axis=0))[0]
    ink_height = float(rows[-1] - rows[0] + 1)
    size = max(8.0, round(ink_height * 0.95 * 2) / 2)
    ink_box = (x0 + int(columns[0]), y0 + int(rows[0]), int(columns[-1] - columns[0] + 1), int(ink_height))

    host = _text_near(elements, ink_box)
    if host is not None:
        # 节点在，但可能被压住了：先解遮挡再谈颜色与字号。这一步以前没有，
        # 于是"被重复面板埋掉的文字"整类工单都被判成误报。
        uncovered = _uncover_text(elements, host, ink_box)
        if uncovered is not None:
            return uncovered
        return _restyle_in_place(host, foreground, size, ticket.text, ink_box)

    digest = hashlib.sha1(
        f"design-text:{x0}:{y0}:{ticket.text}".encode("utf-8")
    ).hexdigest()[:16]
    elements.append(
        {
            "id": f"design-text:{digest}",
            "type": "text",
            "x": x0 + int(columns[0]),
            "y": y0 + int(rows[0]),
            "width": float(columns[-1] - columns[0] + 1),
            "height": ink_height,
            "text": ticket.text,
            "style": {
                "fontSize": size,
                "fontFamily": "Noto Sans SC",
                "textColor": "#{:02x}{:02x}{:02x}".format(*(int(v) for v in foreground)),
                "textAlign": "left",
                "fontWeight": "normal",
                "fontWeightValue": 400,
            },
            "role": "text",
            "name": "Design text",
            "contentRef": f"design-text:{digest}",
            "designEvidence": {"ticket": ticket.type, "note": ticket.note},
        }
    )
    return {"ref": f"design-text:{digest}", "action": "added", "text": ticket.text}


def _text_near(elements: Sequence[dict[str, Any]], box: tuple[int, int, int, int]):
    """The text node that already owns this place, if any.

    Overlap against the *smaller* of the two boxes: a node measured a little wide
    still owns the words, and a node two pixels off still owns them.
    """
    bx, by, bw, bh = box
    best, best_share = None, 0.0
    for element in elements:
        if element.get("type") != "text" or not str(element.get("text") or "").strip():
            continue
        ex, ey = int(element.get("x") or 0), int(element.get("y") or 0)
        ew, eh = int(element.get("width") or 0), int(element.get("height") or 0)
        overlap_w = min(bx + bw, ex + ew) - max(bx, ex)
        overlap_h = min(by + bh, ey + eh) - max(by, ey)
        if overlap_w <= 0 or overlap_h <= 0:
            continue
        smaller = min(max(1, bw * bh), max(1, ew * eh))
        share = (overlap_w * overlap_h) / smaller
        if share > best_share:
            best, best_share = element, share
    return best if best_share >= 0.35 else None


def _restyle_in_place(host, foreground, size: float, expected_text: str, ink_box):
    """Fix the node that was already there: colour, size, and the words."""
    style = host.setdefault("style", {})
    actions = []
    current = str(style.get("textColor") or "")
    wanted = "#{:02x}{:02x}{:02x}".format(*(int(v) for v in foreground))
    if current.lower() != wanted.lower():
        try:
            gap = max(
                abs(int(current[i : i + 2], 16) - int(wanted[i : i + 2], 16))
                for i in (1, 3, 5)
            )
        except (ValueError, IndexError):
            gap = 255
        if gap >= 16:
            style["textColor"] = wanted
            actions.append("recoloured")
    current_size = float(style.get("fontSize") or 0)
    if current_size and size / current_size >= 1.12:
        style["fontSize"] = size
        actions.append("enlarged")
    text = str(host.get("text") or "")
    if not text.strip():
        host["text"] = expected_text
        actions.append("filled")
    elif expected_text and len(expected_text) > len(text) + 3 and expected_text[:2] == text[:2]:
        host["text"] = expected_text
        actions.append("rewritten")
    # 几何一律不动。节点已经在帧里，挪它会把所在帧的绘制连序拆散——AtomGit
    # 就因为一次"顺手对齐"从 13 帧掉到 12。要挪位置是 TEXT_COLLISION_OR_DRIFT
    # 的事，那条工单有自己的门禁。
    host.setdefault("designEvidence", {})["missingTextRepair"] = actions or ["inspected"]
    return {"ref": str(host.get("contentRef") or host.get("id") or ""), "action": "in-place:" + ",".join(actions or ["noop"])}


def _paint_index_for(
    elements: Sequence[Mapping[str, Any]], box: Sequence[int]
) -> int:
    """Where a decoration has to go so it paints over the page but under content.

    A recovered backdrop inserted at index 0 lands *behind* the page fill and is
    never seen; one appended last covers the words it was drawn for.  The slot is
    the first piece of content that overlaps the box, and never before the last
    page-ground element.
    """
    floor = 0
    for index, element in enumerate(elements):
        if str(element.get("role") or "") == "page-ground":
            floor = index + 1
    for index, element in enumerate(elements):
        if index < floor:
            continue
        if element.get("type") not in ("text", "button", "input", "image"):
            continue
        if _share(_rect(element), box) >= 0.3:
            return index
    return len(elements)


def _design_widget(ticket: DesignTicket, elements: list[dict[str, Any]], truth):
    import numpy as np

    x, y, w, h = (int(value) for value in ticket.roi_bbox)
    height, width = truth.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 12 or y1 - y0 < 12:
        return None
    # 这块 ROI 上已经有字了：那缺的只是它下面那块底色，不是这行字。补一块
    # 不透明胶囊只会把字盖掉（ERP 的"生产任务"就是这么被吞的），而帧内元素
    # 的层序不能靠抬 zIndex 解决——所以宁可不要这块胶囊。
    for element in elements:
        if element.get("type") != "text" or not str(element.get("text") or "").strip():
            continue
        if _cover_share(_rect(element), (x0, y0, x1 - x0, y1 - y0)) >= 0.5:
            element.setdefault("designEvidence", {})["widgetSkipped"] = ticket.note or ticket.type
            return None
    crop = truth[y0:y1, x0:x1]
    corners = np.concatenate(
        [
            crop[2:6, 2:6].reshape(-1, 3),
            crop[2:6, -6:-2].reshape(-1, 3),
            crop[-6:-2, 2:6].reshape(-1, 3),
            crop[-6:-2, -6:-2].reshape(-1, 3),
        ]
    )
    fill = np.median(corners, axis=0)
    digest = hashlib.sha1(f"design-widget:{x0}:{y0}:{w}:{h}".encode("utf-8")).hexdigest()[:16]
    style: dict[str, Any] = {
        "fillColor": "#{:02x}{:02x}{:02x}".format(*(int(v) for v in fill)),
        "borderRadius": min(h // 2, 12),
    }
    if ticket.fix == "border":
        style["borderColor"] = "#e6e6e6"
        style["borderWidth"] = 1
    # 底框必须落在"页面底色之上、这块内容之下"。之前插在下标 0，结果被 page-ground
    # 那块整页底色盖住，胶囊等于没画。
    elements.insert(
        _paint_index_for(elements, (x0, y0, x1 - x0, y1 - y0)),
        {
            "id": f"design-widget:{digest}",
            "type": "container",
            "x": x0,
            "y": y0,
            "width": x1 - x0,
            "height": y1 - y0,
            "text": "",
            "style": style,
            "role": "panel",
            "name": "Design widget",
            "contentRef": f"design-widget:{digest}",
            "designEvidence": {"ticket": ticket.type, "note": ticket.note},
        },
    )
    return {"ref": f"design-widget:{digest}", "action": ticket.fix or "pill"}


@dataclass
class DesignGate:
    """设计口径的门禁：结构红线 + 几何防撞，不看像素。"""

    frames: int
    frames_floor: int
    written_equals_accepted: bool
    patch_share: float
    collisions_before: int
    collisions_after: int
    frames_before: int = 0

    @property
    def failures(self) -> list[str]:
        failed = []
        if self.frames < self.frames_floor or (self.frames_before and self.frames < self.frames_before):
            failed.append("frames-lost")
        if not self.written_equals_accepted:
            failed.append("frames-disagree")
        if self.patch_share > PATCH_BUDGET_SHARE * 100:
            failed.append("patch-budget")
        if self.collisions_after > self.collisions_before:
            failed.append("new-collision")
        return failed

    @property
    def passed(self) -> bool:
        return not self.failures
