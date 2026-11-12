"""Adjudicate same-slot conflicts: two different strings in one slot.

The deterministic pass (``resolve_same_slot_conflicts``) only drops provable OCR
concatenations; the rest land in ``font_calibration.json`` under
``same-slot-conflict.unresolved``.  Those are semantic: ``未确认(0)`` vs
``个人信息`` are both plausible readings, and geometry alone cannot say which
belongs at that spot.

This script asks the VLM, but keeps it on a leash:

* it shows the reference crop and the render crop of the same box;
* the model answers which text belongs there and what to do with the other;
* a deterministic vote (which box can actually hold its own text) is computed
  independently;
* only a **drop of a string that repeats elsewhere** is marked ``apply``;
  everything else is ``needs-human``.

There is no relocation path.  An earlier version moved a label to the bbox
recorded in the family's ``gold_tree.json``; that copied gold coordinates into
the pipeline through a benchmark-keyed file, so a benchmark run was not the
pipeline a user would get.  If a label really belongs somewhere else, the move
target has to come from reference-side OCR -- until then it is a human call.

Nothing is written back to the design here: the output is a frozen decision file
(``<run>/conflict_adjudication/decisions.json``) that a later calibration pass
can consume, so the gate stays reproducible.

Usage::

    python scripts/conflict_adjudicator.py --family light-table
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ROOT / "tests/fixtures/benchmark_families"
CACHE = ROOT / "output/_conflict_adjudication_cache"

PROMPT = """你是 UI 还原的仲裁员。参考图里某个位置出现了两个互相重叠的文本候选，
渲染图把它们叠在了一起。请判断参考图该位置真正显示的是哪一个，另一个该怎么办。

候选：
- A: {a}
- B: {b}

规则：
- 只根据参考图（图1）该位置实际显示的内容判断，不要根据渲染图推断；
- 如果两者在参考图里都存在（例如一个在另一个旁边），选 both；
- 对另一个候选：drop（不属于这里）/ move（属于页面别处，只是放错了）/ keep（保留，允许重叠）。

