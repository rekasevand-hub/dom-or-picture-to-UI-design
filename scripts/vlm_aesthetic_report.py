"""Aesthetic acceptance report: does the render look like the screenshot?

The project's numeric gate answers "how far are the pixels", which is the wrong
question for an approximate-reproduction target: on dark-card-grid it scored
94.7 % while the nav bar was missing an item, one label rendered as ``Agent □``
and a dark button had been filled light.  This script asks a VLM the question
that matches the target, one region at a time:

* hard lines (reject): structure missing/duplicated, role swapped, tofu/garbled
  text, colour inversion, overlap/clipping, invalid type values;
* soft lines (allowed): paraphrase, one type step, hue/lightness drift,
  spacing and radius differences.

It is a **report**, not a gate.  Output is frozen next to the run so a later
reader can replay and diff it, and every call is cached by crop hashes so a
rerun is free.

Usage::

    python scripts/vlm_aesthetic_report.py --family dark-card-grid
    python scripts/vlm_aesthetic_report.py --family light-table --max-regions 8
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import time
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ROOT / "tests/fixtures/benchmark_families"
CACHE = ROOT / "output/_vlm_aesthetic_cache"

PROMPT = """你是 UI 还原质量的验收员。验收目标是"观感近似"，不是像素级复刻：
- 允许：文案细微改写、字号差一档、颜色略有偏差、间距与圆角不同；
- 不允许：结构缺失或重复、角色错位（标题当按钮）、乱码或豆腐块、反色
  （深灰底变浅白底）、文字重叠/裁切/挤压、非法字号字重。

给你两张同区域裁图：图1 = 参考截图，图2 = 还原结果。逐项判断：
1. structure 元素数量与排列（缺失/多余/错位）
2. semantics 角色（导航项/标题/按钮/标签/价格）
3. copy 同语种、同槽位、长度相近（允许改写，禁止乱码）
4. color 前景/背景色族（禁止反色）
5. type 字号/字重档位（允许一档误差，必须合法）
6. jarring 重叠、裁切、挤压、断层、鬼影

只输出 JSON：
{"verdict":"accept|minor|reject",
 "issues":[{"type":"structure|semantics|copy|color|type|jarring",
            "where":"尽量引用可见文案","severity":"low|mid|high","detail":"..."}],
 "summary":"一句话"}
