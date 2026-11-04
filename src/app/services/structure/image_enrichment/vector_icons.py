"""Small Lucide-compatible icon subset rendered as native SVG vectors."""

from __future__ import annotations

import html
import re


def _icon_key(name: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")
    if "search" in normalized:
        return "search"
    if "home" in normalized:
        return "home"
    if "monitor" in normalized or "desktop" in normalized:
        return "monitor"
    if "smartphone" in normalized or "mobile" in normalized:
        return "smartphone"
    if "panel_left" in normalized or "sidebar" in normalized:
        return "panel-left"
    if "file_text" in normalized or "document" in normalized:
        return "file-text"
    if "mail" in normalized or "envelope" in normalized:
        return "mail"
    if "calendar" in normalized:
        return "calendar"
    if (
        normalized == "menu"
        or "hamburger" in normalized
        or normalized.endswith("_menu")
    ):
        return "menu"
    if normalized == "list" or "list_icon" in normalized:
        return "list"
    if "chevron" in normalized:
        return "chevron-right" if "right" in normalized else "chevron-down"
    if "clock" in normalized:
        return "clock"
    if "save" in normalized:
        return "save"
    if "expand" in normalized or "resize" in normalized:
        return "maximize"
    if "export" in normalized:
        return "upload"
    if "edit" in normalized:
        return "pencil"
    if "more_actions" in normalized:
        return "ellipsis"
    if "close" in normalized:
        return "x"
    if "log_out" in normalized or "logout" in normalized:
        return "log-out"
    return None


_ICONS = {
    "search": ('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'),
    "mail": (
        '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>'
    ),
    "home": ('<path d="m3 11 9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1Z"/>'),
    "monitor": (
        '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>'
    ),
    "smartphone": (
        '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>'
    ),
    "panel-left": (
        '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>'
    ),
    "file-text": ('<path d="M6 3h8l4 4v14H6V3Z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>'),
    "calendar": (
        '<rect x="3" y="5" width="18" height="16" rx="2"/>'
        '<path d="M16 3v4M8 3v4M3 11h18"/>'
    ),
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "list": (
        '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6h.01M4 12h.01M4 18h.01"/>'
    ),
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-right": '<path d="m9 6 6 6-6 6"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "save": (
        '<path d="M5 3h12l3 3v15H4V4a1 1 0 0 1 1-1Z"/>'
        '<path d="M8 3v6h8V3M8 21v-7h8v7"/>'
    ),
    "maximize": ('<path d="M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5"/>'),
    "upload": ('<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>'),
    "pencil": ('<path d="M4 20h4L19 9l-4-4L4 16v4Z"/><path d="m13.5 6.5 4 4"/>'),
    "ellipsis": (
        '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/>'
        '<circle cx="19" cy="12" r="1"/>'
    ),
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "log-out": ('<path d="M10 17l5-5-5-5M15 12H3M15 3h5v18h-5"/>'),
}


def vector_icon_svg(
    name: str,
    width: int,
    height: int,
    color: str,
) -> str | None:
    key = _icon_key(name)
    if key is None:
        return None
    body = _ICONS[key]
    safe_color = html.escape(str(color or "#555555"), quote=True)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{int(width)}" '
        f'height="{int(height)}" viewBox="0 0 24 24" fill="none" '
        f'stroke="{safe_color}" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    )
