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

## Plugin Offline During Cleanup

1. Preserve the report, root/text ownership job ids and node ids.
2. Stop the soak instead of declaring cleanup successful.
3. Reopen the fixed development plugin and verify `/plugin` authentication.
4. Run `ownership_report` for every retained job id before cleanup.
5. Run exact `cleanup_owned_job` only for matching owner/job markers.
6. Re-read ownership and require zero matches before another soak.

The 2026-10-26 local Figma round 2 failed at this boundary: setup ownership was
verified, but the plugin disconnected near the end of the run and did not return
for cleanup. The report remains `fail`.

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
- Grounding unavailable and fallback trigger counts;
- fallback selection acceptance and write-before-block counts;
- fallback latency p50/p95/p99 and token usage.

No metric label or event may contain raw design text, secrets or action payload.

Fallback selection acceptance means CV was selected after an availability
trigger. It is not content, structure, visual or asset acceptance. Monetary cost
stays unknown until a versioned pricing table is configured.

## Grounding and Fallback Alerts

1. `fallback_write_before_block_total > 0` is critical: stop writes and inspect
   the pre-write fallback record.
2. Repeated `grounding_unavailable_total` keeps CV fallback enabled while
   endpoint health is investigated; do not widen retry bounds.
3. Fallback latency p99 above `30s` is a warning and above `120s` is critical
   for the local-pilot contract.
4. Cache isolation mismatch requires a cache flush and stops image requests
   until the namespace is corrected.
5. Malformed Grounding output is a blocked route, not a CV-fallback trigger.

Detailed configuration, taxonomy and operator actions are in
`GROUNDING_RELIABILITY_RUNBOOK.md`.

## Evidence Collection

- result and manifest hashes;
- bridge journal and business ledger;
- lease state and generation;
- plugin build hash;
- backup/restore reports;
- screenshots or operator notes for failed manual review.
