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
    return "\n".join(lines)
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


# --------------------------------------------------------------------------
# 闭环精修：误差热力图 -> Top-K 工单 -> 定量补丁 -> 单调回滚
#
# 上面所有仲裁都是"一轮、离散动作"：加粗、补边、加一行字。离散动作的好处是
# 不可能把页面改坏，坏处是它表达不了"这一行往左偏了 3px、字号大了 1.5pt"——
# 而那恰好是最后 5% 误差里最常见的一类。
#
# 这一层补上那个缺口，代价是必须先解决一个老问题：模型一旦能改坐标，就能
# 把页面改坏。所以每个补丁落笔后立刻重画、重测，只有该处误差**严格下降**才
# 提交；帧数少了、文字压上了、整页变差了，一律回滚。模型可以猜，页面不会信。
# --------------------------------------------------------------------------

import os  # noqa: E402 - 只有这一层读环境变量，放在段首比顶部更清楚

#: 精修轮数。1 = 保持旧行为（一轮离散仲裁）；2~3 打开定量精修。
ARBITER_MAX_ROUNDS = int(os.environ.get("ARBITER_MAX_ROUNDS") or 1)
#: 每轮最多修几处。同时给模型看三处是它还能分清上下文的极限，再多就开始猜。
ROUND_TOP_K = 3
#: 误差热力图的格子边长。24px 让一张 200px 的卡落进一格半：再小会把同一个
#: 缺陷拆成两张工单，再大又会把两处不相干的缺陷并成一张。
HEAT_CELL = 24
#: 一个连通块至少要有这么多坏像素才参与合并。它只用来滤掉抗锯齿碎屑——排序
#: 靠的是误差总量，所以门槛可以很松；定高了会把 3px 偏移留下的细带一起滤掉。
HEAT_MIN_BAD_PIXELS = 12
#: 工单区块向外扩多少像素：只看缺陷本身看不出它偏了多少，得给它参照物。
ROUND_PAD = 12
#: 裁片放大倍数与刻度间隔（原图像素）。1px 的偏移在 1× 下看不出来。
ROUND_ZOOM = 2
RULER_TICK = 10
#: 描边宽度：裁片四周留出刻度用的白边。
RULER_MARGIN = 26
#: 定量补丁允许动的字段，以及每个字段的钳位区间（都是**增量**）。
PATCH_LIMITS: dict[str, tuple[float, float]] = {
    "dx": (-64.0, 64.0),
    "dy": (-64.0, 64.0),
    "dw": (-64.0, 64.0),
    "dh": (-64.0, 64.0),
    "fontSize": (-24.0, 24.0),
    "fontWeight": (-400.0, 400.0),
    "letterSpacing": (-2.0, 8.0),
}
#: 单行文本能动的字段。**没有 dw/dh**：这一版发射出去的文本是自动宽度的，
#: 改框不改墨——上一轮 A/B 的 8 条补丁里 5 条是 dw，全部 ROI 一模一样
#: （25.84→25.84）后回滚。文字看着比原图宽，可改的是 fontSize / letterSpacing。
TEXT_PATCH_FIELDS = ("dx", "dy", "fontSize", "letterSpacing", "fontWeight")
#: 尺寸自由度只属于"画出来的盒子"：容器、图片、矩形。按钮和输入框的盒子跟着
#: 标签与内边距走，改宽高等于替它们重排。
SIZE_PATCH_TYPES = ("container", "image", "rectangle")
#: 单条工单允许改的字段上限：一次动七个字段就是在重画，不是在修。
PATCH_MAX_FIELDS = 3
#: 语义工具：改文案、改字色/底色、改层序。都是"轻"操作，不移动任何成员。
TEXT_EDIT_LIMIT = 120
HEX_COLOUR_RE = r"^#[0-9a-fA-F]{6}$"
Z_INDEX_MAX = 9999
#: 局部误差要"真的"下降才算数。浮点噪声级别的改善（< 0.02 个灰度级）说明这条
#: 补丁对画面没有作用，收下它只会在报告里写下一个并不存在的修复。
ROI_MIN_GAIN = 0.02
#: 整页误差允许因为一条补丁上涨的比例（相对）。没有这条，模型只要把字挪出
#: 工单包围盒，局部误差就会"下降"——修好一处、弄坏一片。
PAGE_DRIFT_TOLERANCE = 0.005


@dataclass
class WorkOrder:
    """一处要按像素量修掉的地方，绑定到一个可修改的节点。"""

    index: int
    ref: str
    box: list[int]
    element_id: str = ""
    kind: str = "geometry"
    error: float = 0.0
    patch: dict[str, float] = field(default_factory=dict)
    note: str = ""
    status: str = ""
    #: 节点的 type（text/container/image/button/rectangle…）。字段分权看的是它。
    element_type: str = ""
    #: 巡检给出的语义提示（"这里缺按钮文字"、"疑似错字，应为…"）。写进 prompt，
    #: 让模型知道这条不是纯几何偏移。
    hint: str = ""

    @property
    def single_line(self) -> bool:
        return self.kind == "text"

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "index": self.index,
            "ref": self.ref,
            "bbox": list(self.box),
            "kind": self.kind,
            "error": round(self.error, 1),
        }
        if self.hint:
            payload["hint"] = self.hint
        return payload


def _work_order_kind(element: Mapping[str, Any]) -> str:
    """``text`` for a single line of type, ``text-block`` for a wrapped block.

    Only the difference matters: a single line is auto-sized by the renderer, so
    its box width and height are outputs, not inputs.
    """
    if str(element.get("type") or "") != "text":
        return "geometry"
    text = str(element.get("text") or "")
    style = element.get("style") or {}
    size = float(style.get("fontSize") or 0)
    height = float(element.get("height") or 0)
    lines = text.count("\n") + 1
    if lines <= 1 and (size <= 0 or height <= size * 1.9):
        return "text"
    return "text-block"


def patch_fields_for(order: WorkOrder) -> tuple[str, ...]:
    """Which incremental fields this node may be given.

    A single line of text is the one shape where ``dw``/``dh`` is guaranteed to be
    wasted: the box follows the glyphs.  Everything else may use the size axes,
    but only surfaces may use them at all — a button's box is its label plus
    padding, not a free rectangle.
    """
    if order.single_line:
        return TEXT_PATCH_FIELDS
    if order.element_type in SIZE_PATCH_TYPES:
        return tuple(PATCH_LIMITS)
    return TEXT_PATCH_FIELDS


def _array(image) -> Any:
    import numpy as np

    array = np.asarray(image)
    if array.ndim == 2:
        array = np.stack([array] * 3, axis=2)
    return array[..., :3].astype(np.int16)


def heat_grid(truth, drawn, cell: int = HEAT_CELL) -> Any:
    """Mean |dI| per square cell: where the page is wrong, at a scale you can name."""
    import numpy as np

    a, b = _array(truth), _array(drawn)
    if a.shape != b.shape:
        raise ValueError(f"heat map needs equal shapes: {a.shape} vs {b.shape}")
    height, width = a.shape[:2]
    rows, columns = height // cell, width // cell
    if rows < 1 or columns < 1:
        return np.zeros((1, 1), dtype=np.float32)
    distance = np.abs(a - b).max(axis=2)[: rows * cell, : columns * cell]
    return distance.reshape(rows, cell, columns, cell).mean(axis=(1, 3))


def _owner_of(elements: Sequence[Mapping[str, Any]], box: Sequence[int]) -> int:
    """The node that best explains this error block: smallest one it mostly lies in.

    "Smallest" matters.  A hot block inside a card intersects the card, the
    page shell and the text that is actually wrong; the text is the only one of
    the three a coordinate patch should touch.
    """
    x, y, w, h = (int(value) for value in list(box)[:4])
    best, best_area = -1, None
    for index, element in enumerate(elements):
        if element.get("type") not in ("text", "container", "image", "button", "input"):
            continue
        if str(element.get("role") or "") in ("patch", "mark", "page-ground"):
            continue
        ex, ey, ew, eh = (float(element.get(key) or 0) for key in ("x", "y", "width", "height"))
        if ew <= 0 or eh <= 0:
            continue
        overlap_w = min(x + w, ex + ew) - max(x, ex)
        overlap_h = min(y + h, ey + eh) - max(y, ey)
        if overlap_w <= 0 or overlap_h <= 0:
            continue
        intersection = overlap_w * overlap_h
        # 块要落在这个节点的范围里（或节点落在块里），不是擦一下就算。
        if intersection < 0.25 * min(w * h, ew * eh):
            continue
        if best_area is None or ew * eh < best_area:
            best, best_area = index, ew * eh
    return best


