"""Resolve generic CSS font requests to Chromium platform-font evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


FONT_PROBE_ATTRIBUTE = "data-p1-font-probe-id"
GENERIC_FONT_FAMILIES = {
    "serif",
    "sans-serif",
    "monospace",
    "cursive",
    "fantasy",
    "system-ui",
    "ui-serif",
    "ui-sans-serif",
    "ui-monospace",
}
FONT_PROBE_CLEANUP_JS = r"""
(prefix) => {
  let removed = 0;
  const roots = [document];
  while (roots.length) {
    const root = roots.pop();
    for (const el of root.querySelectorAll('*')) {
      const value = el.getAttribute('data-p1-font-probe-id') || '';
      if (value.startsWith(prefix)) {
        el.removeAttribute('data-p1-font-probe-id');
        removed += 1;
      }
      if (el.shadowRoot) roots.push(el.shadowRoot);
    }
  }
  return removed;
}
"""


@dataclass(frozen=True, slots=True)
class FontFaceIdentity:
    declared_family: str
    resolved_family: str
    actual_family: str | None
    resolution: str

    @property
    def gate_status(self) -> str:
        if self.resolution in {
            "font-evidence-missing",
            "ambiguous-platform-font",
        } or not self.actual_family:
            return "blocked-font/partial"
        if self.resolution == "browser-platform-font":
            return "pass"
        if not _family_matches(self.resolved_family, self.actual_family):
            return "blocked-font/fail"
        return "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "declared_family": self.declared_family,
            "resolved_family": self.resolved_family,
            "actual_family": self.actual_family,
            "resolution": self.resolution,
            "gate_status": self.gate_status,
        }


def evaluate_font_face(
    *,
    declared_family: Any,
    resolved_family: Any,
    actual_family: Any,
    resolution: Any,
) -> FontFaceIdentity:
    """Keep declared, resolved and actual faces separate for hard-gate reporting."""
    return FontFaceIdentity(
        declared_family=str(declared_family or "").strip(),
        resolved_family=str(resolved_family or "").strip(),
        actual_family=str(actual_family or "").strip() or None,
        resolution=str(resolution or "font-evidence-missing").strip(),
    )


def _family_matches(candidates: str, actual: str) -> bool:
    normalized_actual = str(actual or "").strip().strip("\"'").casefold()
    if not normalized_actual:
        return False
    values = [
        item.strip().strip("\"'").casefold()
        for item in re.split(r"\s*,\s*", str(candidates or ""))
        if item.strip()
    ]
    return normalized_actual in values


class PlatformFontProbe:
    """Own one Chromium CDP session and resolve marked generic-font elements."""

    def __init__(self, page: Any) -> None:
        self.page = page
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.send("DOM.enable")
        self.cdp.send("CSS.enable")
        self.cdp.send(
            "DOM.getDocument",
            {"depth": -1, "pierce": True},
        )

    def __call__(
        self,
        frame: Any,
        prefix: str,
        nodes: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        node_list = list(nodes)
        errors = []
        try:
            self.cdp.send(
                "DOM.getDocument",
                {"depth": -1, "pierce": True},
            )
            rows = collect_platform_font_rows(self.cdp, node_list)
        except Exception as exc:  # noqa: BLE001 - preserve DOM capture
            rows = {}
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            try:
                frame.evaluate(FONT_PROBE_CLEANUP_JS, prefix)
            except Exception:  # noqa: BLE001 - cleanup is best effort
                pass
        summary = apply_platform_font_provenance(node_list, rows)
        summary["errors"] = errors
        summary["status"] = (
            "pass"
            if not errors
            and summary["missing_count"] == 0
            and summary["ambiguous_count"] == 0
            else "partial"
        )
        return summary


def is_generic_font_stack(value: Any) -> bool:
    families = [
        item.strip().strip("\"'").strip().lower()
        for item in re.split(r"\s*,\s*", str(value or ""))
        if item.strip()
    ]
    return bool(families) and all(
        family in GENERIC_FONT_FAMILIES for family in families
    )


def collect_platform_font_rows(
    cdp: Any,
    nodes: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Read exact Chromium platform fonts for nodes carrying probe markers."""
    rows_by_probe_id: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        probe_id = str(node.get("fontProbeId") or "")
        if not probe_id:
            continue
        search = cdp.send(
            "DOM.performSearch",
            {
                "query": probe_id,
                "includeUserAgentShadowDOM": False,
            },
        )
        search_id = str((search or {}).get("searchId") or "")
        if not search_id:
            continue
        try:
            result_count = int((search or {}).get("resultCount") or 0)
            if result_count <= 0:
                continue
            results = cdp.send(
                "DOM.getSearchResults",
                {
                    "searchId": search_id,
                    "fromIndex": 0,
                    "toIndex": result_count,
                },
            )
            for node_id in (results or {}).get("nodeIds") or []:
                described = cdp.send(
                    "DOM.describeNode",
                    {"nodeId": node_id, "depth": 0, "pierce": True},
                )
                description = (described or {}).get("node") or {}
                attributes = description.get("attributes") or []
                attrs = dict(zip(attributes[0::2], attributes[1::2]))
                if attrs.get(FONT_PROBE_ATTRIBUTE) != probe_id:
                    continue
                report = cdp.send(
                    "CSS.getPlatformFontsForNode",
                    {"nodeId": node_id},
                )
                fonts = [
                    {
                        "familyName": str(item.get("familyName") or ""),
                        "postScriptName": item.get("postScriptName"),
                        "isCustomFont": bool(item.get("isCustomFont")),
                        "glyphCount": int(item.get("glyphCount") or 0),
                    }
                    for item in (report or {}).get("fonts") or []
                    if isinstance(item, dict)
                    and str(item.get("familyName") or "").strip()
                ]
                if fonts:
                    rows_by_probe_id[probe_id] = fonts
                    break
        finally:
            try:
                cdp.send(
                    "DOM.discardSearchResults",
                    {"searchId": search_id},
                )
            except Exception:  # noqa: BLE001 - cleanup is best effort
                pass
    return rows_by_probe_id


def apply_platform_font_provenance(
    nodes: Iterable[dict[str, Any]],
    rows_by_probe_id: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Apply CDP platform-font rows without inventing a face for mixed runs."""
    counts = {
        "generic_node_count": 0,
        "resolved_count": 0,
        "ambiguous_count": 0,
        "missing_count": 0,
    }
    for node in nodes:
        if not isinstance(node, dict):
            continue
        probe_id = node.pop("fontProbeId", None)
        if not probe_id:
            continue
        counts["generic_node_count"] += 1
        requested = str(node.get("fontFamily") or "").strip()
        rows = [
            dict(row)
            for row in (rows_by_probe_id.get(str(probe_id)) or [])
            if isinstance(row, dict) and str(row.get("familyName") or "").strip()
        ]
        if not rows:
            node["fontFamilyResolution"] = "font-evidence-missing"
            counts["missing_count"] += 1
            continue
        node["platformFonts"] = rows
        families = {
            str(row["familyName"]).strip()
            for row in rows
            if str(row.get("familyName") or "").strip()
        }
        if len(families) == 1:
            resolved = next(iter(families))
            node["fontFamilyRequested"] = requested
            node["fontFamily"] = resolved
            node["fontFamilyResolution"] = "browser-platform-font"
            counts["resolved_count"] += 1
        else:
            node["fontFamilyResolution"] = "ambiguous-platform-font"
            counts["ambiguous_count"] += 1
    return counts
