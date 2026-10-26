# P5 Manual Reconciliation Policy

> Status: proposed current scope  
> Applies to: unknown or partial Figma writes, permission failures, plugin
> takeover and collaborator races.

## Principles

1. A matching current state is evidence of current state only. It is not proof
   of actor, revision or original commit ownership.
2. Unknown writes are never automatically replayed.
3. Owned node ids, readback evidence, transaction id and timestamps are retained
   even when the outcome remains unknown.
4. A human operator must approve any transition from unknown to committed,
   rejected or rollback-complete.
5. An incomplete rollback remains `rollback-incomplete/manual-review`.
6. Automatic cleanup is allowed only after a terminal ledger state and only
   with exact owner, job and requested-region evidence.
7. Unknown, in-flight, resume-required and rollback-incomplete jobs require
   operator review before cleanup dispatch.

## Decision Rules

| Observed state | Recommendation | Resend |
|---|---|---|
| `matches-intended` | `operator-confirm-no-resend` | No |
| `partial-match` | `operator-reconcile-partial-state` | No |
| `mismatch` or conflict | `operator-resolve-conflict` | No |
| owned node deleted | `rollback-incomplete-manual-review` | No |
| indeterminate | `operator-reconcile-unknown` | No |

## Permission Outcomes

| Category | Retry | Operator review |
|---|---|---|
| `view-only` | No | Yes |
| `permission-denied` | No | Yes |
| `rate-limited` | Only if failure occurred before send and the server supplied retry metadata | No for pre-send rejection |
| `plugin-token-revoked` | No | Repair authentication |
| `plugin-takeover` | No | Yes |
| `user-modification` | No | Yes |
| `unknown` | No | Yes |

## Cleanup Rules

- Cleanup never removes a node from another owner or job.
- A same-job node with a different region is preserved.
- A missing region marker makes the compensation plan incomplete and routes it
  to manual review.
- A `plugin-takeover` or `user-modification` outcome blocks automatic cleanup
  and compensation.
- Cleanup after an unknown write is never inferred from matching current state.

## Required Real Pilot Inputs

- fixed Figma document and saved version;
- view-only and writable accounts;
- two collaborator identities with controlled timing;
- operator identity and approval channel;
- authoritative attribution source, if one exists.

The code and deterministic policy may be complete without these inputs, but the
production claim must remain blocked until the real scenarios are executed.
