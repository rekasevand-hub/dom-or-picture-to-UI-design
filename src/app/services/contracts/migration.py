"""Versioned runtime-IR migration with explicit preservation checks."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from src.app.services.contracts.models import MigrationResult, RuntimeIR, jsonable

SUPPORTED_RUNTIME_IR_VERSIONS = ("1.0", "2.0")


def canonical_json(value: object) -> str:
    return json.dumps(
        jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def migrate_runtime_ir(ir: RuntimeIR, *, migrated_at: str) -> tuple[RuntimeIR, MigrationResult]:
    if ir.schema_version != "1.0":
        raise ValueError("Only runtime IR schema 1.0 can be migrated to 2.0")
    source_hash = canonical_hash(ir)
    chain_entry = {
        "from_version": "1.0",
        "to_version": "2.0",
        "source_hash": source_hash,
        "migrated_at": migrated_at,
        "preserves": [
            "fields",
            "observations",
            "decisions",
            "authority",
            "order_mapping",
            "tombstones",
            "unknowns",
            "evidence",
        ],
    }
    migrated = replace(
        ir,
        schema_version="2.0",
        migration_chain=ir.migration_chain + (chain_entry,),
    )
    preserved = {
        "fields": migrated.fields == ir.fields,
        "authority": tuple(
            (item.field_id, item.decision.authority, item.decision.status)
            for item in migrated.fields
        )
        == tuple(
            (item.field_id, item.decision.authority, item.decision.status)
            for item in ir.fields
        ),
        "order_mapping": migrated.order_mapping == ir.order_mapping,
        "tombstones": migrated.tombstones == ir.tombstones,
        "unknowns": migrated.unknowns == ir.unknowns,
        "evidence": migrated.evidence == ir.evidence,
    }
    result = MigrationResult(
        source_version=ir.schema_version,
        target_version=migrated.schema_version,
        source_hash=source_hash,
        migrated_hash=canonical_hash(migrated),
        preserved=preserved,
        migration_chain=migrated.migration_chain,
    )
    if not result.all_preserved:
        raise ValueError(f"Migration lost required state: {preserved}")
    return migrated, result
