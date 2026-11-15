"""物理分权感知的 prepare 入口：OCR + OmniParser + CV → 场景计划。

与 ``image_figma_mvp.py --prepare-only`` 写同一组文件（``image_reference.json`` /
``10_pagegraph.json`` / ``11_scene_plan.json`` / ``ocr_supplement.json``），所以
``holdout_replay.py`` 不用改一行就能把这一页交给原来的成帧、装饰、防遮挡与仲裁。

    python scripts/physical_prepare.py --image samples/holdout/holdout_erp.png \
        --out output/_phys_erp --tag holdout_erp
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.structure.image_contract import (  # noqa: E402
    inspect_image_reference,
)
from src.app.services.structure.physical_perception import (  # noqa: E402
    build_physical_plan,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tag", default="")
    parser.add_argument("--omniparser-url", default="http://127.0.0.1:8000")
    parser.add_argument("--no-omniparser", action="store_true")
    args = parser.parse_args()

    image = args.image.resolve()
    pipeline = args.out / "pipeline"
    pipeline.mkdir(parents=True, exist_ok=True)
    reference = inspect_image_reference(image)
    width, height = reference["input"]["size"]

    started = time.time()
    plan, report = build_physical_plan(
        image,
        omniparser_url="" if args.no_omniparser else args.omniparser_url,
        width=width,
        height=height,
    )
    total = time.time() - started

    # 计划里的 text 节点已经全部来自 OCR；这里同时把观测按编译器的口子交出去，
    # 文本度量校准与段落重建读的是同一份基线。
    observations = [
        {
            "text": node["text"],
            "bbox": list(node["bbox"]),
            "confidence": float(node.get("confidence") or 0.0),
            "engine": "easyocr",
        }
        for node in plan["nodes"]
        if node.get("type") == "text" and node.get("text")
    ]
    supplement = {
        "schema_version": "image-ocr-supplement/1.0",
        "status": "applied" if observations else "empty",
        "source": "physical-perception:easyocr",
        "observation_count": len(observations),
        "added_count": len(observations),
        "added": [],
        "observations": observations,
        "languages": ["ch_sim", "en"],
    }

    containers = [
        {
            "id": node["id"],
            "fill": node.get("fill") or "",
            "bbox": node["bbox"],
            "role": node["role"],
            "depth": 0,
            "parent": node.get("parent_id"),
            "elements": [],
            "confidence": 1.0,
            "source": "physical-perception:cv",
            "overlay": False,
            "zIndex": 0,
            "style": {},
            "contentRef": node.get("content_ref"),
        }
        for node in plan["nodes"]
        if node.get("type") == "container"
    ]
    elements = [
        {
            "id": node["id"],
            "bbox": node["bbox"],
            "type": node["type"],
            "text": node.get("text") or "",
            "role": node.get("role") or "",
            "source": (
                "physical-perception:omniparser"
                if node.get("type") == "image"
                else "physical-perception:easyocr"
            ),
            "caption": node.get("caption") or "",
        }
        for node in plan["nodes"]
        if node.get("type") in ("text", "image")
    ]
    tables = [
        {
            "id": node["id"],
            "bbox": list(node["bbox"]),
            "source_ref": node.get("source_ref") or "",
            "grid": dict(node.get("grid") or {}),
        }
        for node in plan["nodes"]
        if node.get("type") == "table"
    ]
    graph = {
        "image": str(image),
        "image_w": width,
        "image_h": height,
        "route": "physical",
        "containers": containers,
        "elements": elements,
        "tables": tables,
        "provenance": {
            "perception": {
                "mode": "physical",
                "sources": ["easyocr", "omniparser", "cv-probe"],
                "report": report.as_dict(),
                "shell_seconds": round(total, 2),
            }
        },
        "scenePlan": plan,
    }

    (pipeline / "image_reference.json").write_text(
        json.dumps(reference, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (pipeline / "11_scene_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (pipeline / "ocr_supplement.json").write_text(
        json.dumps(supplement, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (pipeline / "10_pagegraph.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (pipeline / "prepared.json").write_text(
        json.dumps({"sample_id": args.tag or image.stem}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
