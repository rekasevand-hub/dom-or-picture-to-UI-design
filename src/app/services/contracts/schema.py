"""Version identifiers and portable JSON schemas for v2 contract layers."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

RUNTIME_IR_SCHEMA_ID = "runtime-ir/1.0"
AUDIT_BUNDLE_SCHEMA_ID = "audit-bundle/1.0"
CURRENT_IR_SCHEMA_VERSION = "2.0"
IR_SCHEMA_VERSIONS = ("1.0", "2.0")
ORDERED_AUDIT_ONLY = "ordered-audit-only"

_RUNTIME_IR_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://figma-auto-agent.local/schema/runtime-ir-1.0.json",
    "title": "RuntimeIR",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "outer_schema",
        "job_id",
        "schema_version",
        "policy_version",
        "capture_revision",
        "plan_revision",
        "output_revision",
        "capture_id",
        "state_signature",
        "fields",
        "evidence",
        "assets",
        "tombstones",
        "unknowns",
        "order_mapping",
        "references",
        "retention",
        "access_policy",
        "execution_graph",
    ],
    "properties": {
        "outer_schema": {"const": RUNTIME_IR_SCHEMA_ID},
        "schema_version": {"enum": list(IR_SCHEMA_VERSIONS)},
        "job_id": {"type": "string"},
        "policy_version": {"type": "string"},
        "capture_revision": {"type": "string"},
        "plan_revision": {"type": "string"},
        "output_revision": {"type": "string"},
        "capture_id": {"type": "string"},
        "state_signature": {"type": "string"},
        "fields": {"type": "array"},
        "evidence": {"type": "array"},
        "assets": {"type": "array"},
        "tombstones": {"type": "array"},
        "unknowns": {"type": "array"},
        "order_mapping": {"type": "object"},
        "references": {"type": "array"},
        "retention": {"type": "object"},
        "access_policy": {"type": "object"},
        "migration_chain": {"type": "array"},
        "execution_graph": {
            "type": "object",
            "required": ["nodes", "edges", "sequence_semantics"],
            "properties": {
                "sequence_semantics": {"const": "runtime-dag"},
            },
        },
    },
}

_AUDIT_BUNDLE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://figma-auto-agent.local/schema/audit-bundle-1.0.json",
    "title": "AuditBundle",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "outer_schema",
        "job_id",
        "schema_version",
        "policy_version",
        "ordered_evidence",
        "decisions",
        "tombstones",
        "unknowns",
        "order_mapping",
        "retention",
        "sequence_semantics",
    ],
    "properties": {
        "outer_schema": {"const": AUDIT_BUNDLE_SCHEMA_ID},
        "schema_version": {"enum": list(IR_SCHEMA_VERSIONS)},
        "sequence_semantics": {"const": ORDERED_AUDIT_ONLY},
        "job_id": {"type": "string"},
        "policy_version": {"type": "string"},
        "ordered_evidence": {
            "type": "array",
            "items": {"type": "string"},
        },
        "decisions": {"type": "array"},
        "tombstones": {"type": "array"},
        "unknowns": {"type": "array"},
        "order_mapping": {"type": "object"},
        "retention": {"type": "object"},
        "execution_graph": {"type": "null"},
        "runtime_dependency_graph": {"type": "null"},
    },
}


def runtime_ir_json_schema() -> dict[str, Any]:
    return deepcopy(_RUNTIME_IR_SCHEMA)


def audit_bundle_json_schema() -> dict[str, Any]:
    return deepcopy(_AUDIT_BUNDLE_SCHEMA)
