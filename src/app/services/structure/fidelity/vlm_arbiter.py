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
)
#: 两个文本框重叠超过较小者面积的这个比例，就算 A 压 B。
COLLISION_SHARE = 0.45
#: 整页图缩到这个宽度再送模型：它要看排版，不需要数清每一个像素。
MACRO_WIDTH = 1440


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

    def validate(self) -> None:
        if self.type not in DESIGN_TICKETS:
            raise ValueError(f"unknown design ticket: {self.type}")
        if self.type == "MISSING_TEXT_BLOCK" and len(self.roi_bbox) != 4:
            raise ValueError("MISSING_TEXT_BLOCK needs roi_bbox")
        if self.type in ("TEXT_COLLISION_OR_DRIFT", "TYPOGRAPHY_HIERARCHY") and not self.ref:
            raise ValueError(f"{self.type} needs ref")


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


def design_prompt(digest: str) -> str:
    return (
        "图 1 是整页对比（左原图、右当前 Figma 渲染），图 2/3/4 分别是上/中/下三段，"
        "都是 1:1 原尺寸，左原图右渲染。\n"
        "判断标准是**设计神似**，不是逐像素相等：排版、间距、容器完整、图标、字重字号层级、"
        "整体风格要还原。允许字形有细微差别，但下面六类观感问题必须指出：\n"
        "1 漏掉明显的文字块或副标题；2 文字明显偏移或互相重叠（A 压 B、同文双影）；"
        "3 图标/Logo/印章不完整；4 悬浮小窗结构或零件残缺；"
        "5 标题/价格/导航的字重字号层级不对；6 容器大小异常或同层互相挤占越界。\n"
        f"当前页面骨架（容器的 ref/bbox，文字的 ref/bbox/内容/字号/字重）：\n{digest}\n"
        "只输出 JSON，不要解释：\n"
        '{"tickets":[\n'
        '{"type":"MISSING_TEXT_BLOCK","roi_bbox":[x,y,w,h],"text":"应该出现的文字","note":"依据"},\n'
        '{"type":"TEXT_COLLISION_OR_DRIFT","ref":"<文字的 contentRef>","fix":"remove|nudge","dx":0,"dy":0,"note":"..."},\n'
        '{"type":"INCOMPLETE_GRAPHIC_OR_WIDGET","roi_bbox":[x,y,w,h],"fix":"pill|border","note":"..."},\n'
        '{"type":"TYPOGRAPHY_HIERARCHY","ref":"<文字的 contentRef>","fix":"bold|bigger|both","note":"..."},\n'
        '{"type":"CONTAINER_CROWDING","ref":"<容器的 contentRef>","fix":"clamp","note":"..."}\n'
        "]}\n"
        "最多 6 条，只报确实影响观感的；坐标用原图像素，ref 必须来自上面的清单。"
    )


def parse_design_tickets(payload: Mapping[str, Any]) -> list[DesignTicket]:
    tickets: list[DesignTicket] = []
    for raw in (payload.get("tickets") or [])[:6]:
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
            )
            ticket.validate()
        except (TypeError, ValueError):
            continue
        tickets.append(ticket)
    return tickets


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
    return None


def _design_missing_text(ticket: DesignTicket, elements: list[dict[str, Any]], truth):
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
    size = max(8.0, round(float(rows[-1] - rows[0] + 1) * 0.95 * 2) / 2)
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
            "height": float(rows[-1] - rows[0] + 1),
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


def _design_widget(ticket: DesignTicket, elements: list[dict[str, Any]], truth):
    import numpy as np

    x, y, w, h = (int(value) for value in ticket.roi_bbox)
    height, width = truth.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 12 or y1 - y0 < 12:
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
    # 放在最前面：底框必须在文字之下，不能盖住已经画好的内容。
    elements.insert(
        0,
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

    @property
    def failures(self) -> list[str]:
        failed = []
        if self.frames < self.frames_floor:
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
