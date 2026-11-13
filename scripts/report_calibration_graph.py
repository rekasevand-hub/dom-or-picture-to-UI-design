# -*- coding: utf-8 -*-
"""Print the calibration dependency graph (read-only).

Declaration only: this script reports what each strategy reads and what it
invalidates.  It does not run a calibration, does not render, and cannot change
a number.

Usage:
    python scripts/report_calibration_graph.py
    python scripts/report_calibration_graph.py --json output/_graph.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.app.services.structure.fidelity.calibration_dependency import (  # noqa: E402
    dependency_report,
    validate,
)
from src.app.services.structure.fidelity.calibration_strategies import (  # noqa: E402
    CALIBRATION_GROUPS,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default=None, help="write the full report here")
    args = parser.parse_args(argv)

    problems = validate(CALIBRATION_GROUPS)
    report = dependency_report(CALIBRATION_GROUPS)

    print(f"[groups] {len(CALIBRATION_GROUPS)}")
    for row in report["groups"]:
        flag = "batchable" if row["runs_without_a_render"] else "needs-render"
        print(
            f"  {row['group']:26s} {flag:12s} reads={row['reads'] or ['-']} "
            f"regions={row['regions'] or ['all']}"
        )
        print(f"      strategies: {', '.join(row['strategies'])}")
    print()
    print(f"[design-only strategies] {len(report['design_only_strategies'])}")
    print("  " + ", ".join(sorted(report["design_only_strategies"])))
    print()
    print(
        "[groups that never read a render] "
        f"{report['groups_that_never_read_a_render'] or 'none'}"
    )
    print()
    print("[single-region groups: disjoint clusters may share a round]")
    for region, names in sorted(report["single_region_groups"].items()):
        print(f"  {region:10s} {len(names)} group(s): {names}")
    print(
        "  -> interleaving the clusters saves at most "
        f"{report['round_robin_saving']} render(s); inside a cluster the passes "
        "stay serial"
    )
    if problems:
        print("\n[declaration problems]")
        for problem in problems:
            print("  " + problem)
    if args.json:
        payload = dict(report)
        payload["problems"] = problems
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\n[out] {args.json}")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
