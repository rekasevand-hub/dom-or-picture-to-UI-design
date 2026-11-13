# -*- coding: utf-8 -*-
"""Write the current four-page state machine-readably.

The handoff documents carry the argument; this script carries the numbers.
Every figure in ``docs/STATE.md`` between the generated markers comes from an
``acceptance.json`` on disk plus the ``runtime`` block that the run wrote, so
nothing is transcribed by hand -- the 2026-11-12 light-table 96.33 / 95.35 gap
happened because a number was copied once and never re-derived.

Usage:
  python scripts/report_state.py --write docs/STATE.md
  python scripts/report_state.py            # print the block only
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BEGIN = "<!-- BEGIN GENERATED: state -->"
END = "<!-- END GENERATED: state -->"

# 位图覆盖超过这个比例的页面，native-only 与 within30 差距会大到不可比，表里加粗提示。
NATIVE_ONLY_BOLD_RATIO = 0.10

PAGES = (
    ("holdout #4 内容审核", "output/_benchmark_families/rerun/content-review"),
    ("dark-card-grid", "output/_benchmark_families/rerun/dark-card-grid"),
    ("light-form", "output/_benchmark_families/rerun/light-form"),
    ("light-table", "output/_benchmark_families/rerun/light-table"),
    ("atomgit-home", "output/_benchmark_families/rerun/atomgit-home"),
)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _native(acceptance: Mapping[str, Any]) -> Mapping[str, Any]:
    gate = (acceptance.get("native_text_quality") or {}).get("gate") or {}
    return gate.get("nativeText") or {}


def _dimensions(row: Mapping[str, Any]) -> tuple[str, ...]:
    checks = row.get("checks")
    if not isinstance(checks, Mapping):
        return ("missing-ink",) if row.get("status") else ()
    return tuple(sorted(name for name, value in checks.items() if value is False))


def _page(label: str, run_dir: Path) -> dict[str, Any] | None:
    acceptance_path = run_dir / "acceptance.json"
    if not acceptance_path.is_file():
        return None
    acceptance = _load(acceptance_path)
    visual = acceptance.get("visual") or {}
    critical = acceptance.get("critical_text") or {}
    native = _native(acceptance)
    runtime = acceptance.get("runtime") or {}
    native_only = visual.get("native_only") or {}
    quality_path = run_dir / "native_text_quality.json"
    failures: Counter[tuple[str, ...]] = Counter()
    if quality_path.is_file():
        quality = _load(quality_path)
        for row in quality.get("owners") or []:
            if not isinstance(row, Mapping):
                continue
            if row.get("ownerScope") != "critical-gate" or row.get("status") == "pass":
                continue
            failures[_dimensions(row)] += 1
    return {
        "label": label,
        "status": acceptance.get("status"),
        "within30": visual.get("within30_pct"),
        "nativeOnly": (
            {
                "within30": native_only.get("within30_pct"),
                "coveredRatio": native_only.get("covered_pixel_ratio"),
                "regionCount": native_only.get("region_count"),
            }
            if native_only
            else None
        ),
        "criticalPassed": critical.get("matched_count"),
        "criticalTotal": critical.get("required_count"),
        "nativePassed": native.get("ownerPassCount"),
        "nativeTotal": native.get("ownerCount"),
        "bridgeBuild": runtime.get("bridgeBuild"),
        "buildMatches": runtime.get("buildMatches"),
        "gitSha": runtime.get("gitSha"),
        "strategies": runtime.get("strategies") or [],
        "failureCounts": {
            "/".join(key) or "(none)": count for key, count in failures.most_common()
        },
    }


def collect() -> list[dict[str, Any]]:
    pages = []
    for label, relative in PAGES:
        page = _page(label, ROOT / relative)
        if page is not None:
            pages.append(page)
    return pages


def _fmt_pct(value: Any) -> str:
    return f"{value:.2f}" if isinstance(value, (int, float)) else "—"


def _fmt_ratio(value: Any) -> str:
    return f"{value * 100:.1f}%" if isinstance(value, (int, float)) else "—"


def _native_only_lines(pages: list[dict[str, Any]]) -> list[str]:
    """位图覆盖会把 within30 抬高，跨族只认这一列 —— 所以它也必须生成，不能手抄。"""
    lines = [
        "> native-only：把位图覆盖区域从分子分母同时剔除后重算的 within30。跨族只比这一列。",
        "",
        "| 页面 | within30 | native-only | 位图覆盖 |",
        "|---|---|---|---|",
    ]
    for page in pages:
        extra = page.get("nativeOnly") or {}
        covered = extra.get("coveredRatio")
        bold = isinstance(covered, (int, float)) and covered >= NATIVE_ONLY_BOLD_RATIO
        native_only = _fmt_pct(extra.get("within30"))
        coverage = _fmt_ratio(covered)
        if bold:
            native_only, coverage = f"**{native_only}**", f"**{coverage}**"
        lines.append(
            f"| {page['label']} | {_fmt_pct(page['within30'])} | "
            f"{native_only} | {coverage} |"
        )
    return lines


def render_block(pages: list[dict[str, Any]]) -> str:
    lines = [
        BEGIN,
        f"<!-- generated by scripts/report_state.py at "
        f"{datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')} -->",
        "",
        "| 页面 | within30 | critical | native | 构建一致 |",
        "|---|---|---|---|---|",
    ]
    for page in pages:
        within = page["within30"]
        display = f"{within:.2f}" if isinstance(within, (int, float)) else "—"
        native = (
            f"{page['nativePassed']}/{page['nativeTotal']}"
            if page["nativeTotal"]
            else "—"
        )
        build = {True: "是", False: "**否**", None: "未记录"}[page["buildMatches"]]
        lines.append(
            f"| {page['label']} | {display} | "
            f"{page['criticalPassed']}/{page['criticalTotal']} | {native} | {build} |"
        )
    lines.append("")
    lines.extend(_native_only_lines(pages))
    lines.append("")
    lines.append("剩余 native 失败（按缺失维度）：")
    lines.append("")
    for page in pages:
        detail = "、".join(
            f"{key}×{value}" for key, value in page["failureCounts"].items()
        )
        lines.append(f"- **{page['label']}**：{detail or '无'}")
    lines.append("")
    builds = {page["bridgeBuild"] for page in pages}
    shas = {page["gitSha"] for page in pages}
    lines.append(
        "构建："
        + ("、".join(sorted(build for build in builds if build)) or "未记录")
        + "；提交："
        + ("、".join(sorted(sha[:9] for sha in shas if sha)) or "未记录")
    )
    lines.append(END)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", help="markdown file whose marker block is replaced")
    args = parser.parse_args(argv)

    pages = collect()
    if not pages:
        print("no acceptance.json found; run a page first")
        return 1
    block = render_block(pages)
    if not args.write:
        print(block)
        return 0

    target = Path(args.write)
    text = target.read_text(encoding="utf-8") if target.is_file() else ""
    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        tail = rest.split(END, 1)[1]
        text = head + block + tail
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + block + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target} ({len(pages)} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