def error_blocks(
    truth,
    drawn,
    elements: Sequence[Mapping[str, Any]],
    *,
    gap: int = 8,
    pad: int = ROUND_PAD,
) -> list[tuple[float, list[int], int]]:
    """The worst error clusters, one per node, dearest first.

    A cluster is labelled on the thresholded difference, not on a coarse grid:
    a three-pixel shift leaves two thin bands — one where the ink is missing,
    one where it was painted — and they are one defect.  Grid cells split them
    and then neither half clears any density threshold, which is exactly how the
    first version nominated nothing at all.

    So the two bands are clustered separately and then *joined by the node they
    belong to*: whatever a patch can move defines the work order, not what the
    pixels happened to touch.
    """
    import cv2
    import numpy as np

    a, b = _array(truth), _array(drawn)
    if a.shape != b.shape:
        return []
    height, width = a.shape[:2]
    distance = np.abs(a - b).max(axis=2)
    bad = (distance > 30).astype(np.uint8)
    if not bad.any():
        return []
    grown = cv2.dilate(bad, np.ones((gap, gap), np.uint8))
    count, labels, _stats, _centroids = cv2.connectedComponentsWithStats(grown, 8)
    grouped: dict[int, list[float]] = {}
    for index in range(1, count):
        mask = labels == index
        hot = (bad[mask] > 0)
        if int(hot.sum()) < HEAT_MIN_BAD_PIXELS:
            continue
        xs = np.where(mask.any(axis=0))[0]
        ys = np.where(mask.any(axis=1))[0]
        if xs.size == 0 or ys.size == 0:
            continue
        x0 = max(0, int(xs[0]) - pad)
        y0 = max(0, int(ys[0]) - pad)
        x1 = min(width, int(xs[-1]) + 1 + pad)
        y1 = min(height, int(ys[-1]) + 1 + pad)
        if x1 - x0 < 6 or y1 - y0 < 6:
            continue
        owner = _owner_of(elements, (x0, y0, x1 - x0, y1 - y0))
        if owner < 0:
            # 没有节点对得上：这是背景误差，改坐标修不掉它。
            continue
        weight = float(distance[mask & (bad > 0)].sum())
        entry = grouped.setdefault(owner, [0.0, x0, y0, x1, y1])
        entry[0] += weight
        entry[1] = min(entry[1], x0)
        entry[2] = min(entry[2], y0)
        entry[3] = max(entry[3], x1)
        entry[4] = max(entry[4], y1)
    found = [
        (weight, [int(x0), int(y0), int(x1 - x0), int(y1 - y0)], owner)
        for owner, (weight, x0, y0, x1, y1) in grouped.items()
    ]
    found.sort(key=lambda item: -item[0])
    return found


def nominate_rounds(
    truth,
    drawn,
    elements: Sequence[Mapping[str, Any]],
    *,
    k: int = ROUND_TOP_K,
) -> list[WorkOrder]:
    """The worst k nodes, with the box a patch has to improve."""
    import numpy as np

    blocks = error_blocks(truth, drawn, elements)
    if not blocks:
        return []
    distance = np.abs(_array(truth) - _array(drawn)).max(axis=2)
    orders: list[WorkOrder] = []
    for _weight, box, owner in blocks:
        if len(orders) >= k:
            break
        element = elements[owner]
        x, y, w, h = box
        block = distance[y : y + h, x : x + w]
        if block.size == 0:
            continue
        orders.append(
            WorkOrder(
                index=len(orders),
                ref=str(element.get("contentRef") or element.get("id") or ""),
                box=list(box),
                element_id=str(element.get("id") or ""),
                kind=_work_order_kind(element),
                error=round(float(block.mean()), 1),
                element_type=str(element.get("type") or ""),
            )
        )
    orders.sort(key=lambda item: -item.error)
    for position, order in enumerate(orders):
        order.index = position
    return orders


# --------------------------------------------------------------------------
# 全图语义巡检：像素 Top-K 看不见的那一类
#
# 前两层都按"误差总量"排队，于是三件事永远排不到前面：一个漏掉的按钮文字
# （面积小）、一处被盖住的图标、一个错字（差几个像素）。这些恰恰是眼睛第一
# 眼就看见的。所以每轮开始先做**一次**整页并排巡检，让模型直接点名最多三处
# 硬伤、给个大概 bbox；系统把它吸附到最近的节点，再走同一套 2× 标尺裁片、
# 定量补丁、四重回滚——巡检只负责"指哪"，不负责"怎么改"。
# --------------------------------------------------------------------------

#: 巡检最多点名几处。三处是"最显眼的"还能排得出来的上限，再多就变成罗列。
SWEEP_MAX_DEFECTS = 3
#: 巡检认的缺陷类别。宽一点没关系：它只用来写 hint，真正落笔的是后面的补丁。
SWEEP_KINDS = (
    "missing-text",
    "overlap",
    "typo",
    "missing-icon",
    "color",
    "layout",
)
#: 缺陷框与节点框的重叠达到这个比例，就算"在说这个节点"。
SWEEP_MATCH_SHARE = 0.2
#: 重叠不够时，按中心点距离兜底（原图像素）。小图标、单字常常贴不上框。
SWEEP_MATCH_RADIUS = 48


def sweep_prompt(digest: str, *, max_defects: int = SWEEP_MAX_DEFECTS) -> str:
    """One look at the whole page, three named flaws, no numbers.

    Deliberately *not* a per-block question: the pixel nominator already owns
    "this block is off by k pixels".  This asks the other question — "what would
    a reviewer point at" — which is the only way a missing button label or a
    swapped glyph ever gets a work order.
    """
    return (
        "图 1 是整页并排对比（左原图、右当前渲染），图 2/3/4 是上/中/下三段 1:1。\n"
        "请只看**最显眼的观感硬伤**，最多 " + str(max_defects) + " 处，按严重程度排序：\n"
        "1 整块缺失的文字或按钮文案（渲染里是空白/少字）；2 文字互相重叠或被遮住；"
        "3 明显错别字/乱码（OCR 误识残留）；4 该有的图标/Logo 不见了或残缺；"
        "5 白底白字、深底深字这类对比度错误。\n"
        "允许字形有细微差别、允许 ±2px 的位置误差，这些都不要报。\n"
        f"当前页面骨架（节点 ref/bbox/文字）：{digest}\n"
        "只输出 JSON，不要解释：\n"
        '{"defects":[{"kind":"missing-text|overlap|typo|missing-icon|color|layout",'
        '"bbox":[x,y,w,h],"expected_text":"这里应该是什么字（typo 时填正确文案）",'
        '"note":"一句话说清现象"}]}\n'
        "bbox 用原图像素，只要「大概在哪」，系统会自己吸附到节点；看不清就少答，不要凑数。"
    )


