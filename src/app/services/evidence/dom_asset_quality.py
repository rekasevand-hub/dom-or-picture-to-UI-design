"""Independent asset identity, display payload and replacement evidence."""

from __future__ import annotations

import base64
import hashlib
import io
import re
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from src.app.services.som.design_crops import crop_image_b64
from src.app.services.structure.asset_metadata import (
    build_asset_record,
    deduplicate_asset_records,
    object_fit_source_rect,
    parse_data_uri_asset,
)
from src.app.services.evidence.dom_quality_corpus import validate_corpus


ASSET_DIMENSIONS = (
    "source_identity",
    "display_payload",
    "crop_mapping",
    "missing_behavior",
    "replacement_mode",
    "use_identity",
)


def collect_asset_uses(
    dom: list[Mapping[str, Any]],
    *,
    sample_id: str = "dom",
) -> list[dict[str, Any]]:
    """Collect visible asset uses without assigning original status."""
    uses: list[dict[str, Any]] = []
    for index, node in enumerate(dom):
        if not isinstance(node, Mapping):
            continue
        tag = str(node.get("tag") or "").lower()
        display_box = _display_box(node)
        if display_box is None:
            continue
        if tag in {"img", "input", "video"}:
            source = (
                str(
                    node.get("assetSrc")
                    or node.get("currentSrc")
                    or node.get("src")
                    or ""
                ).strip()
                or None
            )
            natural_size = _natural_size(node)
            uses.append(
                _asset_use(
                    sample_id=sample_id,
                    node_index=index,
                    source_kind="img",
                    source=source,
                    natural_size=natural_size,
                    display_box=display_box,
                    object_fit=str(node.get("objectFit") or "fill"),
                    object_position=str(node.get("objectPosition") or "50% 50%"),
                    load_status=("missing" if natural_size is None else "loaded"),
                )
            )
        elif tag == "svg":
            uses.append(
                _asset_use(
                    sample_id=sample_id,
                    node_index=index,
                    source_kind="inline-svg",
                    source=None,
                    natural_size=None,
                    display_box=display_box,
                    object_fit="fill",
                    object_position="50% 50%",
                    load_status="loaded",
                )
            )
        bg_urls = node.get("bgUrls")
        if isinstance(bg_urls, list):
            for bg_index, source in enumerate(bg_urls[:4]):
                normalized = str(source or "").strip() or None
                if normalized is None:
                    continue
                uses.append(
                    _asset_use(
                        sample_id=sample_id,
                        node_index=index,
                        source_kind=f"bg-{bg_index}",
                        source=normalized,
                        natural_size=_natural_size(node),
                        display_box=display_box,
                        object_fit=str(node.get("objectFit") or "fill"),
                        object_position=str(node.get("objectPosition") or "50% 50%"),
                        load_status="loaded",
                    )
                )
    return uses


