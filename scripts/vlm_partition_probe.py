"""VLM 语义分区探针（只读）：让模型提分组，让 `resolve_frames` 判生死。

为什么不用自己写的校验器验收：`resolve_frames` 的四条守门（成员在后、成员闭包、
单节点、裁剪一致）就是发射端的真实判据。探针另写一套，等于两套判据并存，迟早不一致。

流程：
    元素表 + 截图 → VLM 出扁平分组 → 合成 `mode=NONE` 容器 → paint_order
    → resolve_frames → 逐组 accepted / rejected(+原因)

不连 Figma，不写产物到 pipeline，不改任何门禁。冻结的分区落在
`output/_structure_partition/<family>/partitions.json`，`--replay` 复算不花钱。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.rendering.adapter_base import paint_order, resolve_frames  # noqa: E402
from src.app.services.structure.fidelity.semantic_partition import (  # noqa: E402
    CONTAINER_ID_PREFIX,
    build_partition_containers,
    design_fingerprint,
    validate_partition,
)

BENCH = ROOT / "tests" / "fixtures" / "benchmark_families"
RERUN = ROOT / "output" / "_benchmark_families" / "rerun"
OUT = ROOT / "output" / "_structure_partition"
CACHE = ROOT / "output" / "_vlm_partition_cache"

UNIT_PRICE_RMB = 0.002  # 每张图一次调用；由用户 2026-11-13 指定
PROMPT_VERSION = "partition-v1"

PROMPT = """你在为一套「截图 → Figma」流水线做**结构分组**。给你一张截图和它已识别的元素表，
请把元素按「视觉上属于同一块」分组。

只输出 JSON，不要解释：
{"groups":[{"label":"卡片·昇腾生态","members":[3,4,5]}]}

规则：
1. 每个元素最多进一个组，不要重复。不能发明元素表里没有的下标。
2. 每组至少 2 个、最多 8 个元素。宁可少分，不要硬凑——分错比不分代价大。
3. 只按画面结构分：卡片、工具栏、表单行、表头、导航条、按钮组、列表项、页脚。
   不要把不同区域的元素塞进同一组，哪怕它们长得像。
4. label 用「类别·内容摘要」，不超过 20 字。
5. 不要输出嵌套层级、不要输出坐标、不要输出样式。
6. 元素表里 x/y 是页面绝对坐标，用来判断谁和谁挨着。
7. 如果一个元素自成一区（例如整页背景、独占一行的大标题），不要为它建组。
"""


def _load_env() -> dict[str, str]:
    candidates = [
        ROOT / ".env",
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
    raise SystemExit("没有找到带 VISION_API_KEY 的 .env")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_dir(family_dir: Path) -> Path | None:
    """优先用本轮 rerun 的产物，没有就退回登记的那次运行。"""
    candidate = RERUN / family_dir.name
    if (candidate / "figma_design.json").is_file():
        return candidate
    meta = _read_json(family_dir / "family.json")
    registered = ROOT / str(meta.get("pipeline_run") or "")
    return registered if (registered / "figma_design.json").is_file() else None


def _design_source(run_dir: Path) -> Path:
    """分区必须绑在 mvp 真正会用的那份元素列表上。

    `figma_design.json` 是**校准之后**的终版；mvp 应用分区时是校准**之前**。
    2026-11-13 就是拿终版算分区、套到校准前，89 个元素坐标不同，单页 within30
    从 95.60 掉到 59.37。`--dump-partition-design` 写出的那份才是唯一合法输入。
    """
    dump = run_dir / "figma_design_pre_partition.json"
    return dump if dump.is_file() else run_dir / "figma_design.json"


def _elements(run_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    design = _read_json(_design_source(run_dir))
    return design.get("canvas") or {}, [
        item for item in design.get("elements") or [] if isinstance(item, dict)
    ]


def _table(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只把**有 id** 的元素给模型：没有 id 的成员无法进 `layoutChildren`。"""
    rows: list[dict[str, Any]] = []
    for index, element in enumerate(elements):
        if not element.get("id"):
            continue
        rows.append(
            {
                "index": index,
                "type": str(element.get("type") or "rectangle"),
                "x": int(round(float(element.get("x") or 0))),
                "y": int(round(float(element.get("y") or 0))),
                "w": int(round(float(element.get("width") or 0))),
                "h": int(round(float(element.get("height") or 0))),
                "text": str(element.get("text") or "")[:40],
            }
        )
    return rows


