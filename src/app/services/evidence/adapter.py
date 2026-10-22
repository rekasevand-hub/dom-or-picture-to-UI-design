"""Read-only capture-to-evidence adapter for the P1 shadow slice."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import unquote_to_bytes

from src.app.services.contracts import (
    AccessPolicy,
    AssetRecord,
    AuditBundle,
    EvidenceAvailability,
    EvidenceRecord,
    ExecutionGraph,
    FieldAuthority,
    FieldDecision,
    FieldDecisionStatus,
    FieldObservation,
    FieldRecord,
    OrderMapping,
    ReferenceRecord,
    RuntimeIR,
    UnknownRecord,
    build_audit_bundle,
    canonical_hash,
    jsonable,
    raise_for_issues,
    validate_audit_bundle,
    validate_runtime_ir,
)
from src.app.services.evidence.retention import EvidenceStorePolicy
from src.app.services.evidence.sample_scope import DEFAULT_SAMPLE_SCOPE

SIDECAR_SCHEMA = "evidence-sidecar/1.0"
SHADOW_POLICY_VERSION = "p1-evidence-shadow/1.0"

_REQUIRED_FILES = ("00_screenshot.png", "00_page_state.json")
_OPTIONAL_FILES = (
    "00_dom.json",
    "00_dom_diagnostics.json",
    "00_screenshot_m0.png",
    "00_dom_m0.json",
)
_COPY_MAP = {
    "00_screenshot.png": "evidence/screenshot.png",
    "00_page_state.json": "evidence/page_state.json",
    "00_dom.json": "evidence/dom.json",
    "00_dom_diagnostics.json": "evidence/dom_diagnostics.json",
    "00_screenshot_m0.png": "evidence/screenshot_m0.png",
    "00_dom_m0.json": "evidence/dom_m0.json",
}
_EVIDENCE_KINDS = {
    "00_screenshot.png": "screenshot",
    "00_page_state.json": "page-state-json",
    "00_dom.json": "dom-json",
    "00_dom_diagnostics.json": "dom-diagnostics-json",
    "00_screenshot_m0.png": "m0-screenshot",
    "00_dom_m0.json": "m0-dom-json",
}
_EVIDENCE_IDS = {
    "00_screenshot.png": "ev-screenshot",
    "00_page_state.json": "ev-page-state",
    "00_dom.json": "ev-dom",
    "00_dom_diagnostics.json": "ev-dom-diagnostics",
    "00_screenshot_m0.png": "ev-screenshot-m0",
    "00_dom_m0.json": "ev-dom-m0",
}


class EvidenceAdapterError(ValueError):
    """Raised when a capture cannot become a trustworthy evidence sidecar."""


@dataclass(frozen=True, slots=True)
class EvidenceSidecar:
    runtime_ir: RuntimeIR
    audit_bundle: AuditBundle
    manifest: Mapping[str, Any]
    output_dir: Path | None = None
    asset_payloads: tuple[tuple[str, bytes], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_ir": self.runtime_ir.to_dict(),
            "audit_bundle": self.audit_bundle.to_dict(),
            "manifest": jsonable(self.manifest),
            "output_dir": str(self.output_dir) if self.output_dir else None,
            "asset_payload_count": len(self.asset_payloads),
        }


def adapt_capture(
    capture_dir: str | Path,
    *,
    captured_at: datetime | None = None,
    job_id: str | None = None,
    policy: EvidenceStorePolicy | None = None,
) -> EvidenceSidecar:
    """Build deterministic P0 contracts from one capture directory.

    This function is intentionally side-effect free. It does not write files,
    call OCR, resolve assets, or enter the normal rendering path.
    """
    root = Path(capture_dir)
    if not root.is_dir():
        raise EvidenceAdapterError(f"capture directory does not exist: {root}")
    policy = policy or EvidenceStorePolicy()
    captured_at = captured_at or datetime.now(timezone.utc)
    retention = policy.to_contract(captured_at)

    file_bytes: dict[str, bytes] = {}
    for name in _REQUIRED_FILES:
        path = root / name
        if not path.is_file():
            raise EvidenceAdapterError(f"required capture artifact is missing: {name}")
        file_bytes[name] = path.read_bytes()
    for name in _OPTIONAL_FILES:
        path = root / name
        if path.is_file():
            file_bytes[name] = path.read_bytes()
    total_bytes = sum(len(payload) for payload in file_bytes.values())
    if total_bytes > policy.max_total_bytes:
        raise EvidenceAdapterError(
            f"capture evidence exceeds size budget: {total_bytes} > {policy.max_total_bytes}"
        )

    page_state = _read_json_object(file_bytes["00_page_state.json"], "00_page_state.json")
    dom_nodes = (
        _read_json_array(file_bytes.get("00_dom.json"), "00_dom.json")
        if "00_dom.json" in file_bytes
        else []
    )
    diagnostics = (
        _read_json_object(file_bytes["00_dom_diagnostics.json"], "00_dom_diagnostics.json")
        if "00_dom_diagnostics.json" in file_bytes
        else {}
    )

    hashes = {name: _sha256_bytes(payload) for name, payload in file_bytes.items()}
    capture_digest = canonical_hash(
        {
            name: hashes[name]
            for name in (*_REQUIRED_FILES, *_OPTIONAL_FILES)
            if name in hashes
        }
    )
    capture_id = f"capture-{capture_digest[:16]}"
    state_signature = canonical_hash(
        {
            "page_state": {
                "kind": page_state.get("kind"),
                "final_url": page_state.get("final_url"),
                "signals": page_state.get("signals"),
            },
            "hashes": hashes,
        }
    )
    job_id = job_id or f"shadow-{capture_digest[:12]}"
    page_kind = str(page_state.get("kind") or "unknown")
    screenshot_only = bool(page_state.get("screenshot_only"))

    evidence = tuple(
        EvidenceRecord(
            evidence_id=_EVIDENCE_IDS[name],
            kind=_EVIDENCE_KINDS[name],
            sha256=hashes[name],
            locator=_COPY_MAP[name],
            availability=EvidenceAvailability.AVAILABLE,
            expires_at=retention.evidence_expires_at,
            bytes_present=True,
        )
        for name in _COPY_MAP
        if name in hashes
    )
    by_name = {
        name: _EVIDENCE_IDS[name]
        for name in _COPY_MAP
        if name in hashes
    }
    if page_kind == "content" and not screenshot_only and dom_nodes:
        assets, asset_evidence, asset_payloads, asset_manifest = _asset_evidence(
            dom_nodes,
            retention=retention,
        )
    else:
        assets = ()
        asset_evidence = ()
        asset_payloads = ()
        asset_manifest = []
    asset_bytes_total = sum(len(payload) for _, payload in asset_payloads)
    if total_bytes + asset_bytes_total > policy.max_total_bytes:
        raise EvidenceAdapterError(
            "capture plus decoded assets exceed size budget: "
            f"{total_bytes}+{asset_bytes_total} > {policy.max_total_bytes}"
        )
    evidence = evidence + asset_evidence

    fields: list[FieldRecord] = [
        _page_state_field(page_state, by_name["00_page_state.json"])
    ]
    if page_kind == "content" and not screenshot_only and dom_nodes:
        for index, node in enumerate(dom_nodes):
            if not isinstance(node, Mapping):
                raise EvidenceAdapterError(f"00_dom.json node {index} is not an object")
            fields.extend(
                _node_fields(
                    index,
                    node,
                    by_name["00_dom.json"],
                )
            )

    unknowns = _unknowns(
        page_state=page_state,
        diagnostics=diagnostics,
        has_dom="00_dom.json" in file_bytes,
        screenshot_only=screenshot_only,
    )
    order_mapping = OrderMapping(
        dom_order=tuple(f"dom:{index:04d}" for index in range(len(dom_nodes)))
        if page_kind == "content" and not screenshot_only
        else (),
        screenshot_order=(),
        figma_child_order=(),
        basis="dom-capture-order" if dom_nodes else "no-order-observed",
    )
    runtime_ir = RuntimeIR(
        job_id=job_id,
        schema_version="2.0",
        policy_version=SHADOW_POLICY_VERSION,
        capture_revision=f"{capture_id}:r1",
        plan_revision="plan-pending-shadow",
        output_revision="output-pending-shadow",
        capture_id=capture_id,
        state_signature=state_signature,
        fields=tuple(fields),
        evidence=evidence,
        assets=assets,
        tombstones=(),
        unknowns=unknowns,
        order_mapping=order_mapping,
        references=(
            ReferenceRecord(
                reference_id="capture",
                kind="capture",
                target=capture_id,
            ),
        ),
        retention=retention,
        access_policy=AccessPolicy(
            allow_evidence_read=True,
            allow_materialize=True,
            allow_audit_summary=True,
        ),
        execution_graph=ExecutionGraph(
            nodes=("capture", "evidence", "audit"),
            edges=(("capture", "evidence"), ("evidence", "audit")),
        ),
    )
    issues = list(validate_runtime_ir(runtime_ir))
    if issues:
        raise_for_issues(issues)

    audit_bundle = build_audit_bundle(runtime_ir)
    audit_issues = list(validate_audit_bundle(audit_bundle))
    if audit_issues:
        raise_for_issues(audit_issues)

    manifest = _build_manifest(
        capture_id=capture_id,
        job_id=job_id,
        state_signature=state_signature,
        captured_at=captured_at,
        page_state=page_state,
        file_bytes=file_bytes,
        evidence=evidence,
        fields=tuple(fields),
        unknowns=unknowns,
        retention=retention.to_dict(),
        policy=policy,
        page_kind=page_kind,
        screenshot_only=screenshot_only,
        diagnostics=diagnostics,
        assets=asset_manifest,
        asset_bytes_total=asset_bytes_total,
    )
    return EvidenceSidecar(
        runtime_ir=runtime_ir,
        audit_bundle=audit_bundle,
        manifest=manifest,
        asset_payloads=asset_payloads,
    )


def write_evidence_sidecar(
    capture_dir: str | Path,
    output_dir: str | Path,
    *,
    captured_at: datetime | None = None,
    job_id: str | None = None,
    policy: EvidenceStorePolicy | None = None,
    overwrite: bool = False,
) -> EvidenceSidecar:
    """Write a complete local sidecar atomically from a valid capture."""
    sidecar = adapt_capture(
        capture_dir,
        captured_at=captured_at,
        job_id=job_id,
        policy=policy,
    )
    destination = Path(output_dir).resolve()
    source = Path(capture_dir).resolve()
    if destination == source or destination in source.parents:
        raise EvidenceAdapterError("sidecar output cannot be the capture directory")

    if destination.exists() and any(destination.iterdir()):
        if not overwrite:
            raise EvidenceAdapterError(f"sidecar output already exists: {destination}")
        _assert_existing_sidecar(destination)
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent)
    )
    try:
        for source_name, relative in _COPY_MAP.items():
            source_path = source / source_name
            if not source_path.is_file():
                continue
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target)
            expected = next(
                record.sha256
                for record in sidecar.runtime_ir.evidence
                if record.locator == relative
            )
            if _sha256_file(target) != expected:
                raise EvidenceAdapterError(f"copied evidence hash mismatch: {relative}")

        for asset_id, payload in sidecar.asset_payloads:
            record = next(
                item
                for item in sidecar.runtime_ir.evidence
                if item.evidence_id == f"ev-{asset_id}"
            )
            target = staging / record.locator
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            if _sha256_file(target) != record.sha256:
                raise EvidenceAdapterError(
                    f"asset evidence hash mismatch: {record.locator}"
                )

        _write_json(staging / "runtime_ir.json", sidecar.runtime_ir.to_dict())
        _write_json(staging / "audit_bundle.json", sidecar.audit_bundle.to_dict())
        _write_json(staging / "manifest.json", sidecar.manifest)
        if destination.exists():
            destination.rmdir()
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return replace(sidecar, output_dir=destination)


def _read_json_object(payload: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceAdapterError(f"{name} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceAdapterError(f"{name} must contain a JSON object")
    return value


def _read_json_array(payload: bytes | None, name: str) -> list[Any]:
    if payload is None:
        return []
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceAdapterError(f"{name} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, list):
        raise EvidenceAdapterError(f"{name} must contain a JSON array")
    return value


def _page_state_field(page_state: Mapping[str, Any], evidence_id: str) -> FieldRecord:
    value = {
        "kind": page_state.get("kind"),
        "final_url": page_state.get("final_url"),
        "confidence": page_state.get("confidence"),
        "screenshot_only": bool(page_state.get("screenshot_only")),
        "fallback_used": bool(page_state.get("fallback_used")),
    }
    return _observed_field(
        field_id="page-state",
        node_id="page",
        field_type="page-state",
        source="capture",
        evidence_id=evidence_id,
        value=value,
        authority=FieldAuthority.NONE,
    )


def _node_fields(index: int, node: Mapping[str, Any], evidence_id: str) -> list[FieldRecord]:
    node_id = f"dom:{index:04d}"
    fields: list[FieldRecord] = [
        _observed_field(
            field_id=f"f-{index:04d}-geometry",
            node_id=node_id,
            field_type="geometry",
            source="dom",
            evidence_id=evidence_id,
            value={key: node.get(key) for key in ("x", "y", "w", "h")},
        )
    ]
    text = str(node.get("text") or "").strip()
    if text:
        fields.append(
            _observed_field(
                field_id=f"f-{index:04d}-text-content",
                node_id=node_id,
                field_type="text-content",
                source="dom",
                evidence_id=evidence_id,
                value=text,
            )
        )
        fields.append(
            _observed_field(
                field_id=f"f-{index:04d}-text-style",
                node_id=node_id,
                field_type="text-style",
                source="dom",
                evidence_id=evidence_id,
                value={
                    key: node.get(key)
                    for key in (
                        "fontFamily",
                        "fontSize",
                        "fontWeight",
                        "lineHeight",
                        "textAlign",
                        "color",
                    )
                    if node.get(key) not in (None, "")
                },
            )
        )
    text_box = node.get("textBox") or node.get("textEmBox")
    if text_box:
        fields.append(
            _observed_field(
                field_id=f"f-{index:04d}-text-box",
                node_id=node_id,
                field_type="text-box",
                source="dom",
                evidence_id=evidence_id,
                value={
                    "textBox": node.get("textBox"),
                    "textEmBox": node.get("textEmBox"),
                    "textEmLines": node.get("textEmLines"),
                },
            )
        )
    if node.get("bg") not in (None, "", "rgba(0, 0, 0, 0)") or node.get("bgImage"):
        fields.append(
            _observed_field(
                field_id=f"f-{index:04d}-background",
                node_id=node_id,
                field_type="background",
                source="dom",
                evidence_id=evidence_id,
                value={
                    "backgroundColor": node.get("bg"),
                    "backgroundImageObserved": bool(node.get("bgImage")),
                },
            )
        )
    role_value = {
        key: node.get(key)
        for key in ("tag", "role", "ariaLabel", "title")
        if node.get(key) not in (None, "")
    }
    if node.get("role") or node.get("ariaLabel") or node.get("title"):
        fields.append(
            _observed_field(
                field_id=f"f-{index:04d}-role",
                node_id=node_id,
                field_type="role",
                source="dom",
                evidence_id=evidence_id,
                value=role_value,
            )
        )
    if (
        node.get("bgImage")
        or node.get("iconBox")
        or node.get("alt")
        or str(node.get("tag") or "").lower() in {"img", "svg", "canvas", "picture"}
    ):
        fields.append(
            _observed_field(
                field_id=f"f-{index:04d}-asset-hint",
                node_id=node_id,
                field_type="asset-hint",
                source="dom",
                evidence_id=evidence_id,
                value={
                    "tag": node.get("tag"),
                    "alt": node.get("alt"),
                    "backgroundImageObserved": bool(node.get("bgImage")),
                    "iconBox": bool(node.get("iconBox")),
                },
            )
        )
    if node.get("interactive") or node.get("zIndex") not in (None, 0) or (
        node.get("position") not in (None, "static")
    ):
        fields.append(
            _observed_field(
                field_id=f"f-{index:04d}-stacking-hint",
                node_id=node_id,
                field_type="stacking-hint",
                source="dom",
                evidence_id=evidence_id,
                value={
                    "position": node.get("position"),
                    "zIndex": node.get("zIndex"),
                    "interactive": bool(node.get("interactive")),
                },
            )
        )
    return fields


def _observed_field(
    *,
    field_id: str,
    node_id: str,
    field_type: str,
    source: str,
    evidence_id: str,
    value: Any,
    authority: FieldAuthority = FieldAuthority.DOM,
) -> FieldRecord:
    return FieldRecord(
        field_id=field_id,
        node_id=node_id,
        field_type=field_type,
        observations=(
            FieldObservation(
                source=source,
                evidence_id=evidence_id,
                present=True,
                value=value,
            ),
        ),
        decision=FieldDecision(
            authority=authority,
            status=FieldDecisionStatus.OBSERVED,
            selected_value=None,
            release_eligible=False,
            cannot_promote=(),
            reason="P1 shadow evidence only; authority resolution is deferred.",
            evidence_refs=(evidence_id,),
        ),
    )


def _unknowns(
    *,
    page_state: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    has_dom: bool,
    screenshot_only: bool,
) -> tuple[UnknownRecord, ...]:
    records: list[UnknownRecord] = []
    page_kind = str(page_state.get("kind") or "unknown")
    if page_kind != "content":
        records.append(
            UnknownRecord(
                object_key="page",
                field="page-content",
                status=page_kind,
                reason=f"capture page state is {page_kind}",
            )
        )
    if page_kind == "content" and not has_dom:
        records.append(
            UnknownRecord(
                object_key="page",
                field="dom-capture",
                status="unknown",
                reason="content capture has no DOM artifact",
            )
        )
    if page_kind == "content" and screenshot_only:
        records.append(
            UnknownRecord(
                object_key="page",
                field="dom-content",
                status="screenshot-only",
                reason="capture requires screenshot-only treatment; DOM stays evidence-only",
            )
        )
    gaps = diagnostics.get("capture_gaps") or {}
    if _positive_int(gaps.get("shadow")):
        records.append(
            UnknownRecord(
                object_key="page",
                field="shadow-capture",
                status="unknown",
                reason="closed or otherwise invisible shadow content may be missing",
            )
        )
    unsupported = diagnostics.get("unsupported") or {}
    labels = (
        ("grid", "layout.grid"),
        ("flex_wrap", "layout.flex-wrap"),
        ("gradient", "visual.gradient"),
        ("pseudo", "visual.pseudo-element"),
    )
    for key, field in labels:
        if _positive_int(unsupported.get(key)):
            records.append(
                UnknownRecord(
                    object_key="page",
                    field=field,
                    status="unsupported",
                    reason=f"capture diagnostics report {key}={unsupported[key]}",
                )
            )
    frame_summary = page_state.get("frame_summary") or {}
    if _positive_int(frame_summary.get("opaque_frame_count")):
        records.append(
            UnknownRecord(
                object_key="page",
                field="frame-content",
                status="opaque-frame",
                reason=(
                    f"{frame_summary['opaque_frame_count']} frame(s) are "
                    "cross-origin, sandboxed opaque, or otherwise inaccessible"
                ),
            )
        )
    return tuple(records)


def _asset_evidence(
    dom_nodes: list[Any],
    *,
    retention: Any,
) -> tuple[
    tuple[AssetRecord, ...],
    tuple[EvidenceRecord, ...],
    tuple[tuple[str, bytes], ...],
    list[dict[str, Any]],
]:
    assets: list[AssetRecord] = []
    evidence: list[EvidenceRecord] = []
    payloads: list[tuple[str, bytes]] = []
    manifest: list[dict[str, Any]] = []
    for index, node in enumerate(dom_nodes):
        if not isinstance(node, Mapping):
            continue
        specs: list[tuple[str, str]] = []
        asset_src = node.get("assetSrc")
        if isinstance(asset_src, str) and asset_src.strip():
            specs.append(("img", asset_src.strip()))
        bg_urls = node.get("bgUrls")
        if isinstance(bg_urls, list):
            for bg_index, url in enumerate(bg_urls[:4]):
                if isinstance(url, str) and url.strip():
                    specs.append((f"bg-{bg_index}", url.strip()))
        for source_kind, url in specs:
            asset_id = f"asset-{index:04d}-{source_kind}"
            node_id = f"dom:{index:04d}"
            decoded = _decode_data_uri(url) if url.startswith("data:") else None
            if decoded is not None:
                mime, payload = decoded
                digest = _sha256_bytes(payload)
                locator = f"evidence/assets/{asset_id}{_asset_extension(mime)}"
                evidence_id = f"ev-{asset_id}"
                assets.append(
                    AssetRecord(
                        asset_id=asset_id,
                        source_url=None,
                        url_expires_at=None,
                        local_sha256=digest,
                        local_bytes_present=True,
                        local_expires_at=retention.evidence_expires_at,
                        mime=mime,
                    )
                )
                evidence.append(
                    EvidenceRecord(
                        evidence_id=evidence_id,
                        kind="asset-bytes",
                        sha256=digest,
                        locator=locator,
                        availability=EvidenceAvailability.AVAILABLE,
                        expires_at=retention.evidence_expires_at,
                        bytes_present=True,
                    )
                )
                payloads.append((asset_id, payload))
                manifest.append(
                    {
                        "asset_id": asset_id,
                        "node_id": node_id,
                        "source_kind": source_kind,
                        "source_url": None,
                        "mime": mime,
                        "sha256": digest,
                        "size_bytes": len(payload),
                        "bytes_present": True,
                        "status": "local-bytes",
                    }
                )
                continue

            remote = url.startswith(("http://", "https://"))
            assets.append(
                AssetRecord(
                    asset_id=asset_id,
                    source_url=url,
                    url_expires_at=None,
                    local_sha256="",
                    local_bytes_present=False,
                    local_expires_at=None,
                    mime="",
                )
            )
            manifest.append(
                {
                    "asset_id": asset_id,
                    "node_id": node_id,
                    "source_kind": source_kind,
                    "source_url": url,
                    "mime": None,
                    "sha256": None,
                    "size_bytes": None,
                    "bytes_present": False,
                    "status": "reference-only" if remote else "unsupported-source",
                }
            )
    return tuple(assets), tuple(evidence), tuple(payloads), manifest


def _decode_data_uri(uri: str) -> tuple[str, bytes] | None:
    if not uri.startswith("data:"):
        return None
    header, separator, payload = uri[5:].partition(",")
    if not separator:
        return None
    parts = header.split(";")
    mime = (parts[0] or "application/octet-stream").lower()
    try:
        if "base64" in {item.lower() for item in parts[1:]}:
            return mime, base64.b64decode(payload, validate=False)
        return mime, unquote_to_bytes(payload)
    except (ValueError, TypeError):
        return None


def _asset_extension(mime: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/svg+xml": ".svg",
    }.get(mime, ".bin")


def _build_manifest(
    *,
    capture_id: str,
    job_id: str,
    state_signature: str,
    captured_at: datetime,
    page_state: Mapping[str, Any],
    file_bytes: Mapping[str, bytes],
    evidence: Iterable[EvidenceRecord],
    fields: tuple[FieldRecord, ...],
    unknowns: tuple[UnknownRecord, ...],
    retention: Mapping[str, Any],
    policy: EvidenceStorePolicy,
    page_kind: str,
    screenshot_only: bool,
    diagnostics: Mapping[str, Any],
    assets: list[dict[str, Any]],
    asset_bytes_total: int,
) -> dict[str, Any]:
    field_type_counts: dict[str, int] = {}
    for field in fields:
        field_type_counts[field.field_type] = field_type_counts.get(field.field_type, 0) + 1
    attempt_summaries = _attempt_summaries(page_state.get("attempts"))
    manifest: dict[str, Any] = {
        "sidecar_schema": SIDECAR_SCHEMA,
        "policy_version": SHADOW_POLICY_VERSION,
        "sample_scope_version": DEFAULT_SAMPLE_SCOPE.scope_version,
        "captured_at": captured_at.astimezone(timezone.utc).isoformat(),
        "capture_id": capture_id,
        "job_id": job_id,
        "state_signature": state_signature,
        "page_state": {
            "kind": page_kind,
            "final_url": page_state.get("final_url"),
            "confidence": page_state.get("confidence"),
            "screenshot_only": screenshot_only,
            "fallback_used": bool(page_state.get("fallback_used")),
            "browser_engine": page_state.get("browser_engine"),
            "attempt_count": len(attempt_summaries),
            "attempts": attempt_summaries,
            "capture_profile": page_state.get("capture_profile"),
            "frame_request_policy": dict(
                page_state.get("frame_request_policy") or {}
            ),
        },
        "capture_profile": page_state.get("capture_profile"),
        "frame_request_policy": dict(
            page_state.get("frame_request_policy") or {}
        ),
        "source_files": [name for name in _COPY_MAP if name in file_bytes],
        "early_state": {
            "screenshot_present": "00_screenshot_m0.png" in file_bytes,
            "dom_present": "00_dom_m0.json" in file_bytes,
        },
        "evidence": [item.to_dict() for item in evidence],
        "frames": {
            "summary": dict(page_state.get("frame_summary") or {}),
            "inventory_source": "evidence/page_state.json",
        },
        "navigation": dict(page_state.get("navigation") or {}),
        "field_count": len(fields),
        "field_type_counts": dict(sorted(field_type_counts.items())),
        "unknown_count": len(unknowns),
        "asset_count": len(assets),
        "asset_bytes_total": asset_bytes_total,
        "assets": assets,
        "retention": dict(retention),
        "store_policy": policy.to_dict(),
        "diagnostics": {
            "capture_gaps": dict(diagnostics.get("capture_gaps") or {}),
            "unsupported": dict(diagnostics.get("unsupported") or {}),
            "frames": dict(
                ((diagnostics.get("frames") or {}).get("summary") or {})
            ),
        },
        "shadow_mode": True,
        "default_path_changed": False,
        "figma_write": False,
        "asset_resolution": "data-uri-hashed; remote-reference-only",
        "limitations": [
            "P1 shadow only; no authority selection or release.",
            "No remote asset fetching, OCR, default-path integration, or Figma write.",
            "Raw DOM text is retained in local evidence; sample intake must exclude credentials and secrets.",
        ],
    }
    manifest["content_hash"] = canonical_hash(manifest)
    return manifest


def _attempt_summaries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    summaries: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        summaries.append(
            {
                "label": item.get("label"),
                "final_url": item.get("final_url"),
                "http_status": item.get("http_status"),
                "page_kind": (item.get("page_state") or {}).get("kind")
                if isinstance(item.get("page_state"), Mapping)
                else None,
                "has_image": bool(item.get("image")),
                "has_dom": bool(item.get("dom")),
                "has_diagnostics": bool(item.get("diagnostics")),
                "error": item.get("error"),
            }
        )
    return summaries


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(jsonable(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _assert_existing_sidecar(path: Path) -> None:
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise EvidenceAdapterError(
            f"refusing to overwrite non-sidecar directory: {path}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceAdapterError(
            f"refusing to overwrite unreadable sidecar manifest: {path}"
        ) from exc
    if manifest.get("sidecar_schema") != SIDECAR_SCHEMA:
        raise EvidenceAdapterError(
            f"refusing to overwrite non-sidecar directory: {path}"
        )


def resolve_capture_fields(
    sidecar: EvidenceSidecar,
    *,
    profile: str = "fixed-authored-chromium/1.0",
):
    """Resolve captured field records without mutating the shadow sidecar."""
    from src.app.services.delivery.field_resolution import resolve_fields

    return resolve_fields(sidecar.runtime_ir.fields, profile)
