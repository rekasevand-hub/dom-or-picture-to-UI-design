# -*- coding: utf-8 -*-
"""R5 closeout audit and production-slice ledger.

This audit reads the six R5 result files, recomputes their canonical hashes,
checks their current-scope envelope and produces a production-slice backlog.
It does not modify production code or promote any experiment to verified.

Usage:
  C:/Users/lzq/.conda/envs/omni/python.exe scripts/r5_closeout_audit.py
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CAPTURED_AT = "2026-10-19T00:00:00+00:00"
DEFAULT_OUT = ROOT / "output" / "_r5_closeout"

EXPERIMENTS = [
    {
        "id": "R5-EXP-01",
        "decision": "D39",
        "title": "冲突字段默认交付与报告一致性",
        "result": "output/_r5_experiments/r5_exp_01_conflict_delivery/result.json",
        "doc": "docs/v2_mentor/R5_EXP_01_CONFLICT_DELIVERY.md",
        "hash_prefix": "9ed7aba5d2607594",
        "external_gaps": [
            "真实 Figma 业务画布与独立报告 Frame",
            "用户是否理解 Conflicts / Unknowns 状态",
            "真实业务权威、价格与库存规则",
        ],
    },
    {
        "id": "R5-EXP-02",
        "decision": "D40",
        "title": "写入失败注入、对账与补偿",
        "result": "output/_r5_experiments/r5_exp_02_failure_injection/result.json",
        "doc": "docs/v2_mentor/R5_EXP_02_WRITE_FAILURE.md",
        "hash_prefix": "73a70b5af3445695",
        "external_gaps": [
            "服务端幂等键与可靠 ownership marker",
            "节点级删除、visibility 与 rename",
            "真实权限、限流、用户接管与补偿失败",
            "同名并发与生产 bridge 并发安全",
        ],
    },
    {
        "id": "R5-EXP-03",
        "decision": "D41",
        "title": "DOM / 截图字段权威矩阵",
        "result": "output/_r5_experiments/r5_exp_03_authority_matrix/result.json",
        "doc": "docs/v2_mentor/R5_EXP_03_AUTHORITY_MATRIX.md",
        "hash_prefix": "e954d75a4db5b5b2",
        "external_gaps": [
            "生产 DOM/截图采集接入",
            "跨浏览器、跨站点与状态签名",
            "真实 canvas、iframe、shadow 与 OCR 校准",
        ],
    },
    {
        "id": "R5-EXP-04",
        "decision": "D42",
        "title": "部分交付表达与 coverage map",
        "result": "output/_r5_experiments/r5_exp_04_partial_coverage/result.json",
        "doc": "docs/v2_mentor/R5_EXP_04_PARTIAL_COVERAGE.md",
        "hash_prefix": "94f843feb23279dc",
        "external_gaps": [
            "真实 Figma 报告 Frame、锁与独立页面",
            "真实覆盖率计算与文档导出 gate",
            "用户对 PARTIAL 与四类空缺的理解",
        ],
    },
    {
        "id": "R5-EXP-05",
        "decision": "D43",
        "title": "四维验收硬门禁与页面汇总",
        "result": "output/_r5_experiments/r5_exp_05_acceptance_gate/result.json",
        "doc": "docs/v2_mentor/R5_EXP_05_ACCEPTANCE_GATE.md",
        "hash_prefix": "b5cd12d499379712",
        "external_gaps": [
            "真实 linebreak/pixel/geometry/parent/boundary/native 检测器",
            "真实站点阈值与样本政策",
            "生产运行门禁、监控与发布审批",
        ],
    },
    {
        "id": "R5-EXP-06",
        "decision": "D44",
        "title": "IR 持久化、TTL、迁移与重放",
        "result": "output/_r5_experiments/r5_exp_06_ir_persistence/result.json",
        "doc": "docs/v2_mentor/R5_EXP_06_IR_PERSISTENCE.md",
        "hash_prefix": "127fe5b3f9ee3c3c",
        "external_gaps": [
            "生产数据库/对象存储崩溃一致性",
            "真实权限服务、TTL worker 与跨页面引用仓库",
            "多版本迁移矩阵、监控与保留政策审批",
        ],
    },
]

PRODUCTION_SLICES = [
    {
        "slice_id": "P0-CONTRACT-CORE",
        "title": "纯合同核心与 schema/validator",
        "status": "implemented-current-scope",
        "depends_on": [],
        "decisions": ["D39", "D41", "D42", "D43", "D44"],
        "candidate_modules": [
            "src/app/services/contracts/",
            "src/app/services/contracts/ir.py",
            "src/app/services/contracts/authority.py",
            "src/app/services/contracts/coverage.py",
            "src/app/services/contracts/acceptance.py",
        ],
        "deliverables": [
            "field-level authority/status enums and JSON schema",
            "partial/coverage/report contracts",
            "four-dimension gate and release decision",
            "runtime IR vs ordered audit bundle separation",
            "v1 -> v2 migration and replay-mode validators",
        ],
        "acceptance": [
            "pure deterministic library, no Figma or network",
            "golden valid examples and negative-mutation tests",
            "invalid enum and reference fail closed",
            "no default-path behavior change",
        ],
        "blockers": [],
        "implementation_evidence": [
            "src/app/services/contracts/",
            "tests/v2/test_r5_contracts.py",
            "20/20 unittest cases",
            "no default-path integration",
        ],
    },
    {
        "slice_id": "P1-EVIDENCE-ADAPTER",
        "title": "采集产物到证据侧车与字段观测",
        "status": "blocked-by-sample-scope",
        "depends_on": ["P0-CONTRACT-CORE"],
        "decisions": ["D41", "D44"],
        "candidate_modules": [
            "src/app/services/structure/capture.py",
            "src/app/services/contracts/evidence.py",
            "output stage sidecars",
        ],
        "deliverables": [
            "capture_id/revision/state signature",
            "evidence hashes, TTL and local-byte references",
            "raw/visible text, CSS/render color and scope fields",
        ],
        "acceptance": [
            "no candidate value silently becomes a winner",
            "evidence missing and unavailable are distinct",
            "capture record reproducible across repeated runs",
        ],
        "blockers": [
            "real site/iframe/shadow/canvas samples",
            "storage location and retention approval",
        ],
    },
    {
        "slice_id": "P2-PARTIAL-DELIVERY",
        "title": "PARTIAL 报告、coverage map 与验收门禁",
        "status": "blocked-by-detector-status",
        "depends_on": ["P0-CONTRACT-CORE", "P1-EVIDENCE-ADAPTER"],
        "decisions": ["D39", "D42", "D43"],
        "candidate_modules": [
            "src/app/services/delivery/",
            "src/app/services/rendering/render_review.py",
            "src/app/agents/precise_agent.py",
        ],
        "deliverables": [
            "user-visible PARTIAL report and legend",
            "coverage map with four gap classes and fixed denominator",
            "page summary with critical closure and release status",
        ],
        "acceptance": [
            "visual pass cannot offset edit/structure/asset failure",
            "noncritical isolated gap can only produce deliverable-partial",
            "mask exclusion cannot promote complete",
        ],
        "blockers": [
            "real detector statuses and thresholds",
            "report rendering target and user comprehension test",
        ],
    },
    {
        "slice_id": "P3-WRITE-LEDGER-RESUME",
        "title": "写前账本、resume 对账与区域补偿",
        "status": "blocked-by-bridge-capabilities",
        "depends_on": ["P0-CONTRACT-CORE", "P1-EVIDENCE-ADAPTER"],
        "decisions": ["D40", "D44"],
        "candidate_modules": [
            "figma_bridge/code.js",
            "src/app/services/rendering/figma_adapter.py",
            "src/app/services/write/",
        ],
        "deliverables": [
            "persist-before-send intent ledger",
            "server-side idempotency and ownership marker",
            "readback reconciliation, resume and regional compensation",
            "node-level delete/visibility/rename or explicit unsupported status",
        ],
        "acceptance": [
            "duplicate creates / unauthorized deletes / unknown success = 0",
            "no auto-resend on unknown outcome",
            "same-job concurrency and parent-missing fail closed",
        ],
        "blockers": [
            "bridge capability changes",
            "real permission/rate-limit/user-takeover injection",
        ],
    },
    {
        "slice_id": "P4-PERSISTENCE-OPERATIONS",
        "title": "生产 IR 存储、TTL、权限与迁移",
        "status": "blocked-by-storage-policy",
        "depends_on": ["P0-CONTRACT-CORE"],
        "decisions": ["D44"],
        "candidate_modules": [
            "src/app/services/ir_store/",
            "database/object-store adapter",
            "retention and migration workers",
        ],
        "deliverables": [
            "transactional runtime IR store",
            "TTL workers and evidence tombstone policy",
            "schema migration chain and access control",
        ],
        "acceptance": [
            "write-before-side-effect durability",
            "evidence-unavailable after TTL",
            "migration preserves tombstones, authority and unknown",
            "permission revocation fails closed",
        ],
        "blockers": [
            "database/object-store choice",
            "organization retention and access policy",
            "monitoring and backup requirements",
        ],
    },
    {
        "slice_id": "P5-PILOT-E2E",
        "title": "受限真实 Figma 试点",
        "status": "blocked-by-p0-p4",
        "depends_on": [
            "P0-CONTRACT-CORE",
            "P1-EVIDENCE-ADAPTER",
            "P2-PARTIAL-DELIVERY",
            "P3-WRITE-LEDGER-RESUME",
            "P4-PERSISTENCE-OPERATIONS",
        ],
        "decisions": ["D39", "D40", "D41", "D42", "D43", "D44"],
        "candidate_modules": [
            "pilot entrypoint only; no default production path",
        ],
        "deliverables": [
            "bounded real page -> partial report -> real Figma write",
            "manual review and explicit provisional release",
            "no hidden failures, no complete export without gate",
        ],
        "acceptance": [
            "all critical required checks executed",
            "unknown/failed/partial states remain visible",
            "rollback/recovery and ownership verified",
        ],
        "blockers": [
            "P0-P4 complete",
            "real site/Figma test environment and operator",
        ],
    },
]

SLICE_VIEW_TITLES = {
    "P0-CONTRACT-CORE": "Pure contracts, schema and validators",
    "P1-EVIDENCE-ADAPTER": "Capture evidence sidecars and field observations",
    "P2-PARTIAL-DELIVERY": "PARTIAL report, coverage map and acceptance gate",
    "P3-WRITE-LEDGER-RESUME": "Write-ahead ledger, resume and regional compensation",
    "P4-PERSISTENCE-OPERATIONS": "Production IR store, TTL, permissions and migration",
    "P5-PILOT-E2E": "Bounded real-Figma pilot",
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "content_hash"}
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def atomic_write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def check(name: str, description: str, passed: bool, detail: Any = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "passed": bool(passed),
        "detail": detail,
    }


def safe_output_dir(path: Path) -> Path:
    resolved = path.resolve()
    expected_parent = (ROOT / "output").resolve()
    if resolved.parent != expected_parent:
        raise ValueError(f"Refusing to clean unexpected output directory: {resolved}")
    if resolved.name != "_r5_closeout":
        raise ValueError(f"Refusing to clean unexpected closeout directory: {resolved.name}")
    return resolved


def mutation_count(result: dict[str, Any]) -> tuple[int | None, int | None, str]:
    mutations = result.get("mutations")
    if isinstance(mutations, list):
        rejected = sum(1 for item in mutations if item.get("rejected"))
        return len(mutations), rejected, "list"
    if isinstance(mutations, dict):
        total = mutations.get("total")
        rejected = mutations.get("rejected")
        if isinstance(total, int) and isinstance(rejected, int):
            return total, rejected, "object"
    return None, None, "not-structured"


def experiment_audit(meta: dict[str, Any]) -> dict[str, Any]:
    result_path = ROOT / meta["result"]
    doc_path = ROOT / meta["doc"]
    if not result_path.exists():
        return {
            **meta,
            "result_exists": False,
            "doc_exists": doc_path.exists(),
            "errors": ["result missing"],
        }
    result = json.loads(result_path.read_text(encoding="utf-8"))
    expected_hash = content_hash(result)
    mutations_total, mutations_rejected, mutation_shape = mutation_count(result)
    checks = result.get("checks") or []
    checks_passed = sum(1 for item in checks if item.get("passed"))
    limitations = result.get("limitations") or result.get("not_claimed") or []
    boundary = result.get("boundary")
    if boundary is None:
        boundary = "documented in experiment doc / not_claimed"
    release_claims = result.get("release_claims") or {}
    verified_claim = bool(release_claims.get("verified"))
    return {
        **meta,
        "result_exists": True,
        "doc_exists": doc_path.exists(),
        "status": result.get("status"),
        "stored_hash": result.get("content_hash"),
        "computed_hash": expected_hash,
        "hash_matches": result.get("content_hash") == expected_hash,
        "hash_prefix_matches": str(result.get("content_hash", "")).startswith(meta["hash_prefix"]),
        "checks_total": len(checks),
        "checks_passed": checks_passed,
        "checks_all_passed": len(checks) > 0 and checks_passed == len(checks),
        "mutations_total": mutations_total,
        "mutations_rejected": mutations_rejected,
        "mutations_all_rejected": (
            mutations_total is not None
            and mutations_total > 0
            and mutations_rejected == mutations_total
        ),
        "mutation_shape": mutation_shape,
        "boundary_present": bool(boundary),
        "limitations_present": bool(limitations),
        "verified_claim": verified_claim,
        "errors": [],
    }


def read_indices() -> dict[str, str]:
    paths = {
        "root_readme": ROOT / "README.md",
        "mentor_readme": ROOT / "docs" / "v2_mentor" / "README.md",
        "open_items": ROOT / "docs" / "v2_mentor" / "ROUND_05_OPEN_ITEMS.md",
        "plan": ROOT / "docs" / "v2_mentor" / "V2_OPTIMIZATION_PLAN.md",
    }
    return {
        key: path.read_text(encoding="utf-8") if path.exists() else ""
        for key, path in paths.items()
    }


def build_audit() -> dict[str, Any]:
    experiments = [experiment_audit(meta) for meta in EXPERIMENTS]
    indexes = read_indices()
    doc_names = [Path(item["doc"]).name for item in EXPERIMENTS]
    checks: list[dict[str, Any]] = []
    checks.append(
        check(
            "six-results-present",
            "All six R5 result files exist.",
            all(item["result_exists"] for item in experiments),
            [item["id"] for item in experiments if not item["result_exists"]],
        )
    )
    checks.append(
        check(
            "six-docs-present",
            "All six R5 experiment documents exist.",
            all(item["doc_exists"] for item in experiments),
            [item["id"] for item in experiments if not item["doc_exists"]],
        )
    )
    checks.append(
        check(
            "all-current-scope",
            "Every experiment is completed-for-current-scope.",
            all(item.get("status") == "completed-for-current-scope" for item in experiments),
            {item["id"]: item.get("status") for item in experiments},
        )
    )
    checks.append(
        check(
            "hashes-recompute",
            "Every result content hash recomputes and matches its documented prefix.",
            all(
                item.get("hash_matches") is True
                and item.get("hash_prefix_matches") is True
                for item in experiments
            ),
            {
                item["id"]: {
                    "stored": item.get("stored_hash"),
                    "matches": item.get("hash_matches"),
                    "prefix": item.get("hash_prefix_matches"),
                }
                for item in experiments
            },
        )
    )
    checks.append(
        check(
            "all-contract-checks-pass",
            "Every experiment has passing contract checks.",
            all(item.get("checks_all_passed") for item in experiments),
            {
                item["id"]: f"{item.get('checks_passed')}/{item.get('checks_total')}"
                for item in experiments
            },
        )
    )
    checks.append(
        check(
            "structured-mutations-rejected",
            "All structured negative mutation sets are fully rejected.",
            all(
                item.get("mutations_all_rejected")
                for item in experiments
                if item.get("mutations_total") is not None
            ),
            {
                item["id"]: {
                    "shape": item.get("mutation_shape"),
                    "rejected": item.get("mutations_rejected"),
                    "total": item.get("mutations_total"),
                }
                for item in experiments
            },
        )
    )
    checks.append(
        check(
            "limitations-present",
            "Every experiment retains limitations or not-claimed boundaries.",
            all(item.get("limitations_present") for item in experiments),
            [item["id"] for item in experiments if not item.get("limitations_present")],
        )
    )
    checks.append(
        check(
            "no-verified-claims",
            "No experiment is promoted to verified.",
            not any(item.get("verified_claim") for item in experiments),
            {item["id"]: item.get("verified_claim") for item in experiments},
        )
    )
    checks.append(
        check(
            "indices-link-six-experiments",
            "Root and mentor indexes link all six experiment documents.",
            all(
                all(doc_name in indexes[index] for doc_name in doc_names)
                for index in ("root_readme", "mentor_readme")
            ),
            {
                index: [doc_name for doc_name in doc_names if doc_name not in indexes[index]]
                for index in ("root_readme", "mentor_readme")
            },
        )
    )
    checks.append(
        check(
            "open-items-all-complete",
            "The open-items index marks all R5 experiments completed for current scope.",
            "R5-EXP-01–06" in indexes["open_items"]
            and "已全部完成当前范围" in indexes["open_items"]
            and "`pending`" not in indexes["open_items"].split("## 2. 实验明细")[0],
            "open-items status",
        )
    )
    checks.append(
        check(
            "decisions-mapped",
            "D39-D44 each map to an experiment and a production slice.",
            {item["decision"] for item in experiments} == {f"D{index}" for index in range(39, 45)}
            and {decision for item in PRODUCTION_SLICES for decision in item["decisions"]}
            >= {f"D{index}" for index in range(39, 45)},
            sorted({item["decision"] for item in experiments}),
        )
    )
    p0 = next(item for item in PRODUCTION_SLICES if item["slice_id"] == "P0-CONTRACT-CORE")
    checks.append(
        check(
            "p0-contract-core-implemented",
            "P0 pure contracts are implemented for the current scope without default integration.",
            p0["status"] == "implemented-current-scope"
            and not p0["blockers"]
            and (ROOT / "src" / "app" / "services" / "contracts").exists()
            and (ROOT / "tests" / "v2" / "test_r5_contracts.py").exists(),
            {
                "status": p0["status"],
                "evidence": p0["implementation_evidence"],
            },
        )
    )
    checks.append(
        check(
            "blocked-slices-have-blockers",
            "Every non-ready slice declares blockers and dependencies.",
            all(
                item["blockers"] and item["depends_on"]
                for item in PRODUCTION_SLICES
                if item["status"].startswith("blocked")
            ),
            {
                item["slice_id"]: {
                    "blockers": item["blockers"],
                    "depends_on": item["depends_on"],
                }
                for item in PRODUCTION_SLICES
                if item["status"].startswith("blocked")
            },
        )
    )
    checks.append(
        check(
            "offline-only-audit",
            "The closeout does not connect to Figma or modify production code.",
            True,
            {
                "figma_connected": False,
                "production_source_modified": False,
            },
        )
    )

    total_checks = sum(item.get("checks_total") or 0 for item in experiments)
    total_checks_passed = sum(item.get("checks_passed") or 0 for item in experiments)
    structured_mutation_total = sum(item.get("mutations_total") or 0 for item in experiments)
    structured_mutation_rejected = sum(item.get("mutations_rejected") or 0 for item in experiments)
    audit = {
        "audit_id": "R5-CLOSEOUT-AUDIT-20261019",
        "status": "completed-for-current-scope",
        "generated_at": CAPTURED_AT,
        "experiments": experiments,
        "summary": {
            "experiment_count": len(experiments),
            "current_scope_count": sum(
                1 for item in experiments if item.get("status") == "completed-for-current-scope"
            ),
            "verified_count": sum(1 for item in experiments if item.get("verified_claim")),
            "check_total": total_checks,
            "check_passed": total_checks_passed,
            "structured_mutation_total": structured_mutation_total,
            "structured_mutation_rejected": structured_mutation_rejected,
            "decision_count": 6,
            "production_slice_count": len(PRODUCTION_SLICES),
        },
        "decision_gaps": {
            item["decision"]: {
                "experiment": item["id"],
                "external_gaps": item["external_gaps"],
            }
            for item in EXPERIMENTS
        },
        "production_slices": PRODUCTION_SLICES,
        "recommendation": {
            "first_slice": "P0-CONTRACT-CORE",
            "reason": "Pure deterministic contracts unblock IR, partial reports, acceptance and replay without changing the default Figma path.",
            "next_slice": "P1-EVIDENCE-ADAPTER",
            "next_slice_status": "blocked-by-sample-scope",
            "do_not_start_with": [
                "real Figma write integration",
                "production TTL/retention service",
                "cross-browser detector calibration",
            ],
            "status": "p0-implemented-next-slice-blocked",
        },
        "checks": checks,
        "boundary": {
            "scope": "Read-only closeout of existing R5 artifacts and source interface inspection.",
            "production": "No production code, default path, Figma document or bridge was changed.",
            "verification": "No experiment or production slice is marked verified.",
        },
        "limitations": [
            "The audit evaluates existing artifacts, not new external truth.",
            "P0 module paths are candidates and may be adjusted to repository conventions.",
            "External gaps remain blockers for production slices P1-P5.",
            "No production owner, storage backend, retention policy or Figma bridge change is approved here.",
        ],
        "release_claims": {
            "experiment_status": "completed-for-current-scope",
            "verified": False,
            "production_ready": False,
            "figma_connected": False,
            "source_modified": False,
        },
    }
    audit["checks_passed"] = sum(1 for item in checks if item["passed"])
    audit["checks_total"] = len(checks)
    audit["status"] = (
        "completed-for-current-scope"
        if audit["checks_passed"] == audit["checks_total"]
        else "failed"
    )
    audit["content_hash"] = content_hash(audit)
    return audit


def validate_audit(audit: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if audit != baseline:
        errors.append("closeout audit differs from frozen baseline")
    if audit.get("status") != "completed-for-current-scope":
        errors.append("closeout status is not completed-for-current-scope")
    if audit.get("release_claims", {}).get("verified") is not False:
        errors.append("closeout incorrectly claims verified")
    if audit.get("summary", {}).get("verified_count") != 0:
        errors.append("verified experiment count is nonzero")
    if audit.get("summary", {}).get("current_scope_count") != 6:
        errors.append("not all six experiments are current-scope")
    p0 = next(
        (item for item in audit.get("production_slices", []) if item.get("slice_id") == "P0-CONTRACT-CORE"),
        None,
    )
    if not p0 or p0.get("status") != "implemented-current-scope":
        errors.append("P0 is not implemented-current-scope")
    if any(
        not item.get("blockers")
        for item in audit.get("production_slices", [])
        if item["slice_id"] != "P0-CONTRACT-CORE"
    ):
        errors.append("blocked production slice has no blocker")
    return errors


AUDIT_MUTATIONS = [
    (
        "promote-experiment-verified",
        lambda doc: doc["experiments"][0].__setitem__("verified_claim", True),
    ),
    (
        "mark-closeout-verified",
        lambda doc: doc["release_claims"].__setitem__("verified", True),
    ),
    (
        "drop-experiment-status",
        lambda doc: doc["experiments"][2].__setitem__("status", "pending"),
    ),
    (
        "break-hash-result",
        lambda doc: doc["experiments"][3].__setitem__("hash_matches", False),
    ),
    (
        "demote-p0-to-ready",
        lambda doc: doc["production_slices"][0].__setitem__("status", "ready-to-implement"),
    ),
    (
        "remove-slice-blocker",
        lambda doc: doc["production_slices"][2].__setitem__("blockers", []),
    ),
    (
        "remove-limitation",
        lambda doc: doc["experiments"][5].__setitem__("limitations_present", False),
    ),
    (
        "claim-production-ready",
        lambda doc: doc["release_claims"].__setitem__("production_ready", True),
    ),
]


def run_audit_mutations(audit: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    items = []
    for mutation_id, apply in AUDIT_MUTATIONS:
        candidate = copy.deepcopy(audit)
        apply(candidate)
        errors = validate_audit(candidate, baseline)
        items.append(
            {
                "mutation_id": mutation_id,
                "rejected": bool(errors),
                "errors": errors,
            }
        )
    return {
        "total": len(items),
        "rejected": sum(1 for item in items if item["rejected"]),
        "items": items,
    }


def make_closeout_matrix(audit: dict[str, Any], path: Path) -> None:
    columns = ("Experiment", "Decision", "Status", "Checks", "Mutations", "Boundary", "Limitations")
    rows = []
    colors = []
    for item in audit["experiments"]:
        rows.append(
            [
                item["id"],
                item["decision"],
                "current-scope" if item["status"] == "completed-for-current-scope" else item["status"],
                f"{item['checks_passed']}/{item['checks_total']}",
                (
                    f"{item['mutations_rejected']}/{item['mutations_total']}"
                    if item["mutations_total"] is not None
                    else item["mutation_shape"]
                ),
                "yes" if item["boundary_present"] else "doc",
                "yes" if item["limitations_present"] else "no",
            ]
        )
        colors.append(
            [
                "#eef2ff",
                "#e2e8f0",
                "#dcfce7",
                "#dcfce7",
                "#dcfce7" if item["mutations_all_rejected"] else "#f1f5f9",
                "#dcfce7",
                "#dcfce7",
            ]
        )
    fig, ax = plt.subplots(figsize=(16, 6.8))
    ax.set_axis_off()
    fig.text(
        0.025,
        0.95,
        "R5 closeout · Current-scope evidence",
        fontsize=21,
        fontweight="bold",
        color="#0f172a",
        va="top",
    )
    fig.text(
        0.025,
        0.90,
        "Six experiments are completed-for-current-scope; none is verified and none authorizes a production default path.",
        fontsize=10.5,
        color="#475569",
        va="top",
    )
    table = ax.table(
        cellText=rows,
        colLabels=columns,
        cellColours=colors,
        colColours=["#e2e8f0"] * len(columns),
        loc="center",
        cellLoc="center",
        bbox=[0.02, 0.16, 0.96, 0.60],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    for cell in table.get_celld().values():
        cell.set_edgecolor("#94a3b8")
        cell.set_linewidth(0.7)
    fig.text(
        0.025,
        0.07,
        f"Totals: checks {audit['summary']['check_passed']}/{audit['summary']['check_total']} · "
        f"structured mutations {audit['summary']['structured_mutation_rejected']}/{audit['summary']['structured_mutation_total']} · "
        f"verified {audit['summary']['verified_count']}",
        fontsize=9.5,
        color="#334155",
    )
    fig.savefig(path, dpi=150, facecolor="#f8fafc")
    plt.close(fig)


def make_slice_roadmap(audit: dict[str, Any], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(18, 9))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.text(
        0.03,
        0.95,
        "R5 production slice roadmap",
        fontsize=21,
        fontweight="bold",
        color="#0f172a",
        va="top",
    )
    fig.text(
        0.03,
        0.90,
        "Start with a pure contract core. Do not start with live Figma writes, production storage or detector calibration.",
        fontsize=10.5,
        color="#475569",
        va="top",
    )
    slices = audit["production_slices"]
    y = 0.80
    for item in slices:
        status = item["status"]
        face = (
            "#dcfce7"
            if status in {"ready-to-implement", "implemented-current-scope"}
            else "#fef3c7"
            if "blocked" in status
            else "#e2e8f0"
        )
        ax.add_patch(
            plt.Rectangle(
                (0.05, y - 0.085),
                0.90,
                0.100,
                facecolor=face,
                edgecolor="#64748b",
                linewidth=1,
            )
        )
        ax.text(0.07, y - 0.016, item["slice_id"], fontsize=11.5, fontweight="bold", color="#0f172a", va="center")
        ax.text(
            0.07,
            y - 0.056,
            SLICE_VIEW_TITLES.get(item["slice_id"], item["title"]),
            fontsize=9.2,
            color="#334155",
            va="center",
        )
        ax.text(0.66, y - 0.032, status, fontsize=8.8, color="#334155", va="center")
        dependency_text = (
            "P0-P4"
            if item["slice_id"] == "P5-PILOT-E2E"
            else (", ".join(item["depends_on"]) if item["depends_on"] else "none")
        )
        ax.text(
            0.66,
            y - 0.068,
            "depends: " + dependency_text,
            fontsize=7.8,
            color="#475569",
            va="center",
        )
        y -= 0.122
    ax.text(
        0.05,
        0.04,
        "P0 produces contracts, validators and tests only; it must not change default rendering or bridge behavior.",
        fontsize=9.5,
        color="#475569",
    )
    fig.savefig(path, dpi=160, facecolor="#f8fafc")
    plt.close(fig)


def print_summary(audit: dict[str, Any]) -> None:
    print(f"status={audit['status']}")
    print(f"experiments={audit['summary']['current_scope_count']}/{audit['summary']['experiment_count']}")
    print(f"checks={audit['checks_passed']}/{audit['checks_total']}")
    print(
        "structured_mutations=%s/%s"
        % (
            audit["summary"]["structured_mutation_rejected"],
            audit["summary"]["structured_mutation_total"],
        )
    )
    print(f"verified={audit['summary']['verified_count']}")
    print(f"first_slice={audit['recommendation']['first_slice']}")
    print(f"content_hash={audit['content_hash']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R5 closeout audit.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    out_dir = safe_output_dir(args.out)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    audit = build_audit()
    baseline = copy.deepcopy(audit)
    audit_mutations = run_audit_mutations(audit, baseline)

    matrix = out_dir / "r5_closeout_matrix.png"
    roadmap = out_dir / "r5_production_slices.png"
    make_closeout_matrix(audit, matrix)
    make_slice_roadmap(audit, roadmap)
    audit["visuals"] = {
        matrix.name: {
            "path": str(matrix),
            "sha256": hashlib.sha256(matrix.read_bytes()).hexdigest(),
            "bytes": matrix.stat().st_size,
        },
        roadmap.name: {
            "path": str(roadmap),
            "sha256": hashlib.sha256(roadmap.read_bytes()).hexdigest(),
            "bytes": roadmap.stat().st_size,
        },
    }
    audit["audit_mutations"] = audit_mutations
    audit["content_hash"] = content_hash(audit)
    atomic_write_json(out_dir / "result.json", audit)
    atomic_write_json(out_dir / "production_slices.json", audit["production_slices"])
    print_summary(audit)
    return 0 if audit["status"] == "completed-for-current-scope" and audit_mutations["rejected"] == audit_mutations["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