def _image_part(path: Path, max_width: int = 1600) -> tuple[str, str]:
    from PIL import Image

    with Image.open(path) as image:
        image = image.convert("RGB")
        if image.width > max_width:
            ratio = max_width / float(image.width)
            image = image.resize(
                (max_width, max(1, int(round(image.height * ratio)))),
                Image.LANCZOS,
            )
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
    payload = buffer.getvalue()
    sha = hashlib.sha256(payload).hexdigest()[:16]
    return "data:image/png;base64," + base64.b64encode(payload).decode("ascii"), sha


def _parse_json(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _ask(
    client: Any,
    model: str,
    table: list[dict[str, Any]],
    image_url: str,
    hint: str | None,
) -> tuple[dict[str, Any] | None, str]:
    table_text = json.dumps(table, ensure_ascii=False, separators=(",", ":"))
    content: list[dict[str, Any]] = [
        {"type": "text", "text": PROMPT},
        {"type": "text", "text": "元素表：\n" + table_text},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]
    if hint:
        content.insert(0, {"type": "text", "text": "上一次输出不合法：" + hint})
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=4000,
        messages=[{"role": "user", "content": content}],
    )
    raw = (response.choices[0].message.content or "").strip()
    return _parse_json(raw), raw


def _evaluate(
    elements: list[dict[str, Any]],
    partition: Mapping[str, Any],
    canvas: Mapping[str, Any] | None = None,
    close_backing: bool = False,
) -> dict[str, Any]:
    """合成容器 → 真绘制序 → `resolve_frames` 验收。"""
    groups, schema_rejects = validate_partition(partition, len(elements))
    merged, stats = build_partition_containers(
        elements, groups, canvas=canvas, close_backing=close_backing
    )
    ordered = paint_order(merged)
    reasons: dict[int, str] = {}
    frames = resolve_frames(merged, ordered, reasons)

    built: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, element in enumerate(merged):
        element_id = str(element.get("id") or "")
        if not element_id.startswith(CONTAINER_ID_PREFIX):
            continue
        record = {
            "group": element_id[len(CONTAINER_ID_PREFIX) :],
            "label": element.get("name"),
            "members": [item.get("id") for item in element.get("layoutChildren") or []],
            "bbox": [
                element.get("x"),
                element.get("y"),
                element.get("width"),
                element.get("height"),
            ],
        }
        if index in frames:
            built.append(record)
        else:
            record["reason"] = reasons.get(index, "unknown")
            rejected.append(record)

    reason_counts: dict[str, int] = {}
    for item in rejected:
        reason_counts[str(item["reason"])] = (
            reason_counts.get(str(item["reason"]), 0) + 1
        )
    for item in schema_rejects:
        reason = f"schema:{item.reason}"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    return {
        "groups_returned": len(partition.get("groups") or []),
        "groups_valid": len(groups),
        "containers_created": stats.containers_created,
        "frames_built": len(built),
        "groups_rejected": len(rejected) + len(schema_rejects),
        "reason_counts": reason_counts,
        "built": built,
        "rejected": rejected,
    }


def _resolve_run_dir(args: argparse.Namespace, family_dir: Path) -> Path | None:
    """`--run-dir` 优先：单页验证时读的是 `--dump-partition-design` 写出的那份。"""
    if args.run_dir:
        return Path(args.run_dir).resolve()
    return _run_dir(family_dir)


