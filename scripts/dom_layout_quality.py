"""Report L1/L2/L3 evidence and fixed fallbacks for the DOM corpus."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.evidence.dom_layout_quality import (  # noqa: E402
    evaluate_layout_tree,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report Auto Layout L1/L2/L3 evidence and fixed fallbacks."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=_ROOT
        / "tests"
        / "fixtures"
        / "dom_quality"
        / "real_site_corpus_v1.json",
    )
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def build_layout_report(
    corpus: Mapping[str, Any],
    capture_root: str | Path,
) -> dict[str, Any]:
    root = Path(capture_root)
    thresholds = corpus.get("thresholds") or {}
    samples: list[dict[str, Any]] = []
    total_levels = {
        "l1": {"pass_count": 0},
        "l2": {"pass_count": 0},
        "l3": {"pass_count": 0},
    }
    fallback_reasons: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    container_count = 0
    for sample in corpus.get("samples") or []:
        sample_id = str(sample.get("sample_id") or "")
        dom_path = root / sample_id / "00_dom.json"
        try:
            dom = json.loads(dom_path.read_text(encoding="utf-8"))
            if not isinstance(dom, list):
                raise ValueError("DOM must be an array")
            report = evaluate_layout_tree(dom, thresholds)
            sample_summary = {
                "sample_id": sample_id,
                "status": "current-scope",
                "dom_path": str(dom_path),
                "container_count": report["container_count"],
                "levels": report["levels"],
                "fallback_reasons": report["fallback_reasons"],
                "source_counts": dict(
                    sorted(
                        Counter(
                            item["l1"]["source"]
                            for item in report["decisions"]
                            if item["l1"]["pass"]
                        ).items()
                    )
                ),
                "decisions": report["decisions"],
            }
            samples.append(sample_summary)
            container_count += report["container_count"]
            for name in total_levels:
                total_levels[name]["pass_count"] += report["levels"][name]["pass_count"]
            fallback_reasons.update(report["fallback_reasons"])
            sources.update(sample_summary["source_counts"])
        except Exception as exc:  # noqa: BLE001 - preserve per-sample failure
            samples.append(
                {
                    "sample_id": sample_id,
                    "status": "error",
                    "dom_path": str(dom_path),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    failed = any(item["status"] == "error" for item in samples)
    for item in total_levels.values():
        item["coverage"] = (
            item["pass_count"] / container_count if container_count else 0.0
        )
    return {
        "schema_version": "dom-layout-quality-report/1.0",
        "corpus_id": corpus.get("corpus_id"),
        "capture_root": str(root),
        "status": "error" if failed else "current-scope",
        "composite_score_used": False,
        "sample_count": len(samples),
        "container_count": container_count,
        "levels": total_levels,
        "source_counts": dict(sorted(sources.items())),
        "fallback_reasons": dict(sorted(fallback_reasons.items())),
        "source_behavior": "not-evaluated",
        "parent_propagation": "not-evaluated",
        "figma_runtime": "not-evaluated",
        "samples": samples,
        "non_claims": [
            "Geometry-source layouts preserve static geometry only; they are not CSS semantic flow.",
            "L3 is a bounded local output-contract simulation, not source-browser or Figma runtime evidence.",
            "Parent height propagation is not evaluated in D-005.",
        ],
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        corpus = json.loads(args.manifest.read_text(encoding="utf-8"))
        report = build_layout_report(corpus, args.capture_root)
        _write_json(args.out / "summary.json", report)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "sample_count": report["sample_count"],
                    "container_count": report["container_count"],
                    "levels": report["levels"],
                },
                ensure_ascii=False,
            )
        )
        return 1 if report["status"] == "error" else 0
    except Exception as exc:  # noqa: BLE001 - CLI reports one typed failure
        print(
            json.dumps(
                {"status": "error", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
