# Production Verification Matrix

> Status: `production-not-admitted`  
> Date: 2026-10-22  
> This matrix records what production claims would require. It does not convert
> local pilot evidence into production evidence.

| Claim ID | Dimension | Claim | Environment | Code Revision | Plugin Build | Test Set | Thresholds | Evidence Hash | Status | Residual Unknown |
|---|---|---|---|---|---|---|---|---|---|---|
| PV-01 | bootstrap | Contract delivery path preserves legacy default and explicit contract profile. | Authored fixtures. | `1f4d67d+dirty` | `not-used` | `tests/v2/test_delivery_profile.py`, `test_precise_agent_contract_integration.py` | Exact byte identity and fail-before-dispatch. | `2bc1cdca82f14df8bf4ca042e03d1964766f862e8146f727e921d659c9146c0d` | verified-for:authored-contract-profile | Production Figma composition remains unmeasured. |
| PV-02 | soak-1h | One-hour cloud staged soak drains requests and classifies every outcome. | User cloud Windows host with official Figma Desktop. | `pending-cloud-run` | `pending-fixed-plugin-run` | Staged writer/reconnect probe per runbook. | 1000 writes, zero unexplained unknown, bounded resources. | `pending:output/_p4_cloud_soak_1h/<run-id>/` | not-run | Host, document and operator are unavailable. |
| PV-03 | soak-24h | Twenty-four-hour soak preserves bounds and reconnect behavior. | User cloud Windows host. | `pending-cloud-run` | `pending-fixed-plugin-run` | Stage B from `P4_LONG_SOAK_BACKLOG.md`. | No unexplained unknown, bounded RSS/handles/journal. | `pending:output/_p4_cloud_soak_24h/<run-id>/` | blocked | Requires successful 1h stage first. |
| PV-04 | soak-7d | Seven-day soak supports a bounded long-duration claim. | User cloud Windows host. | `pending-cloud-run` | `pending-fixed-plugin-run` | Stage C from `P4_LONG_SOAK_BACKLOG.md`. | Daily checkpoints and bounded resource trend. | `pending:output/_p4_cloud_soak_7d/<run-id>/` | blocked | Requires successful 24h stage first; renderer memory may remain unmeasured. |
| PV-05 | permission | Permission, rate-limit, takeover and collaboration races are conservatively reconciled. | Fixed pilot document with view-only/writable/two-collaborator accounts. | `1f4d67d+dirty` | `8b02befb-current` | `p5_permission_takeover_probe.py`, `p5_collaboration_race_probe.py` | No inferred actor/revision and no automatic resend. | `dcf760d1-current-scope` | blocked-environment | Real accounts and timing are unavailable. |
| PV-06 | storage | Backup, restore, migration and exact cleanup are verified on production storage. | Selected production PostgreSQL plus encrypted object storage. | `pending-production-backend` | `8b02befb-current` | Backup/restore and cleanup drills against deployed backend. | Hash, tombstone, unknown and release decision preserved. | `pending:production-backup-run` | blocked | Production backend is selected but not implemented. |
| PV-07 | observability | Metrics and alerts disclose no raw text, secret or action payload. | Declared production monitoring stack. | `1f4d67d+dirty` | `8b02befb-current` | `p4_observability_probe.py` and deployed dashboard validation. | Thirteen required metrics; disclosure count zero. | `14c95595366fe5acd58ef702c123b74136d01e2535d75272dbe8aaba0ec10c1c` | verified-for:local-pilot-metric-contract | Remote monitoring and on-call ownership are unavailable. |
| PV-08 | admission | All blocking risks have owner, mitigation, rollback and evidence. | Declared production scope. | `pending-admission-review` | `pending-admission-review` | Task 13 admission review. | No blocking risk silently accepted. | `pending:R5_PRODUCTION_ADMISSION_DECISION.md` | blocked | Admission review cannot proceed before PV-02 through PV-06. |

## Required Evidence Binding

Every future `verified-for` result must retain:

- exact code revision and dirty state;
- exact plugin `code.js` and manifest hashes;
- OS, browser, viewport and DPR;
- fixed document and root nodes;
- test set and thresholds;
- result JSON and evidence hash;
- failures classified as reproduced, explained, accepted risk or blocker.

## Admission Rule

The matrix can support only a named claim, environment and action set. It never
supports project-wide verification or production admission by itself.
