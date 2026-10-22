"""Create, verify, and clean a job-scoped Figma ownership marker probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.job_namespace import build_job_namespace  # noqa: E402
from src.app.services.rendering.figma_adapter import (  # noqa: E402
    FigmaBridgeAdapter,
    FigmaBridgeError,
)
from src.config.settings import load_config  # noqa: E402


ROOT_NAME = "P4 Ownership Marker Probe"
DEFAULT_JOB_ID = "p4-ownership-marker-20261022"
PROBE_CLIENT_ID = "p4-ownership-marker-probe"


def _owned_job_id(raw_job_id: str) -> str:
    return build_job_namespace(PROBE_CLIENT_ID, raw_job_id)


def _hash(report: dict[str, Any]) -> str:
    payload = {key: value for key, value in report.items() if key != "content_hash"}
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write_report(path: Path, report: dict[str, Any]) -> None:
    report["content_hash"] = _hash(report)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _manifest_path(out: Path) -> Path:
    return out / "ownership_marker_manifest.json"


def _load_manifest(out: Path) -> dict[str, Any]:
    path = _manifest_path(out)
    if not path.exists():
        raise RuntimeError(f"manifest missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _create(
    adapter: FigmaBridgeAdapter,
    *,
    out: Path,
    job_id: str,
) -> dict[str, Any]:
    namespaced_job_id = _owned_job_id(job_id)
    report: dict[str, Any] = {
        "schema_version": "p4-figma-ownership-marker/1.1",
        "experiment": "P4-OWNERSHIP-MARKER",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "create",
        "job_id": job_id,
        "namespaced_job_id": namespaced_job_id,
        "client_id": PROBE_CLIENT_ID,
        "status": "failed",
    }
    try:
        # A job may be retried after a failed create phase. Clean only this
        # job's exact markers before creating fresh probe nodes.
        precleanup = adapter.cleanup_owned_job(namespaced_job_id)
        result = adapter.apply_batch(
            [
                {
                    "action": "create_frame",
                    "params": {
                        "name": ROOT_NAME,
                        "width": 180,
                        "height": 120,
                        "fillColor": "#ffffff",
                    },
                },
                {
                    "action": "create_rectangle",
                    "params": {
                        "name": f"{ROOT_NAME} Rectangle",
                        "width": 40,
                        "height": 24,
                        "fillColor": "#2563eb",
                    },
                },
            ],
            transaction_id=namespaced_job_id,
        )
        committed = result.get("committed") or []
        node_ids = [
            item.get("result")
            for item in committed
            if isinstance(item, dict) and isinstance(item.get("result"), str)
        ]
        ownership = result.get("ownership") or {}
        report.update(
            {
                "precleanup": precleanup,
                "transaction": result,
                "ownership": ownership,
                "created_node_ids": node_ids,
            }
        )
        if result.get("status") != "committed":
            raise RuntimeError(f"create batch not committed: {result}")
        if ownership.get("marker") != "plugin-data-v1":
            raise RuntimeError(f"ownership receipt missing: {ownership}")
        if ownership.get("jobId") != namespaced_job_id:
            raise RuntimeError(f"ownership job mismatch: {ownership}")
        if int(ownership.get("marked", 0)) != len(node_ids):
            raise RuntimeError(f"marker count mismatch: {ownership}")
        ownership_readback = adapter.ownership_report(namespaced_job_id)
        report["ownership_readback"] = ownership_readback
        reported_ids = {
            node.get("nodeId")
            for node in ownership_readback.get("nodes", [])
            if isinstance(node, dict)
        }
        if ownership_readback.get("matched") != len(node_ids):
            raise RuntimeError(
                f"ownership readback count mismatch: {ownership_readback}"
            )
        if not set(node_ids).issubset(reported_ids):
            raise RuntimeError(
                f"created ids missing from ownership readback: {node_ids}"
            )
        report["status"] = "pass"
    except (FigmaBridgeError, RuntimeError, ValueError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    _write_report(out / "figma_ownership_marker_create.json", report)
    if report["status"] == "pass":
        manifest = {
            "schema_version": "p4-figma-ownership-marker-manifest/1.1",
            "job_id": job_id,
            "namespaced_job_id": namespaced_job_id,
            "client_id": PROBE_CLIENT_ID,
            "node_ids": report["created_node_ids"],
            "root_name": ROOT_NAME,
            "create_content_hash": report["content_hash"],
        }
        _manifest_path(out).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return report


def _verify(
    adapter: FigmaBridgeAdapter,
    *,
    out: Path,
    job_id: str,
    allow_legacy_job_id: bool = False,
) -> dict[str, Any]:
    namespaced_job_id = _owned_job_id(job_id)
    report: dict[str, Any] = {
        "schema_version": "p4-figma-ownership-marker/1.1",
        "experiment": "P4-OWNERSHIP-MARKER",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "verify",
        "job_id": job_id,
        "namespaced_job_id": namespaced_job_id,
        "status": "failed",
    }
    try:
        manifest = _load_manifest(out)
        if str(manifest.get("job_id") or "") != job_id:
            raise RuntimeError("manifest job id mismatch")
        manifest_job_id = str(manifest.get("namespaced_job_id") or "")
        if manifest_job_id:
            if manifest_job_id != namespaced_job_id:
                raise RuntimeError("manifest namespace/client mismatch")
            readback_job_id = manifest_job_id
        elif allow_legacy_job_id:
            readback_job_id = str(manifest.get("job_id") or "")
        else:
            raise RuntimeError(
                "legacy manifest requires --allow-legacy-job-id"
            )
        expected_ids = set(manifest.get("node_ids") or [])
        readback = adapter.ownership_report(readback_job_id)
        actual_ids = {
            node.get("nodeId")
            for node in readback.get("nodes", [])
            if isinstance(node, dict)
        }
        report.update(
            {
                "manifest": manifest,
                "ownership_readback": readback,
                "expected_node_ids": sorted(expected_ids),
                "actual_node_ids": sorted(actual_ids),
            }
        )
        if readback.get("status") != "reported":
            raise RuntimeError(f"ownership report failed: {readback}")
        if not expected_ids.issubset(actual_ids):
            raise RuntimeError("persisted ownership markers are incomplete")
        report["status"] = "pass"
    except (FigmaBridgeError, RuntimeError, ValueError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    _write_report(out / "figma_ownership_marker_verify.json", report)
    return report


def _cleanup(
    adapter: FigmaBridgeAdapter,
    *,
    out: Path,
    job_id: str,
    allow_legacy_job_id: bool = False,
) -> dict[str, Any]:
    namespaced_job_id = _owned_job_id(job_id)
    report: dict[str, Any] = {
        "schema_version": "p4-figma-ownership-marker/1.1",
        "experiment": "P4-OWNERSHIP-MARKER",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "cleanup",
        "job_id": job_id,
        "namespaced_job_id": namespaced_job_id,
        "status": "failed",
    }
    try:
        manifest = _load_manifest(out)
        manifest_job_id = str(manifest.get("namespaced_job_id") or "")
        if manifest_job_id:
            if manifest_job_id != namespaced_job_id:
                raise RuntimeError("manifest namespace/client mismatch")
            cleanup_job_id = manifest_job_id
        elif allow_legacy_job_id:
            cleanup_job_id = str(manifest.get("job_id") or "")
        else:
            raise RuntimeError(
                "legacy manifest requires --allow-legacy-job-id"
            )
        expected_ids = set(manifest.get("node_ids") or [])
        cleanup = adapter.cleanup_owned_job(cleanup_job_id)
        readback = adapter.ownership_report(cleanup_job_id)
        report.update(
            {
                "manifest": manifest,
                "cleanup": cleanup,
                "post_cleanup_readback": readback,
            }
        )
        if cleanup.get("status") not in {"cleaned", "partial"}:
            raise RuntimeError(f"cleanup failed: {cleanup}")
        if cleanup.get("matched") != len(expected_ids):
            raise RuntimeError(
                f"cleanup matched {cleanup.get('matched')} of {len(expected_ids)}"
            )
        if readback.get("matched") != 0:
            raise RuntimeError(f"markers survived cleanup: {readback}")
        report["status"] = "pass"
    except (FigmaBridgeError, RuntimeError, ValueError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    _write_report(out / "figma_ownership_marker_cleanup.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--phase",
        choices=("create", "verify", "cleanup"),
        required=True,
    )
    parser.add_argument("--job-id", default=DEFAULT_JOB_ID)
    parser.add_argument("--allow-legacy-job-id", action="store_true")
    parser.add_argument("--bridge-url", default=None)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    adapter = FigmaBridgeAdapter(
        args.bridge_url or load_config().figma_bridge_url,
        client_id=PROBE_CLIENT_ID,
        allow_legacy_job_ids=args.allow_legacy_job_id,
    )
    adapter.connect()
    try:
        if args.phase == "create":
            report = _create(adapter, out=out, job_id=args.job_id)
        elif args.phase == "verify":
            report = _verify(
                adapter,
                out=out,
                job_id=args.job_id,
                allow_legacy_job_id=args.allow_legacy_job_id,
            )
        else:
            report = _cleanup(
                adapter,
                out=out,
                job_id=args.job_id,
                allow_legacy_job_id=args.allow_legacy_job_id,
            )
    finally:
        adapter.disconnect()
    print(f"[ownership-marker] {report['status']} phase={args.phase}")
    print(f"[out ] {out}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
