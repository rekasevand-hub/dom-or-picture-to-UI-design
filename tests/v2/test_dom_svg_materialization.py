from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.app.services.structure.asset_metadata import parse_data_uri_asset
from src.app.services.structure.capture import DOM_JS
from src.app.services.structure.svg_materialization import (
    classify_svg_source,
    materialize_svg_assets,
)


def test_simple_svg_is_vector_preferred_and_uses_viewbox_size():
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 16">'
        b'<path d="M0 0 L24 16" fill="none" stroke="#112233"/>'
        b"</svg>"
    )
    result = classify_svg_source(svg, page_url="https://example.test/page")

    assert result["mode"] == "vector-preferred"
    assert result["naturalSize"] == [24.0, 16.0]
    assert result["sha256"]
    assert result["sanitizedSha256"]


def test_same_document_symbol_use_is_preserved_as_sanitized_vector():
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
        b'<defs><symbol id="mark"><circle cx="10" cy="10" r="8"/></symbol></defs>'
        b'<use href="#mark"/>'
        b"</svg>"
    )
    result = classify_svg_source(svg, page_url="https://example.test/")

    assert result["mode"] == "sanitized-vector"
    assert result["sameDocumentUse"] is True


def test_external_image_requires_raster_fallback():
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
        b'<image href="https://cdn.example.test/photo.png" width="40" height="20"/>'
        b"</svg>"
    )
    result = classify_svg_source(svg, page_url="https://example.test/")

    assert result["mode"] == "raster-required"
    assert "external-image" in result["reasons"]


def test_script_is_blocked_and_never_rasterized():
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
        b"<script>alert(1)</script><rect width=\"20\" height=\"20\"/>"
        b"</svg>"
    )
    result = classify_svg_source(svg, page_url="https://example.test/")

    assert result["mode"] == "blocked"
    assert result["rasterAllowed"] is False
    assert "script" in result["reasons"]


def test_data_uri_asset_uses_svg_policy_and_identity():
    payload = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 18">'
        b'<rect width="32" height="18"/>'
        b"</svg>"
    )
    uri = "data:image/svg+xml;base64," + base64.b64encode(payload).decode("ascii")

    parsed = parse_data_uri_asset(uri)

    assert parsed["natural_size"] == [32.0, 18.0]
    assert parsed["svg_mode"] == "vector-preferred"
    assert parsed["svg_sanitized_sha256"]


def test_safe_svg_materializes_content_addressed_png_display_payload(tmp_path):
    source = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 16">'
        b'<rect width="24" height="16" fill="#112233"/>'
        b"</svg>"
    )
    manifest = materialize_svg_assets(
        [{"svgSource": source.decode("utf-8"), "w": 24, "h": 16}],
        tmp_path,
        page_url="https://example.test/",
    )

    row = manifest["assets"][0]
    assert row["displayMode"] == "svg-rasterized"
    assert (tmp_path / row["originalVectorPath"]).is_file()
    assert (tmp_path / row["sanitizedVectorPath"]).is_file()
    assert (tmp_path / row["displayPayloadPath"]).is_file()
    assert row["displayPayloadPath"].endswith(".png")


def test_dom_capture_retains_inline_svg_source():
    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "inline-svg.html"
        fixture.write_text(
            "<!doctype html><svg id='icon' width='24' height='16' "
            "viewBox='0 0 24 16'><path d='M0 0 L24 16'/></svg>",
            encoding="utf-8",
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 200, "height": 100})
                page.goto(fixture.resolve().as_uri(), wait_until="domcontentloaded")
                nodes = page.evaluate(DOM_JS)
            finally:
                browser.close()

    svg = next(node for node in nodes if node.get("tag") == "svg")
    assert "<svg" in svg["svgSource"]
    assert "viewBox" in svg["svgSource"]
