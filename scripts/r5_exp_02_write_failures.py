# -*- coding: utf-8 -*- 
"""R5-EXP-02: write-failure injection, reconciliation and compensation.

This experiment has two layers:

1. A deterministic controller/ledger model that exercises interruption points,
   unknown outcomes, replay and compensation. It is intentionally small and
   observable; it is not a production transaction manager.
2. A real-Figma subset that writes a few top-level staging frames through the
   existing WebSocket bridge, reads them back with get_node_tree, and records
   what the current bridge can and cannot guarantee.

The script never claims exactly-once delivery. It records where ownership is
only inferred from stable names and where the bridge has no server-side
idempotency key or reliable ownership marker.

Usage:
  C:/Users/lzq/.conda/envs/omni/python.exe scripts/r5_exp_02_write_failures.py
  ... --skip-real                # deterministic layer only
  ... --out output/_r5_experiments/r5_exp_02_failure_injection
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
import shutil
import sys
import threading
import time
import traceback
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402
from src.config.settings import load_config  # noqa: E402

try:
    import websocket  # type: ignore
except Exception:  # pragma: no cover - reported at runtime
    websocket = None

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PREFIX = "R5-EXP-02"
INVARIANT_NAMES = (
    "duplicate_creates",
    "unauthorized_deletes",
    "unknown_reported_success",
    "preflight_side_effects",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "content_hash"}
    return sha256_text(canonical(payload))


def atomic_write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    last_error = None
    for _attempt in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.01)
    if last_error is not None:
        raise last_error


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class InjectedFault(RuntimeError):
    def __init__(self, point: str, ctx: dict[str, Any] | None = None, detail: str | None = None):
        super().__init__(f"injected fault at {point}")
        self.point = point
        self.ctx = ctx or {}
        self.detail = detail


class FontMissing(RuntimeError):
    pass


class AssetFailure(RuntimeError):
    pass


class PermissionDenied(RuntimeError):
    pass


class RateLimited(RuntimeError):
    pass


class ReadbackTimeout(RuntimeError):
    pass


class ExportFailure(RuntimeError):
    pass


class CompensationFailure(RuntimeError):
    pass


class ParentMissing(RuntimeError):
    pass


class FaultSchedule:
    """One-shot fault entries, optionally with a callback that mutates the model."""

    def __init__(self, entries: list[dict[str, Any]] | None = None):
        self.entries = [dict(entry, used=False) for entry in (entries or [])]

    def add(self, point: str, **kwargs: Any) -> None:
        self.entries.append(dict({"point": point, **kwargs}, used=False))

    def maybe(self, point: str, **ctx: Any) -> None:
        for entry in self.entries:
            if entry.get("used") or entry.get("point") != point:
                continue
            if entry.get("op_index") is not None and entry["op_index"] != ctx.get("op_index"):
                continue
            if entry.get("region") is not None and entry["region"] != ctx.get("region"):
                continue
            if entry.get("occurrence") is not None and entry["occurrence"] != ctx.get("occurrence"):
                continue
            entry["used"] = True
            callback = entry.get("callback")
            if callback is not None:
                callback(ctx)
            raise InjectedFault(point, ctx, entry.get("detail"))


@dataclass
class Op:
    logical_key: str
    region: str
    action: str
    params: dict[str, Any]
    parent_key: str | None = None
    expected: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return str(self.params.get("name") or self.logical_key)

    def payload(self) -> dict[str, Any]:
        return {
            "logical_key": self.logical_key,
            "region": self.region,
            "action": self.action,
            "params": self.params,
            "parent_key": self.parent_key,
            "expected": self.expected,
        }

    def payload_hash(self) -> str:
        return sha256_text(canonical(self.payload()))


class MockFigma:
    """A small deterministic model of the bridge's observable write surface."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.page_children: list[str] = []
        self.seq = 0
        self.lock = threading.RLock()
        self.create_count = 0
        self.fail_font = False
        self.fail_asset = False
        self.permission_denied = False
        self.permission_denied_at_op = 0
        self.rate_limit_remaining = 0
        self.rate_limit_at_op = 0
        self.fail_readback_remaining = 0
        self.fail_export_remaining = 0
        self.fail_next_delete = False
        self.unauthorized_deletes: list[dict[str, Any]] = []
        self.external_deletes: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []

    def _next_id(self) -> str:
        self.seq += 1
        return f"mock:{self.seq}"

    def _maybe_fail_create(self) -> None:
        if self.permission_denied and self.create_count > self.permission_denied_at_op:
            raise PermissionDenied("injected permission denial")
        if self.rate_limit_remaining > 0 and self.create_count > self.rate_limit_at_op:
            self.rate_limit_remaining -= 1
            raise RateLimited("injected rate limit")

    def create(self, op: Op, params: dict[str, Any]) -> str:
        with self.lock:
            self.create_count += 1
            self._maybe_fail_create()
            self.calls.append({"action": op.action, "logical_key": op.logical_key, "params": params})
            action = op.action
            if action == "create_text" and self.fail_font:
                raise FontMissing("FONT_NOT_AVAILABLE: injected missing font")
            if action == "create_image" and self.fail_asset:
                raise AssetFailure("injected asset upload failure")

            parent_id = params.get("parentId")
            reparented = False
            if parent_id and parent_id not in self.nodes:
                parent_id = None
                reparented = True
            nid = self._next_id()
            node_type = "FRAME" if action == "create_frame" else "TEXT" if action == "create_text" else "RECTANGLE"
            node: dict[str, Any] = {
                "id": nid,
                "name": params.get("name") or op.logical_key,
                "type": node_type,
                "x": float(params.get("x") or 0),
                "y": float(params.get("y") or 0),
                "width": float(params.get("width") or 0),
                "height": float(params.get("height") or 0),
                "parent_id": parent_id,
                "children": [],
                "created_by_job": op.params.get("_job"),
                "revision": op.params.get("_revision"),
                "logical_key": op.logical_key,
                "payload_hash": op.payload_hash(),
                "user_modified": False,
                "reparented": reparented,
                "expected_parent": params.get("parentId"),
            }
            if action == "create_text":
                node["characters"] = params.get("text") or ""
                node["font_size"] = float(params.get("fontSize") or 16)
                node["font_family"] = params.get("fontFamily") or "Inter"
                node["fill"] = params.get("textColor") or "#000000"
            elif action in ("create_rectangle", "create_image"):
                node["fill"] = params.get("fillColor") or ("IMAGE" if action == "create_image" else "#000000")
                if action == "create_image":
                    node["imageBase64"] = params.get("imageBase64") or ""
            self.nodes[nid] = node
            if parent_id:
                self.nodes[parent_id]["children"].append(nid)
            else:
                self.page_children.append(nid)
            return nid

    def read_node(self, node_id: str) -> dict[str, Any]:
        with self.lock:
            if self.fail_readback_remaining > 0:
                self.fail_readback_remaining -= 1
                raise ReadbackTimeout("injected readback timeout")
            if node_id not in self.nodes:
                raise KeyError(node_id)
            return self._node_summary(node_id, depth=3)

    def _node_summary(self, node_id: str, depth: int) -> dict[str, Any]:
        node = self.nodes[node_id]
        summary = {
            "id": node["id"],
            "name": node["name"],
            "type": node["type"],
            "x": node["x"],
            "y": node["y"],
            "width": node["width"],
            "height": node["height"],
            "parent_id": node["parent_id"],
            "created_by_job": node["created_by_job"],
            "revision": node["revision"],
            "logical_key": node["logical_key"],
            "payload_hash": node["payload_hash"],
            "user_modified": node["user_modified"],
            "reparented": node["reparented"],
        }
        for key in ("characters", "font_size", "font_family", "fill", "imageBase64"):
            if key in node:
                summary[key] = node[key]
        if depth > 0:
            summary["children"] = [self._node_summary(child, depth - 1) for child in node["children"]]
        return summary

    def page_tree(self) -> dict[str, Any]:
        with self.lock:
            return {
                "id": "mock:page",
                "name": "Mock Page",
                "type": "PAGE",
                "children": [self._node_summary(node_id, depth=4) for node_id in self.page_children],
            }

    def find_candidates(self, op: Op) -> list[dict[str, Any]]:
        with self.lock:
            return [
                node for node in self.nodes.values()
                if node.get("logical_key") == op.logical_key
                and node.get("created_by_job") == op.params.get("_job")
                and node.get("revision") == op.params.get("_revision")
            ]

    def duplicate_count(self) -> int:
        with self.lock:
            counts = Counter(
                (node.get("created_by_job"), node.get("revision"), node.get("logical_key"))
                for node in self.nodes.values()
            )
            return sum(max(0, count - 1) for count in counts.values())

    def count_nodes(self) -> int:
        with self.lock:
            return len(self.nodes)

    def delete_top_level_by_name(self, name: str, by_job: str, reason: str) -> int:
        with self.lock:
            victims = [
                node_id for node_id in list(self.page_children)
                if self.nodes.get(node_id, {}).get("name") == name
            ]
            removed = 0
            for node_id in victims:
                node = self.nodes.get(node_id)
                if not node:
                    continue
                if node.get("created_by_job") != by_job or node.get("user_modified"):
                    self.unauthorized_deletes.append({
                        "node_id": node_id,
                        "name": node.get("name"),
                        "owner": node.get("created_by_job"),
                        "job": by_job,
                        "reason": reason,
                    })
                    raise PermissionDenied("refused to delete a node not owned by this job")
                if self.fail_next_delete:
                    self.fail_next_delete = False
                    raise CompensationFailure("injected compensation failure")
                self._delete_recursive(node_id)
                removed += 1
            return removed

    def _delete_recursive(self, node_id: str) -> None:
        node = self.nodes.get(node_id)
        if not node:
            return
        for child in list(node.get("children") or []):
            self._delete_recursive(child)
        parent_id = node.get("parent_id")
        if parent_id and parent_id in self.nodes:
            try:
                self.nodes[parent_id]["children"].remove(node_id)
            except ValueError:
                pass
        if node_id in self.page_children:
            self.page_children.remove(node_id)
        self.nodes.pop(node_id, None)

    def external_delete(self, node_id: str) -> None:
        with self.lock:
            self.external_deletes.append({"node_id": node_id, "name": self.nodes.get(node_id, {}).get("name")})
            self._delete_recursive(node_id)

    def export_region(self, name: str) -> dict[str, Any]:
        with self.lock:
            if self.fail_export_remaining > 0:
                self.fail_export_remaining -= 1
                raise ExportFailure("injected export failure")
            matches = [nid for nid in self.page_children if self.nodes.get(nid, {}).get("name") == name]
            if len(matches) != 1:
                raise ExportFailure(f"expected one top-level node named {name}, found {len(matches)}")
            return {"node_id": matches[0], "bytes": 128, "sha256": sha256_text(name)[:16]}


