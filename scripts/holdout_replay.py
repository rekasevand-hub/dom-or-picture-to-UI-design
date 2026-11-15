"""Cold-start a *new* screenshot through the same default chain as the seven.

Perception is the only stage that needs the model; ``image_figma_mvp.py
--prepare-only`` already ran it and left a pipeline directory.  From there this
driver hands the page to ``replay_pagegraph.replay`` with the same defaults the
frozen samples use — text calibration, the two-stage judge, residual patches —
so a holdout is measured by the shipped pipeline, not by a copy of it.

    python scripts/holdout_replay.py holdout_erp output/_prep_erp

Nothing here may set a flag, threshold or font: the point of the exercise is to
find out what the defaults do on a page they have never seen.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
for _path in (ROOT, SCRIPTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import replay_pagegraph as rp  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    parser.add_argument("prepared", help="directory that holds pipeline/ from --prepare-only")
    parser.add_argument("--out-suffix", default="_holdout")
    parser.add_argument("--no-arbiter", action="store_true")
    args = parser.parse_args()

    prepared = Path(args.prepared)
    pipeline = prepared / "pipeline"
    if not (pipeline / "10_pagegraph.json").is_file():
        print(f"missing 10_pagegraph.json under {pipeline}", file=sys.stderr)
        return 2
    rp.SAMPLES[args.tag] = str(prepared)
    started = time.time()
    report = rp.replay(
        args.tag,
        args.out_suffix,
        patches=True,
        calibrate_text=True,
        arbiter=not args.no_arbiter,
        fresh=True,
    )
    report["seconds"] = round(time.time() - started, 1)
    out = ROOT / "output" / f"{args.out_suffix}_{args.tag}" / "pipeline"
    (out / "holdout_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
