# R5 Production Admission Decision

> Date: 2026-10-27
> Decision: `not-admitted`
> P5 pilot: `blocked-pending-rulings`
> Production long soak: `blocked-24h-7d`
> Controlled one-hour soak: `verified-for:controlled-one-hour-fault-soak`
> Real local Figma one-hour: `verified-for:local-real-figma-write-1h`
> Project-wide boolean verification: forbidden

## Decision Summary

Production admission is rejected. The controlled one-hour fault soak and the
local real-Figma one-hour write run both passed, but Q8-Q10 policy rulings are
pending. The 24-hour and seven-day cloud stages, real two-collaborator timing,
production secret/certificate lifecycle, production storage and deployed remote
monitoring remain incomplete. No supported production environment or action
scope can be admitted.

## Residual Risk Disposition

| Risk ID | Owner | Disposition | Mitigation | Evidence | Rollback | Expiry Or Resolution |
|---|---|---|---|---|---|---|
| RR-001 | Typography owner | conditional | Keep numeric weight values and mark arbitrary axes unsupported. | Font provenance tests and `RESIDUAL_RISKS.md`. | Rebind to named Figma face and report unsupported axis. | Only if exact variable-axis claims enter scope. |
| RR-002 | Typography owner | conditional | Keep mixed-script fallback ambiguous and fail closed. | Font provenance and Figma font readback. | Split runs or block exact glyph claim. | Only if glyph-level identity enters scope. |
| RR-003 | Browser compatibility owner | conditional | Do not infer Firefox from Chromium or WebKit. | Firefox launch failure record. | Exclude Firefox from the claim. | Requires independent Firefox environment. |
| RR-004 | P1 real-site owner | blocking | Freeze profiles and run repeated real-site sampling. | Independent site observations remain diagnostic only. | Disable real-site admission claim. | Before production admission review. |
| RR-005 | Layout owner | blocking | Expand Grid holdouts and cross-version readback. | Grid holdout and reopen evidence, incomplete combinations. | Fall back to supported fixed layout actions. | Before adaptive Grid production claim. |
| RR-006 | P3 Figma fault owner | blocking | Exercise upload interruption, collaboration conflict and process termination. | Controlled 1h covers 429/503, reconnect, unknown readback and 0 failures; real 1h passed but did not deliberately interrupt upload/collaboration. | Stop writes and preserve evidence. | Before production fault admission. |
| RR-007 | P3 bridge owner | blocking | Verify cross-host fence and commit-attribution limits explicitly. | Controlled-timeout resume and journal evidence. | Revert to one-host topology and no automatic replay. | Before distributed write admission. |
| RR-008 | Platform owner | blocking | Define document routing and tenant isolation before scaling. | Client namespace evidence only. | Keep one document and one client scope. | Before multi-tenant admission. |
| RR-009 | Performance owner | blocking | Run staged cloud soak and preserve fairness metrics. | Controlled 1h and real local 1h pass; cloud 24h/7d remain not run. | Disable production writes on bound breach. | Before production performance claim. |
| RR-010 | Deployment security owner | blocking | Require configured per-client identity and rotation audit. | Generated-canary security pass; production identity deployment and rotation audit remain absent. | Reject writes and return to development mode. | Before production security admission. |
| RR-011 | Deployment security owner | blocking | Select secret manager, private ACL and leak response owner. | Atomic rotation and conservative ACL evidence. | Rotate secrets and disable bridge. | Before production secret admission. |
| RR-012 | Deployment security owner | blocking | Provision certificate lifecycle and system trust. | Local TLS handshake evidence only. | Disable TLS deployment and stop public access. | Before production transport admission. |
| RR-013 | Deployment security owner | blocking | Automate plugin token provisioning, revocation and recovery notification. | Real UI revocation/recovery evidence. | Revoke active plugin and stop reconnect. | Before production plugin deployment. |
| RR-014 | P3 collaboration owner | blocking | Require authoritative attribution or operator approval. | Controlled client/takeover/unknown recovery pass; real two-collaborator timing and attribution remain unavailable. | Keep transaction unknown and no-resend. | Before collaborator-safe admission. |
| RR-015 | P4 persistence owner | blocking | Implement cross-process fencing, purge policy and production restore drills. | Local-pilot backup/restore, ledger lifecycle and source-hashed 1h evidence pass; production storage remains absent. | Restore known-good snapshot and stop compaction. | Before production persistence admission. |

## Production Prerequisites

| Prerequisite | Status | Evidence Gap | Required Exit |
|---|---|---|---|
| identity-secret-lifecycle | current-scope | Production secret manager, ACL ownership and rotation audit are not deployed. | Deployed lifecycle review. |
| permission-and-takeover | blocked | Real view-only, collaborator timing and authoritative attribution remain absent. | Fixed-document execution with two collaborators and approved attribution source. |
| single-writer-fencing | current-scope | Local Windows lease, takeover recovery and 57,039-write real hour pass; distributed topology is out of scope. | Declare and verify one-host topology or add distributed fencing. |
| backup-and-restore | current-scope | Local-pilot restore passes; production backend is not implemented. | Production backup and restore drill. |
| monitoring-and-alerts | current-scope | 21-metric contract and local alerts pass; remote monitoring is absent. | Deployed dashboard and alert ownership. |
| incident-response | incomplete | Runbook exists; no production incident drill has run. | Operator drill with evidence. |
| production-long-soak | blocked | Local real 1h and controlled 1h pass; 24h and 7d cloud runs have not executed. | Sequential 24h/7d stages on user cloud host after Q8-Q10 rulings. |

## Release Scope

Supported environment: none for production.  
Supported actions: none for production.  
Document scope: none for production.  
Exclusions: all Figma production writes, public bridge exposure, multi-host
journal ownership, collaborator-safe attribution, Firefox parity and
cross-host scaling.

## Admission Conditions

Admission may be reconsidered only after:

1. Q8-Q10 are resolved and the fixed-registry P5 pilot is accepted;
2. real two-collaborator timing and attribution are exercised or excluded;
3. production secret manager, certificate lifecycle and ACL ownership are
   deployed;
4. production storage and restore drills are completed;
5. 24-hour and seven-day cloud soak stages pass in order.

The current one-hour passes remain bounded to their named local and controlled
scopes. They are not production admission.