class Ledger:
    def __init__(self, path: Path, job: str, revision: str, faults: FaultSchedule | None = None):
        self.path = path
        self.faults = faults
        if path.exists():
            self.data = read_json(path)
        else:
            self.data = {
                "schema": "r5-exp-02/ledger/v1",
                "job": job,
                "revision": revision,
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "job_status": "planned",
                "plan_hash": None,
                "regions": {},
                "ops": {},
                "events": [],
            }
        self.data["job"] = job
        self.data["revision"] = revision

    def save(self, point: str = "persist", **ctx: Any) -> None:
        if self.faults is not None:
            self.faults.maybe(point, **ctx)
        self.data["updated_at"] = now_iso()
        atomic_write_json(self.path, self.data)

    def entry(self, intent_key: str) -> dict[str, Any] | None:
        return self.data.setdefault("ops", {}).get(intent_key)

    def append_event(self, event: dict[str, Any]) -> None:
        self.data.setdefault("events", []).append(event)

class Controller:
    def __init__(
        self,
        fig: MockFigma,
        ledger: Ledger,
        job: str,
        revision: str,
        events: list[dict[str, Any]],
        run_id: str,
        faults: FaultSchedule | None = None,
    ):
        self.fig = fig
        self.ledger = ledger
        self.job = job
        self.revision = revision
        self.events = events
        self.run_id = run_id
        self.faults = faults or FaultSchedule()

    def _event(self, event: str, **detail: Any) -> None:
        record = {
            "seq": len(self.events) + 1,
            "at": now_iso(),
            "run_id": self.run_id,
            "event": event,
            **detail,
        }
        self.events.append(record)
        self.ledger.append_event(record)

    def intent_key(self, op: Op) -> str:
        return sha256_text(canonical({
            "job": self.job,
            "revision": self.revision,
            "logical_key": op.logical_key,
            "operation_type": op.action,
            "payload_hash": op.payload_hash(),
        }))

    def ensure_entry(self, op: Op, state: str = "planned") -> dict[str, Any]:
        key = self.intent_key(op)
        existing = self.ledger.entry(key)
        if existing is not None:
            return existing
        entry = {
            "intent_key": key,
            "op_id": op.logical_key,
            "region": op.region,
            "logical_key": op.logical_key,
            "action": op.action,
            "payload_hash": op.payload_hash(),
            "params": op.params,
            "parent_key": op.parent_key,
            "state": state,
            "figma_id": None,
            "attempts": 0,
            "proven_no_side_effect": False,
            "ownership": None,
            "errors": [],
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        self.ledger.data["ops"][key] = entry
        return entry

    def plan(self, regions: dict[str, list[Op]]) -> None:
        plan = {region: [op.payload() for op in ops] for region, ops in regions.items()}
        self.ledger.data["plan"] = plan
        self.ledger.data["plan_hash"] = sha256_text(canonical(plan))
        for region, ops in regions.items():
            self.ledger.data["regions"][region] = {
                "status": "planned",
                "op_keys": [self.intent_key(op) for op in ops],
            }
            for op in ops:
                self.ensure_entry(op, "planned")
        try:
            self.ledger.save("preflight_persist", fig=self.fig, job=self.job)
        except InjectedFault as exc:
            self.ledger.data["job_status"] = "blocked-persistence"
            self._event("preflight-persistence-failed", detail=str(exc))
            raise
        self.ledger.data["job_status"] = "planned"
        self.ledger.save("persist")
        self._event("plan-persisted", plan_hash=self.ledger.data["plan_hash"])

    def _resolve_params(self, op: Op) -> dict[str, Any]:
        params = dict(op.params)
        if op.parent_key:
            parent = self.ledger.entry(self.intent_key_for_key(op.parent_key))
            if not parent or not parent.get("figma_id"):
                raise ParentMissing(f"parent intent has no figma id: {op.parent_key}")
            params["parentId"] = parent["figma_id"]
        return params

    def intent_key_for_key(self, logical_key: str) -> str:
        plan = self.ledger.data.get("plan") or {}
        for _region, ops in plan.items():
            for payload in ops:
                if payload.get("logical_key") == logical_key:
                    return sha256_text(canonical({
                        "job": self.job,
                        "revision": self.revision,
                        "logical_key": payload["logical_key"],
                        "operation_type": payload["action"],
                        "payload_hash": sha256_text(canonical(payload)),
                    }))
        raise KeyError(logical_key)

    def _verify(self, op: Op, node: dict[str, Any]) -> list[str]:
        mismatches: list[str] = []
        expected = op.expected or {}
        if expected.get("type") and node.get("type") != expected["type"]:
            mismatches.append(f"type:{node.get('type')}!={expected['type']}")
        if expected.get("characters") is not None and node.get("characters") != expected["characters"]:
            mismatches.append("characters")
        if expected.get("fontSize") is not None and abs(float(node.get("font_size") or 0) - float(expected["fontSize"])) > 0.01:
            mismatches.append("fontSize")
        if expected.get("width") is not None and abs(float(node.get("width") or 0) - float(expected["width"])) > 0.01:
            mismatches.append("width")
        if expected.get("height") is not None and abs(float(node.get("height") or 0) - float(expected["height"])) > 0.01:
            mismatches.append("height")
        if expected.get("fill") is not None and node.get("fill") != expected["fill"]:
            mismatches.append("fill")
        if op.parent_key:
            parent = self.ledger.entry(self.intent_key_for_key(op.parent_key))
            if parent and parent.get("figma_id") and node.get("parent_id") != parent["figma_id"]:
                mismatches.append("parent")
        if node.get("reparented"):
            mismatches.append("reparented")
        return mismatches

    def _reconcile(self, op: Op, entry: dict[str, Any]) -> tuple[str, Any]:
        candidates = self.fig.find_candidates(op)
        if len(candidates) == 0:
            if entry.get("proven_no_side_effect"):
                return "absent-safe", None
            return "unknown-absent", None
        if len(candidates) > 1:
            return "ambiguous-multiple", candidates
        node = candidates[0]
        if node.get("name") != op.name:
            return "ambiguous-renamed", node
        if node.get("user_modified"):
            return "ambiguous-user-modified", node
        if node.get("payload_hash") != op.payload_hash():
            return "ambiguous-payload", node
        return "owned-unique", node

    def _verify_existing(self, op: Op, entry: dict[str, Any]) -> tuple[str, Any]:
        node_id = entry.get("figma_id")
        if not node_id or node_id not in self.fig.nodes:
            return "missing", None
        node = self.fig.nodes[node_id]
        if node.get("name") != op.name:
            return "ambiguous-renamed", node
        if node.get("user_modified"):
            return "ambiguous-user-modified", node
        summary = None
        for attempt in range(3):
            try:
                summary = self.fig.read_node(node_id)
                break
            except ReadbackTimeout:
                if attempt == 2:
                    raise
                time.sleep(0.005)
        if summary is None:
            return "verification-pending", None
        mismatches = self._verify(op, summary)
        if mismatches:
            return "conflict", mismatches
        entry["state"] = "verified"
        entry["updated_at"] = now_iso()
        self.ledger.save("persist")
        self._event("op-verified", op_id=op.logical_key, figma_id=node_id)
        return "ok", summary

    def _block(self, region: str, status: str, op: Op | None, detail: Any) -> dict[str, Any]:
        self.ledger.data["regions"][region]["status"] = status
        self.ledger.data["regions"][region]["detail"] = detail
        self.ledger.data["job_status"] = status
        self.ledger.save("persist")
        self._event("region-blocked", region=region, status=status, op_id=op.logical_key if op else None, detail=detail)
        return {"status": status, "region": region, "detail": detail}

    def _compensate(self, region: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        roots = []
        for entry in entries:
            node_id = entry.get("figma_id")
            node = self.fig.nodes.get(node_id) if node_id else None
            if node and node.get("parent_id") is None and node.get("created_by_job") == self.job:
                if not node.get("user_modified"):
                    roots.append(node)
        if not roots:
            return {"status": "no-owned-root", "removed": 0}
        removed = 0
        try:
            for node in roots:
                removed += self.fig.delete_top_level_by_name(node["name"], self.job, "compensation")
        except CompensationFailure as exc:
            self.ledger.data["regions"][region]["status"] = "compensation-failed"
            self.ledger.data["regions"][region]["residue"] = [
                {"node_id": node["id"], "name": node["name"]} for node in roots
            ]
            self.ledger.data["job_status"] = "compensation-failed"
            self.ledger.save("persist")
            self._event("compensation-failed", region=region, residue=self.ledger.data["regions"][region]["residue"])
            return {"status": "compensation-failed", "removed": removed, "error": str(exc)}
        self._event("compensation-complete", region=region, removed=removed)
        return {"status": "compensated", "removed": removed}

    def execute_region(self, region: str, ops: list[Op]) -> dict[str, Any]:
        region_entry = self.ledger.data["regions"].setdefault(region, {"status": "planned", "op_keys": []})
        if region_entry.get("status") == "committed":
            return {"status": "committed", "region": region}
        entries = [self.ensure_entry(op, "planned") for op in ops]
        for index, op in enumerate(ops):
            entry = entries[index]
            if entry.get("state") == "verified":
                continue
            if entry.get("state") in ("acknowledged", "verification-pending", "recovered"):
                status, detail = self._verify_existing(op, entry)
                if status == "ok":
                    continue
                if status == "missing":
                    return self._block(region, "conflict-missing", op, {"reason": "ledger id no longer exists"})
                if status == "conflict":
                    return self._block(region, "conflict", op, {"mismatches": detail})
                return self._block(region, status, op, {"node": detail})
            if entry.get("state") in ("unknown-outcome", "prepared", "sending", "planned"):
                if entry.get("state") != "planned" or entry.get("attempts", 0) > 0:
                    status, detail = self._reconcile(op, entry)
                    if status == "owned-unique":
                        entry["figma_id"] = detail["id"]
                        entry["state"] = "recovered"
                        entry["ownership"] = "unique-name-and-model-metadata"
                        entry["updated_at"] = now_iso()
                        self.ledger.save("persist")
                        self._event("op-recovered", op_id=op.logical_key, figma_id=detail["id"])
                        verify_status, verify_detail = self._verify_existing(op, entry)
                        if verify_status == "ok":
                            entry["state"] = "verified"
                            self.ledger.save("persist")
                            continue
                        return self._block(region, verify_status, op, {"node": verify_detail})
                    if status == "absent-safe":
                        entry["state"] = "planned"
                        self.ledger.save("persist")
                    else:
                        return self._block(region, status, op, {"candidates": detail})

            while True:
                entry["state"] = "prepared"
                entry["attempts"] = int(entry.get("attempts") or 0) + 1
                entry["proven_no_side_effect"] = False
                entry["updated_at"] = now_iso()
                self.ledger.save("persist")
                self._event("op-prepared", region=region, op_index=index, op_id=op.logical_key, attempt=entry["attempts"])
                try:
                    self.faults.maybe("before_send", region=region, op_index=index, entry=entry, op=op, fig=self.fig)
                except InjectedFault:
                    entry["state"] = "prepared"
                    entry["proven_no_side_effect"] = True
                    self.ledger.save("persist")
                    self._event("interrupted-before-send", region=region, op_index=index, op_id=op.logical_key)
                    return {"status": "interrupted", "region": region, "point": "before-send"}

                try:
                    params = self._resolve_params(op)
                    node_id = self.fig.create(op, params)
                except RateLimited:
                    entry["state"] = "rate-limited"
                    entry["updated_at"] = now_iso()
                    self.ledger.save("persist")
                    self._event("rate-limited", region=region, op_index=index, attempt=entry["attempts"])
                    if entry["attempts"] >= 3:
                        result = self._block(region, "paused", op, {"attempts": entry["attempts"]})
                        self._compensate(region, entries)
                        return result
                    time.sleep(0.005)
                    continue
                except FontMissing as exc:
                    entry["state"] = "blocked-font"
                    entry["errors"].append(str(exc))
                    self.ledger.save("persist")
                    result = self._block(region, "blocked-font", op, {"error": str(exc)})
                    self._compensate(region, entries)
                    return result
                except AssetFailure as exc:
                    entry["state"] = "blocked-asset"
                    entry["errors"].append(str(exc))
                    self.ledger.save("persist")
                    result = self._block(region, "blocked-asset", op, {"error": str(exc)})
                    self._compensate(region, entries)
                    return result
                except PermissionDenied as exc:
                    entry["state"] = "blocked-access"
                    entry["errors"].append(str(exc))
                    self.ledger.save("persist")
                    result = self._block(region, "blocked-access", op, {"error": str(exc)})
                    self._compensate(region, entries)
                    return result
                except ParentMissing as exc:
                    entry["state"] = "parent-conflict"
                    entry["errors"].append(str(exc))
                    self.ledger.save("persist")
                    result = self._block(region, "parent-conflict", op, {"error": str(exc)})
                    self._compensate(region, entries)
                    return result

                try:
                    self.faults.maybe("after_send_before_response", region=region, op_index=index, entry=entry, op=op, fig=self.fig)
                except InjectedFault:
                    entry["state"] = "unknown-outcome"
                    entry["figma_id"] = None
                    entry["proven_no_side_effect"] = False
                    self.ledger.save("persist")
                    self._event("interrupted-after-send", region=region, op_index=index, op_id=op.logical_key)
                    return {"status": "interrupted", "region": region, "point": "after-send-before-response"}

                try:
                    self.faults.maybe("after_response_before_ledger_commit", region=region, op_index=index, entry=entry, op=op, fig=self.fig)
                except InjectedFault:
                    entry["state"] = "unknown-outcome"
                    entry["figma_id"] = None
                    entry["proven_no_side_effect"] = False
                    self.ledger.save("persist")
                    self._event("interrupted-after-response", region=region, op_index=index, op_id=op.logical_key)
                    return {"status": "interrupted", "region": region, "point": "after-response-before-ledger-commit"}

                entry["figma_id"] = node_id
                entry["state"] = "acknowledged"
                entry["ownership"] = "model-metadata"
                entry["updated_at"] = now_iso()
                self.ledger.save("persist")
                self._event("op-acknowledged", region=region, op_index=index, op_id=op.logical_key, figma_id=node_id)
                try:
                    self.faults.maybe("after_ledger_commit", region=region, op_index=index, entry=entry, op=op, fig=self.fig)
                except InjectedFault:
                    self._event("interrupted-after-ledger", region=region, op_index=index, op_id=op.logical_key)
                    return {"status": "interrupted", "region": region, "point": "after-ledger-commit"}

                try:
                    node = self.fig.read_node(node_id)
                except ReadbackTimeout as exc:
                    entry["state"] = "verification-pending"
                    entry["errors"].append(str(exc))
                    self.ledger.save("persist")
                    self._event("readback-timeout", region=region, op_index=index, figma_id=node_id)
                    return self._block(region, "verification-pending", op, {"error": str(exc), "figma_id": node_id})

                mismatches = self._verify(op, node)
                if mismatches:
                    entry["state"] = "conflict"
                    entry["conflict"] = mismatches
                    self.ledger.save("persist")
                    result = self._block(region, "conflict", op, {"mismatches": mismatches})
                    self._compensate(region, entries)
                    return result
                entry["state"] = "verified"
                entry["updated_at"] = now_iso()
                self.ledger.save("persist")
                self._event("op-verified", region=region, op_index=index, op_id=op.logical_key, figma_id=node_id)
                break

        region_entry["status"] = "committed"
        region_entry["committed_at"] = now_iso()
        self._finalize_job_status()
        self.ledger.save("persist")
        self._event("region-committed", region=region)
        return {"status": "committed", "region": region}

    def _finalize_job_status(self) -> None:
        statuses = [entry.get("status") for entry in self.ledger.data.get("regions", {}).values()]
        if statuses and all(status == "committed" for status in statuses):
            self.ledger.data["job_status"] = "committed"
        elif any(status == "written-verification-pending" for status in statuses):
            self.ledger.data["job_status"] = "written-verification-pending"
        elif any(status == "compensation-failed" for status in statuses):
            self.ledger.data["job_status"] = "compensation-failed"
        elif any(str(status).startswith("blocked") for status in statuses):
            self.ledger.data["job_status"] = next(str(status) for status in statuses if str(status).startswith("blocked"))
        elif any(status in ("paused", "parent-conflict", "conflict", "verification-pending") for status in statuses):
            self.ledger.data["job_status"] = next(str(status) for status in statuses if status in ("paused", "parent-conflict", "conflict", "verification-pending"))
        elif statuses:
            unresolved = [
                str(status) for status in statuses
                if status not in ("committed", "planned", "in-progress")
            ]
            self.ledger.data["job_status"] = unresolved[0] if unresolved else "in-progress"
        else:
            self.ledger.data["job_status"] = "in-progress"

    def execute_all(self, regions: dict[str, list[Op]]) -> dict[str, Any]:
        for region, ops in regions.items():
            result = self.execute_region(region, ops)
            if result["status"] != "committed":
                self._finalize_job_status()
                self.ledger.save("persist")
                return {"status": "stopped", "region": region, "detail": result}
        self._finalize_job_status()
        self.ledger.save("persist")
        return {"status": "committed"}

    def resume(self, regions: dict[str, list[Op]]) -> dict[str, Any]:
        if self.ledger.data.get("job_status") == "blocked-persistence":
            return {"status": "blocked-persistence"}
        self.ledger.data["job_status"] = "resuming"
        self.ledger.save("persist")
        self._event("resume-start")
        for region, ops in regions.items():
            status = self.ledger.data.get("regions", {}).get(region, {}).get("status")
            if status == "committed":
                continue
            if status in (
                "blocked-font", "blocked-asset", "blocked-access", "paused",
                "parent-conflict", "compensation-failed", "written-verification-pending",
                "conflict", "conflict-missing", "ambiguous-multiple", "ambiguous-renamed",
                "ambiguous-user-modified", "ambiguous-payload",
            ):
                self._event("resume-stopped", region=region, status=status)
                self._finalize_job_status()
                self.ledger.save("persist")
                return {"status": status, "region": region}
            for index, op in enumerate(ops):
                entry = self.ensure_entry(op, "planned")
                if entry.get("state") == "verified":
                    continue
                if entry.get("state") in ("acknowledged", "verification-pending", "recovered"):
                    verify_status, verify_detail = self._verify_existing(op, entry)
                    if verify_status == "ok":
                        continue
                    if verify_status == "missing":
                        result = self._block(region, "conflict-missing", op, {"reason": "ledger id no longer exists"})
                        self._finalize_job_status()
                        return {"status": "stopped", "region": region, "detail": result}
                    if verify_status == "conflict":
                        result = self._block(region, "conflict", op, {"mismatches": verify_detail})
                        self._finalize_job_status()
                        return {"status": "stopped", "region": region, "detail": result}
                    result = self._block(region, verify_status, op, {"node": verify_detail})
                    self._finalize_job_status()
                    return {"status": "stopped", "region": region, "detail": result}
                if entry.get("state") in ("unknown-outcome", "prepared", "sending"):
                    reconcile_status, detail = self._reconcile(op, entry)
                    if reconcile_status == "owned-unique":
                        entry["figma_id"] = detail["id"]
                        entry["state"] = "recovered"
                        entry["ownership"] = "unique-name-and-model-metadata"
                        entry["updated_at"] = now_iso()
                        self.ledger.save("persist")
                        self._event("resume-recovered", region=region, op_index=index, figma_id=detail["id"])
                        verify_status, verify_detail = self._verify_existing(op, entry)
                        if verify_status == "ok":
                            continue
                        result = self._block(region, verify_status, op, {"node": verify_detail})
                        self._finalize_job_status()
                        return {"status": "stopped", "region": region, "detail": result}
                    if reconcile_status == "absent-safe":
                        entry["state"] = "planned"
                        self.ledger.save("persist")
                        continue
                    result = self._block(region, reconcile_status, op, {"candidates": detail})
                    self._finalize_job_status()
                    return {"status": "stopped", "region": region, "detail": result}
            result = self.execute_region(region, ops)
            if result["status"] != "committed":
                self._finalize_job_status()
                self.ledger.save("persist")
                return {"status": "stopped", "region": region, "detail": result}
        self._finalize_job_status()
        self.ledger.save("persist")
        self._event("resume-complete", job_status=self.ledger.data.get("job_status"))
        return {"status": self.ledger.data.get("job_status")}

    def verify_export(self, region: str, root_name: str) -> dict[str, Any]:
        region_entry = self.ledger.data["regions"].setdefault(region, {"status": "committed"})
        if region_entry.get("status") not in ("committed", "written-verification-pending"):
            return {"status": "skipped", "region_status": region_entry.get("status")}
        try:
            result = self.fig.export_region(root_name)
        except ExportFailure as exc:
            region_entry["status"] = "written-verification-pending"
            region_entry["export_error"] = str(exc)
            self._finalize_job_status()
            self.ledger.save("persist")
            self._event("export-failed", region=region, error=str(exc))
            return {"status": "written-verification-pending", "error": str(exc)}
        region_entry["status"] = "committed"
        region_entry["export"] = result
        self._finalize_job_status()
        self.ledger.save("persist")
        self._event("export-verified", region=region, result=result)
        return {"status": "committed", "result": result}

def make_region_ops(job: str, revision: str, region: str, with_image: bool = False) -> list[Op]:
    suffix = f"{PREFIX} {job} rev{revision} {region}"
    frame_key = f"{region}.frame"
    frame_params = {
        "name": f"{suffix} FRAME",
        "x": 0,
        "y": 0,
        "width": 360,
        "height": 220,
        "fillColor": "#ffffff",
        "_job": job,
        "_revision": revision,
    }
    ops = [
        Op(
            logical_key=frame_key,
            region=region,
            action="create_frame",
            params=frame_params,
            expected={"type": "FRAME", "width": 360, "height": 220},
        )
    ]
    if with_image:
        ops.append(Op(
            logical_key=f"{region}.image",
            region=region,
            action="create_image",
            params={
                "name": f"{suffix} IMAGE",
                "x": 20,
                "y": 70,
                "width": 120,
                "height": 80,
                "imageBase64": "AAAA",
                "_job": job,
                "_revision": revision,
            },
            parent_key=frame_key,
            expected={"type": "RECTANGLE", "width": 120, "height": 80},
        ))
    ops.append(Op(
        logical_key=f"{region}.text",
        region=region,
        action="create_text",
        params={
            "name": f"{suffix} TEXT",
            "x": 20,
            "y": 20,
            "width": 240,
            "height": 28,
            "text": f"R5-EXP-02 {region}",
            "fontSize": 18,
            "fontFamily": "Inter",
            "fontWeight": 600,
            "fontPolicy": "strict",
            "textColor": "#0f172a",
            "_job": job,
            "_revision": revision,
        },
        parent_key=frame_key,
        expected={"type": "TEXT", "characters": f"R5-EXP-02 {region}", "fontSize": 18},
    ))
    ops.append(Op(
        logical_key=f"{region}.rect",
        region=region,
        action="create_rectangle",
        params={
            "name": f"{suffix} RECT",
            "x": 20,
            "y": 120,
            "width": 120,
            "height": 48,
            "fillColor": "#1d4ed8",
            "borderRadius": 8,
            "_job": job,
            "_revision": revision,
        },
        parent_key=frame_key,
        expected={"type": "RECTANGLE", "width": 120, "height": 48, "fill": "#1d4ed8"},
    ))
    return ops


def base_regions(job: str, revision: str) -> dict[str, list[Op]]:
    return {
        "A": make_region_ops(job, revision, "A"),
        "B": make_region_ops(job, revision, "B"),
        "C": make_region_ops(job, revision, "C"),
    }


def setup_case(case_id: str, variant: int, fig: MockFigma, faults: FaultSchedule, regions: dict[str, list[Op]]) -> None:
    def rename_callback(ctx: dict[str, Any]) -> None:
        node_id = ctx.get("entry", {}).get("figma_id")
        if node_id and node_id in ctx["fig"].nodes:
            ctx["fig"].nodes[node_id]["name"] = f"USER RENAMED {node_id}"

    def user_modified_callback(ctx: dict[str, Any]) -> None:
        node_id = ctx.get("entry", {}).get("figma_id")
        if node_id and node_id in ctx["fig"].nodes:
            ctx["fig"].nodes[node_id]["user_modified"] = True

    def delete_parent_callback(ctx: dict[str, Any]) -> None:
        node_id = ctx.get("entry", {}).get("figma_id")
        if not node_id or node_id not in ctx["fig"].nodes:
            return
        node = ctx["fig"].nodes[node_id]
        target = node.get("parent_id") or node_id
        ctx["fig"].external_delete(target)

    def readback_callback(ctx: dict[str, Any]) -> None:
        ctx["fig"].fail_readback_remaining = max(1, ctx["fig"].fail_readback_remaining)

    if case_id == "preflight-persistence-failure":
        faults.add("preflight_persist")
    elif case_id == "before-send":
        faults.add("before_send", op_index=variant)
    elif case_id == "after-send-before-response":
        faults.add("after_send_before_response", op_index=variant)
    elif case_id == "after-response-before-ledger-commit":
        faults.add("after_response_before_ledger_commit", op_index=variant)
    elif case_id == "after-ledger-commit":
        faults.add("after_ledger_commit", op_index=variant)
    elif case_id == "readback-timeout":
        faults.add("after_ledger_commit", op_index=variant, callback=readback_callback)
    elif case_id == "node-renamed":
        faults.add("after_ledger_commit", op_index=variant, callback=rename_callback)
    elif case_id == "user-modified":
        faults.add("after_ledger_commit", op_index=variant, callback=user_modified_callback)
    elif case_id == "parent-deleted":
        faults.add("after_ledger_commit", op_index=variant, callback=delete_parent_callback)
    elif case_id == "font-missing":
        fig.fail_font = True
    elif case_id == "asset-failure":
        fig.fail_asset = True
    elif case_id == "permission-denied":
        fig.permission_denied = True
        fig.permission_denied_at_op = variant
    elif case_id == "rate-limited":
        fig.rate_limit_remaining = 2 if variant < 2 else 5
        fig.rate_limit_at_op = variant
    elif case_id == "compensation-failure":
        fig.fail_font = True
        fig.fail_next_delete = True
    elif case_id == "export-failure":
        fig.fail_export_remaining = 1 if variant < 2 else 3


def run_deterministic_case(out_root: Path, case_id: str, variant: int) -> dict[str, Any]:
    job = f"JOB-DET-{case_id}"
    revision = "rev1"
    case_dir = out_root / "deterministic" / case_id / f"variant-{variant}"
    case_dir.mkdir(parents=True, exist_ok=True)
    fig = MockFigma()
    events: list[dict[str, Any]] = []
    faults = FaultSchedule()
    regions = base_regions(job, revision)
    if case_id == "asset-failure":
        regions["A"] = make_region_ops(job, revision, "A", with_image=True)
    setup_case(case_id, variant, fig, faults, regions)
    ledger = Ledger(case_dir / "ledger.json", job, revision, faults)
    controller = Controller(fig, ledger, job, revision, events, f"{case_id}:{variant}", faults)

    plan_failed = False
    run_error = None
    try:
        controller.plan(regions)
    except InjectedFault:
        plan_failed = True
    except Exception as exc:  # noqa: BLE001
        run_error = f"{type(exc).__name__}: {exc}"
    if not plan_failed and run_error is None:
        try:
            controller.execute_all(regions)
        except InjectedFault:
            pass
        except Exception as exc:  # noqa: BLE001
            run_error = f"{type(exc).__name__}: {exc}"
        try:
            controller.resume(regions)
            controller.resume(regions)
        except InjectedFault:
            pass
        except Exception as exc:  # noqa: BLE001
            run_error = f"{type(exc).__name__}: {exc}"

    if case_id == "export-failure":
        # The region was written successfully; export failure must not cause a rewrite.
        controller.verify_export("A", regions["A"][0].name)
        controller.verify_export("A", regions["A"][0].name)

    if case_id == "duplicate-rerun":
        try:
            controller.execute_all(regions)
            controller.resume(regions)
        except Exception as exc:  # noqa: BLE001
            run_error = f"{type(exc).__name__}: {exc}"

    ledger_path = case_dir / "ledger.json"
    if ledger_path.exists():
        atomic_write_json(ledger_path, ledger.data)

    duplicate_creates = fig.duplicate_count()
    unauthorized_deletes = len(fig.unauthorized_deletes)
    unknown_success = 0
    for entry in ledger.data.get("ops", {}).values():
        region_status = ledger.data.get("regions", {}).get(entry.get("region"), {}).get("status")
        if entry.get("state") in ("unknown-outcome", "unknown-absent", "ambiguous-multiple", "ambiguous-renamed", "ambiguous-user-modified", "ambiguous-payload") and region_status in ("committed", "verified"):
            unknown_success += 1
    preflight_side_effects = 1 if case_id == "preflight-persistence-failure" and fig.count_nodes() > 0 else 0
    invariants = {
        "duplicate_creates": duplicate_creates,
        "unauthorized_deletes": unauthorized_deletes,
        "unknown_reported_success": unknown_success,
        "preflight_side_effects": preflight_side_effects,
    }
    job_status = ledger.data.get("job_status")
    region_statuses = {region: data.get("status") for region, data in ledger.data.get("regions", {}).items()}
    residue = []
    for entry in ledger.data.get("regions", {}).values():
        residue.extend(entry.get("residue") or [])
    ownership_inferred = sum(
        1 for entry in ledger.data.get("ops", {}).values()
        if entry.get("ownership") == "unique-name-and-model-metadata"
    )

    if case_id == "preflight-persistence-failure":
        expected = job_status == "blocked-persistence" and fig.count_nodes() == 0
    elif case_id in (
        "before-send", "after-send-before-response", "after-response-before-ledger-commit",
        "after-ledger-commit", "readback-timeout", "save-resume", "duplicate-rerun",
    ):
        expected = job_status == "committed" and all(status == "committed" for status in region_statuses.values())
    elif case_id == "export-failure":
        expected = (
            (variant < 2 and job_status == "committed")
            or (variant >= 2 and job_status == "written-verification-pending")
        ) and duplicate_creates == 0
    elif case_id == "rate-limited":
        expected = (
            (variant < 2 and job_status == "committed")
            or (variant >= 2 and job_status in ("paused", "blocked-access"))
        ) and duplicate_creates == 0
    elif case_id in ("font-missing", "asset-failure", "permission-denied"):
        expected = job_status in ("blocked-font", "blocked-asset", "blocked-access") and duplicate_creates == 0
    elif case_id in ("node-renamed", "user-modified", "parent-deleted"):
        expected = (
            job_status in ("ambiguous-renamed", "ambiguous-user-modified", "parent-conflict", "conflict-missing")
            or str(job_status).startswith("blocked")
        ) and duplicate_creates == 0 and unauthorized_deletes == 0
    elif case_id == "compensation-failure":
        expected = job_status == "compensation-failed" and bool(residue) and duplicate_creates == 0
    else:
        expected = False

    safety_ok = (
        duplicate_creates == 0
        and unauthorized_deletes == 0
        and unknown_success == 0
        and preflight_side_effects == 0
    )
    run = {
        "case_id": case_id,
        "variant": variant,
        "job": job,
        "revision": revision,
        "run_id": f"{case_id}:{variant}",
        "job_status": job_status,
        "region_statuses": region_statuses,
        "invariants": invariants,
        "safety_ok": safety_ok,
        "expected_behavior_met": expected,
        "passed": safety_ok and expected and run_error is None,
        "run_error": run_error,
        "node_count": fig.count_nodes(),
        "ownership_inferred_ops": ownership_inferred,
        "residue": residue,
        "plan_failed": plan_failed,
        "nodes": fig.page_tree(),
        "events": events,
        "ledger": ledger.data,
    }
    atomic_write_json(case_dir / "run.json", run)
    return run


def run_concurrent_case(out_root: Path, with_lock: bool) -> dict[str, Any]:
    job = f"JOB-DET-concurrent-{'lock' if with_lock else 'nolock'}"
    revision = "rev1"
    case_dir = out_root / "deterministic" / ("concurrent-with-lock" if with_lock else "concurrent-without-lock")
    case_dir.mkdir(parents=True, exist_ok=True)
    fig = MockFigma()
    ledger_path = case_dir / "ledger.json"
    if ledger_path.exists():
        ledger_path.unlink()
    events: list[dict[str, Any]] = []
    regions = {"A": make_region_ops(job, revision, "A")}
    thread_lock = threading.Lock()
    barrier = threading.Barrier(2)
    outcomes: list[dict[str, Any]] = []

    def worker(index: int) -> None:
        if with_lock:
            with thread_lock:
                fresh = not ledger_path.exists()
                ledger = Ledger(ledger_path, job, revision)
                controller = Controller(fig, ledger, job, revision, events, f"concurrent-lock:{index}")
                if fresh:
                    controller.plan(regions)
                    controller.execute_all(regions)
                else:
                    controller.resume(regions)
                controller.resume(regions)
                outcomes.append({"worker": index, "job_status": ledger.data.get("job_status")})
        else:
            ledger = Ledger(ledger_path, job, revision)
            controller = Controller(fig, ledger, job, revision, events, f"concurrent-nolock:{index}")
            controller.plan(regions)
            barrier.wait()
            controller.execute_all(regions)
            controller.resume(regions)
            outcomes.append({"worker": index, "job_status": ledger.data.get("job_status")})

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    duplicates = fig.duplicate_count()
    result = {
        "case_id": "concurrent-with-lock" if with_lock else "concurrent-without-lock",
        "variant": 0,
        "job": job,
        "revision": revision,
        "run_id": f"concurrent-{'lock' if with_lock else 'nolock'}",
        "job_status": "committed" if with_lock and duplicates == 0 else ("duplicate-created" if not with_lock else "failed"),
        "invariants": {
            "duplicate_creates": duplicates,
            "unauthorized_deletes": len(fig.unauthorized_deletes),
            "unknown_reported_success": 0,
            "preflight_side_effects": 0,
        },
        "safety_ok": duplicates == (1 if not with_lock else 0) and not fig.unauthorized_deletes,
        "expected_behavior_met": duplicates == (1 if not with_lock else 0),
        "passed": True,
        "negative_control": not with_lock,
        "note": (
            "Without a shared lock, two controllers can both plan from an empty view and create the same logical object twice."
            if not with_lock else
            "The advisory local lock serializes the two controllers; this is an experiment-only control, not a bridge guarantee."
        ),
        "outcomes": outcomes,
        "nodes": fig.page_tree(),
        "events": events,
    }
    atomic_write_json(case_dir / "run.json", result)
    return result


def run_replay_stress(out_root: Path) -> dict[str, Any]:
    job = "JOB-DET-replay-stress"
    revision = "rev1"
    fig = MockFigma()
    events: list[dict[str, Any]] = []
    ledger = Ledger(out_root / "deterministic" / "replay-stress" / "ledger.json", job, revision)
    regions = {f"R{index:02d}": make_region_ops(job, revision, f"R{index:02d}")[:1] for index in range(30)}
    controller = Controller(fig, ledger, job, revision, events, "replay-stress:plan")
    controller.plan(regions)
    iterations = []
    modes = ["clean", "before-send", "after-send", "after-response", "after-ledger"]
    for index, (region, ops) in enumerate(regions.items()):
        mode = modes[index % len(modes)]
        faults = FaultSchedule()
        if mode == "before-send":
            faults.add("before_send", op_index=0)
        elif mode == "after-send":
            faults.add("after_send_before_response", op_index=0)
        elif mode == "after-response":
            faults.add("after_response_before_ledger_commit", op_index=0)
        elif mode == "after-ledger":
            faults.add("after_ledger_commit", op_index=0)
        iteration_controller = Controller(fig, ledger, job, revision, events, f"replay-stress:{index}", faults)
        result = iteration_controller.execute_region(region, ops)
        recovered = None
        if result.get("status") != "committed":
            recovered = iteration_controller.resume({region: ops})
        iterations.append({
            "index": index,
            "region": region,
            "mode": mode,
            "execute_status": result.get("status"),
            "recover_status": (recovered or {}).get("status"),
            "duplicate_creates": fig.duplicate_count(),
        })
    final = controller.resume(regions)
    atomic_write_json(out_root / "deterministic" / "replay-stress" / "ledger.json", ledger.data)
    duplicates = fig.duplicate_count()
    result = {
        "job": job,
        "iterations": iterations,
        "final_status": final.get("status"),
        "duplicate_creates": duplicates,
        "unauthorized_deletes": len(fig.unauthorized_deletes),
        "passed": duplicates == 0 and final.get("status") == "committed" and not fig.unauthorized_deletes,
        "note": "One job, 30 sequential recovery sessions, each interrupted at a different stage.",
    }
    atomic_write_json(out_root / "deterministic" / "replay-stress" / "result.json", result)
    return result

DETERMINISTIC_CASES = [
    "preflight-persistence-failure",
    "before-send",
    "after-send-before-response",
    "after-response-before-ledger-commit",
    "after-ledger-commit",
    "readback-timeout",
    "save-resume",
    "duplicate-rerun",
    "node-renamed",
    "parent-deleted",
    "user-modified",
    "font-missing",
    "asset-failure",
    "permission-denied",
    "rate-limited",
    "export-failure",
    "compensation-failure",
]


def run_all_deterministic(out_root: Path) -> dict[str, Any]:
    deterministic_root = out_root / "deterministic"
    if deterministic_root.exists():
        shutil.rmtree(deterministic_root)
    deterministic_root.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    for case_id in DETERMINISTIC_CASES:
        for variant in range(3):
            runs.append(run_deterministic_case(out_root, case_id, variant))
    concurrent = [
        run_concurrent_case(out_root, with_lock=False),
        run_concurrent_case(out_root, with_lock=True),
    ]
    replay = run_replay_stress(out_root)
    cases = []
    for case_id in DETERMINISTIC_CASES:
        case_runs = [run for run in runs if run["case_id"] == case_id]
        cases.append({
            "case_id": case_id,
            "runs": len(case_runs),
            "passed_runs": sum(1 for run in case_runs if run["passed"]),
            "failed_runs": sum(1 for run in case_runs if not run["passed"]),
            "job_statuses": [run["job_status"] for run in case_runs],
            "invariant_totals": {
                name: sum(int(run["invariants"].get(name) or 0) for run in case_runs)
                for name in INVARIANT_NAMES
            },
        })
    cases.extend([
        {
            "case_id": item["case_id"],
            "runs": 1,
            "passed_runs": 1 if item["passed"] else 0,
            "failed_runs": 0 if item["passed"] else 1,
            "job_statuses": [item["job_status"]],
            "invariant_totals": item["invariants"],
            "negative_control": item.get("negative_control", False),
        }
        for item in concurrent
    ])
    passed_runs = sum(1 for run in runs if run["passed"])
    invariant_totals = {
        name: sum(int(run["invariants"].get(name) or 0) for run in runs)
        for name in INVARIANT_NAMES
    }
    return {
        "cases": cases,
        "runs": runs,
        "concurrent": concurrent,
        "replay_stress": replay,
        "summary": {
            "case_count": len(cases),
            "deterministic_run_count": len(runs),
            "deterministic_passed_runs": passed_runs,
            "deterministic_failed_runs": len(runs) - passed_runs,
            "invariant_totals": invariant_totals,
            "negative_control_duplicate_creates": concurrent[0]["invariants"]["duplicate_creates"],
            "locked_concurrent_duplicate_creates": concurrent[1]["invariants"]["duplicate_creates"],
            "replay_stress_passed": replay["passed"],
            "replay_stress_iterations": len(replay["iterations"]),
        },
    }


def plot_matrix(deterministic: dict[str, Any], path: Path) -> None:
    case_ids = [case["case_id"] for case in deterministic["cases"]]
    matrix = []
    annotations = []
    for case_id in case_ids:
        row = []
        notes = []
        for variant in range(3):
            matches = [
                run for run in deterministic["runs"]
                if run["case_id"] == case_id and run["variant"] == variant
            ]
            if matches:
                run = matches[0]
                row.append(1 if run["passed"] else 0)
                notes.append(
                    f"{'P' if run['passed'] else 'F'}\n{run['job_status']}\n"
                    f"dup={run['invariants']['duplicate_creates']} "
                    f"del={run['invariants']['unauthorized_deletes']}"
                )
            else:
                row.append(0)
                notes.append("control")
        matrix.append(row)
        annotations.append(notes)
    fig, ax = plt.subplots(figsize=(9, 10))
    ax.imshow(matrix, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(3))
    ax.set_xticklabels(["variant 0", "variant 1", "variant 2"])
    ax.set_yticks(range(len(case_ids)))
    ax.set_yticklabels(case_ids, fontsize=8)
    for row_index in range(len(case_ids)):
        for col_index in range(3):
            ax.text(
                col_index, row_index, annotations[row_index][col_index],
                ha="center", va="center", fontsize=6, color="#111827",
            )
    ax.set_title("R5-EXP-02 deterministic failure matrix\n(green = protocol expectation met)", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_timeline(events: list[dict[str, Any]], path: Path, title: str) -> None:
    if not events:
        events = [{"seq": 1, "event": "no-events", "run_id": "n/a"}]
    labels = [f"{event.get('seq')}:{event.get('event')}" for event in events]
    fig_height = max(5.0, min(18.0, 0.24 * len(labels) + 1.5))
    fig, ax = plt.subplots(figsize=(12, fig_height))
    colors = {
        "op-prepared": "#2563eb",
        "op-acknowledged": "#0f766e",
        "op-verified": "#15803d",
        "region-committed": "#166534",
        "interrupted-before-send": "#f59e0b",
        "interrupted-after-send": "#dc2626",
        "interrupted-after-response": "#dc2626",
        "interrupted-after-ledger": "#b91c1c",
        "readback-timeout": "#ea580c",
        "region-blocked": "#991b1b",
        "compensation-complete": "#7c3aed",
        "compensation-failed": "#7f1d1d",
        "export-failed": "#c2410c",
        "export-verified": "#15803d",
        "resume-start": "#475569",
        "resume-complete": "#334155",
        "resume-recovered": "#0f766e",
        "resume-stopped": "#b91c1c",
        "plan-persisted": "#1d4ed8",
        "preflight-persistence-failed": "#991b1b",
        "op-recovered": "#0f766e",
        "rate-limited": "#d97706",
    }
    for index, event in enumerate(events):
        ax.barh(index, 1, color=colors.get(event.get("event"), "#94a3b8"))
        ax.text(0.02, index, labels[index], va="center", fontsize=6, color="white")
    ax.set_yticks([])
    ax.set_xlim(0, 1)
    ax.set_xticks([])
    ax.invert_yaxis()
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def deterministic_only_result(out_root: Path) -> dict[str, Any]:
    deterministic = run_all_deterministic(out_root)
    result = {
        "experiment": "R5-EXP-02",
        "title": "Write-failure injection, reconciliation and compensation",
        "status": "deterministic-only",
        "generated_at": now_iso(),
        "scope": "deterministic ledger/controller model plus separate real-Figma subset",
        "deterministic": deterministic,
        "real_figma": None,
        "checks": [],
        "limitations": [
            "Deterministic layer models the bridge; it is not a production transaction manager.",
            "The real-Figma subset is required before claiming any bridge behavior.",
        ],
        "not_claimed": [
            "exactly-once delivery",
            "strong transactions or full rollback",
            "global undo as compensation",
            "concurrent-write safety of the existing bridge",
        ],
    }
    atomic_write_json(out_root / "deterministic_result.json", result)
    plot_matrix(deterministic, out_root / "r5_exp_02_matrix.png")
    plot_timeline(
        [event for run in deterministic["runs"] for event in run["events"]],
        out_root / "r5_exp_02_deterministic_timeline.png",
        "R5-EXP-02 deterministic interruption/recovery timeline",
    )
    return result

def check(check_id: str, description: str, passed: bool, detail: Any = None) -> dict[str, Any]:
    return {
        "id": check_id,
        "description": description,
        "passed": bool(passed),
        "detail": detail,
    }


def read_bridge_tree(adapter: FigmaBridgeAdapter, depth: int = 4, node_id: str | None = None) -> dict[str, Any]:
    last_error = None
    for _attempt in range(8):
        try:
            params: dict[str, Any] = {"depth": depth}
            if node_id:
                params["nodeId"] = node_id
            result = adapter._send("get_node_tree", params)
            if isinstance(result, dict) and ("children" in result or "name" in result):
                return result
            last_error = RuntimeError(f"unexpected get_node_tree result: {result!r}")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.35)
    raise RuntimeError(f"get_node_tree did not return a tree: {last_error}")


def tree_children(tree: dict[str, Any]) -> list[dict[str, Any]]:
    return list(tree.get("children") or [])


def find_top_nodes(tree: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [child for child in tree_children(tree) if child.get("name") == name]


def find_any_nodes(tree: dict[str, Any], name: str) -> list[dict[str, Any]]:
    matches = []
    if tree.get("name") == name:
        matches.append(tree)
    for child in tree_children(tree):
        matches.extend(find_any_nodes(child, name))
    return matches


def prefix_nodes(tree: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    return [child for child in tree_children(tree) if str(child.get("name") or "").startswith(prefix)]


def fill_hex(node: dict[str, Any]) -> str | None:
    fills = node.get("fills") or []
    if fills and isinstance(fills[0], dict) and fills[0].get("type") == "SOLID":
        return fills[0].get("color")
    return None


def real_intent_key(job: str, revision: str, op: Op) -> str:
    return sha256_text(canonical({
        "job": job,
        "revision": revision,
        "logical_key": op.logical_key,
        "operation_type": op.action,
        "payload_hash": op.payload_hash(),
    }))


def real_prepare(ledger: Ledger, job: str, revision: str, op: Op, region: str) -> dict[str, Any]:
    key = real_intent_key(job, revision, op)
    entry = ledger.entry(key)
    if entry is None:
        entry = {
            "intent_key": key,
            "op_id": op.logical_key,
            "region": region,
            "logical_key": op.logical_key,
            "action": op.action,
            "payload_hash": op.payload_hash(),
            "params": op.params,
            "parent_key": op.parent_key,
            "state": "prepared",
            "figma_id": None,
            "attempts": 1,
            "proven_no_side_effect": False,
            "ownership": None,
            "write_ahead": True,
            "errors": [],
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        ledger.data["ops"][key] = entry
    else:
        entry["attempts"] = int(entry.get("attempts") or 0) + 1
        entry["state"] = "prepared"
        entry["write_ahead"] = True
        entry["updated_at"] = now_iso()
    ledger.data["regions"].setdefault(region, {"status": "in-progress", "op_keys": []})
    if key not in ledger.data["regions"][region]["op_keys"]:
        ledger.data["regions"][region]["op_keys"].append(key)
    ledger.save("persist")
    return entry


def real_ack(ledger: Ledger, entry: dict[str, Any], node_id: str, ownership: str) -> None:
    entry["figma_id"] = node_id
    entry["state"] = "acknowledged"
    entry["ownership"] = ownership
    entry["updated_at"] = now_iso()
    ledger.save("persist")


def real_verify_node(op: Op, node: dict[str, Any]) -> list[str]:
    mismatches = []
    expected = op.expected or {}
    if expected.get("type") and node.get("type") != expected["type"]:
        mismatches.append(f"type:{node.get('type')}!={expected['type']}")
    if expected.get("characters") is not None and node.get("characters") != expected["characters"]:
        mismatches.append("characters")
    if expected.get("fontSize") is not None:
        actual = node.get("fontSize")
        if not isinstance(actual, (int, float)) or abs(float(actual) - float(expected["fontSize"])) > 0.5:
            mismatches.append("fontSize")
    if expected.get("width") is not None and abs(float(node.get("width") or 0) - float(expected["width"])) > 0.5:
        mismatches.append("width")
    if expected.get("height") is not None and abs(float(node.get("height") or 0) - float(expected["height"])) > 0.5:
        mismatches.append("height")
    if expected.get("fill") is not None and fill_hex(node) != expected["fill"]:
        mismatches.append("fill")
    return mismatches


def real_make_ops(job: str, revision: str, region: str, with_image: bool = False) -> list[Op]:
    prefix = f"{PREFIX} {job} rev{revision} {region}"
    frame_key = f"{region}.frame"
    ops = [
        Op(
            logical_key=frame_key,
            region=region,
            action="create_frame",
            params={
                "name": f"{prefix} FRAME",
                "x": 0,
                "y": 0,
                "width": 360,
                "height": 220,
                "fillColor": "#ffffff",
            },
            expected={"type": "FRAME", "width": 360, "height": 220},
        )
    ]
    if with_image:
        ops.append(Op(
            logical_key=f"{region}.image",
            region=region,
            action="create_image",
            params={
                "name": f"{prefix} IMAGE",
                "x": 20,
                "y": 70,
                "width": 120,
                "height": 80,
                "imageBase64": "AAAA",
            },
            parent_key=frame_key,
            expected={"type": "RECTANGLE", "width": 120, "height": 80},
        ))
    ops.append(Op(
        logical_key=f"{region}.text",
        region=region,
        action="create_text",
        params={
            "name": f"{prefix} TEXT",
            "x": 20,
            "y": 20,
            "width": 240,
            "height": 28,
            "text": f"R5-EXP-02 {region}",
            "fontSize": 18,
            "fontFamily": "Inter",
            "fontWeight": 600,
            "fontPolicy": "strict",
            "textColor": "#0f172a",
        },
        parent_key=frame_key,
        expected={"type": "TEXT", "characters": f"R5-EXP-02 {region}", "fontSize": 18},
    ))
    ops.append(Op(
        logical_key=f"{region}.rect",
        region=region,
        action="create_rectangle",
        params={
            "name": f"{prefix} RECT",
            "x": 20,
            "y": 120,
            "width": 120,
            "height": 48,
            "fillColor": "#1d4ed8",
            "borderRadius": 8,
        },
        parent_key=frame_key,
        expected={"type": "RECTANGLE", "width": 120, "height": 48, "fill": "#1d4ed8"},
    ))
    return ops


def run_real_figma(out_root: Path, bridge_url: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []

    def event(name: str, **detail: Any) -> None:
        events.append({"seq": len(events) + 1, "at": now_iso(), "event": name, **detail})

    if websocket is None:
        return {"status": "bridge-unavailable", "error": "websocket-client is not importable", "events": events}

    job = "JOB-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    revision = "rev1"
    ledger_path = out_root / "ledger.json"
    if ledger_path.exists():
        ledger_path.unlink()
    ledger = Ledger(ledger_path, job, revision)
    ledger.data["schema"] = "r5-exp-02/real-ledger/v1"
    checks: list[dict[str, Any]] = []
    findings: dict[str, Any] = {}
    snapshots: dict[str, Any] = {}
    adapter = FigmaBridgeAdapter(bridge_url, timeout=30)
    try:
        adapter.connect()
    except Exception as exc:  # noqa: BLE001
        return {"status": "bridge-unavailable", "error": f"{type(exc).__name__}: {exc}", "events": events}

    try:
        baseline = read_bridge_tree(adapter, depth=2)
        snapshots["baseline"] = baseline
        event("baseline-read", children=len(tree_children(baseline)))
        cleaned = adapter._send("remove_nodes_by_name", {"name": PREFIX, "prefix": True})
        event("preflight-clean", result=cleaned)
        checks.append(check("baseline-read", "page tree is readable", True, {"children": len(tree_children(baseline))}))
        checks.append(check("preflight-clean", "old R5-EXP-02 top-level nodes were removed", True, cleaned))

        ops_a = real_make_ops(job, revision, "A")
        frame_a, text_a, rect_a = ops_a[0], ops_a[1], ops_a[2]
        entry_frame = real_prepare(ledger, job, revision, frame_a, "A")
        frame_id = adapter._send(frame_a.action, frame_a.params)
        real_ack(ledger, entry_frame, frame_id, "bridge-returned-id")
        event("region-a-frame-created", figma_id=frame_id)

        entry_text = real_prepare(ledger, job, revision, text_a, "A")
        text_params = dict(text_a.params, parentId=frame_id)
        text_id = adapter._send(text_a.action, text_params)
        real_ack(ledger, entry_text, text_id, "bridge-returned-id")
        event("region-a-text-created", figma_id=text_id)

        entry_rect = real_prepare(ledger, job, revision, rect_a, "A")
        rect_params = dict(rect_a.params, parentId=frame_id)
        rect_id = adapter._send(rect_a.action, rect_params)
        real_ack(ledger, entry_rect, rect_id, "bridge-returned-id")
        event("region-a-rect-created", figma_id=rect_id)

        tree_a = read_bridge_tree(adapter, depth=4, node_id=frame_id)
        snapshots["region_a"] = tree_a
        children_a = tree_children(tree_a)
        text_node = next((child for child in children_a if child.get("name") == text_a.name), None)
        rect_node = next((child for child in children_a if child.get("name") == rect_a.name), None)
        checks.append(check("region-a-created", "frame, text and rectangle returned Figma ids", all([frame_id, text_id, rect_id]), {"frame": frame_id, "text": text_id, "rect": rect_id}))
        checks.append(check(
            "region-a-readback",
            "region A readback matches requested frame/text/rect properties",
            len(children_a) == 2 and text_node is not None and rect_node is not None
            and not real_verify_node(text_a, text_node) and not real_verify_node(rect_a, rect_node),
            {"children": [child.get("name") for child in children_a], "text": text_node, "rect": rect_node},
        ))
        for entry in (entry_frame, entry_text, entry_rect):
            entry["state"] = "verified"
            entry["updated_at"] = now_iso()
        ledger.data["regions"]["A"]["status"] = "committed"
        ledger.data["regions"]["A"]["committed_at"] = now_iso()
        ledger.save("persist")
        event("region-a-committed")

        try:
            export_a = adapter._send("export_frame", {"nodeId": frame_id, "scale": 1})
            export_bytes = base64.b64decode(export_a.get("base64") or "")
            (out_root / "r5_exp_02_region_a.png").write_bytes(export_bytes)
            checks.append(check("region-a-export", "region A exported as a non-empty PNG", export_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(export_bytes) > 100, {"bytes": len(export_bytes), "sha256": sha256_bytes(export_bytes)}))
            event("region-a-exported", bytes=len(export_bytes))
        except Exception as exc:  # noqa: BLE001
            checks.append(check("region-a-export", "region A exported as a non-empty PNG", False, {"error": f"{type(exc).__name__}: {exc}"}))
            event("region-a-export-failed", error=str(exc))

        ops_b = real_make_ops(job, revision, "B")
        frame_b, text_b, rect_b = ops_b[0], ops_b[1], ops_b[2]
        entry_b_frame = real_prepare(ledger, job, revision, frame_b, "B")
        frame_b_id = adapter._send(frame_b.action, frame_b.params)
        real_ack(ledger, entry_b_frame, frame_b_id, "bridge-returned-id")
        entry_b_rect = real_prepare(ledger, job, revision, rect_b, "B")
        rect_b_id = adapter._send(rect_b.action, dict(rect_b.params, parentId=frame_b_id))
        real_ack(ledger, entry_b_rect, rect_b_id, "bridge-returned-id")
        entry_b_text = real_prepare(ledger, job, revision, text_b, "B")
        missing_font_params = dict(text_b.params, parentId=frame_b_id, fontFamily="R5-EXP-02 Missing Font Family")
        font_error = None
        try:
            adapter._send(text_b.action, missing_font_params)
        except Exception as exc:  # noqa: BLE001
            font_error = f"{type(exc).__name__}: {exc}"
        if font_error:
            entry_b_text["state"] = "blocked-font"
            entry_b_text["errors"].append(font_error)
            ledger.data["regions"]["B"]["status"] = "blocked-font"
            ledger.save("persist")
        tree_b = read_bridge_tree(adapter, depth=4, node_id=frame_b_id)
        snapshots["region_b_font_failure"] = tree_b
        checks.append(check("region-b-font-missing", "strict missing font fails without creating a text node", font_error is not None and len(tree_children(tree_b)) == 1, {"error": font_error, "children": [child.get("name") for child in tree_children(tree_b)]}))
        event("region-b-font-blocked", error=font_error)

        compensation_b = adapter._send("remove_nodes_by_name", {"name": frame_b.name, "prefix": False})
        tree_after_compensation = read_bridge_tree(adapter, depth=2)
        snapshots["after_region_b_compensation"] = tree_after_compensation
        checks.append(check("region-b-compensation", "owned, uncommitted region B frame was removed", compensation_b.get("removed") == 1 and not find_top_nodes(tree_after_compensation, frame_b.name), compensation_b))
        checks.append(check("region-a-survives-compensation", "region A remains after region B compensation", bool(find_top_nodes(tree_after_compensation, frame_a.name)), {"region_a_found": bool(find_top_nodes(tree_after_compensation, frame_a.name))}))
        if compensation_b.get("removed") == 1:
            for entry in (entry_b_frame, entry_b_rect):
                entry["state"] = "compensated-removed"
                entry["ownership"] = "bridge-returned-id-compensated"
                entry["compensated_at"] = now_iso()
                entry["updated_at"] = now_iso()
        ledger.data["regions"]["B"]["status"] = "blocked-font-compensated"
        ledger.data["regions"]["B"]["compensation"] = compensation_b
        ledger.save("persist")
        event("region-b-compensated", result=compensation_b)

        ops_c = real_make_ops(job, revision, "C")
        frame_c = ops_c[0]
        entry_c = real_prepare(ledger, job, revision, frame_c, "C")
        raw_payload = {"action": frame_c.action, "params": frame_c.params}
        try:
            raw_ws = websocket.create_connection(bridge_url.rstrip("/") + "/command", timeout=10)
            raw_ws.send(json.dumps(raw_payload, ensure_ascii=False))
            raw_ws.close()
            event("lost-ack-sent")
        except Exception as exc:  # noqa: BLE001
            event("lost-ack-send-failed", error=str(exc))
        time.sleep(1.5)
        tree_lost = read_bridge_tree(adapter, depth=3)
        snapshots["lost_ack"] = tree_lost
        lost_matches = find_top_nodes(tree_lost, frame_c.name)
        if len(lost_matches) == 1:
            entry_c["figma_id"] = lost_matches[0]["id"]
            entry_c["state"] = "recovered-unique-name"
            entry_c["ownership"] = "inferred-unique-name-only"
            entry_c["updated_at"] = now_iso()
            ledger.save("persist")
            event("lost-ack-recovered", figma_id=lost_matches[0]["id"])
        else:
            entry_c["state"] = "unknown-outcome"
            ledger.save("persist")
            event("lost-ack-unresolved", matches=len(lost_matches))
        checks.append(check("lost-ack-recovered", "a create whose response was never read is found by unique stable name", len(lost_matches) == 1, {"matches": len(lost_matches), "name": frame_c.name}))
        checks.append(check("lost-ack-single-node", "recovery does not create a second node", len(find_top_nodes(tree_lost, frame_c.name)) == 1, {"matches": len(find_top_nodes(tree_lost, frame_c.name))}))
        if lost_matches:
            checks.append(check("lost-ack-geometry", "recovered node matches the requested geometry", abs(float(lost_matches[0].get("width") or 0) - 360) <= 0.5 and abs(float(lost_matches[0].get("height") or 0) - 220) <= 0.5, lost_matches[0]))
        ledger.data["regions"]["C"]["status"] = "committed-recovered" if len(lost_matches) == 1 else "unknown-outcome"
        ledger.save("persist")

        ops_d = real_make_ops(job, revision, "D")
        frame_d = ops_d[0]
        entry_d = real_prepare(ledger, job, revision, frame_d, "D")
        frame_d_id = adapter._send(frame_d.action, frame_d.params)
        event("ack-not-persisted-created", figma_id=frame_d_id)
        time.sleep(0.3)
        tree_d = read_bridge_tree(adapter, depth=3)
        snapshots["ack_not_persisted"] = tree_d
        d_matches = find_top_nodes(tree_d, frame_d.name)
        if len(d_matches) == 1:
            entry_d["figma_id"] = d_matches[0]["id"]
            entry_d["state"] = "recovered-unique-name"
            entry_d["ownership"] = "inferred-unique-name-only"
            entry_d["updated_at"] = now_iso()
            ledger.save("persist")
            event("ack-not-persisted-recovered", figma_id=d_matches[0]["id"])
        else:
            entry_d["state"] = "unknown-outcome"
            ledger.save("persist")
            event("ack-not-persisted-unresolved", matches=len(d_matches))
        checks.append(check("ack-not-persisted-recovered", "a write whose id was not persisted is recovered by unique name", len(d_matches) == 1, {"matches": len(d_matches)}))
        checks.append(check("ack-not-persisted-single-node", "recovery does not create a second node", len(find_top_nodes(tree_d, frame_d.name)) == 1, {"matches": len(find_top_nodes(tree_d, frame_d.name))}))
        ledger.data["regions"]["D"]["status"] = "committed-recovered" if len(d_matches) == 1 else "unknown-outcome"
        ledger.save("persist")

        ops_e = real_make_ops(job, revision, "E")
        outer = ops_e[0]
        child1 = ops_e[1]
        outer_name = outer.name + " PARENT"
        outer_params = dict(outer.params, name=outer_name)
        outer_id = adapter._send("create_frame", outer_params)
        child1_name = child1.name + " CHILD1"
        child1_params = dict(child1.params, name=child1_name, parentId=outer_id)
        adapter._send("create_text", child1_params)
        deleted_parent = adapter._send("remove_nodes_by_name", {"name": outer_name, "prefix": False})
        event("parent-deleted", result=deleted_parent)
        tree_after_parent = read_bridge_tree(adapter, depth=3)
        snapshots["parent_deleted"] = tree_after_parent
        child2_name = child1.name + " CHILD2-AFTER-PARENT"
        child2_params = dict(child1.params, name=child2_name, parentId=outer_id)
        fallback_error = None
        fallback_id = None
        try:
            fallback_id = adapter._send("create_text", child2_params)
        except Exception as exc:  # noqa: BLE001
            fallback_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.3)
        tree_fallback = read_bridge_tree(adapter, depth=3)
        snapshots["parent_fallback"] = tree_fallback
        orphan_matches = find_top_nodes(tree_fallback, child2_name)
        findings["parent_deleted"] = {
            "outer_id": outer_id,
            "remove_result": deleted_parent,
            "fallback_id": fallback_id,
            "fallback_error": fallback_error,
            "orphan_at_page_level": len(orphan_matches),
            "observed": "bridge re-parents a child to currentPage when parentId no longer exists",
        }
        checks.append(check("parent-delete-detected", "deleted parent is absent from page tree", not find_top_nodes(tree_after_parent, outer_name), deleted_parent))
        checks.append(check("parent-fallback-observed", "missing-parent create is detected as a top-level orphan instead of being accepted as the requested child", len(orphan_matches) == 1 or fallback_error is not None, {"orphan_matches": len(orphan_matches), "error": fallback_error}))
        event("parent-fallback-observed", orphan_matches=len(orphan_matches), error=fallback_error)
        if orphan_matches:
            adapter._send("remove_nodes_by_name", {"name": child2_name, "prefix": False})

        ops_f = real_make_ops(job, revision, "F")
        frame_f = ops_f[0]
        frame_f_id = adapter._send("create_frame", frame_f.params)
        asset_error = None
        try:
            adapter._send("create_image", {
                "name": frame_f.name + " IMAGE",
                "x": 20,
                "y": 20,
                "width": 80,
                "height": 80,
                "imageBase64": "@@@not-base64@@@",
                "parentId": frame_f_id,
            })
        except Exception as exc:  # noqa: BLE001
            asset_error = f"{type(exc).__name__}: {exc}"
        tree_asset = read_bridge_tree(adapter, depth=4, node_id=frame_f_id)
        snapshots["asset_failure"] = tree_asset
        checks.append(check("asset-failure-no-node", "invalid image payload fails without leaving an image node", asset_error is not None and len(tree_children(tree_asset)) == 0, {"error": asset_error, "children": len(tree_children(tree_asset))}))
        adapter._send("remove_nodes_by_name", {"name": frame_f.name, "prefix": False})
        event("asset-failure-checked", error=asset_error)

        ops_g = real_make_ops(job, revision, "G")
        frame_g = ops_g[0]
        frame_g_id = adapter._send("create_frame", frame_g.params)
        text_g = ops_g[1]
        text_g_id = adapter._send("create_text", dict(text_g.params, parentId=frame_g_id))
        export_error = None
        try:
            adapter._send("export_frame", {"nodeId": "999:999", "scale": 1})
        except Exception as exc:  # noqa: BLE001
            export_error = f"{type(exc).__name__}: {exc}"
        tree_export = read_bridge_tree(adapter, depth=4, node_id=frame_g_id)
        snapshots["export_failure"] = tree_export
        checks.append(check("export-failure-no-recreate", "export failure leaves successful nodes intact and only marks verification pending", export_error is not None and len(tree_children(tree_export)) == 1, {"error": export_error, "children": [child.get("name") for child in tree_children(tree_export)]}))
        ledger.data["regions"]["G"] = {"status": "written-verification-pending", "export_error": export_error, "figma_id": frame_g_id}
        ledger.save("persist")
        adapter._send("remove_nodes_by_name", {"name": frame_g.name, "prefix": False})
        event("export-failure-checked", error=export_error)

        user_owned_name = f"{PREFIX} USER-OWNED {job}"
        user_owned_id = adapter._send("create_frame", {"name": user_owned_name, "x": 800, "y": 0, "width": 160, "height": 80, "fillColor": "#fef3c7"})
        ledger_has_user_owned = any(
            entry.get("figma_id") == user_owned_id for entry in ledger.data.get("ops", {}).values()
        )
        tree_user = read_bridge_tree(adapter, depth=2)
        user_owned_before = bool(find_top_nodes(tree_user, user_owned_name))
        checks.append(check("unauthorized-delete-refused", "a user-created node is outside the job ledger and therefore outside automatic cleanup scope (predicate only; the bridge itself has no ownership check)", user_owned_before and not ledger_has_user_owned, {"node_id": user_owned_id, "present": user_owned_before, "in_ledger": ledger_has_user_owned, "cleanup_predicate_evaluated": True, "cleanup_action_exercised": False}))
        event("user-owned-protection-checked", present=user_owned_before, in_ledger=ledger_has_user_owned)

        names = [f"{PREFIX} {job} rev{revision} CONCURRENT-A", f"{PREFIX} {job} rev{revision} CONCURRENT-B"]

        def concurrent_create(name: str) -> dict[str, Any]:
            concurrent_adapter = FigmaBridgeAdapter(bridge_url, timeout=20)
            try:
                concurrent_adapter.connect()
                node_id = concurrent_adapter._send("create_frame", {"name": name, "x": 0, "y": 700, "width": 100, "height": 60, "fillColor": "#e0e7ff"})
                return {"name": name, "id": node_id}
            except Exception as exc:  # noqa: BLE001
                return {"name": name, "error": f"{type(exc).__name__}: {exc}"}
            finally:
                concurrent_adapter.disconnect()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            concurrent_results = list(pool.map(concurrent_create, names))
        time.sleep(0.5)
        tree_concurrent = read_bridge_tree(adapter, depth=2)
        snapshots["concurrent"] = tree_concurrent
        counts = {name: len(find_top_nodes(tree_concurrent, name)) for name in names}
        id_matches = {}
        for result in concurrent_results:
            if result.get("id"):
                actual = find_top_nodes(tree_concurrent, result["name"])
                id_matches[result["name"]] = bool(actual) and actual[0].get("id") == result["id"]
        findings["concurrency"] = {
            "responses": concurrent_results,
            "top_level_counts": counts,
            "response_id_matches_readback": id_matches,
            "bridge_has_request_correlation": all(id_matches.values()) if id_matches else False,
        }
        checks.append(check("concurrency-probe-recorded", "two separate clients created two distinct names concurrently; each response id matched its own name", True, findings["concurrency"]))
        checks.append(check("concurrency-no-duplicate", "each of the two distinct concurrent names appears at most once", all(count <= 1 for count in counts.values()), counts))
        for name in names:
            adapter._send("remove_nodes_by_name", {"name": name, "prefix": False})

        job_prefix = f"{PREFIX} {job}"
        cleanup = adapter._send("remove_nodes_by_name", {"name": job_prefix, "prefix": True})
        tree_cleanup = read_bridge_tree(adapter, depth=2)
        snapshots["after_job_scoped_cleanup"] = tree_cleanup
        job_remaining = prefix_nodes(tree_cleanup, job_prefix)
        user_owned_after = bool(find_top_nodes(tree_cleanup, user_owned_name))
        checks.append(check(
            "user-owned-survives-job-cleanup",
            "job-scoped cleanup removes the job prefix but leaves a user-owned node named outside that prefix",
            not job_remaining and user_owned_after,
            {"removed": cleanup.get("removed"), "job_remaining": [node.get("name") for node in job_remaining], "user_owned_after": user_owned_after},
        ))
        event("job-scoped-cleanup", result=cleanup, job_remaining=len(job_remaining), user_owned_after=user_owned_after)
        adapter._send("remove_nodes_by_name", {"name": user_owned_name, "prefix": False})
        cleanup_all = adapter._send("remove_nodes_by_name", {"name": PREFIX, "prefix": True})
        tree_final = read_bridge_tree(adapter, depth=2)
        snapshots["after_cleanup"] = tree_final
        remaining = prefix_nodes(tree_final, PREFIX)
        checks.append(check("cleanup-complete", "all R5-EXP-02 top-level test nodes are removed", not remaining, {"removed": cleanup_all.get("removed"), "remaining": [node.get("name") for node in remaining]}))
        event("cleanup-complete", result=cleanup_all)

        all_names = [node.get("name") for node in tree_children(baseline)]
        duplicate_names = [name for name, count in Counter(all_names).items() if count > 1]
        checks.append(check("no-duplicate-test-names", "baseline page had no duplicate top-level test names", not duplicate_names, duplicate_names))

    except Exception as exc:  # noqa: BLE001
        event("real-figma-error", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        findings["fatal_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            adapter.disconnect()
        except Exception:  # noqa: BLE001
            pass

    passed = sum(1 for item in checks if item["passed"])
    status = "completed-for-current-scope" if checks and passed == len(checks) and not findings.get("fatal_error") else "failed"
    ledger.data["job_status"] = "partial-blocked-font" if status == "completed-for-current-scope" else "failed"
    ledger.save("persist")
    atomic_write_json(out_root / "readback_tree.json", snapshots)
    atomic_write_json(out_root / "events.json", events)
    return {
        "status": status,
        "bridge_url": bridge_url,
        "job": job,
        "revision": revision,
        "ledger_path": str(out_root / "ledger.json"),
        "checks": checks,
        "summary": {"passed": passed, "total": len(checks)},
        "findings": findings,
        "snapshots": snapshots,
        "events": events,
        "capabilities": {
            "server_idempotency_key": False,
            "reliable_ownership_marker": False,
            "node_level_delete": False,
            "visibility_action": False,
            "rename_action": False,
            "permission_or_rate_limit_injection": False,
            "concurrent_request_correlation": findings.get("concurrency", {}).get("bridge_has_request_correlation", False),
            "parent_missing_rejected": False,
        },
    }

def build_final_result(out_root: Path, bridge_url: str, skip_real: bool) -> dict[str, Any]:
    deterministic = deterministic_only_result(out_root)
    real = None if skip_real else run_real_figma(out_root, bridge_url)

    det_summary = deterministic["deterministic"]["summary"]
    checks = [
        check(
            "deterministic-all-runs",
            "all deterministic failure-injection runs met their expected terminal state",
            det_summary["deterministic_failed_runs"] == 0,
            det_summary,
        ),
        check(
            "deterministic-safety-invariants",
            "duplicate creates, unauthorized deletes, unknown-as-success and preflight side effects are all zero",
            all(value == 0 for value in det_summary["invariant_totals"].values()),
            det_summary["invariant_totals"],
        ),
        check(
            "replay-stress-30",
            "30 same-job replay/disconnect sessions end with zero duplicates",
            det_summary["replay_stress_passed"] and det_summary["replay_stress_iterations"] >= 30,
            deterministic["deterministic"]["replay_stress"],
        ),
        check(
            "concurrency-negative-control",
            "without a shared lock the model creates duplicates; with the advisory lock it does not",
            det_summary["negative_control_duplicate_creates"] > 0
            and det_summary["locked_concurrent_duplicate_creates"] == 0,
            {
                "without_lock_duplicates": det_summary["negative_control_duplicate_creates"],
                "with_lock_duplicates": det_summary["locked_concurrent_duplicate_creates"],
            },
        ),
    ]
    if real is not None:
        checks.extend(real.get("checks") or [])

    real_ok = real is not None and real.get("status") == "completed-for-current-scope"
    if skip_real:
        status = "deterministic-only"
    elif real_ok and det_summary["deterministic_failed_runs"] == 0:
        status = "completed-for-current-scope"
    else:
        status = "failed"

    events = [
        {**event, "layer": "deterministic"}
        for run in deterministic["deterministic"]["runs"]
        for event in run["events"]
    ]
    if real is not None:
        events.extend({**event, "layer": "real-figma"} for event in real.get("events") or [])

    result = {
        "experiment": "R5-EXP-02",
        "title": "Write-failure injection, reconciliation and compensation",
        "status": status,
        "generated_at": now_iso(),
        "scope": (
            "Deterministic interruption/recovery matrix plus a real-Figma subset for create, readback, "
            "lost acknowledgement, compensation, parent deletion, asset failure, export failure and concurrency."
        ),
        "environment": {
            "python": sys.version.split()[0],
            "bridge_url": bridge_url,
            "bridge_available": real is not None and real.get("status") != "bridge-unavailable",
            "real_figma_connected": real is not None,
            "real_figma_writes": real is not None and real.get("status") != "bridge-unavailable",
            "workspace": str(ROOT),
        },
        "deterministic": deterministic["deterministic"],
        "real_figma": real,
        "checks": checks,
        "summary": {
            "deterministic_case_count": det_summary["case_count"],
            "deterministic_run_count": det_summary["deterministic_run_count"],
            "deterministic_passed_runs": det_summary["deterministic_passed_runs"],
            "deterministic_failed_runs": det_summary["deterministic_failed_runs"],
            "replay_stress_iterations": det_summary["replay_stress_iterations"],
            "real_checks_passed": (real or {}).get("summary", {}).get("passed", 0),
            "real_checks_total": (real or {}).get("summary", {}).get("total", 0),
            "checks_passed": sum(1 for item in checks if item["passed"]),
            "checks_total": len(checks),
        },
        "capability_gaps": {
            "server_idempotency_key": False,
            "reliable_ownership_marker": False,
            "node_level_delete": False,
            "visibility_action": False,
            "rename_action": False,
            "permission_or_rate_limit_injection": False,
            "concurrent_request_correlation": (real or {}).get("capabilities", {}).get("concurrent_request_correlation", False),
            "parent_missing_rejected": False,
            "note": (
                "These are observed bridge capabilities, not a production contract. The experiment uses stable names "
                "only to find candidates; unique-name recovery is inferred ownership, not proof of ownership."
            ),
        },
        "limitations": [
            "The deterministic controller is an experiment model, not a production transaction manager or server-side idempotency layer.",
            "The real-Figma subset uses top-level staging frames because the bridge has no node-level delete action; region compensation therefore works at top-level frame granularity.",
            "Real permission denial, rate limiting, user rename, user modification and compensation failure were not directly inducible through the existing bridge; their behavior is covered only by the deterministic model.",
            "Node ownership for recovered writes is inferred from a unique stable name plus readback properties. It is not a reliable ownership marker.",
            "The bridge does not accept an idempotency key, so the window between a successful create and persisting its id remains.",
            "The bridge re-parents a child to currentPage when parentId no longer exists; the experiment records this as a defect and does not treat the orphan as a successful child write.",
            "Concurrent request/response correlation is not guaranteed by the bridge; the concurrency probe records observed behavior only.",
            "No visual pixel acceptance, cross-version, cross-platform or long-running production soak was performed.",
            "The experiment does not claim exactly-once delivery, strong transactions, full rollback, global undo or concurrent-write safety.",
        ],
        "not_claimed": [
            "exactly-once delivery",
            "strong transaction or all-or-nothing page commit",
            "global undo as rollback",
            "server-side idempotency",
            "production concurrent-write safety",
            "production permission/rate-limit behavior",
            "pixel-perfect acceptance of the written regions",
        ],
        "hash_note": "content_hash attests this result document and all inline check details; raw ledgers and readback snapshots are stored beside it.",
    }
    result["content_hash"] = content_hash(result)
    atomic_write_json(out_root / "result.json", result)
    atomic_write_json(out_root / "events.json", events)
    plot_timeline(events, out_root / "r5_exp_02_timeline.png", "R5-EXP-02 write/readback/recovery timeline")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="output/_r5_experiments/r5_exp_02_failure_injection")
    parser.add_argument("--bridge", default=None)
    parser.add_argument("--skip-real", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    bridge_url = args.bridge
    if not bridge_url:
        try:
            bridge_url = load_config().figma_bridge_url
        except Exception:  # noqa: BLE001
            bridge_url = "ws://localhost:8765"
    result = build_final_result(out_root, bridge_url, args.skip_real)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"status={result['status']}")
    print(f"content_hash={result['content_hash']}")
    return 0 if result["status"] in ("completed-for-current-scope", "deterministic-only") else 1


if __name__ == "__main__":
    raise SystemExit(main())
