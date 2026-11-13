# -*- coding: utf-8 -*-
"""Two-node probe: does a child land where the spec asked, inside a parent?

The specs carry *page* coordinates.  ``appendChild`` reinterprets them as
parent-local, so before 2026-11-13 a child asked for at x=30100 inside a frame
at x=30000 landed at 60100 -- invisible while every node hung off the root, and
fatal the moment Phase 5 introduces child frames.

Run it after syncing ``figma_bridge/code.js`` and reloading the plugin:

    python scripts/probe_parent_geometry.py

Pass means: given a frame at (31000, 0), a child asked for at the absolute point
(31100, 50) reads back as local (100, 50).  The script also refuses to judge a
plugin whose ``BRIDGE_BUILD`` differs from the repository's, because a stale
plugin would answer for the old code and the result would be meaningless.

The nodes it creates are named ``PROBE``; the bridge has no delete command, so
remove them by hand afterwards.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.export_gold_tree import _connect  # noqa: E402

BUILD_PATTERN = re.compile(r"""BRIDGE_BUILD\s*=\s*["']([^"']+)["']""")
ORIGIN = (31000.0, 0.0)
CASES = (("A", 31100.0, 50.0, 100.0, 50.0), ("B", 31050.0, 70.0, 50.0, 70.0))


def _expected_build() -> str | None:
    source = (ROOT / "figma_bridge" / "code.js").read_text(encoding="utf-8")
    match = BUILD_PATTERN.search(source)
    return match.group(1) if match else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default=None, help="write the result here")
    args = parser.parse_args(argv)

    expected = _expected_build()
    adapter = _connect()
    created: list[str] = []
    result: dict[str, object] = {"expected_build": expected, "cases": []}
    try:
        frame_id = adapter._send(
            "create_frame",
            {
                "name": "PROBE · parent geometry (可删)",
                "x": ORIGIN[0],
                "y": ORIGIN[1],
                "width": 200,
                "height": 120,
                "fillColor": "#ffffff",
            },
        )
        created.append(frame_id)
        for label, ax, ay, want_x, want_y in CASES:
            node_id = adapter._send(
                "create_rectangle",
                {
                    "parentId": frame_id,
                    "name": f"PROBE · child {label} (可删)",
                    "x": ax,
                    "y": ay,
                    "width": 40,
                    "height": 30,
                    "fillColor": "#ff0000",
                },
            )
            created.append(node_id)

        tree = adapter._send("get_node_tree", {"nodeId": frame_id, "depth": 2})
        build = tree.get("bridgeBuild")
        result["plugin_build"] = build
        children = {
            str(child.get("name")): child for child in tree.get("children") or []
        }
        ok = build == expected
        for label, ax, ay, want_x, want_y in CASES:
            child = children.get(f"PROBE · child {label} (可删)") or {}
            got = (child.get("x"), child.get("y"))
            case_ok = got == (want_x, want_y)
            ok = ok and case_ok
            result["cases"].append(
                {
                    "label": label,
                    "asked_absolute": [ax, ay],
                    "expected_local": [want_x, want_y],
                    "read_back": list(got),
                    "ok": case_ok,
                }
            )
            print(
                f"  child {label}: 绝对 ({ax:.0f}, {ay:.0f}) -> "
                f"期望局部 ({want_x:.0f}, {want_y:.0f})，回读 {got}  "
                f"{'OK' if case_ok else 'FAIL'}"
            )
        if build != expected:
            print(
                f"[stale] 插件报 {build}，仓库是 {expected}：先在 Figma 里重载插件，"
                "否则这一跑回答的是旧代码"
            )
        print(f"[frame] {frame_id}（连同两个 PROBE 子节点，请手动删）")
        print("RESULT", "PASS" if ok else "FAIL")
        result["ok"] = ok
    finally:
        try:
            adapter.ws.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass

    if args.json:
        Path(args.json).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