def parse_sweep_defects(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Keep the well-formed defects, in the order the model ranked them."""
    found: list[dict[str, Any]] = []
    for raw in payload.get("defects") or []:
        if len(found) >= SWEEP_MAX_DEFECTS:
            break
        if not isinstance(raw, Mapping):
            continue
        try:
            box = [int(value) for value in (raw.get("bbox") or [])]
        except (TypeError, ValueError):
            continue
        if len(box) != 4 or box[2] <= 0 or box[3] <= 0:
            continue
        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in SWEEP_KINDS:
            continue
        found.append(
            {
                "kind": kind,
                "bbox": box,
                "expected_text": str(raw.get("expected_text") or "").strip()[:TEXT_EDIT_LIMIT],
                "note": str(raw.get("note") or "").strip()[:120],
            }
        )
    return found


def sweep_work_orders(
    elements: Sequence[Mapping[str, Any]],
    defects: Sequence[Mapping[str, Any]],
    *,
    start: int = 0,
    exclude: set[str] | None = None,
) -> list[WorkOrder]:
    """Turn "somewhere around here" into "this node", or drop it.

    Overlap first, nearest centre second — a missing button label has no box of
    its own, so its bbox lands on the button, and a swapped glyph lands on the
    word.  A defect that matches nothing is dropped rather than guessed: a work
    order on the wrong node costs a real edit.
    """
    orders: list[WorkOrder] = []
    seen: set[str] = set()
    for defect in defects:
        box = list(defect["bbox"])
        ranked: list[tuple[float, float, Mapping[str, Any]]] = []
        for element in elements:
            if str(element.get("type") or "") in ("patch", ""):
                continue
            if str(element.get("role") or "") in ("patch", "mark", "page-ground"):
                continue
            rect = _rect(element)
            if rect[2] <= 0 or rect[3] <= 0:
                continue
            share = max(_share(box, rect), _share(rect, box))
            if share >= SWEEP_MATCH_SHARE:
                ranked.append((share, float(rect[2]) * float(rect[3]), element))
        best = None
        if ranked:
            # 重叠一样时**取最小的那个**：一个错字所在的行容器和那个字都 100%
            # 盖住缺陷框，只有字能改文案。大的那个是"这一带"，不是"这个节点"。
            top_share = max(item[0] for item in ranked)
            near = [item for item in ranked if item[0] >= top_share - 0.05]
            best = min(near, key=lambda item: item[1])[2]
        else:
            best, _distance = _nearest_centre(elements, box)
        # 文案类缺陷经常被框成"整列/整段"：这时框套住的是一个行容器，而能改字的
        # 只有里面的文本节点。取**完全落在缺陷框里**、面积最大的那个字。
        if best is not None and defect["kind"] in ("typo", "missing-text"):
            if str(best.get("type") or "") != "text":
                alternative = _text_inside(elements, box)
                if alternative is not None:
                    best = alternative
        if best is None:
            continue
        node_id = str(best.get("id") or "")
        if not node_id or node_id in seen or (exclude and node_id in exclude):
            continue
        seen.add(node_id)
        rect = _rect(best)
        hint = defect["kind"].replace("-", " ")
        note = str(defect.get("note") or "")
        expected = str(defect.get("expected_text") or "")
        if note:
            hint += f": {note}"
        if expected:
            hint += f" (应为「{expected}」)"
        orders.append(
            WorkOrder(
                index=start + len(orders),
                ref=str(best.get("contentRef") or node_id),
                box=[
                    max(0, rect[0] - ROUND_PAD),
                    max(0, rect[1] - ROUND_PAD),
                    rect[2] + 2 * ROUND_PAD,
                    rect[3] + 2 * ROUND_PAD,
                ],
                element_id=node_id,
                kind=_work_order_kind(best),
                error=0.0,
                note=note,
                element_type=str(best.get("type") or ""),
                hint=hint,
            )
        )
    return orders


def _text_inside(
    elements: Sequence[Mapping[str, Any]],
    box: Sequence[int],
) -> Mapping[str, Any] | None:
    """The text node that sits inside a flagged band, largest first.

    A defect framed around a whole column has no single owner; the words do.  The
    node has to be *inside* the band (over 60% of it inside the box), or this
    would happily hand a "missing label" to the caption next door.
    """
    best = None
    best_area = 0.0
    for element in elements:
        if str(element.get("type") or "") != "text":
            continue
        if not str(element.get("text") or "").strip():
            continue
        rect = _rect(element)
        if rect[2] <= 0 or rect[3] <= 0:
            continue
        if _share(rect, box) < 0.6:
            continue
        area = float(rect[2]) * float(rect[3])
        if area > best_area:
            best, best_area = element, area
    return best


def _nearest_centre(
    elements: Sequence[Mapping[str, Any]],
    box: Sequence[int],
) -> tuple[Mapping[str, Any] | None, float]:
    """Fallback binding: the closest node centre inside ``SWEEP_MATCH_RADIUS``."""
    cx = box[0] + box[2] / 2.0
    cy = box[1] + box[3] / 2.0
    best = None
    best_distance = float(SWEEP_MATCH_RADIUS)
    for element in elements:
        if str(element.get("type") or "") not in ("text", "container", "image", "button", "icon"):
            continue
        rect = _rect(element)
        if rect[2] <= 0 or rect[3] <= 0:
            continue
        distance = ((rect[0] + rect[2] / 2.0 - cx) ** 2 + (rect[1] + rect[3] / 2.0 - cy) ** 2) ** 0.5
        if distance < best_distance:
            best, best_distance = element, distance
    return best, best_distance


def ruler_panel(truth, drawn, box: Sequence[int], *, zoom: int = ROUND_ZOOM,
                tick: int = RULER_TICK) -> Any:
    """One 2x side-by-side strip inside a ruler, so a pixel offset can be read.

    Without the ruler the model can say "the text sits low" and not by how much.
    Ten source pixels per tick, labelled every five ticks: at 2x that is a mark
    every 20 screen pixels, which reads as a scale rather than as noise.  The
    ticks are in **source** coordinates, so the number the model reads is the
    number the patch has to use.
    """
    import cv2
    import numpy as np

    x, y, w, h = (int(value) for value in box)
    height, width = _array(truth).shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return np.full((16, 16, 3), 255, dtype=np.uint8)
    left = cv2.resize(_array(truth)[y0:y1, x0:x1].astype(np.uint8), None,
                      fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
    right = cv2.resize(_array(drawn)[y0:y1, x0:x1].astype(np.uint8), None,
                       fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
    return _wrap_ruler(_side_by_side(left, right), zoom=zoom, tick=tick)


def _side_by_side(left, right):
    import numpy as np

    gap = np.full((left.shape[0], 10, 3), 255, dtype=np.uint8)
    return np.concatenate([left, gap, right], axis=1)


def _wrap_ruler(panel, *, zoom: int = ROUND_ZOOM, tick: int = RULER_TICK):
    """刻度边框：单位是原图像素，模型读到的数就是补丁要填的数。"""
    import cv2
    import numpy as np

    frame = np.full(
        (panel.shape[0] + 2 * RULER_MARGIN, panel.shape[1] + 2 * RULER_MARGIN, 3),
        255,
        dtype=np.uint8,
    )
    frame[RULER_MARGIN : RULER_MARGIN + panel.shape[0], RULER_MARGIN : RULER_MARGIN + panel.shape[1]] = panel
    ink = (74, 74, 74)
    step = max(1, int(tick)) * zoom
    for offset in range(0, panel.shape[1] + 1, step):
        column = RULER_MARGIN + offset
        cv2.line(frame, (column, RULER_MARGIN - 6), (column, RULER_MARGIN - 1), ink, 1)
        cv2.line(frame, (column, RULER_MARGIN + panel.shape[0] + 1),
                 (column, RULER_MARGIN + panel.shape[0] + 6), ink, 1)
        source = offset // zoom
        if source % (int(tick) * 5) == 0:
            cv2.putText(frame, str(source), (column + 1, RULER_MARGIN - 9),
                        cv2.FONT_HERSHEY_PLAIN, 0.7, ink, 1, cv2.LINE_AA)
    for offset in range(0, panel.shape[0] + 1, step):
        row = RULER_MARGIN + offset
        cv2.line(frame, (RULER_MARGIN - 6, row), (RULER_MARGIN - 1, row), ink, 1)
        cv2.line(frame, (RULER_MARGIN + panel.shape[1] + 1, row),
                 (RULER_MARGIN + panel.shape[1] + 6, row), ink, 1)
        source = offset // zoom
        if source % (int(tick) * 5) == 0:
            cv2.putText(frame, str(source), (2, row + 3),
                        cv2.FONT_HERSHEY_PLAIN, 0.7, ink, 1, cv2.LINE_AA)
    # ROI 本身画一圈细线：模型要能分清"工单范围"和"刻度范围"。
    cv2.rectangle(
        frame,
        (RULER_MARGIN, RULER_MARGIN),
        (RULER_MARGIN + panel.shape[1] - 1, RULER_MARGIN + panel.shape[0] - 1),
        (188, 188, 188),
        1,
    )
    return frame


def round_prompt(orders: Sequence[WorkOrder]) -> str:
    """The one question this layer asks, and the only shapes an answer may take."""
    listing = json.dumps([order.as_dict() for order in orders], ensure_ascii=False)
    text_orders = [order for order in orders if order.single_line]
    size_orders = [order for order in orders if order.element_type in SIZE_PATCH_TYPES]
    rules = [
        "只回答这些区域该怎么微调，不要解释。所有数值都是**增量**，可以为负：",
        "优先级：从刻度上读得出偏差就填 dx/dy/fontSize/fontWeight/letterSpacing —— "
        "这是本层的主职；setText/textColor/fillColor/zIndex 只在 hint 点名要改文字、"
        "改对比度或解遮挡时使用，别拿它替代坐标读数。",
        '{"patches":[{"index":0,"dx":0,"fontSize":0,"setText":"",'
        '"textColor":"","fillColor":"","zIndex":null,"note":"..."}]}',
        "模板里的 0、空字符串、null 都是「这一项不改」，**不要照抄**："
        "一条补丁里只出现你真正要改的字段，其余整个键都不要写。",
        "dx/dy 正数向右向下；fontSize 是**磅值增量**（1px 字高约 0.75pt）；"
        "fontWeight 是 100 的倍数增量；letterSpacing 是绝对像素值。",
        "**单行文字（kind=text）禁止填 dw/dh**：文本框宽高由字自动决定，改框不改墨，"
        "上一轮 5/8 条补丁就是这么空转的。文字看着比原图宽或窄，请改 fontSize 或 "
        "letterSpacing。dw/dh 只对 kind=geometry 且 type 是 container/image/rectangle 的节点开放。",
        "setText 只在**确实读错了字**（错字、乱码、OCR 误识）时使用，填原文该有的文字；"
        "textColor/fillColor 用于修白底白字、深底深字这类对比度错误；zIndex 用于把被"
        "装饰块盖住的节点抬到遮挡者之上（填目标层号，不是增量）。",
        "一行最多填 3 个数**值**字段；读不出来就不要报这一处——报错一条，整轮都会被回滚。",
    ]
    if text_orders:
        rules.append(
            "本次工单里的单行文字："
            + "、".join(f"#{order.index}" for order in text_orders)
            + " 只能改 " + "/".join(TEXT_PATCH_FIELDS) + "。"
        )
    if size_orders:
        rules.append(
            "可改框大小的节点："
            + "、".join(f"#{order.index}" for order in size_orders)
            + "。"
        )
    # 巡检给的那几条要单独交代：它们不是"偏了几像素"，是"这里该有字/这是个错字"。
    # 不点明的话，模型会照着像素差去调颜色——上一轮 6 条补丁里 4 条是 #000000。
    for order in orders:
        if not order.hint:
            continue
        if order.hint.startswith(("typo", "missing text")):
            rules.append(
                f"工单 #{order.index} 是巡检点名的文案问题（{order.hint}）："
                "请用 setText 填上正确的文字；文字不缺就不要硬改，也不要改颜色。"
            )
        elif order.hint.startswith(("missing icon", "overlap")):
            rules.append(
                f"工单 #{order.index} 是巡检点名的结构/遮挡问题（{order.hint}）："
                "能用 zIndex 把被盖住的东西抬出来就用 zIndex；否则跳过。"
            )
    return (
        f"图 1..{len(orders)} 是{len(orders)}处误差最大区域的 2× 对照（左原图、右当前渲染），"
        "每张外围有刻度：**单位是原图像素**，每小格 10px。\n"
        f"工单清单（hint 是整页巡检给的语义线索，不是结论）：{listing}\n"
        + "\n".join(rules)
    )


def parse_round_patches(
    payload: Mapping[str, Any],
    *,
    orders: Sequence[WorkOrder] = (),
) -> dict[int, dict[str, float]]:
    """Clamp and keep only the quantitative fields, per work order.

    Without ``orders`` there is no node type to consult, so every field is kept —
    the historical behaviour, still used by callers that only want the numbers.
    With them, a single line of text loses ``dw``/``dh`` before it is ever tried.
    """
    return {
        index: dict(edit.numeric)
        for index, edit in parse_round_edits(payload, orders=orders).items()
        if edit.numeric
    }


@dataclass
class RoundEdit:
    """One model answer for one work order: numbers, words, colour, or order.

    The numeric half is the old patch.  The other three are the light tools: fix
    the words (OCR left a wrong glyph), fix a contrast the eye can name, lift a
    node out from under something.  None of them moves a member, so all of them
    survive the same four gates as a coordinate nudge.
    """

    numeric: dict[str, float] = field(default_factory=dict)
    text: str = ""
    text_color: str = ""
    fill_color: str = ""
    z_index: int | None = None
    note: str = ""

    def is_empty(self) -> bool:
        return not (self.numeric or self.text or self.text_color or self.fill_color or (
            self.z_index is not None
        ))


def _clean_colour(value: Any) -> str:
    import re as _re

    raw = str(value or "").strip()
    if not raw:
        return ""
    if not raw.startswith("#"):
        raw = "#" + raw
    if not _re.match(HEX_COLOUR_RE, raw):
        return ""
    return raw.lower()


def parse_round_edits(
    payload: Mapping[str, Any],
    *,
    orders: Sequence[WorkOrder] = (),
) -> dict[int, RoundEdit]:
    """Parse one round's answer, keeping only what the node type may take."""
    by_index = {order.index: order for order in orders}
    out: dict[int, RoundEdit] = {}
    for raw in payload.get("patches") or []:
        if not isinstance(raw, Mapping):
            continue
        try:
            index = int(raw.get("index"))
        except (TypeError, ValueError):
            continue
        order = by_index.get(index)
        allowed = patch_fields_for(order) if order is not None else tuple(PATCH_LIMITS)
        numeric: dict[str, float] = {}
        for name in allowed:
            if name not in raw:
                continue
            low, high = PATCH_LIMITS[name]
            try:
                value = float(raw[name])
            except (TypeError, ValueError):
                continue
            if value == 0.0:
                continue
            numeric[name] = max(low, min(high, value))
        numeric = dict(
            sorted(numeric.items(), key=lambda item: -abs(item[1]))[:PATCH_MAX_FIELDS]
        )
        text = str(raw.get("setText") or raw.get("text") or "").strip()
        if len(text) > TEXT_EDIT_LIMIT:
            text = ""
        z_index: int | None = None
        if raw.get("zIndex") is not None:
            try:
                z_index = max(0, min(Z_INDEX_MAX, int(raw["zIndex"])))
            except (TypeError, ValueError):
                z_index = None
        edit = RoundEdit(
            numeric=numeric,
            text=text,
            text_color=_clean_colour(raw.get("textColor")),
            fill_color=_clean_colour(raw.get("fillColor")),
            z_index=z_index,
            note=str(raw.get("note") or ""),
        )
        if edit.is_empty():
            continue
        out[index] = edit
    return out


def apply_round_edit(
    element: dict[str, Any],
    edit: RoundEdit | Mapping[str, float],
    *,
    frozen: bool = False,
    element_type: str = "",
) -> dict[str, Any] | None:
    """Land one edit on one node, or refuse.

    ``frozen`` means "this node is a frame": geometry and paint order would
    re-parent its members, so only typography passes.  ``element_type`` is only
    needed when the caller passes a bare numeric patch, because the size axes
    belong to surfaces alone.
    """
    if isinstance(edit, Mapping):
        edit = RoundEdit(numeric=dict(edit))
    kind_type = element_type or str(element.get("type") or "")
    applied: dict[str, Any] = {}
    numeric = dict(edit.numeric)
    if kind_type not in SIZE_PATCH_TYPES:
        # 二次防线：调用方忘了按类型过滤，也不能把 dw/dh 落到文字上。
        numeric.pop("dw", None)
        numeric.pop("dh", None)
    geometry = {"dx", "dy", "dw", "dh"} & set(numeric)
    if geometry and frozen:
        numeric = {name: value for name, value in numeric.items() if name not in geometry}
    if numeric.get("dx") or numeric.get("dy"):
        element["x"] = round(float(element.get("x") or 0) + float(numeric.get("dx", 0.0)), 1)
        element["y"] = round(float(element.get("y") or 0) + float(numeric.get("dy", 0.0)), 1)
        applied["dx"] = float(numeric.get("dx", 0.0))
        applied["dy"] = float(numeric.get("dy", 0.0))
    if numeric.get("dw") or numeric.get("dh"):
        width = max(1.0, float(element.get("width") or 0) + float(numeric.get("dw", 0.0)))
        height = max(1.0, float(element.get("height") or 0) + float(numeric.get("dh", 0.0)))
        element["width"], element["height"] = round(width, 1), round(height, 1)
        applied["dw"] = float(numeric.get("dw", 0.0))
        applied["dh"] = float(numeric.get("dh", 0.0))
    style = element.get("style")
    if style is None and ({"fontSize", "fontWeight", "letterSpacing"} & set(numeric) or
                          edit.text_color or edit.fill_color):
        style = element["style"] = {}
    if style is not None:
        if "fontSize" in numeric:
            size = float(style.get("fontSize") or 14.0) + float(numeric["fontSize"])
            style["fontSize"] = round(max(8.0, min(200.0, size)) * 2) / 2
            applied["fontSize"] = float(numeric["fontSize"])
        if "fontWeight" in numeric:
            weight = int(style.get("fontWeightValue") or 400) + int(numeric["fontWeight"])
            weight = max(100, min(900, int(round(weight / 100.0)) * 100))
            style["fontWeightValue"] = weight
            style["fontWeight"] = "bold" if weight >= 700 else "normal"
            applied["fontWeight"] = float(numeric["fontWeight"])
        if "letterSpacing" in numeric:
            style["letterSpacing"] = round(float(numeric["letterSpacing"]), 2)
            applied["letterSpacing"] = float(numeric["letterSpacing"])
        # ---- 语义工具 ----------------------------------------------------
        if edit.text and kind_type == "text":
            current = str(element.get("text") or "")
            if edit.text != current:
                element["text"] = edit.text
                applied["setText"] = edit.text
        if edit.text_color:
            key = "textColor" if kind_type == "text" else "fillColor"
            current = str(style.get(key) or "").lower()
            if edit.text_color != current:
                style[key] = edit.text_color
                applied[key] = edit.text_color
        if edit.fill_color and kind_type != "text":
            current = str(style.get("fillColor") or "").lower()
            if edit.fill_color != current:
                style["fillColor"] = edit.fill_color
                applied["fillColor"] = edit.fill_color
    if edit.z_index is not None and not frozen:
        if int(element.get("zIndex") or 0) != edit.z_index:
            element["zIndex"] = edit.z_index
            applied["zIndex"] = edit.z_index
    if not applied:
        return None
    element.setdefault("arbiterEvidence", {})["quantitative"] = applied
    return applied


def _structural_indices(elements: Sequence[Mapping[str, Any]]) -> set[int]:
    """Elements whose *own* box is structure: the frame containers.

    A leaf member may be nudged — the frame guard measures whether the frame
    still holds (``frames-lost`` rolls the patch back), so geometry on a word is
    a proposal the guards can judge.  A frame *container* is a different thing:
    moving it re-parents its members, which is not a correction but a rewrite.
    """
    return {
        index
        for index, element in enumerate(elements)
        if element.get("layoutChildren")
    }


def apply_quantitative(
    element: dict[str, Any],
    patch: Mapping[str, float],
    *,
    frozen: bool = False,
) -> dict[str, float] | None:
    """Move and restyle one node by the numbers, or refuse.

    Kept as the narrow entry point for callers that only have numbers; the round
    loop goes through :func:`apply_round_edit`, which also carries the words and
    the paint order.
    """
    applied = apply_round_edit(element, dict(patch), frozen=frozen)
    if applied is None:
        return None
    return {key: float(value) for key, value in applied.items() if isinstance(value, float)}


def roi_error(truth, drawn, box: Sequence[int]) -> float:
    """Mean |dI| inside one box — the only number a patch is allowed to move."""
    import numpy as np

    a, b = _array(truth), _array(drawn)
    if a.shape != b.shape:
        return float("inf")
    height, width = a.shape[:2]
    x, y, w, h = (int(value) for value in list(box)[:4])
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return float("inf")
    return float(np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]).max(axis=2).mean())


