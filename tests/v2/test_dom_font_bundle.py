from __future__ import annotations

from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter
from src.app.services.structure.font_bundle import build_font_manifest


def _node(index: int, **overrides) -> dict:
    node = {
        "tag": "p",
        "text": "Font sample",
        "x": 0,
        "y": index * 30,
        "w": 200,
        "h": 30,
        "interactive": False,
        "fontFamily": "sans-serif",
        "fontSize": "16px",
        "fontWeight": "400",
        "fontStyle": "normal",
    }
    node.update(overrides)
    return node


def test_font_manifest_preserves_faces_and_browser_resolution():
    resources = [
        {
            "family": "Example Sans",
            "style": "normal",
            "weight": "400",
            "status": "loaded",
            "source_url": "https://example.test/fonts/example.woff2",
            "mime": "font/woff2",
        }
    ]
    nodes = [
        {},
        {},
        {},
        {},
        _node(
            4,
            fontFamily="Microsoft YaHei",
            fontFamilyRequested="sans-serif",
            fontFamilyResolution="browser-platform-font",
            platformFonts=[
                {
                    "familyName": "Microsoft YaHei",
                    "postScriptName": "MicrosoftYaHei",
                    "glyphCount": 11,
                }
            ],
        ),
    ]

    manifest = build_font_manifest(resources, nodes)

    assert manifest["schema_version"] == "dom-font-bundle/1.0"
    assert manifest["faces"][0]["family"] == "Example Sans"
    assert manifest["faces"][0]["source_url"].endswith(".woff2")
    assert manifest["nodes"]["n4"]["requestedFamily"] == "sans-serif"
    assert manifest["nodes"]["n4"]["resolvedFamily"] == "Microsoft YaHei"
    assert manifest["nodes"]["n4"]["resolution"] == "browser-platform-font"
    assert manifest["unresolved"] == []


def test_ambiguous_generic_font_stays_unresolved():
    nodes = [
        {},
        {},
        {},
        {},
        _node(
            4,
            platformFonts=[
                {"familyName": "Segoe UI", "glyphCount": 4},
                {"familyName": "Microsoft YaHei", "glyphCount": 7},
            ],
            fontFamilyResolution="ambiguous-platform-font",
        )
    ]
    manifest = build_font_manifest([], nodes)

    assert manifest["nodes"]["n4"]["resolution"] == "ambiguous-platform-font"
    assert manifest["nodes"]["n4"]["resolvedFamily"] is None
    assert "n4" in manifest["unresolved"]


class _RecordingFigmaAdapter(FigmaBridgeAdapter):
    def __init__(self) -> None:
        self.calls = []

    def _send(self, action, params=None, **kwargs):
        self.calls.append((action, params))
        return {
            "requested": {
                "family": params["family"],
                "style": params["style"],
                "weight": params["weight"],
            },
            "selected": {"family": "Example Fallback", "style": "Regular"},
            "status": "family-fallback",
            "candidateCount": 1,
        }


def test_adapter_resolve_font_uses_explicit_bridge_action():
    adapter = _RecordingFigmaAdapter()
    result = adapter.resolve_font("Missing Sans", "Regular", 400)

    assert result["status"] == "family-fallback"
    assert adapter.calls == [
        (
            "resolve_font",
            {
                "family": "Missing Sans",
                "style": "Regular",
                "weight": 400,
            },
        )
    ]
