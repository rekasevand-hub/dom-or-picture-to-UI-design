"""Which renderer produced a run -- checked, not transcribed.

``BRIDGE_BUILD`` lives in ``figma_bridge/code.js`` and comes back in every
readback, but nothing ever compared the two.  On 2026-11-11 a session burned
three rounds on a plugin that had never been reloaded, and the numbers in the
handoff could only be traced by opening a JSON by hand.  The plugin also loads
from a separate checkout, so "what is on disk here" is not "what ran there".

This module is the single comparison point: the expected build is read from
the bridge source, the actual build from the readback, and a run whose plugin
does not match is refused instead of silently producing plausible pixels.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CODE_JS = ROOT / "figma_bridge" / "code.js"
RUNTIME_SCHEMA_VERSION = "image-figma-runtime/1.0"

_BUILD_PATTERN = re.compile(r"""BRIDGE_BUILD\s*=\s*["']([^"']+)["']""")


def expected_bridge_build(code_js: Path | str | None = None) -> str | None:
    """The build stamp declared by the bridge source, if it can be read."""
    path = Path(code_js) if code_js is not None else DEFAULT_CODE_JS
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _BUILD_PATTERN.search(text)
    return match.group(1) if match else None


def readback_bridge_build(readback: Mapping[str, Any]) -> str | None:
    """The build stamp the plugin reported when it answered the readback."""
    value = readback.get("bridgeBuild")
    return str(value) if value else None


def _git(*args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = completed.stdout.strip()
    return text or None


def git_identity() -> dict[str, Any]:
    """Where this run came from; ``None`` when the tree is not a checkout."""
    status = _git("status", "--porcelain")
    return {
        "gitSha": _git("rev-parse", "HEAD"),
        "gitBranch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "gitDirty": bool(status),
    }


def runtime_identity(
    *,
    readback: Mapping[str, Any],
    strategies: Sequence[str] | None = None,
    code_js: Path | str | None = None,
) -> dict[str, Any]:
    """Attach the run to a renderer build, a commit, and a set of strategies.

    ``buildMatches`` is only true when both stamps are known and equal -- a
    missing stamp is not a match, it is an unverified run.
    """
    actual = readback_bridge_build(readback)
    expected = expected_bridge_build(code_js)
    return {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "bridgeBuild": actual,
        "expectedBridgeBuild": expected,
        "buildMatches": bool(actual and expected and actual == expected),
        "strategies": list(strategies or []),
        **git_identity(),
    }


def build_mismatch(runtime: Mapping[str, Any]) -> str | None:
    """A human-readable reason when the plugin is not the one on disk."""
    actual = runtime.get("bridgeBuild")
    expected = runtime.get("expectedBridgeBuild")
    if not actual or not expected or actual == expected:
        return None
    return (
        f"Figma plugin build {actual!r} != {expected!r} on disk; "
        "reload the plugin (it loads figma_bridge/code.js from another checkout)"
    )
