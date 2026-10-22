# P5 Pilot Runbook

> Frozen profile: `p5-dry-run-profile/1.0`  
> Delivery profile: explicit `contract-v2`; outside the P5 command the default
> remains `legacy`.

## Frozen Inputs

- code revision and dirty state;
- plugin `code.js` and `manifest.json` hashes;
- canonical Chromium build;
- fixed Figma document and saved version;
- approved root nodes;
- allowed actions: `apply_edit_batch`, `ownership_report`,
  `cleanup_owned_job`;
- operator and manual-review owner.

## Abort Thresholds

- maximum writes: 1000;
- maximum unexplained unknowns: 0;
- allowed PARTIAL cases: 1, declared before the run;
- cleanup deadline: 60 seconds;
- abort on stale lease, cleanup mismatch, or journal/ledger bound breach.

## Deterministic Dry Run

1. Confirm `legacy` is the default outside the P5 command.
2. Run four writers with no client sleep.
3. Reconnect every 100 transactions.
4. Include one controlled timeout and reconcile it without resend.
5. Verify bounded journal/ledger, resource trend and exact cleanup.

## One-Hour Staged Rehearsal

Required but not yet run:

- real Figma plugin and fixed document;
- four writers for the full hour;
- no client sleep;
- reconnect every 100 transactions;
- one deliberate reconnect and controlled timeout;
- dedicated journal and ledger;
- checkpoint resource samples;
- manual reconciliation owner available.

## Rollback

Stop writes, preserve journal/ledger/lease evidence, verify owner/job markers,
and compensate only the declared region. Incomplete rollback remains
`rollback-incomplete/manual-review`.

## Acceptance

The dry run passes only if every request is completed or explicitly classified,
there is no unexplained unknown, no automatic resend occurs, storage bounds hold,
resource trends remain bounded, cleanup is exact and evidence hashes reproduce.

Without the one-hour real rehearsal, the result remains
`blocked-environment`, not `pilot-verified-for`.