def page_error(truth, drawn) -> float:
    import numpy as np

    a, b = _array(truth), _array(drawn)
    if a.shape != b.shape:
        return float("inf")
    return float(np.abs(a - b).max(axis=2).mean())


def count_frames(elements: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for element in elements if element.get("layoutChildren"))


def covered_texts(elements: Sequence[Mapping[str, Any]]) -> int:
    """Words an opaque node paints over — the question `_guard_text_occlusion` asks.

    That pass *repairs* what it finds, so it cannot also serve as the before and
    after measurement a rollback needs: it mutates.  This counts the finding
    instead, with the same rule (half the word covered by something opaque
    painted after it), so a patch that buries a label is caught by the number
    and not by the repair it would have triggered.
    """
    ranks = paint_ranks(list(elements))
    covered = 0
    for index, element in enumerate(elements):
        if element.get("type") != "text" or not str(element.get("text") or "").strip():
            continue
        box = _rect(element)
        rank = ranks.get(index, 0)
        for other_index, other in enumerate(elements):
            if str(other.get("type") or "") == "text" or not _is_opaque(other):
                continue
            if ranks.get(other_index, 0) <= rank:
                continue
            if _cover_share(_rect(other), box) >= OCCLUSION_COVER:
                covered += 1
                break
    return covered