def build_asset_quality_report(
    corpus: Mapping[str, Any],
    capture_root: str | Path,
    source_probes: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate source, display, crop, missing and replacement dimensions."""
    corpus_errors = validate_corpus(corpus)
    if corpus_errors:
        raise ValueError(f"invalid frozen corpus: {corpus_errors}")
    root = Path(capture_root)
    probes = _probe_map(source_probes)
    probe_root = Path(str(source_probes.get("_root") or ".")).resolve()
    records: list[dict[str, Any]] = []
    sample_rows: list[dict[str, Any]] = []
    sample_ledgers: dict[str, dict[str, Any]] = {}
    missing_capture_samples: list[str] = []
    for sample in corpus.get("samples") or []:
        if not isinstance(sample, Mapping):
            continue
        sample_id = str(sample.get("sample_id") or "")
        capture = root / sample_id
        dom_path = capture / "00_dom.json"
        screenshot_path = capture / "00_screenshot.png"
        if not dom_path.is_file() or not screenshot_path.is_file():
            missing_capture_samples.append(sample_id)
            continue
        dom = _read_json_array(dom_path)
        screenshot_sha = _file_sha256(screenshot_path)
        screenshot_size = _image_size(screenshot_path)
        uses = collect_asset_uses(dom, sample_id=sample_id)
        sample_records = [
            _record_for_use(
                use,
                screenshot_path=screenshot_path,
                screenshot_sha256=screenshot_sha,
                screenshot_size=screenshot_size,
                probes=probes,
                probe_root=probe_root,
            )
            for use in uses
        ]
        ledger = deduplicate_asset_records(sample_records)
        sample_ledgers[sample_id] = ledger
        records.extend(sample_records)
        sample_rows.append(
            {
                "sample_id": sample_id,
                "site": sample.get("site"),
                "asset_count": ledger["asset_count"],
                "use_count": ledger["use_count"],
                "missing_use_count": ledger["missing_use_count"],
                "status_counts": ledger["status_counts"],
                "screenshot_sha256": screenshot_sha,
            }
        )
    aggregate = deduplicate_asset_records(records)
    source_counts = _source_status_counts(aggregate["assets"])
    display_rows = [
        {
            "use_id": use["use_id"],
            "asset_id": use["asset_id"],
            **dict(use.get("display_payload") or {}),
        }
        for use in aggregate["uses"]
    ]
    crop_mapping = _crop_mapping_summary(aggregate["uses"])
    replacement = _replacement_summary(aggregate["assets"])
    deduplication = _deduplication_summary(aggregate["assets"], aggregate["uses"])
    missing_outcome = (
        str(
            (
                corpus.get("thresholds", {}).get("assets", {})
                if isinstance(corpus.get("thresholds"), Mapping)
                else {}
            ).get("missing_asset_outcome")
            or "partial-not-pass"
        )
        if aggregate["missing_use_count"]
        else "pass"
    )
    dimensions = {
        "source_identity": _dimension_summary(
            source_counts,
            use_count=aggregate["use_count"],
        ),
        "display_payload": {
            "status": (
                "pass"
                if display_rows
                and all(row["kind"] == "screenshot-crop" for row in display_rows)
                else "partial"
            ),
            "screenshot_crop_uses": len(display_rows),
        },
        "crop_mapping": crop_mapping,
        "missing_behavior": {
            "status": "partial-not-pass" if aggregate["missing_use_count"] else "pass",
            "outcome": missing_outcome,
            "missing_use_count": aggregate["missing_use_count"],
        },
        "replacement_mode": replacement,
        "use_identity": deduplication,
    }
    return {
        "schema_version": "dom-asset-quality/1.0",
        "status": "partial",
        "corpus_id": corpus.get("corpus_id"),
        "corpus_sha256": corpus.get("corpus_sha256"),
        "thresholds_sha256": corpus.get("thresholds_sha256"),
        "sample_count": len(sample_rows),
        "required_sample_count": len(corpus.get("samples") or []),
        "missing_capture_samples": missing_capture_samples,
        "dimensions": dimensions,
        "source_identity": {
            **_empty_source_counts(),
            **source_counts,
        },
        "display_payload": {
            "screenshot_crop_uses": len(display_rows),
            "original_uses": sum(bool(row.get("original")) for row in display_rows),
            "rows": display_rows,
        },
        "assets": {
            "asset_count": aggregate["asset_count"],
            "use_count": aggregate["use_count"],
            "missing_use_count": aggregate["missing_use_count"],
        },
        "missing": {
            "outcome": missing_outcome,
            "missing_use_count": aggregate["missing_use_count"],
        },
        "deduplication": deduplication,
        "replacement": replacement,
        "samples": sample_rows,
        "details": {
            "assets": aggregate["assets"],
            "uses": aggregate["uses"],
            "missing_uses": aggregate["missing_uses"],
        },
        "network_probe": _probe_summary(source_probes),
        "composite_score_used": False,
        "generated_assets": 0,
        "figma_runtime": "not-evaluated",
        "non_claims": [
            "Screenshot crops are reference-only display payloads.",
            "Replacement eligibility is a contract result, not a Figma runtime pass.",
            "Inline SVG source bytes and effect semantics are not recovered here.",
            "The report covers only the frozen controlled corpus.",
        ],
    }


def _asset_use(
    *,
    sample_id: str,
    node_index: int,
    source_kind: str,
    source: str | None,
    natural_size: tuple[float, float] | None,
    display_box: list[float],
    object_fit: str,
    object_position: str,
    load_status: str,
) -> dict[str, Any]:
    crop = None
    if natural_size is not None:
        crop = object_fit_source_rect(
            display_size=display_box[2:4],
            natural_size=natural_size,
            object_fit=object_fit,
            object_position=object_position,
        )
    return {
        "sample_id": sample_id,
        "node_index": node_index,
        "source_kind": source_kind,
        "source": source,
        "natural_size": natural_size,
        "display_box": display_box,
        "object_fit": object_fit,
        "object_position": object_position,
        "source_rect": (crop or {}).get("source_rect"),
        "load_status": load_status,
    }


def _record_for_use(
    use: Mapping[str, Any],
    *,
    screenshot_path: Path,
    screenshot_sha256: str,
    screenshot_size: tuple[int, int],
    probes: Mapping[str, Mapping[str, Any]],
    probe_root: Path,
) -> dict[str, Any]:
    source = str(use.get("source") or "").strip() or None
    natural_size = use.get("natural_size")
    source_sha = None
    mime = None
    bytes_present = False
    provenance = None
    if source and source.startswith("data:"):
        parsed = parse_data_uri_asset(source)
        source_sha = parsed.get("sha256")
        mime = parsed.get("mime")
        bytes_present = parsed.get("bytes") is not None
        provenance = "data-uri"
        if parsed.get("natural_size") and natural_size is None:
            natural_size = tuple(parsed["natural_size"])
    elif source and source.startswith(("http://", "https://")):
        probe_row = probes.get(source)
        probe = _verified_probe(
            source,
            probe_row,
            probe_root=probe_root,
            dom_natural_size=natural_size,
        )
        if probe is not None:
            source_sha = probe["sha256"]
            mime = probe["mime"]
            bytes_present = True
            provenance = "network-response"
            natural_size = tuple(probe["natural_size"])
        elif isinstance(probe_row, Mapping):
            source_sha = str(probe_row.get("sha256") or "") or None
            mime = str(probe_row.get("mime") or "") or None
            natural_size = _positive_size(probe_row.get("natural_size")) or natural_size
            bytes_present = False
            provenance = "network-response"
    display_box = tuple(float(value) for value in use["display_box"])
    payload_sha = _crop_payload_sha(
        screenshot_path,
        display_box,
        canvas_size=screenshot_size,
    )
    return build_asset_record(
        sample_id=str(use.get("sample_id") or "dom"),
        node_index=int(use.get("node_index") or 0),
        source_kind=str(use.get("source_kind") or "unknown"),
        source=source,
        natural_size=natural_size,
        source_payload_sha256=source_sha,
        mime=mime,
        source_bytes_present=bytes_present,
        source_provenance=provenance,
        display_box=display_box,
        display_payload_sha256=payload_sha,
        screenshot_sha256=screenshot_sha256,
        source_rect=use.get("source_rect"),
        object_fit=str(use.get("object_fit") or "fill"),
        load_status=str(use.get("load_status") or "loaded"),
    )


def _verified_probe(
    source_url: str,
    row: Mapping[str, Any] | None,
    *,
    probe_root: Path,
    dom_natural_size: Any,
) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    if row.get("status") != "verified-original" or not row.get("bytes_present"):
        return None
    digest = str(row.get("sha256") or "").lower()
    mime = str(row.get("mime") or "").lower()
    natural_size = _positive_size(row.get("natural_size"))
    locator = str(row.get("locator") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        return None
    if not mime.startswith("image/") or natural_size is None or not locator:
        return None
    path = (probe_root / locator).resolve()
    try:
        if probe_root not in path.parents or not path.is_file():
            return None
        if _file_sha256(path) != digest:
            return None
        inspected = _inspect_source_bytes(path, dom_natural_size=dom_natural_size)
    except OSError:
        return None
    if inspected is None:
        return None
    actual_mime, actual_size = inspected
    if actual_mime != mime or any(
        abs(actual - declared) > 1.0
        for actual, declared in zip(actual_size, natural_size, strict=True)
    ):
        return None
    return {
        "source_url": source_url,
        "sha256": digest,
        "mime": actual_mime,
        "natural_size": actual_size,
    }


def _inspect_source_bytes(
    path: Path,
    *,
    dom_natural_size: Any,
) -> tuple[str, tuple[float, float]] | None:
    payload = path.read_bytes()
    mime, natural_size = _detect_image_identity(payload)
    if mime is None or natural_size is None:
        return None
    dom_size = _positive_size(dom_natural_size)
    if dom_size is None:
        return mime, natural_size
    if mime == "image/svg+xml":
        actual_ratio = natural_size[0] / natural_size[1]
        dom_ratio = dom_size[0] / dom_size[1]
        if abs(actual_ratio - dom_ratio) / max(actual_ratio, dom_ratio) > 0.02:
            return None
        return mime, natural_size
    if any(
        abs(actual - observed) > 1.0
        for actual, observed in zip(natural_size, dom_size, strict=True)
    ):
        return None
    return mime, natural_size


def _detect_image_identity(
    payload: bytes,
) -> tuple[str | None, tuple[float, float] | None]:
    head = payload[:4096].decode("utf-8", errors="ignore").lstrip().lower()
    if head.startswith("<?xml") or head.startswith("<svg") or "<svg" in head[:512]:
        encoded = base64.b64encode(payload).decode("ascii")
        parsed = parse_data_uri_asset(f"data:image/svg+xml;base64,{encoded}")
        size = _positive_size(parsed.get("natural_size"))
        return ("image/svg+xml", size) if size is not None else (None, None)
    formats = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "GIF": "image/gif",
        "WEBP": "image/webp",
    }
    try:
        with Image.open(io.BytesIO(payload)) as image:
            mime = formats.get(str(image.format or "").upper())
            if mime is None:
                return None, None
            return mime, (float(image.width), float(image.height))
    except Exception:
        return None, None


def _crop_payload_sha(
    screenshot_path: Path,
    display_box: tuple[float, float, float, float],
    *,
    canvas_size: tuple[int, int],
) -> str | None:
    x, y, width, height = display_box
    encoded = crop_image_b64(
        str(screenshot_path),
        int(round(x)),
        int(round(y)),
        int(round(width)),
        int(round(height)),
        canvas_size[0],
        canvas_size[1],
    )
    if not encoded:
        return None
    try:
        return hashlib.sha256(base64.b64decode(encoded)).hexdigest()
    except (ValueError, TypeError):
        return None


def _source_status_counts(assets: list[dict[str, Any]]) -> dict[str, int]:
    counts = _empty_source_counts()
    for asset in assets:
        status = str((asset.get("source_identity") or {}).get("status") or "unknown")
        key = status.replace("-", "_")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _empty_source_counts() -> dict[str, int]:
    return {
        "verified_original": 0,
        "reference_only": 0,
        "unavailable": 0,
        "missing": 0,
        "blocked_incomplete_identity": 0,
    }


def _dimension_summary(
    counts: Mapping[str, int],
    *,
    use_count: int,
) -> dict[str, Any]:
    if counts.get("verified_original", 0) == use_count and use_count:
        status = "pass"
    elif counts.get("verified_original", 0):
        status = "partial"
    else:
        status = "blocked"
    return {"status": status, "counts": dict(counts)}


def _crop_mapping_summary(uses: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        use
        for use in uses
        if (use.get("display_payload") or {}).get("original") is False
        and (use.get("display_payload") or {}).get("status") == "available"
    ]
    mapped = [
        use
        for use in eligible
        if (use.get("display_payload") or {}).get("source_rect") is not None
    ]
    return {
        "status": "pass" if len(mapped) == len(eligible) else "partial",
        "mapped_uses": len(mapped),
        "eligible_uses": len(eligible),
        "note": "Display crops are hashed; source_rect maps decoded source space.",
    }


def _replacement_summary(assets: list[dict[str, Any]]) -> dict[str, Any]:
    modes: dict[str, int] = {}
    allowed = 0
    for asset in assets:
        replacement = asset.get("replacement") or {}
        mode = str(replacement.get("mode") or "none")
        modes[mode] = modes.get(mode, 0) + 1
        if replacement.get("allowed"):
            allowed += 1
    return {
        "status": "partial" if allowed else "not-evaluated",
        "allowed_assets": allowed,
        "modes": modes,
        "figma_runtime": "not-evaluated",
    }


def _deduplication_summary(
    assets: list[dict[str, Any]],
    uses: list[dict[str, Any]],
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    use_ids: set[str] = set()
    duplicate_use_ids = 0
    for use in uses:
        use_id = str(use.get("use_id") or "")
        if use_id in use_ids:
            duplicate_use_ids += 1
        use_ids.add(use_id)
        asset_id = str(use.get("asset_id") or "")
        counts[asset_id] = counts.get(asset_id, 0) + 1
    shared = {asset_id: count for asset_id, count in counts.items() if count > 1}
    return {
        "status": "pass" if duplicate_use_ids == 0 else "fail",
        "asset_count": len(assets),
        "unique_use_count": len(use_ids),
        "shared_asset_count": len(shared),
        "max_uses_per_asset": max(counts.values(), default=0),
        "duplicate_use_ids": duplicate_use_ids,
    }


def _probe_map(source_probes: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = source_probes.get("rows")
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("source_url")): row
        for row in rows
        if isinstance(row, Mapping) and row.get("source_url")
    }


def _probe_summary(source_probes: Mapping[str, Any]) -> dict[str, Any]:
    rows = source_probes.get("rows")
    rows = rows if isinstance(rows, list) else []
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {
        "row_count": len(rows),
        "status_counts": counts,
        "policy": source_probes.get("policy"),
    }


def _display_box(node: Mapping[str, Any]) -> list[float] | None:
    try:
        values = [
            float(node.get("x") or 0),
            float(node.get("y") or 0),
            float(node.get("w") or 0),
            float(node.get("h") or 0),
        ]
    except (TypeError, ValueError):
        return None
    if values[2] <= 0 or values[3] <= 0:
        return None
    return [round(value, 3) for value in values]


def _natural_size(node: Mapping[str, Any]) -> tuple[float, float] | None:
    try:
        width = float(node.get("naturalWidth") or 0)
        height = float(node.get("naturalHeight") or 0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return round(width, 6), round(height, 6)


def _positive_size(value: Any) -> tuple[float, float] | None:
    try:
        width, height = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError):
        return None
    if width <= 0 or height <= 0:
        return None
    return round(width, 6), round(height, 6)


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.width, image.height


def _read_json_array(path: Path) -> list[dict[str, Any]]:
    import json

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"DOM capture is not an array: {path}")
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
