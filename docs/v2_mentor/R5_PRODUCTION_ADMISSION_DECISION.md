# R5 Production Admission Decision

> Date: 2026-10-22  
> Decision: `not-admitted`  
> P5 pilot: `not-run`  
> Production long soak: `not-run`  
> Project-wide boolean verification: forbidden

## Decision Summary

Production admission is rejected. Current-scope contracts, local pilot storage,
single-writer lease, conflict/PARTIAL gates and hard-gate matrices are useful
evidence, but the one-hour real Figma rehearsal, bounded P5 pilot and staged
cloud soak have not run. No supported production environment or action scope
can be admitted from the present evidence.

## Residual Risk Disposition

| Risk ID | Owner | Disposition | Mitigation | Evidence | Rollback | Expiry Or Resolution |
|---|---|---|---|---|---|---|
| RR-001 | Typography owner | conditional | Keep numeric weight values and mark arbitrary axes unsupported. | Font provenance tests and `RESIDUAL_RISKS.md`. | Rebind to named Figma face and report unsupported axis. | Only if exact variable-axis claims enter scope. |
| RR-002 | Typography owner | conditional | Keep mixed-script fallback ambiguous and fail closed. | Font provenance and Figma font readback. | Split runs or block exact glyph claim. | Only if glyph-level identity enters scope. |
| RR-003 | Browser compatibility owner | conditional | Do not infer Firefox from Chromium or WebKit. | Firefox launch failure record. | Exclude Firefox from the claim. | Requires independent Firefox environment. |
| RR-004 | P1 real-site owner | blocking | Freeze profiles and run repeated real-site sampling. | Independent site observations remain diagnostic only. | Disable real-site admission claim. | Before production admission review. |
| RR-005 | Layout owner | blocking | Expand Grid holdouts and cross-version readback. | Grid holdout and reopen evidence, incomplete combinations. | Fall back to supported fixed layout actions. | Before adaptive Grid production claim. |
| RR-006 | P3 Figma fault owner | blocking | Exercise upload interruption, collaboration conflict and process termination. | Runtime fault probe covers API constraint rollback only. | Stop writes and preserve evidence. | Before production fault admission. |
| RR-007 | P3 bridge owner | blocking | Verify cross-host fence and commit-attribution limits explicitly. | Controlled-timeout resume and journal evidence. | Revert to one-host topology and no automatic replay. | Before distributed write admission. |
| RR-008 | Platform owner | blocking | Define document routing and tenant isolation before scaling. | Client namespace evidence only. | Keep one document and one client scope. | Before multi-tenant admission. |
| RR-009 | Performance owner | blocking | Run staged cloud soak and preserve fairness metrics. | Short deterministic and real pacing results only. | Disable production writes on bound breach. | Before production performance claim. |
| RR-010 | Deployment security owner | blocking | Require configured per-client identity and rotation audit. | Client identity probe with anonymous default. | Reject writes and return to development mode. | Before production security admission. |
| RR-011 | Deployment security owner | blocking | Select secret manager, private ACL and leak response owner. | Atomic rotation and conservative ACL evidence. | Rotate secrets and disable bridge. | Before production secret admission. |
| RR-012 | Deployment security owner | blocking | Provision certificate lifecycle and system trust. | Local TLS handshake evidence only. | Disable TLS deployment and stop public access. | Before production transport admission. |
| RR-013 | Deployment security owner | blocking | Automate plugin token provisioning, revocation and recovery notification. | Real UI revocation/recovery evidence. | Revoke active plugin and stop reconnect. | Before production plugin deployment. |
| RR-014 | P3 collaboration owner | blocking | Require authoritative attribution or operator approval. | Multiplayer boundary evidence and Q1-Q3. | Keep transaction unknown and no-resend. | Before collaborator-safe admission. |
| RR-015 | P4 persistence owner | blocking | Implement cross-process fencing, purge policy and production restore drills. | Local-pilot backup/restore and ledger lifecycle. | Restore known-good snapshot and stop compaction. | Before production persistence admission. |

## Production Prerequisites

| Prerequisite | Status | Evidence Gap | Required Exit |
|---|---|---|---|
| identity-secret-lifecycle | current-scope | Production secret manager, ACL ownership and rotation audit are not deployed. | Deployed lifecycle review. |
| permission-and-takeover | blocked | Real view-only, rate-limit, takeover and collaborator race evidence is absent. | Fixed-document execution with two collaborators. |
| single-writer-fencing | current-scope | Local Windows lease passes; distributed topology is out of scope. | Declare and verify one-host topology or add distributed fencing. |
| backup-and-restore | current-scope | Local-pilot restore passes; production backend is not implemented. | Production backup and restore drill. |
| monitoring-and-alerts | current-scope | Metric contract passes locally; remote monitoring is absent. | Deployed dashboard and alert ownership. |
| incident-response | incomplete | Runbook exists; no production incident drill has run. | Operator drill with evidence. |
| production-long-soak | not-run | 1h, 24h and 7d cloud runs have not executed. | Sequential soak stages on user cloud host. |

## Release Scope

Supported environment: none for production.  
Supported actions: none for production.  
Document scope: none for production.  
Exclusions: all Figma production writes, public bridge exposure, multi-host
journal ownership, collaborator-safe attribution, Firefox parity and
cross-host scaling.

## Admission Conditions

Admission may be reconsidered only after the P5 one-hour rehearsal and fixed
registry pilot pass, followed by Task 12 cloud soak stages and a new review.
Current local evidence remains bounded to its named authored or local-pilot
scope.
