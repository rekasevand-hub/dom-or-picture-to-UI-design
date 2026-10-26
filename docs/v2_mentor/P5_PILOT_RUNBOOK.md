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

Required real-environment profile:

- real Figma plugin and fixed document;
- four writers for the full hour;
- no client sleep;
- reconnect every 100 transactions;
- one deliberate reconnect and controlled timeout;
- dedicated journal and ledger;
- checkpoint resource samples;
- manual reconciliation owner available.

Before promoting a run to the frozen gate, resolve `20261022问题文档.md` Q8
and Q9. Q8 determines whether a fresh real controlled timeout is mandatory;
Q9 determines whether `max_writes=1000` is a total-write cap that conflicts
with the four-writer/no-sleep profile. A throughput run made before those
answers is stress evidence only and cannot be promoted by changing thresholds
after observation.

The repaired stress run is recorded under
`output/_p5_dry_run_round1/real_staged_1h_round3/`; failed round 2 remains
under `real_staged_1h_round2/` as required negative evidence.

Round 3 sustained 56,973 writes and the repaired journal bound held, but its
day-end cleanup reused an admin connection that had been idle for one hour and
failed with `WinError 10053`. The report correctly failed. Owned nodes were
then removed manually, and a post-fix short run verified reconnect-before-
cleanup with exact readback. Round 3 remains stress evidence, not a pass.

Q10 records that this probe exercises the real bridge, lease, journal and
cleanup path directly, while `contract-v2`, PARTIAL reporting and the
local-pilot store are covered by deterministic/full-stack tests rather than
the same real Figma request. The two evidence layers must not be merged into a
claim without the mentor ruling requested in Q10.

## Rollback

Stop writes, preserve journal/ledger/lease evidence, verify owner/job markers,
and compensate only the declared region. Incomplete rollback remains
`rollback-incomplete/manual-review`.

## Acceptance

The dry run passes only if every request is completed or explicitly classified,
there is no unexplained unknown, no automatic resend occurs, storage bounds hold,
resource trends remain bounded, cleanup is exact and evidence hashes reproduce.

Run the mechanical audit before reviewing any claim:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_evidence_audit.py `
  --report <figma_bridge_soak.json> `
  --inputs output\_p5_pilot_inputs\inputs.json `
  --max-journal-events 4096 `
  --pending-ruling Q8 --pending-ruling Q9 --pending-ruling Q10 `
  --out <evidence_audit.json>
```

`mechanical_pass=true` only proves the report and its recorded checks are
internally consistent. It does not resolve pending rulings. With any pending
ruling the audit remains `blocked-pending-rulings`, never
`pilot-verified-for`.

Without the one-hour real rehearsal, the result remains
`blocked-environment`, not `pilot-verified-for`.
