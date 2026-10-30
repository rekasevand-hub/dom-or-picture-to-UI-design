from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def test_figma_bridge_materializes_structured_linear_gradient():
    node = shutil.which("node")
    assert node is not None, "node is required for the Figma bridge gradient test"
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "tests" / "bridge" / "test_gradient_fills.js"
    result = subprocess.run(
        [node, str(script)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "gradient fills materialized" in result.stdout