只输出 JSON：
{"keep":"A|B|both","other_action":"drop|move|keep","reason":"一句话"}
"""


def _load_env() -> dict[str, str]:
    for path in (
        ROOT / ".env",
        Path(
            r"C:/Users/lzq/WorkBuddy/Worktrees/Figma_auto_agent/"
            r"feature-precise-agent-router-656141e2/.env"
        ),
        Path(r"D:/LLM-Data/Figma_auto_agent/.env"),
    ):
        if not path.is_file():
            continue
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
        if values.get("VISION_API_KEY"):
            return values
    raise SystemExit("no .env with VISION_API_KEY found")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _conflicts(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "font_calibration.json"
    if not path.is_file():
        return []
    data = _read_json(path)
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("schema_version") == "grounding-same-slot-conflict/1.0":
                found.extend(node.get("unresolved") or [])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return found


def _glyph_width(text: str, size: float) -> float:
    return sum(1.0 if ord(char) > 0x2E80 else 0.55 for char in text) * size


def _geometry_vote(conflict: dict[str, Any], design: dict[str, Any]) -> str | None:
    """Which candidate's box can hold its own text?

    Returns the text of the plausible one, ``None`` when both or neither fit.
    """
    texts = {conflict.get("kept"), conflict.get("conflict")}
    fitting: list[str] = []
    for element in design.get("elements") or []:
        text = str(element.get("text") or "").strip()
        if text not in texts:
            continue
        style = element.get("style") or {}
        size = style.get("fontSize")
        width = float(element.get("width") or 0)
        if not isinstance(size, (int, float)) or width <= 0:
            continue
        if _glyph_width(text, float(size)) / width <= 1.05:
            fitting.append(text)
    return fitting[0] if len(fitting) == 1 else None


def _crop(image: Image.Image, box: list[float], pad: int = 60) -> Image.Image:
    x0 = max(0, int(box[0]) - pad)
    y0 = max(0, int(box[1]) - pad)
    x1 = min(image.width, int(box[0] + box[2]) + pad)
    y1 = min(image.height, int(box[1] + box[3]) + pad)
    crop = image.crop((x0, y0, x1, y1))
    if crop.width > 900:
        ratio = 900 / crop.width
        crop = crop.resize((900, max(1, int(crop.height * ratio))))
    return crop


def _data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True)
    parser.add_argument("--run", default=None)
    args = parser.parse_args()

    family_dir = FAMILIES / args.family
    meta = _read_json(family_dir / "family.json")
    run_dir = (
        Path(args.run)
        if args.run
        else ROOT / "output/_benchmark_families/rerun" / args.family
    )
    if not run_dir.is_dir():
        run_dir = ROOT / str(meta.get("pipeline_run") or "")
    reference_path = family_dir / "reference.png"
    export_path = run_dir / "figma_ink_converged/export.png"
    design_path = run_dir / "pipeline/12_design.json"
    if not export_path.is_file() or not design_path.is_file():
        raise SystemExit(f"missing render or design under {run_dir}")

    conflicts = _conflicts(run_dir)
    if not conflicts:
        print(f"{args.family}: no unresolved conflicts")
        return

    reference = Image.open(reference_path).convert("RGB")
    rendered = Image.open(export_path).convert("RGB")
    if rendered.size != reference.size:
        rendered = rendered.resize(reference.size)
    design = _read_json(design_path)
    occurrences: dict[str, int] = {}
    for element in design.get("elements") or []:
        text = str(element.get("text") or "").strip()
        if text:
            occurrences[text] = occurrences.get(text, 0) + 1
    env = _load_env()
    from openai import OpenAI

    client = OpenAI(
        base_url=env["VISION_BASE_URL"], api_key=env["VISION_API_KEY"], timeout=180.0
    )
    model = env.get("VISION_MODEL", "gpt-4o")
    CACHE.mkdir(parents=True, exist_ok=True)

    decisions: list[dict[str, Any]] = []
    for index, conflict in enumerate(conflicts):
        a = str(conflict.get("kept") or "")
        b = str(conflict.get("conflict") or "")
        box = conflict.get("bbox") or [0, 0, 1, 1]
        ref_crop = _crop(reference, box)
        run_crop = _crop(rendered, box)
        key = hashlib.sha256(
            f"{model}|{a}|{b}|{ref_crop.tobytes()[:2048]}|{run_crop.tobytes()[:2048]}".encode(
                "utf-8"
            )
        ).hexdigest()[:20]
        cache_path = CACHE / f"{key}.json"
        if cache_path.is_file():
            answer = _read_json(cache_path)
            source = "cache"
        else:
            try:
                response = client.chat.completions.create(
                    model=model,
                    temperature=0,
                    max_tokens=300,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": PROMPT.replace("{a}", a).replace("{b}", b),
                                },
                                {"type": "text", "text": "图1 参考截图："},
                                {"type": "image_url", "image_url": {"url": _data_url(ref_crop)}},
                                {"type": "text", "text": "图2 还原结果："},
                                {"type": "image_url", "image_url": {"url": _data_url(run_crop)}},
                            ],
                        }
                    ],
                )
                raw = (response.choices[0].message.content or "").strip()
                start, end = raw.find("{"), raw.rfind("}")
                answer = json.loads(raw[start : end + 1]) if start >= 0 else {}
                answer["raw"] = raw[:400]
                cache_path.write_text(
                    json.dumps(answer, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                source = "vlm"
            except Exception as exc:  # noqa: BLE001 - report failures verbatim
                answer = {"error": f"{type(exc).__name__}: {exc}"}
                source = "error"

        vote = _geometry_vote(conflict, design)
        keep = {"A": a, "B": b, "both": None}.get(str(answer.get("keep")), None)
        other = str(answer.get("other_action") or "")
        drop_text = (b if keep == a else a) if keep else None
        repeats = occurrences.get(drop_text, 0) if drop_text else 0
        # Dropping a unique label deletes content.  Only a repeated string can
        # be removed at this slot without losing it from the page.
        safe = bool(drop_text) and other == "drop" and repeats > 1
        apply = safe
        decisions.append(
            {
                "kept": a,
                "conflict": b,
                "bbox": box,
                "model": {"keep": answer.get("keep"), "other_action": other, "reason": answer.get("reason")},
                "geometry_vote": vote,
                "agreement": bool(keep) and vote is not None and keep == vote,
                "drop_occurrences": repeats,
                "status": "apply" if apply else "needs-human",
                "drop": drop_text if apply else None,
                "source": source,
                "index": index,
            }
        )
        print(
            f"[{index}] {a!r} vs {b!r} -> keep={answer.get('keep')} "
            f"other={other} vote={vote!r} {'APPLY' if apply else 'human'}"
        )

    out_dir = run_dir / "conflict_adjudication"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "conflict-adjudication/1.0",
        "family": args.family,
        "model": model,
        "count": len(decisions),
        "applied": sum(1 for item in decisions if item["status"] == "apply"),
        "decisions": decisions,
    }
    (out_dir / "decisions.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{args.family}: {payload['applied']}/{len(decisions)} auto-applicable -> {out_dir}")


if __name__ == "__main__":
    main()
