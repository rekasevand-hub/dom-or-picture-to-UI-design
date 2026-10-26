"""Report independent text quality dimensions for the frozen DOM corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.evidence.dom_text_quality import (  # noqa: E402
    evaluate_text_nodes,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate text/layout/font dimensions without a composite score."
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
    parser.add_argument(
        "--capture-root",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
    )
    return parser


def build_report(
    corpus: Mapping[str, Any],
    capture_root: str | Path,
) -> dict[str, Any]:
    root = Path(capture_root)
    thresholds = corpus.get("thresholds") or {}
    samples: list[dict[str, Any]] = []
    for sample in corpus.get("samples") or []:
        sample_id = str(sample.get("sample_id") or "")
        dom_path = root / sample_id / "00_dom.json"
        try:
            dom = json.loads(dom_path.read_text(encoding="utf-8"))
            if not isinstance(dom, list):
                raise ValueError("DOM must be an array")
            evaluation = evaluate_text_nodes(dom, thresholds)
            critical_text = _critical_text_check(sample, dom)
            hard_fail = critical_text["status"] == "fail" or any(
                evaluation["dimensions"][name]["status"] == "fail"
                for name in ("content", "linebreak", "box")
            )
            samples.append(
                {
                    "sample_id": sample_id,
                    "status": "fail" if hard_fail else "partial",
                    "hard_fail": hard_fail,
                    "critical_text": critical_text,
                    "dimensions": evaluation["dimensions"],
                    "text_node_count": evaluation["text_node_count"],
                    "nodes": evaluation["nodes"],
                    "dom_path": str(dom_path),
                }
            )
        except Exception as exc:  # noqa: BLE001 - preserve per-sample failure
            samples.append(
                {
                    "sample_id": sample_id,
                    "status": "fail",
                    "hard_fail": True,
                    "error": f"{type(exc).__name__}: {exc}",
                    "dom_path": str(dom_path),
                }
            )
    hard_gate_failed = any(item["hard_fail"] for item in samples)
    return {
        "schema_version": "dom-text-quality-report/1.0",
        "corpus_id": corpus.get("corpus_id"),
        "capture_root": str(root),
        "status": "fail" if hard_gate_failed else "partial",
        "hard_gate_failed": hard_gate_failed,
        "composite_score_used": False,
        "sample_count": len(samples),
        "required_sample_fail_count": sum(item["hard_fail"] for item in samples),
        "samples": samples,
        "non_claims": [
            "Canvas font metrics provide a derived baseline, not direct glyph-baseline identity.",
            "CDP platform fonts provide face and glyph-count evidence, not outline identity.",
            "This report does not perform Figma write/readback acceptance.",
        ],
    }


def _critical_text_check(
    sample: Mapping[str, Any],
    dom: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    measured_parts: list[str] = []
    for node in dom:
        lines = [
            str(line.get("text") or "")
            for line in node.get("textLines") or []
            if isinstance(line, Mapping) and str(line.get("text") or "").strip()
        ]
        if lines:
            measured_parts.extend(lines)
        elif str(node.get("text") or "").strip():
            measured_parts.append(str(node.get("text") or ""))
    haystack = "\n".join(measured_parts).casefold()
    required = [str(value) for value in sample.get("required_text") or []]
    missing = [value for value in required if value.casefold() not in haystack]
    return {
        "status": "pass" if not missing else "fail",
        "required": required,
        "missing": missing,
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
        report = build_report(corpus, args.capture_root)
        _write_json(args.out / "summary.json", report)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "hard_gate_failed": report["hard_gate_failed"],
                    "sample_count": report["sample_count"],
                },
                ensure_ascii=False,
            )
        )
        return 1 if report["hard_gate_failed"] else 0
    except Exception as exc:  # noqa: BLE001 - CLI has one typed failure
        print(
            json.dumps(
                {"status": "error", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