def audit_structure(elements: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """The three numbers a quantitative patch may not make worse."""
    return {
        "frames": count_frames(elements),
        "collisions": count_collisions(elements),
        "covered": covered_texts(elements),
    }


def text_edit_is_correction(current: str, wanted: str) -> bool:
    """Is this a repaired word, or a deleted sentence?

    The pixel guard cannot tell them apart — and on AtomGit it *rewarded* the
    deletion: the whole second half of a headline was dropped and the block
    error fell from 24.77 to 22.13, because blank paper was closer to the
    original's light grey than the render's misaligned glyphs were.  So the rule
    is structural: a text edit may fix glyphs and add missing words, but it may
    not shorten the sentence.  Two characters of slack are allowed, for the
    stray quote OCR likes to append.
    """
    if not wanted or wanted == current:
        return False
    if current.startswith(wanted) or current.endswith(wanted):
        return False
    if len(wanted) < len(current) - 2:
        return False
    if len(current) <= 2:
        # 一两个字符的误识（`d` 读成 `PC端`）本来就没有相似度可言。
        return True
    import difflib

    return difflib.SequenceMatcher(None, current, wanted).ratio() >= 0.34


#: 颜色补丁与原图实测色的允许差：每个通道。超过就不是"校准"，是"换一种颜色"。
COLOUR_AGREEMENT = 18


def _colour_gap(first: str, second: str) -> int:
    """Largest per-channel distance between two ``#rrggbb`` strings."""
    try:
        return max(
            abs(int(first[index : index + 2], 16) - int(second[index : index + 2], 16))
            for index in (1, 3, 5)
        )
    except (ValueError, IndexError):
        return 255


def colour_is_supported(
    kind_type: str,
    truth,
    box: Sequence[int],
    colour: str,
) -> bool:
    """Is the model's colour the colour that is actually in the picture?

    The live model's favourite answer is ``#000000``: the render looks lighter
    than the original, and it reads that as "the text colour is wrong".  It is
    usually the *font weight*, and repainting every label black makes the page
    worse.  The picture already holds the answer — the median ink colour inside
    the box — so a colour patch has to agree with it.
    """
    if not colour:
        return False
    actual = _ink_colour(truth, box) if kind_type == "text" else _median_fill(truth, box)
    if not actual:
        return False
    return _colour_gap(actual, colour) <= COLOUR_AGREEMENT


def _edit_dict(edit: RoundEdit) -> dict[str, Any]:
    """One answer, flat, the way it is written to the report."""
    payload: dict[str, Any] = dict(edit.numeric)
    if edit.text:
        payload["setText"] = edit.text
    if edit.text_color:
        payload["textColor"] = edit.text_color
    if edit.fill_color:
        payload["fillColor"] = edit.fill_color
    if edit.z_index is not None:
        payload["zIndex"] = edit.z_index
    return payload


#: "这里缺字"要成立，渲染图那块必须真的没有墨。图上已经有墨、只是小了一号或
#: 淡了一号，那是字太小，不是缺字——这一条把上一轮 18 条点名里 6 条假阳性挡掉。
SWEEP_TEXT_PRESENT_SHARE = 0.35
#: 判墨的通道差：与底色中位数比。
SWEEP_INK_DELTA = 40
#: 一个框里墨点占比低于这个数，就不是"一行字"的框，不参与缺字判定。
SWEEP_TEXT_MIN_DENSITY = 0.005


def _ink_pixels(image, box: Sequence[int]) -> int:
    """Ink pixels inside one box — the measurement a "missing text" claim is about."""
    import numpy as np

    array = _array(image)
    height, width = array.shape[:2]
    x, y, w, h = (int(value) for value in list(box)[:4])
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return 0
    crop = array[y0:y1, x0:x1]
    # 底色取自**框外一圈**，不是框内中位数：一个纯墨块（按钮、色条）用框内中位数
    # 量出来是 0——它的中位数就是墨色本身。
    pad = 3
    rx0, ry0 = max(0, x0 - pad), max(0, y0 - pad)
    rx1, ry1 = min(width, x1 + pad), min(height, y1 + pad)
    ring = array[ry0:ry1, rx0:rx1]
    mask = np.ones(ring.shape[:2], dtype=bool)
    mask[y0 - ry0 : y1 - ry0, x0 - rx0 : x1 - rx0] = False
    background = float(np.median(ring[mask])) if mask.any() else float(np.median(array))
    return int((np.abs(crop - background).max(axis=2) > SWEEP_INK_DELTA).sum())


def still_missing(drawn, truth, box: Sequence[int]) -> bool:
    """Is the word really absent from the render, or just too small to read?

    The model judges a downscaled panel: 11.5px type in a 0.75 scale strip is not
    legible, so it reports "missing text" for words that are painted in full.
    Asking the pixels settles it — a word that is there has ink where the source
    has ink; a word that is absent has none.
    """
    source_ink = _ink_pixels(truth, box)
    if source_ink < 20:
        return False
    # 一块 320x30 的框里只有 38 个墨点（0.4%），那不是"一行字"，是别处的字尾
    # 扫进了这个框。密度不够的框没有资格说"这里缺字"。
    area = max(1, int(box[2]) * int(box[3]))
    if source_ink / area < SWEEP_TEXT_MIN_DENSITY:
        return False
    return _ink_pixels(drawn, box) < SWEEP_TEXT_PRESENT_SHARE * source_ink


def _sweep_round(
    elements: Sequence[Mapping[str, Any]],
    truth,
    drawn,
    *,
    propose_sweep: Callable[[str, Sequence[Any]], Mapping[str, Any]] | None,
    start: int,
    existing: set[str],
) -> dict[str, Any]:
    """One whole-page look, turned into work orders the guards already understand.

    Returns the raw defects as well: "the model named nothing" and "the model
    named something that matched no node" are different outcomes, and only the
    first one means the page passed the eye test.
    """
    if propose_sweep is None:
        return {"defects": [], "orders": [], "report": {"skipped": "no-sweep-model"}}
    digest = scene_digest(elements)
    panels = macro_panels(truth, drawn)
    try:
        answer = propose_sweep(sweep_prompt(digest), panels) or {}
    except Exception as exc:  # noqa: BLE001 - a failed look must not kill the round
        return {"defects": [], "orders": [], "report": {"error": f"{type(exc).__name__}: {exc}"}}
    claimed = parse_sweep_defects(answer)
    # "缺字"类点名先过像素：设计里有、渲染里也有墨的，是字号问题不是缺失。
    defects = [
        defect
        for defect in claimed
        if defect["kind"] != "missing-text" or still_missing(drawn, truth, defect["bbox"])
    ]
    dismissed = [
        defect for defect in claimed if defect not in defects
    ]
    orders = sweep_work_orders(elements, defects, start=start, exclude=existing)
    return {
        "defects": defects,
        "orders": orders,
        "report": {
            "named": len(defects),
            "dismissed": len(dismissed),
            "dismissedKinds": [item["kind"] for item in dismissed],
            "bound": len(orders),
            "defects": defects,
        },
    }


def refine(
    elements: list[dict[str, Any]],
    truth,
    draw: Callable[[list[dict[str, Any]]], Any],
    *,
    propose: Callable[[Sequence[WorkOrder], Sequence[Any]], Mapping[str, Any]] | None,
    rounds: int = ARBITER_MAX_ROUNDS,
    k: int = ROUND_TOP_K,
    audit: Callable[[Sequence[Mapping[str, Any]]], Mapping[str, int]] | None = None,
    propose_wireframe: Callable[[Sequence[Any], Sequence[Any]], Mapping[str, Any]] | None = None,
    propose_sweep: Callable[[str, Sequence[Any]], Mapping[str, Any]] | None = None,
    structure: bool = True,
) -> dict[str, Any]:
    """Closed loop: nominate, ask, patch, re-draw, keep only what improved.

    ``draw`` re-renders the elements and returns pixels.  It is injected rather
    than imported so this layer has no opinion about SVG, Figma, or anything
    else: the same guard runs over whatever the target happens to be, and the
    tests can drive it with a painter they control.

    ``propose`` is the model.  ``None`` means no key; the loop then does nothing
    at all — an unavailable referee must not be mistaken for an approving one.
    """
    import copy

    inspect = audit or audit_structure
    report: dict[str, Any] = {"rounds": 0, "orders": 0, "kept": 0, "rolledBack": 0, "log": []}
    if propose is None or rounds <= 0:
        report["skipped"] = "no-vision" if propose is None else "rounds<=0"
        return report
    frozen = _structural_indices(elements)
    for round_index in range(int(rounds)):
        # 结构先于像素：一个容器套错了两层，再怎么调字也调不好。所以每轮先做
        # 一次线框仲裁，改完的结构直接进入后面的定量补丁。
        if structure and propose_wireframe is not None:
            report.setdefault("structure", []).append(
                refine_structure(
                    elements,
                    truth,
                    draw,
                    propose=propose_wireframe,
                    k=k,
                    audit=inspect,
                )
            )
        drawn = draw(list(elements))
        orders = nominate_rounds(truth, drawn, elements, k=k)
        # 全图巡检先点名，再把用户看得见的硬伤并进同一批工单：像素 Top-K 按
        # 误差总量排队，一个漏掉的按钮文案永远排不进前三。
        sweep = _sweep_round(
            elements,
            truth,
            drawn,
            propose_sweep=propose_sweep,
            start=len(orders),
            existing={order.element_id for order in orders},
        )
        if sweep["defects"] or sweep.get("skipped"):
            report.setdefault("sweeps", []).append({"round": round_index, **sweep["report"]})
        orders.extend(sweep["orders"])
        if not orders:
            report["log"].append({"round": round_index, "orders": [], "note": "converged"})
            break
        report.setdefault("nominations", []).append(
            {
                "round": round_index,
                "orders": [order.as_dict() for order in orders],
            }
        )
        strips = [ruler_panel(truth, drawn, order.box) for order in orders]
        answer = propose(orders, strips) or {}
        edits = parse_round_edits(answer, orders=orders)
        if not edits:
            report["log"].append({"round": round_index, "orders": len(orders), "note": "no-patch"})
            break
        report["rounds"] = round_index + 1
        report["orders"] += len(orders)
        page_before = page_error(truth, drawn)
        before_state = inspect(elements)
        for order in orders:
            edit = edits.get(order.index)
            if edit is None or edit.is_empty():
                continue
            patch = dict(edit.numeric)
            index = next(
                (
                    position
                    for position, element in enumerate(elements)
                    if str(element.get("id") or "") == order.element_id
                ),
                None,
            )
            if index is None:
                order.status = "rolled-back:node-gone"
                order.patch = dict(patch)
                report["rolledBack"] += 1
                report["log"].append(
                    {
                        "round": round_index,
                        "ref": order.ref,
                        "proposed": _edit_dict(edit),
                        "status": order.status,
                        "roi": None,
                    }
                )
                continue
            # 颜色要跟着原图的实测色走；对不上就**只丢这个字段**，别把整条补丁
            # 一起作废——模型经常把 setText 和模板里的默认色一起回上来。
            dropped: list[str] = []
            for field in ("text_color", "fill_color"):
                colour = getattr(edit, field)
                if colour and not colour_is_supported(
                    order.element_type, truth, order.box, colour
                ):
                    setattr(edit, field, "")
                    dropped.append(field)
            if dropped:
                order.note = (order.note + " " if order.note else "") + "colour-dropped"
                report.setdefault("colourDropped", 0)
                report["colourDropped"] += 1
            if edit.is_empty():
                order.status = "rolled-back:colour-not-in-picture"
                report["rolledBack"] += 1
                report["log"].append(
                    {
                        "round": round_index,
                        "ref": order.ref,
                        "proposed": _edit_dict(edit),
                        "status": order.status,
                        "roi": None,
                    }
                )
                continue
            # 一条"改文案"的意见经常落在整列/整段的容器上（误差带跨了好几行）。
            # 能改字的只有里面的文本节点，所以把这条意见转投给它；ROI 与整页两道
            # 门还是按原来的框量，改坏了照样回滚。
            target = elements[index]
            if edit.text and str(target.get("type") or "") != "text":
                nested = _text_inside(elements, order.box)
                if nested is not None:
                    nested_index = next(
                        (
                            position
                            for position, element in enumerate(elements)
                            if element is nested
                        ),
                        None,
                    )
                    if nested_index is not None:
                        index = nested_index
                        target = nested
                        order.note = (order.note + " " if order.note else "") + "retargeted"
            # 文案守卫要在**转投之后**跑：一条落在整列上的意见，比较对象是那一行
            # 真正的字，不是那个容器的空 text。
            if edit.text:
                current_text = str(elements[index].get("text") or "")
                if not text_edit_is_correction(current_text, edit.text):
                    edit.text = ""
                    order.note = (order.note + " " if order.note else "") + "text-dropped"
                    report.setdefault("textDropped", 0)
                    report["textDropped"] += 1
            if edit.is_empty():
                order.status = "rolled-back:text-edit-not-a-correction"
                report["rolledBack"] += 1
                report["log"].append(
                    {
                        "round": round_index,
                        "ref": order.ref,
                        "proposed": _edit_dict(edit),
                        "status": order.status,
                        "roi": None,
                    }
                )
                continue
            snapshot = copy.deepcopy(elements[index])
            before = roi_error(truth, drawn, order.box)
            applied = apply_round_edit(
                elements[index],
                edit,
                frozen=index in frozen,
                element_type=str(target.get("type") or order.element_type),
            )
            if applied is None:
                geometry = {"dx", "dy", "dw", "dh"} & set(patch)
                order.status = (
                    "rolled-back:refused-geometry-on-frame-member"
                    if geometry and index in frozen
                    else "rolled-back:refused-no-op"
                )
                order.patch = dict(patch)
                report["rolledBack"] += 1
                report["log"].append(
                    {
                        "round": round_index,
                        "ref": order.ref,
                        "proposed": _edit_dict(edit),
                        "status": order.status,
                        "roi": None,
                    }
                )
                continue
            order.patch = dict(applied)
            after_drawn = draw(list(elements))
            after = roi_error(truth, after_drawn, order.box)
            page_after = page_error(truth, after_drawn)
            after_state = inspect(elements)
            failures = []
            if before - after < ROI_MIN_GAIN:
                failures.append("roi-not-better")
            if int(after_state.get("frames", 0)) < int(before_state.get("frames", 0)):
                failures.append("frames-lost")
            if int(after_state.get("collisions", 0)) > int(before_state.get("collisions", 0)):
                failures.append("new-collision")
            if int(after_state.get("covered", 0)) > int(before_state.get("covered", 0)):
                failures.append("text-buried")
            if page_after > page_before * (1.0 + PAGE_DRIFT_TOLERANCE):
                failures.append("page-worse")
            if failures:
                elements[index] = snapshot
                order.status = "rolled-back:" + ",".join(failures)
                report["rolledBack"] += 1
                report["log"].append(
                    {
                        "round": round_index,
                        "ref": order.ref,
                        "patch": order.patch,
                        "status": order.status,
                        "roi": [round(before, 2), round(after, 2)],
                    }
                )
                continue
            order.status = "kept"
            report["kept"] += 1
            report["log"].append(
                {
                    "round": round_index,
                    "ref": order.ref,
                    "patch": order.patch,
                    "status": "kept",
                    "roi": [round(before, 2), round(after, 2)],
                }
            )
        if report["kept"] == 0 and round_index == 0:
            # 一条都没留住：再问一次只会重复同样的答案。
            break
    return report


# --------------------------------------------------------------------------
# 容器级 Split / Merge：线框仲裁
#
# 上面两层都假设"容器是画对的"。可容器也会错，而且错法只有两种：一层被画成
# 两层，或者两层被并成一层。前者在感知层刚被那条"禁止跨贯穿缝合并"挡住一次，
# 但那是页面级几何，遇到没见过的版式仍可能判错；后者是同一套标尺的另一面。
#
# 所以这一层的动作集只有两个，候选由几何确定性地提名，模型只回答"是/否"——
# 和上面一样，它没有发明结构的权力。落笔之后照样重画重测，改坏就回滚。
# --------------------------------------------------------------------------

#: 切分带的最小高度/宽度：比这更薄的是描边，不是一层。
WIREFRAME_MIN_BAND = 8
#: 切分带里要有多少行/列与容器填充色不同：容器在替页面画一块它没有的底。
WIREFRAME_FILL_TOLERANCE = 8
#: 切分带内允许的色差：超过它就不是一条平整的缝，切了会切在内容上。
WIREFRAME_BAND_STD = 6.0
#: 两侧各要至少几个孩子，否则切出来的是一个空壳。
WIREFRAME_MIN_SIDE_CHILDREN = 1


@dataclass
class Wireframe:
    """一处结构缺陷：一个容器该切开，或两个容器该并上。"""

    index: int
    op: str
    refs: list[str]
    axis: str
    at: float
    box: list[int]
    reason: str = ""
    status: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "op": self.op,
            "refs": list(self.refs),
            "axis": self.axis,
            "at": round(self.at, 1),
            "bbox": list(self.box),
            "why": self.reason,
        }


