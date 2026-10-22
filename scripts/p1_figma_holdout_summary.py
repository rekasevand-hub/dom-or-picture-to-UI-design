# -*- coding: utf-8 -*-
"""Summarize independent Figma holdout acceptance reports without scoring."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


def summarize_acceptance_reports(
    reports: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    rows = []
    failed = []
    for report in reports:
        design_path = str(
            ((report.get("inputs") or {}).get("design") or {}).get("path") or ""
        )
        sample_id = Path(design_path).parent.name or "unknown"
        dimensions = {
            name: str((item or {}).get("status") or "unknown")
            for name, item in (report.get("dimensions") or {}).items()
        }
        visual = report.get("checks", {}).get("visual") or {}
        row = {
            "sample_id": sample_id,
            "acceptance_status": str(report.get("acceptance_status") or "unknown"),
            "figma_evaluated_count": int(report.get("figma_evaluated_count") or 0),
            "dimensions": dimensions,
            "failed_metrics": list(visual.get("failed_metrics") or []),
            "visual_metrics": visual.get("metrics") or {},
        }
        rows.append(row)
        if row["acceptance_status"] not in {"pass", "partial"}:
            failed.append(row)
    return {
        "schema_version": "p1-figma-holdout-summary/1.0",
        "sample_count": len(rows),
        "pass_count": sum(row["acceptance_status"] == "pass" for row in rows),
        "partial_count": sum(row["acceptance_status"] == "partial" for row in rows),
        "blocked_count": sum(
            row["acceptance_status"] not in {"pass", "partial"} for row in rows
        ),
        "figma_evaluated_count": sum(row["figma_evaluated_count"] for row in rows),
        "failed_samples": failed,
        "samples": rows,
        "composite_score_used": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="append", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    report_paths = [Path(value).resolve() for value in args.report]
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in report_paths]
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    artifact = {
        "experiment": "P1-FIGMA-HOLDOUT-SUMMARY",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **summarize_acceptance_reports(reports),
        "inputs": [
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in report_paths
        ],
    }
    payload = {key: value for key, value in artifact.items() if key != "content_hash"}
    artifact["content_hash"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    out_path = out / "round1.json"
    out_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        "[holdout] %d pass / %d partial / %d blocked; evaluated=%d"
        % (
            artifact["pass_count"],
            artifact["partial_count"],
            artifact["blocked_count"],
            artifact["figma_evaluated_count"],
        )
    )
    for item in artifact["failed_samples"]:
        print(
            "  [blocked] %s %s"
            % (item["sample_id"], ",".join(item["failed_metrics"]) or "-")
        )
    print("[out    ] %s" % out_path)
    return 0 if artifact["blocked_count"] == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
