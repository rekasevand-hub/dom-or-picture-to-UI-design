from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.evidence.native_text_mask_audit import (
    audit_native_text_masks,
)


def test_native_text_mask_audit_preserves_multiple_roi_measurements(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path in (reference, rendered):
        image = Image.new("RGB", (120, 80), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, 59, 27), fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "type": "text",
                "contentRef": "text:label",
                "text": "Label",
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 40, 8],
                    }
                },
            }
        ]
    }
    output = tmp_path / "audit"

    report = audit_native_text_masks(
        design,
        str(reference),
        str(rendered),
        owner_refs=["text:label"],
        output_dir=str(output),
        halo_px=2,
    )

    owner = report["owners"][0]
    assert report["status"] == "measured"
    assert owner["contentRef"] == "text:label"
    assert set(owner["variants"]) == {"source-bbox", "ink-bbox", "ink-halo"}
    assert owner["variants"]["source-bbox"]["coverage"] == 1.0
    assert owner["variants"]["ink-halo"]["coverage"] == 1.0
    assert (output / "text_label" / "reference_source-bbox.png").is_file()
    assert (output / "text_label" / "rendered_ink-halo.png").is_file()


def test_native_text_mask_audit_cli_writes_report(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path in (reference, rendered):
        image = Image.new("RGB", (80, 50), "white")
        ImageDraw.Draw(image).rectangle((10, 10, 29, 17), fill="black")
        image.save(path)
    design_path = tmp_path / "design.json"
    design_path.write_text(
        json.dumps(
            {
                "elements": [
                    {
                        "type": "text",
                        "contentRef": "text:label",
                        "text": "Label",
                        "styleEvidence": {
                            "evidence": {
                                "source_bbox": [0, 0, 40, 30],
                                "ink_bbox": [10, 10, 20, 8],
                            }
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "cli-audit"
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "native_text_mask_audit.py"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--design",
            str(design_path),
            "--reference",
            str(reference),
            "--rendered",
            str(rendered),
            "--output-dir",
            str(output),
            "--owner-ref",
            "text:label",
        ],
        cwd=script.parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads((output / "native_text_mask_audit.json").read_text("utf-8"))
    assert report["ownerCount"] == 1
    assert report["owners"][0]["contentRef"] == "text:label"