def _process(
    args: argparse.Namespace, family_dir: Path, client: Any, model: str
) -> dict[str, Any]:
    run_dir = _resolve_run_dir(args, family_dir)
    if run_dir is None:
        return {"family": family_dir.name, "status": "no-artifacts"}
    canvas, elements = _elements(run_dir)
    table = _table(elements)
    frozen = OUT / family_dir.name / "partitions.json"

    record: dict[str, Any] = {
        "family": family_dir.name,
        "run_dir": str(run_dir.relative_to(ROOT)),
        "elements": len(elements),
        "groupable": len(table),
        "canvas": [canvas.get("width"), canvas.get("height")],
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "calls": 0,
    }

    if args.replay or (frozen.is_file() and not args.refresh):
        if not frozen.is_file():
            return {**record, "status": "no-frozen-partition"}
        partition = _read_json(frozen)
        record["source"] = "frozen"
        record["partition_path"] = str(frozen.relative_to(ROOT))
    else:
        if args.calls >= args.max_calls:
            return {**record, "status": "skipped-budget"}
        image_url, image_sha = _image_part(family_dir / "reference.png")
        key = hashlib.sha256(
            f"{model}|{PROMPT_VERSION}|{image_sha}|"
            f"{hashlib.sha256(json.dumps(table, sort_keys=True).encode()).hexdigest()[:16]}".encode()
        ).hexdigest()[:20]
        cache_path = CACHE / f"{key}.json"
        started = time.time()
        if cache_path.is_file():
            partition = _read_json(cache_path)
            source = "cache"
        else:
            partition, raw = _ask(client, model, table, image_url, None)
            args.calls += 1
            record["calls"] += 1
            if partition is None:
                partition, raw2 = _ask(
                    client,
                    model,
                    table,
                    image_url,
                    '不是合法 JSON。请只输出 {"groups":[...]}，不要任何解释文字。',
                )
                args.calls += 1
                record["calls"] += 1
                raw = raw2
            if partition is None:
                return {**record, "status": "unparseable", "raw": raw[:600]}
            _write_json(cache_path, partition)
            source = "model"
        record["source"] = source
        record["elapsed_s"] = round(time.time() - started, 1)
        # 分区只对**这份**元素列表成立；指纹写进去，mvp 应用前比对。
        partition["designSha256"] = design_fingerprint(elements)
        _write_json(frozen, partition)
        record["partition_path"] = str(frozen.relative_to(ROOT))

    result = _evaluate(elements, partition, canvas, args.close_backing)
    record.update(result)
    record["close_backing"] = bool(args.close_backing)
    record["status"] = "measured"
    record["cost_rmb"] = round(record["calls"] * UNIT_PRICE_RMB, 4)
    accepted = result["frames_built"]
    total = result["groups_valid"] or 1
    record["accept_rate"] = round(accepted / total, 4)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", action="append", help="restrict to family name(s)")
    parser.add_argument("--replay", action="store_true", help="只用冻结分区，不调模型")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="忽略已冻结分区，重新调模型（默认已有就复用）",
    )
    parser.add_argument(
        "--run-dir",
        default=None,
        help=(
            "read this directory instead of the family's run dir; use it with the "
            "figma_design_pre_partition.json dump from --dump-partition-design"
        ),
    )
    parser.add_argument("--max-calls", type=int, default=15)
    parser.add_argument(
        "--close-backing",
        action="store_true",
        help="把包住整组的底板补进成员（几何闭合，不是语义猜测）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印元素表，不调模型")
    parser.add_argument(
        "--out",
        default=str(OUT / "probe.json"),
        help="probe 汇总输出路径",
    )
    args = parser.parse_args(argv)

    families = sorted(
        (d for d in BENCH.iterdir() if d.is_dir() and (d / "family.json").is_file()),
        key=lambda d: d.name,
    )
    if args.family:
        wanted = set(args.family)
        families = [d for d in families if d.name in wanted]

    if args.dry_run:
        for family_dir in families:
            run_dir = _resolve_run_dir(args, family_dir)
            if run_dir is None:
                print(f"[skip ] {family_dir.name}: 无产物")
                continue
            _, elements = _elements(run_dir)
            table = _table(elements)
            chars = len(json.dumps(table, ensure_ascii=False, separators=(",", ":")))
            print(
                f"[table] {family_dir.name:15s} elements={len(elements):3d} "
                f"groupable={len(table):3d} chars={chars}"
            )
        return 0

    env = _load_env()
    from openai import OpenAI

    client = OpenAI(
        base_url=env["VISION_BASE_URL"],
        api_key=env["VISION_API_KEY"],
        timeout=180.0,
    )
    model = env.get("VISION_MODEL", "gpt-4o")
    args.calls = 0

    records = [_process(args, family_dir, client, model) for family_dir in families]
    _write_json(Path(args.out), {"unit_price_rmb": UNIT_PRICE_RMB, "records": records})

    print()
    header = f"{'family':15s} {'组':>4} {'容器':>5} {'建成':>5} {'接受率':>7} {'调用':>4} {'元':>7}"
    print(header)
    for record in records:
        if record.get("status") != "measured":
            print(f"{record['family']:15s} {record.get('status')}")
            continue
        print(
            f"{record['family']:15s} {record['groups_returned']:4d} "
            f"{record['containers_created']:5d} {record['frames_built']:5d} "
            f"{record['accept_rate'] * 100:6.1f}% {record['calls']:4d} "
            f"{record['cost_rmb']:7.4f}"
        )
    reasons: dict[str, int] = {}
    for record in records:
        for reason, count in (record.get("reason_counts") or {}).items():
            reasons[reason] = reasons.get(reason, 0) + count
    if reasons:
        print("\n拒绝原因：", json.dumps(reasons, ensure_ascii=False, sort_keys=True))
    print(f"\n总调用 {args.calls}，成本 {round(args.calls * UNIT_PRICE_RMB, 4)} 元")
    print(f"报告：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
