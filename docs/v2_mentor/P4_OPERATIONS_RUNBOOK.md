# P4 Operations Runbook

> Scope: controlled local P5 pilot and future production admission  
> Status: current-scope backup/restore and metric contract

## Kill Switch

1. Stop accepting new writes at the bridge.
2. Keep read-only status queries available.
3. Preserve journal, ledger, lease and evidence files.
4. Require an operator decision before clearing write degradation.

## Rollback

1. Identify the transaction, owned node ids and region.
2. Verify exact job and owner markers.
3. Apply region-scoped compensation only to matching nodes.
4. Preserve nodes modified or deleted by a collaborator.
5. Mark incomplete rollback as `rollback-incomplete/manual-review`.

## Stale Token Recovery

1. Stop automatic reconnect.
2. Rotate the plugin token through the approved secret path.
3. Clear stale `figma.clientStorage` values when required.
4. Reconnect only with the new token and record a new lease generation.

## Stale Lease Recovery

1. Confirm the prior owner process is stopped.
2. Wait for lease expiry or explicitly revoke it through the approved operator path.
3. Acquire a new monotonic generation.
4. Re-read journal and ledger before any new write.
5. Never replay an unknown write merely because the lease changed.

## Manual Unknown Review

- Compare current state with intent and owned-node evidence.
- Keep actor/revision unavailable unless an authoritative source exists.
- Record operator, decision and reason.
- Use `reconcile-no-resend` when the state matches; never report commit attribution.

## Backup and Restore

- Build a manifest containing every stored file hash.
- Detect corruption before restore.
- Restore to a separate directory and verify hashes, tombstones, unknown state,
  evidence metadata and release decision.
- Do not overwrite the only known-good copy during a drill.

## Monitoring

Required metrics:

- pending and unknown transactions;
- 409 conflicts;
- write p50/p95/p99;
- journal and ledger size;
- compaction removed events;
- plugin reconnects;
- lease generation;
- storage errors;
- disclosure counts.

No metric label or event may contain raw design text, secrets or action payload.

## Evidence Collection

- result and manifest hashes;
- bridge journal and business ledger;
- lease state and generation;
- plugin build hash;
- backup/restore reports;
- screenshots or operator notes for failed manual review.