"""


def _load_env() -> dict[str, str]:
    candidates = [
        ROOT / ".env",
        Path(
            r"C:/Users/lzq/WorkBuddy/Worktrees/Figma_auto_agent/"
            r"feature-precise-agent-router-656141e2/.env"
        ),
        Path(r"D:/LLM-Data/Figma_auto_agent/.env"),
    ]
    for path in candidates:
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


def _design_elements(run_dir: Path) -> list[dict[str, Any]]:
    for name in ("pipeline/12_design.json", "figma_design.json"):
        path = run_dir / name
        if path.is_file():
            data = _read_json(path)
            return [item for item in data.get("elements") or [] if isinstance(item, dict)]
    return []


def _boxes_from_elements(elements: list[dict[str, Any]]) -> list[tuple[float, ...]]:
    """Text-bearing owners as (top, bottom, left, right) rows."""
    boxes = []
    for element in elements:
        if not str(element.get("text") or "").strip():
            continue
        if str(element.get("type") or "").lower() not in {
            "text",
            "button",
            "input",
            "link",
        }:
            continue
        try:
            x = float(element.get("x") or 0)
            y = float(element.get("y") or 0)
            w = float(element.get("width") or 0)
            h = float(element.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if w > 0 and h > 0:
            boxes.append((y, y + h, x, x + w))
    return boxes


def _gold_boxes(family_dir: Path, scale: float) -> list[tuple[float, ...]]:
    """Reference-side content, so an element the render never emitted still gets a region."""
    path = family_dir / "gold_tree.json"
    if not path.is_file():
        return []
    tree = _read_json(path)
    # Gold coordinates are page-absolute; zero the root so boxes land in
    # reference space (same trick as the benchmark gate's _flatten_texts).
    tree["x"], tree["y"] = 0, 0
    boxes: list[tuple[float, ...]] = []

    def walk(node: dict[str, Any], ox: float = 0.0, oy: float = 0.0) -> None:
        x = ox + float(node.get("x") or 0)
        y = oy + float(node.get("y") or 0)
        if node.get("type") == "TEXT" and str(node.get("characters") or "").strip():
            w = float(node.get("width") or 0)
            h = float(node.get("height") or 0)
            if w > 0 and h > 0:
                boxes.append((y * scale, (y + h) * scale, x * scale, (x + w) * scale))
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, x, y)

    walk(tree)
    return boxes


def _cluster(boxes: list[tuple[float, ...]], gap: float = 16.0) -> list[list[float]]:
    if not boxes:
        return []
    ordered = sorted(boxes)
    bands: list[list[float]] = []
    for top, bottom, left, right in ordered:
        if bands and top - bands[-1][1] <= gap:
            bands[-1][1] = max(bands[-1][1], bottom)
            bands[-1][2] = min(bands[-1][2], left)
            bands[-1][3] = max(bands[-1][3], right)
        else:
            bands.append([top, bottom, left, right])
    return bands


def _regions(
    run_dir: Path,
    size: tuple[int, int],
    max_regions: int,
    family_dir: Path | None = None,
    gold_scale: float = 1.0,
) -> list[dict[str, Any]]:
    """Cover the render *and* the reference.

    Regions used to come from the design alone, which made missing content
    invisible: the dark footer logo and ``Kimi K3`` were absent from the render,
    so no region ever contained them and the judge could not report them.  The
    gold tree supplies reference-side boxes; bands that no design box covers are
    audited first.
    """
    width, height = size
    design_boxes = _boxes_from_elements(_design_elements(run_dir))
    reference_boxes = (
        _gold_boxes(family_dir, gold_scale) if family_dir is not None else []
    )
    bands = _cluster(design_boxes + reference_boxes)
    if not bands:
        return [{"name": "whole", "x": 0, "y": 0, "width": width, "height": height}]

    design_rects = [
        (box[2], box[0], box[3], box[1]) for box in design_boxes
    ]

    def _covered(band: list[float]) -> bool:
        left, top, right, bottom = band[2], band[0], band[3], band[1]
        area = max(1.0, (right - left) * (bottom - top))
        for rect in design_rects:
            overlap = max(0.0, min(right, rect[2]) - max(left, rect[0])) * max(
                0.0, min(bottom, rect[3]) - max(top, rect[1])
            )
            if overlap / area >= 0.2:
                return True
        return False

    regions: list[dict[str, Any]] = []
    window = 1000
    step = 800
    for index, band in enumerate(bands):
        top, bottom, left, right = band
        y0 = max(0, int(top) - 12)
        y1 = min(height, int(bottom) + 12)
        if y1 - y0 < 24:
            continue
        starts = [max(0, int(left) - 24)]
        while starts[-1] + window < int(right) + 24:
            starts.append(starts[-1] + step)
        for window_index, start in enumerate(starts):
            x0 = start
            x1 = min(width, start + window)
            if x1 - x0 < 80:
                continue
            suffix = f"w{window_index}" if len(starts) > 1 else ""
            regions.append(
                {
                    "name": f"band{index:02d}{suffix}",
                    "x": x0,
                    "y": y0,
                    "width": x1 - x0,
                    "height": y1 - y0,
                    "reference_only": not _covered(band),
                }
            )
    missing = [region for region in regions if region["reference_only"]]
    covered = [region for region in regions if not region["reference_only"]]
    missing.sort(key=lambda r: r["width"] * r["height"], reverse=True)
    covered.sort(key=lambda r: r["width"] * r["height"], reverse=True)
    selected = missing[:6] + covered[: max(1, max_regions - min(6, len(missing)))]
    selected = selected[:max_regions]
    selected.sort(key=lambda r: (r["y"], r["x"]))
    return selected


def _crop(image: Image.Image, region: dict[str, Any], max_width: int = 900) -> Image.Image:
    box = (
        region["x"],
        region["y"],
        region["x"] + region["width"],
        region["y"] + region["height"],
    )
    crop = image.crop(box)
    if crop.width > max_width:
        ratio = max_width / crop.width
        crop = crop.resize((max_width, max(1, int(crop.height * ratio))))
    return crop


def _data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _sha(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return hashlib.sha256(buffer.getvalue()).hexdigest()[:16]


def _parse(raw: str) -> dict[str, Any]:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {"parse_error": True, "raw": raw[:400]}
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {"parse_error": True, "raw": raw[:400]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True)
    parser.add_argument("--run", default=None, help="run dir; default: benchmark rerun")
    parser.add_argument("--max-regions", type=int, default=12)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    family_dir = FAMILIES / args.family
    meta = _read_json(family_dir / "family.json")
    reference_path = family_dir / "reference.png"
    if args.run:
        run_dir = Path(args.run)
    elif (ROOT / "output/_benchmark_families/rerun" / args.family).is_dir():
        run_dir = ROOT / "output/_benchmark_families/rerun" / args.family
    else:
        run_dir = ROOT / str(meta.get("pipeline_run") or "")
    export_path = run_dir / "figma_ink_converged/export.png"
    if not export_path.is_file():
        candidates = sorted(run_dir.glob("figma*/export.png"))
        if not candidates:
            raise SystemExit(f"no export under {run_dir}")
        export_path = candidates[-1]

    reference = Image.open(reference_path).convert("RGB")
    exported = Image.open(export_path).convert("RGB")
    if exported.size != reference.size:
        exported = exported.resize(reference.size)

    gold_scale = float((meta.get("gold") or {}).get("scale_to_reference") or 1.0)
    regions = _regions(
        run_dir, reference.size, args.max_regions, family_dir, gold_scale
    )
    env = _load_env()
    from openai import OpenAI

    client = OpenAI(
        base_url=env["VISION_BASE_URL"],
        api_key=env["VISION_API_KEY"],
        timeout=180.0,
    )
    model = env.get("VISION_MODEL", "gpt-4o")
    prompt_sha = hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()[:12]
    CACHE.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for region in regions:
        ref_crop = _crop(reference, region)
        run_crop = _crop(exported, region)
        key = hashlib.sha256(
            f"{model}|{prompt_sha}|{_sha(ref_crop)}|{_sha(run_crop)}".encode("utf-8")
        ).hexdigest()[:20]
        cache_path = CACHE / f"{key}.json"
        started = time.time()
        if cache_path.is_file():
            payload = _read_json(cache_path)
            source = "cache"
        else:
            try:
                response = client.chat.completions.create(
                    model=model,
                    temperature=0,
                    max_tokens=700,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": PROMPT},
                                {"type": "text", "text": "图1 参考截图："},
                                {"type": "image_url", "image_url": {"url": _data_url(ref_crop)}},
                                {"type": "text", "text": "图2 还原结果："},
                                {"type": "image_url", "image_url": {"url": _data_url(run_crop)}},
                            ],
                        }
                    ],
                )
                raw = (response.choices[0].message.content or "").strip()
                payload = _parse(raw)
                payload["raw"] = raw[:1200]
                cache_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                source = "vlm"
            except Exception as exc:  # noqa: BLE001 - report keeps failures
                payload = {"error": f"{type(exc).__name__}: {exc}"}
                source = "error"
        seconds = round(time.time() - started, 1)
        issues = payload.get("issues") or []
        high = [item for item in issues if item.get("severity") == "high"]
        marker = " ref-only" if region.get("reference_only") else ""
        print(
            f"[{region['name']}{marker}] {source:5s} {seconds:5.1f}s "
            f"verdict={payload.get('verdict')} issues={len(issues)} high={len(high)}"
        )
        record = {
            "region": region,
            "cache_key": key,
            "source": source,
            "seconds": seconds,
            "verdict": payload.get("verdict"),
            "summary": payload.get("summary"),
            "issues": issues,
            "error": payload.get("error"),
        }
        if payload.get("verdict") in {"reject", "minor"}:
            crop_dir = CACHE / "crops"
            crop_dir.mkdir(exist_ok=True)
            ref_crop.save(crop_dir / f"{key}_ref.png")
            run_crop.save(crop_dir / f"{key}_render.png")
        records.append(record)

    counts: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for record in records:
        verdict = str(record.get("verdict") or "error")
        counts[verdict] = counts.get(verdict, 0) + 1
        for issue in record.get("issues") or []:
            key = str(issue.get("type") or "unknown")
            by_type[key] = by_type.get(key, 0) + 1

    report = {
        "schema_version": "vlm-aesthetic-report/1.0",
        "family": args.family,
        "run_dir": str(run_dir),
        "reference": str(reference_path),
        "export": str(export_path),
        "model": model,
        "prompt_sha256": prompt_sha,
        "goal": "approximate likeness; hard lines = structure/role/copy/colour/type/jarring",
        "region_count": len(records),
        "verdicts": counts,
        "non_accept": len(records) - counts.get("accept", 0),
        "issues_by_type": by_type,
        "regions": records,
    }
    out_dir = Path(args.out) if args.out else run_dir / "vlm_aesthetic"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    non_accept = len(records) - counts.get("accept", 0)
    print(
        f"\n{args.family}: {counts.get('accept', 0)} accept / "
        f"{counts.get('minor', 0)} minor / {counts.get('reject', 0)} reject "
        f"| non-accept {non_accept}/{len(records)} | issues {by_type}"
    )
    print(f"report: {out_path}")


if __name__ == "__main__":
    main()