def _fill_rgb(element: Mapping[str, Any]) -> tuple[int, int, int] | None:
    style = element.get("style") or {}
    raw = str(style.get("fillColor") or style.get("backgroundColor") or "")
    if not raw.startswith("#") or len(raw) not in (4, 7):
        return None
    digits = raw[1:]
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    try:
        return tuple(int(digits[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def _members(elements: Sequence[Mapping[str, Any]], container: Mapping[str, Any]) -> list[int]:
    by_id = {str(element.get("id") or ""): index for index, element in enumerate(elements)}
    out = []
    for child in container.get("layoutChildren") or []:
        if isinstance(child, Mapping):
            index = by_id.get(str(child.get("id") or ""))
            if index is not None:
                out.append(index)
    return out


def _rect(element: Mapping[str, Any]) -> list[int]:
    return [
        int(float(element.get("x") or 0)),
        int(float(element.get("y") or 0)),
        int(float(element.get("width") or 0)),
        int(float(element.get("height") or 0)),
    ]


def _uniform_band(image, rows: range, left: int, right: int, fill) -> tuple[bool, float, float]:
    """Is this strip of the picture a flat seam that the container is faking?"""
    import numpy as np

    strip = _array(image)[rows.start : rows.stop, left:right]
    if strip.size == 0:
        return False, 0.0, 0.0
    median = np.median(strip.reshape(-1, 3), axis=0)
    spread = float(strip.reshape(-1, 3).std(axis=0).max())
    distance = 0.0
    if fill is not None:
        distance = float(np.abs(median - np.asarray(fill, dtype=np.float64)).max())
    return spread <= WIREFRAME_BAND_STD and distance > WIREFRAME_FILL_TOLERANCE, spread, distance


def nominate_wireframes(
    elements: Sequence[Mapping[str, Any]],
    truth,
    *,
    k: int = ROUND_TOP_K,
) -> list[Wireframe]:
    """Containers that paint over a seam, and pairs separated by nothing of their own."""
    found: list[Wireframe] = []
    frames = [index for index, element in enumerate(elements) if element.get("layoutChildren")]
    for index in frames:
        container = elements[index]
        kids = _members(elements, container)
        if len(kids) < 2 * WIREFRAME_MIN_SIDE_CHILDREN:
            continue
        fill = _fill_rgb(container)
        x, y, w, h = _rect(container)
        boxes = [(kid, _rect(elements[kid])) for kid in kids]
        # 只看横向切分带：一列卡片的左右切分在版面上比上下少一个数量级，
        # 而误合并几乎总是纵向的（同宽卡片被粘成一条）。
        ordered = sorted(boxes, key=lambda item: item[1][1] + item[1][3] / 2.0)
        for position in range(len(ordered) - 1):
            above = ordered[position][1]
            below = ordered[position + 1][1]
            start = above[1] + above[3]
            end = below[1]
            if end - start < WIREFRAME_MIN_BAND:
                continue
            ok, spread, distance = _uniform_band(truth, range(max(y, start), min(y + h, end)), x, x + w, fill)
            if not ok:
                continue
            found.append(
                Wireframe(
                    index=len(found),
                    op="split",
                    refs=[str(container.get("id") or "")],
                    axis="y",
                    at=(start + end) / 2.0,
                    box=[x, max(y, start), w, min(y + h, end) - max(y, start)],
                    reason=f"band {end - start}px, spread {spread:.1f}, fill差 {distance:.0f}",
                )
            )
            break
    # 合并候选：两个同跨度容器，中间夹着的元素不属于任何一方——那是被劈开的一层。
    containers = [
        index
        for index, element in enumerate(elements)
        if element.get("type") == "container"
    ]
    for first in containers:
        for second in containers:
            if second <= first:
                continue
            a, b = _rect(elements[first]), _rect(elements[second])
            if abs(a[0] - b[0]) > 2 or abs(a[2] - b[2]) > 2:
                continue
            gap_start, gap_end = min(a[1] + a[3], b[1] + b[3]), max(a[1], b[1])
            if gap_end - gap_start < 0:
                continue
            if gap_end - gap_start == 0:
                # 无缝相接的两块：那就是一块，没有孩子夹在中间可依据。
                continue
            inside = [
                kid
                for kid in range(len(elements))
                if elements[kid].get("type") != "container"
                and _rect(elements[kid])[1] >= gap_start - 1
                and _rect(elements[kid])[1] + _rect(elements[kid])[3] <= gap_end + 1
                and _rect(elements[kid])[0] >= a[0] - 1
                and _rect(elements[kid])[0] + _rect(elements[kid])[2] <= a[0] + a[2] + 1
            ]
            if not inside:
                continue
            # 缝必须被这些元素整个盖住：盖不满，合并后容器的底色就会从两侧漏出来，
            # 那是把一个结构问题换成一个像素问题。实测：缝宽 80、夹着 40 宽的芯片，
            # 合并后该带误差从 0 涨到 110。
            covered_width = sum(_rect(elements[kid])[2] for kid in inside)
            if covered_width < 0.95 * a[2]:
                continue
            found.append(
                Wireframe(
                    index=len(found),
                    op="merge",
                    refs=[str(elements[first].get("id") or ""), str(elements[second].get("id") or "")],
                    axis="y",
                    at=(gap_start + gap_end) / 2.0,
                    box=[a[0], gap_start, a[2], max(1, gap_end - gap_start)],
                    reason=f"gap {gap_end - gap_start}px 夹着 {len(inside)} 个元素",
                )
            )
    found.sort(key=lambda item: -item.box[3])
    for position, item in enumerate(found[:k]):
        item.index = position
    return found[:k]


def wireframe_panel(truth, drawn, elements: Sequence[Mapping[str, Any]], wireframe: Wireframe):
    """2× 对照 + 线框：容器一圈、成员各一圈，让"谁套着谁"在图上就能读出来。"""
    import cv2
    import numpy as np

    x, y, w, h = wireframe.box
    height, width = _array(truth).shape[:2]
    pad = ROUND_PAD
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(width, x + w + pad), min(height, y + h + pad)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return np.full((24, 24, 3), 255, dtype=np.uint8)
    panels = []
    for picture in (truth, drawn):
        crop = cv2.resize(
            _array(picture)[y0:y1, x0:x1].astype(np.uint8), None,
            fx=ROUND_ZOOM, fy=ROUND_ZOOM, interpolation=cv2.INTER_NEAREST,
        )
        panels.append(crop)
    drawn_wire = False
    for panel in panels:
        colour = (36, 96, 220) if not drawn_wire else (220, 60, 36)
        for ref in wireframe.refs:
            host = next((item for item in elements if str(item.get("id") or "") == ref), None)
            if host is None:
                continue
            hx, hy, hw, hh = _rect(host)
            cv2.rectangle(
                panel,
                (int((hx - x0) * ROUND_ZOOM), int((hy - y0) * ROUND_ZOOM)),
                (int((hx + hw - x0) * ROUND_ZOOM), int((hy + hh - y0) * ROUND_ZOOM)),
                colour,
                1,
            )
            for kid in _members(elements, host):
                kx, ky, kw, kh = _rect(elements[kid])
                cv2.rectangle(
                    panel,
                    (int((kx - x0) * ROUND_ZOOM), int((ky - y0) * ROUND_ZOOM)),
                    (int((kx + kw - x0) * ROUND_ZOOM), int((ky + kh - y0) * ROUND_ZOOM)),
                    (120, 120, 120),
                    1,
                )
        if wireframe.op == "split":
            row = int((wireframe.at - y0) * ROUND_ZOOM)
            cv2.line(panel, (0, row), (panel.shape[1] - 1, row), (20, 160, 20), 1)
        drawn_wire = True
    return _wrap_ruler(_side_by_side(panels[0], panels[1]))


def wireframe_prompt(candidates: Sequence[Wireframe]) -> str:
    listing = json.dumps([item.as_dict() for item in candidates], ensure_ascii=False)
    return (
        f"图 1..{len(candidates)} 是{len(candidates)}处结构可疑区域的 2× 对照：左原图、右当前渲染，"
        "蓝框是容器、灰框是它的成员，绿线是建议的切分位置；外围刻度单位是原图像素。\n"
        f"候选：{listing}\n"
        "对每一处只回答：这个容器的范围对不对？只接受两种动作——\n"
        '{"wireframes":[{"index":0,"op":"split","at":312,"reason":"..."}]}\n'
        '{"wireframes":[{"index":1,"op":"merge","reason":"..."}]}\n'
        "op=split 表示候选给出的那条线应该切开（at 可微调，单位原图像素）；"
        "op=merge 表示两个容器是同一层；不需要动的直接省略。不要发明候选以外的动作。"
    )


def parse_wireframe_answers(payload: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for raw in payload.get("wireframes") or []:
        if not isinstance(raw, Mapping):
            continue
        try:
            index = int(raw.get("index"))
        except (TypeError, ValueError):
            continue
        op = str(raw.get("op") or "")
        if op not in ("split", "merge"):
            continue
        out[index] = {"op": op}
    return out


def apply_split(elements: list[dict[str, Any]], wireframe: Wireframe) -> bool:
    """在缝处切开：上段止于缝的上沿，下段始于缝的下沿。

    简单地把盒子一分为二（上半 + 下半）像素一点都不会变——两半仍然连在一起，
    缝还是被涂着的。要修的是"容器替页面画了一条它没有的底"，所以切完必须让
    那条缝露出来：上段到缝的上沿为止，下段从缝的下沿开始。
    """
    import copy

    ref = wireframe.refs[0] if wireframe.refs else ""
    index = next(
        (position for position, item in enumerate(elements) if str(item.get("id") or "") == ref),
        None,
    )
    if index is None:
        return False
    container = elements[index]
    x, y, w, h = _rect(container)
    band_top = max(y, int(round(wireframe.box[1])))
    band_bottom = min(y + h, int(round(wireframe.box[1] + wireframe.box[3])))
    if band_top <= y or band_bottom >= y + h:
        # 缝贴着头或尾：切出来是一段空壳，不是两层。
        return False
    kids = _members(elements, container)
    above, below = [], []
    for kid in kids:
        kx, ky, kw, kh = _rect(elements[kid])
        (above if ky + kh / 2.0 < band_top else below).append(kid)
    if len(above) < WIREFRAME_MIN_SIDE_CHILDREN or len(below) < WIREFRAME_MIN_SIDE_CHILDREN:
        return False
    lower = copy.deepcopy(container)
    lower["id"] = f"{ref}:split"
    lower["y"] = float(band_bottom)
    lower["height"] = float(y + h - band_bottom)
    lower.pop("layout", None)
    lower["layoutChildren"] = [{"id": str(elements[kid].get("id") or "")} for kid in below]
    container["height"] = float(band_top - y)
    container.pop("layout", None)
    container["layoutChildren"] = [{"id": str(elements[kid].get("id") or "")} for kid in above]
    elements.insert(index + 1, lower)
    return True


def apply_merge(elements: list[dict[str, Any]], wireframe: Wireframe) -> bool:
    """两个同跨度容器并成一个；被并掉的那个只留下成员，成员不动。"""
    ids = list(wireframe.refs)
    if len(ids) < 2:
        return False
    upper = next((item for item in elements if str(item.get("id") or "") == ids[0]), None)
    lower = next((item for item in elements if str(item.get("id") or "") == ids[1]), None)
    if upper is None or lower is None or upper is lower:
        return False
    a, b = _rect(upper), _rect(lower)
    if abs(a[0] - b[0]) > 2 or abs(a[2] - b[2]) > 2:
        return False
    top = min(a[1], b[1])
    bottom = max(a[1] + a[3], b[1] + b[3])
    merged: list[dict[str, str]] = []
    for host in (upper, lower):
        for kid in host.get("layoutChildren") or []:
            if isinstance(kid, Mapping):
                merged.append({"id": str(kid.get("id") or "")})
    upper["y"] = float(top)
    upper["height"] = float(bottom - top)
    upper.pop("layout", None)
    upper["layoutChildren"] = merged
    elements.remove(lower)
    return True


def check_wireframe(
    elements: Sequence[Mapping[str, Any]],
    wireframe: Wireframe,
    *,
    before: Mapping[str, int],
    after: Mapping[str, int],
    band_error: tuple[float, float],
) -> list[str]:
    """The invariants a structural edit may not break.

    A split is only worth doing if the band it exposes was being painted wrong;
    a merge is only safe if it does not start painting over what used to show
    through.  Everything else — members, frames, buried words — is absolute.
    """
    failures: list[str] = []
    if int(after.get("covered", 0)) > int(before.get("covered", 0)):
        failures.append("text-buried")
    if int(after.get("collisions", 0)) > int(before.get("collisions", 0)):
        failures.append("new-collision")
    expected = int(before.get("frames", 0)) + (1 if wireframe.op == "split" else -1)
    if int(after.get("frames", 0)) != expected:
        failures.append("frames-wrong")
    before_error, after_error = band_error
    if wireframe.op == "split":
        if not after_error < before_error:
            failures.append("band-not-better")
    elif after_error > before_error:
        failures.append("band-worse")
    return failures


def refine_structure(
    elements: list[dict[str, Any]],
    truth,
    draw: Callable[[list[dict[str, Any]]], Any],
    *,
    propose: Callable[[Sequence[Wireframe], Sequence[Any]], Mapping[str, Any]] | None,
    k: int = ROUND_TOP_K,
    audit: Callable[[Sequence[Mapping[str, Any]]], Mapping[str, int]] | None = None,
) -> dict[str, Any]:
    """One structural pass: nominate, ask, apply, re-draw, keep only what held."""
    import copy

    inspect = audit or audit_structure
    report: dict[str, Any] = {"candidates": 0, "kept": 0, "rolledBack": 0, "log": []}
    if propose is None:
        report["skipped"] = "no-vision"
        return report
    drawn = draw(list(elements))
    candidates = nominate_wireframes(elements, truth, k=k)
    report["candidates"] = len(candidates)
    if not candidates:
        return report
    panels = [wireframe_panel(truth, drawn, elements, item) for item in candidates]
    answers = parse_wireframe_answers(propose(candidates, panels) or {})
    for candidate in candidates:
        answer = answers.get(candidate.index)
        if not answer or answer.get("op") != candidate.op:
            candidate.status = "declined"
            continue
        snapshot = copy.deepcopy(elements)
        before_state = inspect(elements)
        before_error = roi_error(truth, drawn, candidate.box)
        applied = (
            apply_split(elements, candidate)
            if candidate.op == "split"
            else apply_merge(elements, candidate)
        )
        if not applied:
            elements[:] = snapshot
            candidate.status = "rolled-back:not-applicable"
            report["rolledBack"] += 1
            continue
        after_drawn = draw(list(elements))
        after_state = inspect(elements)
        after_error = roi_error(truth, after_drawn, candidate.box)
        failures = check_wireframe(
            elements,
            candidate,
            before=before_state,
            after=after_state,
            band_error=(before_error, after_error),
        )
        if failures:
            elements[:] = snapshot
            candidate.status = "rolled-back:" + ",".join(failures)
            report["rolledBack"] += 1
        else:
            candidate.status = "kept"
            report["kept"] += 1
        report["log"].append(
            {
                "op": candidate.op,
                "refs": candidate.refs,
                "status": candidate.status,
                "band": [round(before_error, 2), round(after_error, 2)],
            }
        )
    return report
