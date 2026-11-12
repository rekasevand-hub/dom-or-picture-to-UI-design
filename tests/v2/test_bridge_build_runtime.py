"""A run has to say which renderer produced it.

`BRIDGE_BUILD` was written into every readback and read by nobody: the
2026-11-11 session ran three rounds against a plugin that had never been
reloaded. These cases pin the comparison, including the direction that
matters -- an unknown stamp is not a match.
"""

from __future__ import annotations

from src.app.services.rendering.bridge_build import (
    RUNTIME_SCHEMA_VERSION,
    build_mismatch,
    expected_bridge_build,
    readback_bridge_build,
    runtime_identity,
)


def _code_js(tmp_path, build: str) -> str:
    path = tmp_path / "code.js"
    path.write_text(
        "const OTHER = 1;\n"
        f'const BRIDGE_BUILD = "{build}";\n'
        "figma.ui.postMessage({ bridgeBuild: BRIDGE_BUILD });\n",
        encoding="utf-8",
    )
    return str(path)


def test_reads_the_stamp_from_the_bridge_source(tmp_path):
    assert expected_bridge_build(_code_js(tmp_path, "2026-11-11-multiline-rotation")) == (
        "2026-11-11-multiline-rotation"
    )


def test_accepts_single_quotes(tmp_path):
    path = tmp_path / "code.js"
    path.write_text("const BRIDGE_BUILD = 'abc-1';\n", encoding="utf-8")

    assert expected_bridge_build(path) == "abc-1"


def test_a_missing_file_is_unknown_not_empty(tmp_path):
    assert expected_bridge_build(tmp_path / "absent.js") is None


def test_the_real_bridge_declares_a_stamp():
    # Guards against someone dropping BRIDGE_BUILD from the plugin.
    assert expected_bridge_build()


def test_readback_stamp_is_read_from_the_root():
    assert readback_bridge_build({"bridgeBuild": "abc-1"}) == "abc-1"
    assert readback_bridge_build({}) is None


def test_matching_stamps_are_a_match(tmp_path):
    runtime = runtime_identity(
        readback={"bridgeBuild": "abc-1"},
        strategies=["ink-convergence", "text-positions"],
        code_js=_code_js(tmp_path, "abc-1"),
    )

    assert runtime["buildMatches"] is True
    assert build_mismatch(runtime) is None
    assert runtime["strategies"] == ["ink-convergence", "text-positions"]
    assert runtime["schema_version"] == RUNTIME_SCHEMA_VERSION


def test_a_stale_plugin_is_refused_with_a_readable_reason(tmp_path):
    runtime = runtime_identity(
        readback={"bridgeBuild": "old-0"},
        code_js=_code_js(tmp_path, "new-1"),
    )

    assert runtime["buildMatches"] is False
    reason = build_mismatch(runtime)
    assert reason is not None
    assert "old-0" in reason and "new-1" in reason


def test_an_unknown_stamp_never_counts_as_a_match(tmp_path):
    # The plugin did not report a build: that is unverified, not verified.
    runtime = runtime_identity(readback={}, code_js=_code_js(tmp_path, "new-1"))

    assert runtime["buildMatches"] is False
    assert runtime["bridgeBuild"] is None
    # ... but it is not a mismatch either: there is nothing to compare.
    assert build_mismatch(runtime) is None
