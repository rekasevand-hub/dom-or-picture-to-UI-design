# R5-P5 Pilot and Production Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the mentor-derived D1-D44 contracts and completed current-scope
experiments into a controlled R5-P5 pilot, then into a production-admission
decision without overstating `verified`.

**Architecture:** Keep two separate gates. The P5 pilot gate needs a fixed
Chromium/Figma environment, the contracts on the default path behind an explicit
profile, real detector-backed PARTIAL/acceptance reports, single-writer
enforcement, and pilot-level persistence. The production gate adds security
lifecycle, real concurrency/takeover behavior, production storage operations,
staged long soak, and an explicit admission review.

**Tech Stack:** Python 3.12, pytest/unittest, immutable contract dataclasses,
JSONL journals/ledgers, Figma Plugin API, Playwright/Chromium, existing
BridgeHub and FigmaBridgeAdapter.

**Spec:**

- `docs/v2_mentor/V2_OPTIMIZATION_PLAN.md`
- `docs/v2_mentor/ROUND_05_OPEN_ITEMS.md`
- `docs/v2_mentor/R5_PRODUCTION_BACKLOG.md`
- `docs/v2_mentor/R5_PRODUCTION_REASSESSMENT_2026-10-22.md`
- `docs/v2_mentor/RESIDUAL_RISKS.md`
- `docs/v2_mentor/P4_PRODUCTION_GAP_ASSESSMENT.md`
- `docs/v2_mentor/P4_LONG_SOAK_BACKLOG.md`

## Current Baseline

| Area | Current state | Meaning |
|---|---|---|
| Mentor decisions | D1-D44 adopted | Specification baseline, not 44 independent code tasks |
| R5 experiments | 6/6 `completed-for-current-scope` | Contract evidence exists for authored/deterministic scope |
| Checks | 118/118 pass | Experiment contracts are internally consistent |
| Negative mutations | 123/123 rejected | Fail-closed checks catch targeted contract violations |
| Verified | 0 project-level claims | No production-wide verification exists |
| Residual risks | RR-001-RR-015 tracked | Known uncertainties with mitigation/exit conditions |
| P0 | implemented current scope | Contracts exist but are not the default delivery path |
| P1 | diagnostics/canonical output current scope | Real production delivery and detector-backed gates remain |
| P2 | blocked | Real detector/coverage, PARTIAL report and release gate remain |
| P3 | current scope, production not admitted | Fencing, real concurrency, security operations and migration policy remain |
| P4 | blocked | Production storage, TTL, permissions, operations and long soak remain |
| P5 | blocked | Controlled end-to-end pilot not started |

## Gate Definitions

### P5 Pilot Gate

The P5 pilot may start only when:

- P0 contracts are available through an explicit `contract-v2` delivery profile;
- P1/P2 can explain unknown/conflict/PARTIAL outcomes and block unsafe export;
- P3 enforces one plugin writer and never retries unknown writes automatically;
- P4 has a bounded pilot store with retention, backup and cleanup rules;
- P5 scope, operator, thresholds, stop conditions and rollback runbook are frozen;
- a 1-hour staged rehearsal passes with no unexplained unknown transaction.

The P5 result can be `pilot-verified-for:<scope>` or
`pilot-allowed-provisional`. It is not production admission.

### Production Gate

Production admission may be considered only when:

- all P5 pilot exit criteria pass;
- authentication, certificate/token/secret lifecycle and ACL policy are
  operationally owned;
- single-writer/fencing and backup/restore behavior are verified;
- real permission, rate-limit, takeover, same-name and collaborator races are
  exercised;
- unknown/partial/rollback-incomplete outcomes have a manual review policy;
- production storage, TTL, purge, migration, monitoring and incident response
  are exercised;
- the staged 1h/24h/7d soak evidence is reviewed.

`verified` is a bounded evidence status produced by tasks below. Production
admission is the later policy decision that consumes those claims.

### Task-to-Gate Mapping

| Gate | Required tasks | Optional/deferred until later |
|---|---|---|
| P5 deterministic dry-run | 0, 1, 2, 3, 4, 5, pilot subset of 8, pilot subset of 9, 10 | Full permission/takeover matrix, production storage, 24h/7d |
| P5 limited pilot | Dry-run pass, frozen runbook, manual operator/reconciliation path, 11 | Full certificate/secret automation and cross-host scaling |
| Production evidence | 6, 7, production backend in 8, full operations in 9, results from 11, 12 | None for the declared production scope |
| Production admission | 13 plus all declared production claims | Claims explicitly excluded from the release scope |

Task order is a recommended implementation order, not a rule that every
production-hardening task must block a bounded P5 dry-run. However, any action
or failure mode excluded from Tasks 6-7 must also be excluded from the P5 action
scope.

## Global Constraints

- `current-scope` is not `verified`; `verified` is not production admission.
- P5 is a bounded pilot and may only produce `pilot-verified-for:<scope>` or
  `pilot-allowed-provisional`.
- The current default delivery path remains `legacy` until Task 1 explicitly
  enables `contract-v2`.
- The pilot target is the fixed Chromium canonical profile; broader browser
  equality is a separate claim.
- An unknown sent write must never be automatically replayed.
- Nonterminal/unknown ledger state must never be removed by retention.
- Exact cleanup requires matching owner and job markers.
- Do not start the local 24h/7d soak; execute it on the user cloud host.
- Preserve unrelated modified, deleted and untracked worktree files.
- Do not commit unless the user explicitly requests a commit.
- Every `verified-for` claim must name code revision, plugin build,
  environment, claim scope, thresholds and evidence hash.

## Review Focus

- A test can pass through the legacy delivery path and never exercise the new
  contracts.
- A PARTIAL result can be visually clean yet incorrectly allow export.
- Authored fixtures can hide real detector or state-gate failures.
- An unknown write can be retried after persistence or restart.
- Security, fencing and backup can be listed as present but absent from the
  actual dispatch path.
- A successful probe can be used to claim a wider `verified` scope than it
  tested.

---

### Task 0: Freeze Gate Matrix and Verification Vocabulary

**Files:**
- Create: `docs/v2_mentor/R5_GATE_MATRIX.md`
- Modify: `docs/v2_mentor/R5_PRODUCTION_BACKLOG.md`
- Modify: `docs/v2_mentor/R5_PRODUCTION_REASSESSMENT_2026-10-22.md`
- Test: `tests/v2/test_r5_gate_matrix.py`

**Interfaces:**
- Produces: status vocabulary `current-scope`, `pilot-verified`,
  `verified-for:<scope>`, `production-admitted`.
- Produces: one row per gate with `claim`, `environment`, `evidence`,
  `owner`, `blocking`, `status`.

- [ ] **Step 1: Write a failing gate-inventory test**

The test parses `R5_GATE_MATRIX.md` and asserts every P5/production blocker has
exactly one gate, status and evidence field. It also asserts that no row says a
project-wide `verified=true`.

- [ ] **Step 2: Run the test and verify failure**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_r5_gate_matrix.py -q
```

Expected: missing matrix file.

- [ ] **Step 3: Write the gate matrix**

Include separate `P5_GATE` and `PRODUCTION_GATE` rows. Mark conditional claims
such as Firefox, arbitrary variable-font axes and cross-host scaling as
`conditional`, not core pilot blockers.

- [ ] **Step 4: Verify**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_r5_gate_matrix.py -q
```

Expected: pass.

---

### Task 1: Put P0 Contracts on an Explicit Default-Path Profile

**Files:**
- Modify: `src/app/agents/precise_agent.py`
- Modify: `src/app/controllers/rendering_controller.py`
- Modify: `src/config/settings.py`
- Modify: `src/app/services/contracts/__init__.py`
- Create: `src/app/services/delivery/runtime_delivery.py`
- Test: `tests/v2/test_delivery_profile.py`
- Test: `tests/v2/test_precise_agent_contract_integration.py`

**Interfaces:**
- Produces: `DeliveryProfile = Literal["legacy", "contract-v2"]`.
- Produces: `build_runtime_delivery(capture_sidecar, design, acceptance) ->
  ContractDeliveryBundle`.
- Produces: `ContractDeliveryBundle.runtime_ir`, `audit_bundle`,
  `release_decision`, `trace_id`.
- Consumes: existing `RuntimeIR`, `AuditBundle`, `validate_runtime_ir`,
  `validate_audit_bundle`, `evaluate_release`.

- [ ] **Step 1: Write a failing equivalence test**

Run the same authored design through `legacy` and `contract-v2`. Assert the
rendered node/action output is byte-identical, while only `contract-v2` emits a
valid runtime IR and audit bundle.

- [ ] **Step 2: Write a failing fallback test**

When contract validation fails, assert `contract-v2` stops before adapter
dispatch and returns a contract error; `legacy` remains unchanged.

- [ ] **Step 3: Implement the opt-in profile**

Default remains `legacy` until P5 starts. `contract-v2` must be explicit in
configuration and recorded in the run manifest.

- [ ] **Step 4: Verify focused and full tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_delivery_profile.py tests/v2/test_precise_agent_contract_integration.py -q
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
```

Exit criterion: `verified-for: default-path contract bundle on authored
fixtures`.

---

### Task 2: Implement Field Authority Fusion and Conflict/Unknown Delivery

**Files:**
- Create: `src/app/services/delivery/field_resolution.py`
- Create: `src/app/services/delivery/conflicts.py`
- Modify: `src/app/services/contracts/authority.py`
- Modify: `src/app/services/evidence/adapter.py`
- Test: `tests/v2/test_field_resolution.py`
- Test: `tests/v2/test_conflict_delivery_real_fixture.py`
- Create: `scripts/p5_conflict_delivery_probe.py`
- Evidence: `output/_p5_conflict_delivery_round1/`

**Interfaces:**
- Produces: `resolve_fields(observations, profile) -> FieldResolution`.
- Produces: `build_conflict_report(resolution) -> ConflictReport`.
- Consumes: `text_decision_from_ocr`, `assert_field_authority`.

- [ ] **Step 1: Write failing conflict tests**

Cover text conflict, color unknown, visibility unknown, price
authority-required, tombstone and OCR candidate promotion. Assert unresolved
values never enter final node content.

- [ ] **Step 2: Write a failing report test**

Assert every conflict/unknown has field, both observations, authority gap,
current display behavior, blocked operations and next step.

- [ ] **Step 3: Implement resolution and report projection**

Keep `winner=null`, `deferred`, `skipped` and `authority-required` distinct.
Do not add decorative candidate text to the rendered body.

- [ ] **Step 4: Run the real authored probe and verify**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_conflict_delivery_probe.py --out output\_p5_conflict_delivery_round1
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_field_resolution.py tests/v2/test_conflict_delivery_real_fixture.py -q
```

Exit criterion: `verified-for: conflict/unknown delivery on fixed authored
Chromium profile`.

---

### Task 3: Close P1 Asset, Font and Text Acceptance

**Files:**
- Modify: `src/app/services/structure/asset_metadata.py`
- Modify: `src/app/services/structure/font_provenance.py`
- Modify: `src/app/services/rendering/text_wrap.py`
- Modify: `src/app/services/rendering/figma_acceptance.py`
- Modify: `tests/v2/test_p1_asset_metadata.py`
- Modify: `tests/v2/test_p1_font_provenance.py`
- Modify: `tests/v2/test_p1_figma_acceptance.py`
- Create: `scripts/p5_output_fidelity_matrix.py`
- Evidence: `output/_p5_output_fidelity_round1/`

**Interfaces:**
- Produces: `AssetIdentity(source_url, payload_sha256, natural_size,
  replacement_mode, status)`.
- Produces: `accept_output(bundle, profile) -> FourDimensionDecision`.
- Consumes: canonical Chromium profile, Figma readback and acceptance records.

- [ ] **Step 1: Write failing asset tests**

Assert remote URL alone is insufficient; replacement requires stable payload
hash/natural size; expired URLs use retained bytes or fail closed.

- [ ] **Step 2: Write failing font/text tests**

Assert missing fonts become `blocked-font/partial`, declared versus actual
faces remain separate, and text content/linebreak/box/baseline/glyph results
are reported independently.

- [ ] **Step 3: Implement the hard-gate matrix**

Keep visual, structure, editability and asset dimensions separate. A visual
pass cannot offset edit or asset failure.

- [ ] **Step 4: Run the fixed output matrix**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_output_fidelity_matrix.py --out output\_p5_output_fidelity_round1
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_p1_asset_metadata.py tests/v2/test_p1_font_provenance.py tests/v2/test_p1_figma_acceptance.py -q
```

Exit criterion: `verified-for: canonical output matrix on fixed Chromium and
plugin build`.

---

### Task 4: Implement Real PARTIAL Detection, Coverage and Release Gate

**Files:**
- Modify: `src/app/services/contracts/coverage.py`
- Modify: `src/app/services/contracts/acceptance.py`
- Create: `src/app/services/delivery/partial_report.py`
- Create: `src/app/services/delivery/release_gate.py`
- Create: `scripts/p5_partial_release_probe.py`
- Test: `tests/v2/test_partial_release_gate.py`
- Test: `tests/v2/test_p5_partial_release_probe.py`
- Evidence: `output/_p5_partial_release_round1/`

**Interfaces:**
- Produces: `build_partial_report(page_coverage, checks) -> PartialReport`.
- Produces: `release_decision(report, profile) -> ReleaseDecision`.
- Produces: `assert_export_allowed(decision)`.
- Consumes: real detector statuses; no caller-injected `pass` shortcuts.

- [ ] **Step 1: Write failing release tests**

Cover intentional omission, write failure, observed absence, not captured,
critical unknown, tiny price failure and high-area background pass.

- [ ] **Step 2: Write a failing export test**

Assert `partial` and `blocked` decisions cannot be converted to
`complete_export_allowed=true`; masks cannot shrink the contract denominator.

- [ ] **Step 3: Implement the report and gate**

Emit a user-visible PARTIAL report plus a machine manifest. Unknown and
not-captured remain distinct.

- [ ] **Step 4: Verify**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_partial_release_probe.py --out output\_p5_partial_release_round1
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_partial_release_gate.py tests/v2/test_p5_partial_release_probe.py -q
```

Exit criterion: `verified-for: detector-backed PARTIAL and release gate on
fixed pilot profile`.

---

### Task 5: Enforce Single-Writer/Fencing Before Any P5 Write

**Files:**
- Modify: `src/app/services/bridge_server.py`
- Modify: `src/app/services/bridge_config.py`
- Modify: `src/app/services/rendering/write_job_ledger.py`
- Modify: `figma_bridge.config.json`
- Create: `src/app/services/write_lease.py`
- Test: `tests/v2/test_write_lease.py`
- Test: `tests/v2/test_bridge_fencing.py`
- Create: `scripts/p5_single_writer_probe.py`
- Evidence: `output/_p5_single_writer_round1/`

**Interfaces:**
- Produces: `WriterLease(owner_id, generation, expires_at)`.
- Produces: `acquire_writer_lease()`, `assert_current_lease(token)`.
- Consumes: bridge journal, ledger path and plugin identity.

- [ ] **Step 1: Write failing lease tests**

Cover stale owner, expired lease, wrong generation, two local processes,
pause/resume, partition simulation and journal append failure.

- [ ] **Step 2: Write a failing dispatch test**

Assert no journal intent or plugin send occurs without the current lease.
Assert unknown outcomes still block automatic resend.

- [ ] **Step 3: Implement the least production-safe mode**

P5 may use a strict local single-host lease. Production mode must support a
monotonic generation token and explicit single-writer topology.

- [ ] **Step 4: Verify**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_single_writer_probe.py --out output\_p5_single_writer_round1
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_write_lease.py tests/v2/test_bridge_fencing.py -q
```

Exit criterion: `verified-for: single-writer fence on controlled Windows host`.

---

### Task 6: Close Real Permission, Rate-Limit, Takeover and Collaboration Races

**Files:**
- Modify: `src/app/services/bridge_server.py`
- Modify: `src/app/services/rendering/figma_adapter.py`
- Modify: `figma_bridge/code.js`
- Create: `scripts/p5_permission_takeover_probe.py`
- Create: `scripts/p5_collaboration_race_probe.py`
- Test: `tests/v2/test_p5_permission_takeover_probe.py`
- Test: `tests/v2/test_p5_collaboration_race_probe.py`
- Create: `docs/v2_mentor/P5_MANUAL_RECONCILIATION_POLICY.md`
- Create: `docs/v2_mentor/P5_DETERMINISTIC_FAULT_MATRIX.md`
- Evidence: `output/_p5_permission_takeover_round1/`
- Evidence: `output/_p5_collaboration_race_round1/`

**Interfaces:**
- Produces: `classify_permission_failure(error) -> PermissionOutcome`.
- Produces: `reconciliation_policy(transaction, readback, attribution) ->
  ManualReviewDecision`.

- [ ] **Step 1: Write failing permission/takeover tests**

Cover view-only document, denied write, Figma rate limit, revoked plugin token,
plugin takeover and user modification after send.

- [ ] **Step 2: Write failing two-collaborator tests**

Cover same target, same resulting state, conflicting state and concurrent
node deletion. Assert actor/revision remain `unavailable` unless an authoritative
source exists.

- [ ] **Step 3: Implement manual review and no-resend policy**

Do not infer commit attribution from matching current state. Preserve owned
node evidence and require explicit operator resolution.

- [ ] **Step 4: Verify**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_permission_takeover_probe.py --out output\_p5_permission_takeover_round1
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_collaboration_race_probe.py --out output\_p5_collaboration_race_round1
node --check figma_bridge\code.js
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_p5_permission_takeover_probe.py tests/v2/test_p5_collaboration_race_probe.py -q
```

Exit criterion: `verified-for: permission/takeover/conservative collaboration
reconciliation on the fixed pilot document`.

Deterministic audit 2026-10-23: Steps 1-3 are covered by the round-2
deterministic probes and JS harness, including partial-state reconciliation,
authoritative-attribution preservation, unknown no-resend and
`NODE_NOT_FOUND` classification. Step 4 remains pending because real accounts
and controlled collaborator timing are unavailable. This does not satisfy the
exit criterion.

---

### Task 7: Complete Expected-State and Region Compensation Coverage

**Files:**
- Modify: `src/app/services/bridge_server.py`
- Modify: `src/app/services/rendering/figma_adapter.py`
- Modify: `src/app/services/rendering/write_job_ledger.py`
- Modify: `figma_bridge/code.js`
- Test: `tests/v2/test_bridge_protocol.py`
- Test: `tests/v2/test_figma_adapter_edits.py`
- Create: `scripts/p5_region_compensation_probe.py`
- Update: `docs/v2_mentor/P5_DETERMINISTIC_FAULT_MATRIX.md`
- Evidence: `output/_p5_region_compensation_round1/`

**Interfaces:**
- Produces: expected checks for image fill hash, layout snapshot, node bounds,
  text runs and region membership.
- Produces: `CompensationScope(job_id, region_id, node_ids,
  user_takeover_state)`.

- [ ] **Step 1: Write failing expected-state tests**

Cover image replacement, Auto Layout propagation, partial region failure,
rollback overlap and cleanup after user takeover.

- [ ] **Step 2: Write a failing compensation test**

Assert compensation never removes nodes outside the job/owner, and incomplete
rollback remains `rollback-incomplete/manual-review`.

- [ ] **Step 3: Implement region-level checks and receipts**

Keep readback evidence separate from commit attribution.

- [ ] **Step 4: Verify**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_region_compensation_probe.py --out output\_p5_region_compensation_round1
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_bridge_protocol.py tests/v2/test_figma_adapter_edits.py -q
```

Exit criterion: `verified-for: expected-state and region compensation for
supported pilot actions`.

Deterministic audit 2026-10-23: image fill hashes now come from actual
`image_fill_report` bytes, layout aliases are normalized, `set_bounds` is an
executable edit action, region membership is read from plugin data, partial
regions are grouped, and compensation requires exact job/owner/region markers.
Round-2 evidence is `output/_p5_region_compensation_round2/result.json`.
Real takeover, upload interruption and concurrent deletion remain blocked, so
the exit criterion is not claimed.

---

### Task 8: Implement Pilot and Production Storage Boundaries

**Files:**
- Create: `docs/v2_mentor/P4_STORAGE_DECISION.md`
- Create: `src/app/services/persistence/__init__.py`
- Create: `src/app/services/persistence/store.py`
- Create: `src/app/services/persistence/local_pilot.py`
- Create: `tests/v2/test_persistence_contract.py`
- Create: `tests/v2/test_local_pilot_store.py`
- Modify: `src/app/services/evidence/retention.py`
- Modify: `src/app/services/contracts/models.py`

**Interfaces:**
- Produces: `DeliveryStore.put(bundle, idempotency_key)`,
  `get(trace_id)`, `list_expired(now)`, `purge(expired)`.
- Produces: `StorageProfile = Literal["local-pilot", "production"]`.
- Consumes: RuntimeIR, audit bundle, evidence hashes, access policy and
  retention policy.

- [ ] **Step 1: Write failing contract tests**

Cover write-before-render persistence, duplicate idempotency key, partial write,
TTL expiry, tombstone preservation, unknown enum rejection and audit/runtime
separation.

- [ ] **Step 2: Implement the local pilot backend**

Use an explicit local directory and atomic writes. This backend is only for P5;
it must report `production_eligible=false`.

- [ ] **Step 3: Freeze the production backend decision**

Choose database/object store, encryption, tenant isolation, access policy,
backup model and migration policy. Do not silently promote local files.

- [ ] **Step 4: Verify**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_persistence_contract.py tests/v2/test_local_pilot_store.py -q
```

P5 exit criterion: local pilot store verified for bounded single-host use.
Production exit criterion: selected production backend verified separately.

---

### Task 9: Prove Backup, Restore, Monitoring and Migration Operations

**Files:**
- Create: `scripts/p4_backup_restore_probe.py`
- Create: `scripts/p4_observability_probe.py`
- Create: `tests/v2/test_p4_backup_restore_probe.py`
- Create: `tests/v2/test_p4_observability_probe.py`
- Create: `docs/v2_mentor/P4_OPERATIONS_RUNBOOK.md`
- Evidence: `output/_p4_backup_restore_round1/`
- Evidence: `output/_p4_observability_round1/`

**Interfaces:**
- Produces: backup manifest, restore verification, migration report and
  dashboard metric contract.
- Metrics: pending/unknown transactions, 409 conflicts, write p50/p95/p99,
  journal/ledger size, compaction result, plugin reconnects, lease generation,
  storage errors and disclosure counts.

- [ ] **Step 1: Write failing restore tests**

Corrupt a copy, restore a known bundle, and assert hashes, tombstone, unknown,
evidence metadata and release decision survive.

- [ ] **Step 2: Write failing observability tests**

Assert every metric is emitted without raw text, secret or action payload.

- [ ] **Step 3: Implement the runbook and probes**

Include rollback, kill switch, stale-token recovery, stale-lease recovery,
manual unknown review and evidence collection.

- [ ] **Step 4: Verify**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p4_backup_restore_probe.py --out output\_p4_backup_restore_round1
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p4_observability_probe.py --out output\_p4_observability_round1
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_p4_backup_restore_probe.py tests/v2/test_p4_observability_probe.py -q
```

Exit criterion: `verified-for: backup/restore and metric contract on the
selected storage profile`.

---

### Task 10: Run the P5 Dry Run on a Frozen Profile

**Files:**
- Create: `docs/v2_mentor/P5_PILOT_RUNBOOK.md`
- Create: `scripts/p5_dry_run.py`
- Create: `scripts/p5_evidence_audit.py`
- Create: `tests/v2/test_p5_dry_run_contract.py`
- Create: `tests/v2/test_p5_evidence_audit.py`
- Evidence: `output/_p5_dry_run_round1/`

**Interfaces:**
- Produces: frozen run manifest with code revision, plugin build, Chromium
  build, Figma document, root nodes, allowed actions, thresholds and operator.
- Consumes: Tasks 1-5, the local-pilot backend from Task 8 and the pilot-level
  backup/monitoring checks from Task 9.
- Does not consume: production backend, full takeover matrix or 24h/7d claims.

- [ ] **Step 1: Freeze the run manifest and abort thresholds**

Include maximum writes, maximum unknowns, allowed PARTIAL cases, cleanup
deadline, manual review owner and rollback triggers.

- [ ] **Step 2: Run the deterministic dry run first**

Assert `legacy` remains the default outside the P5 command and
`contract-v2` is explicit in evidence.

- [ ] **Step 3: Run the 1-hour staged rehearsal**

Use four writers, no client sleep, reconnect every 100 transactions and a
dedicated journal/ledger. Include one deliberate reconnect and controlled
timeout.

- [ ] **Step 4: Verify acceptance**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_dry_run.py --out output\_p5_dry_run_round1
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_evidence_audit.py `
  --report <figma_bridge_soak.json> `
  --inputs output\_p5_pilot_inputs\inputs.json `
  --max-journal-events 4096 `
  --out <evidence_audit.json>
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_p5_dry_run_contract.py -q
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_p5_evidence_audit.py -q
```

Pass requires:

- all requests completed or explicitly classified;
- no unexplained unknown;
- no automatic resend;
- bounded journal/ledger;
- stable RSS/handles trend;
- exact cleanup;
- reproducible evidence hashes.

Exit criterion: `pilot-verified-for: P5 dry-run profile`.

---

### Task 11: Execute the Bounded P5 Pilot

**Files:**
- Use: `docs/v2_mentor/P5_PILOT_RUNBOOK.md`
- Use: `scripts/p5_dry_run.py`
- Create: `scripts/p5_pilot.py`
- Create: `tests/v2/test_p5_pilot_contract.py`
- Evidence: `output/_p5_pilot_round1/`

**Interfaces:**
- Consumes: frozen P5 dry-run profile.
- Produces: per-page decision `pilot-allowed-provisional`, `blocked` or
  `manual-review`.
- Produces: user-visible PARTIAL/unknown report and machine manifest.

- [ ] **Step 1: Write the failing pilot contract test**

Assert no page can pass if it contains critical unknown, unauthorized action,
unexplained unknown transaction or missing evidence.

- [ ] **Step 2: Run the pilot on the frozen sample registry**

Keep the same profile and thresholds. Do not remove failed samples from the
denominator.

- [ ] **Step 3: Reconcile every unknown manually**

Record current state, ownership evidence, actor attribution status, operator
decision and no-resend justification.

- [ ] **Step 4: Verify release**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_pilot.py --out output\_p5_pilot_round1
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_p5_pilot_contract.py -q
```

Exit criterion: `pilot-verified-for: fixed pilot registry`. This is still not
production admission.

---

### Task 12: Execute Production Verification and Staged Long Soak

**Files:**
- Use: `docs/v2_mentor/P4_LONG_SOAK_BACKLOG.md`
- Create: `docs/v2_mentor/PRODUCTION_VERIFICATION_MATRIX.md`
- Create: `tests/v2/test_production_verification_matrix.py`
- Evidence: `output/_p4_cloud_soak_1h/<run-id>/`
- Evidence: `output/_p4_cloud_soak_24h/<run-id>/`
- Evidence: `output/_p4_cloud_soak_7d/<run-id>/`

**Interfaces:**
- Produces: one `verified-for` claim per dimension/environment/claim.
- Produces: soak stage result with failures and residual unknowns.

- [ ] **Step 1: Write the failing matrix test**

Assert every production claim is bound to code revision, plugin build,
environment, test set, thresholds and evidence hash.

- [ ] **Step 2: Run 1h, then 24h, then 7d on the cloud host**

Do not jump stages. Do not start locally. Record plugin renderer memory if
instrumentation exists; otherwise state it as unmeasured.

- [ ] **Step 3: Review failures without changing thresholds post hoc**

Classify every failure as reproduced, explained, accepted risk or blocker.

- [ ] **Step 4: Verify evidence**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_production_verification_matrix.py -q
```

Exit criterion: bounded production claims have reproducible evidence; no
global `verified=true` is inferred.

---

### Task 13: Hold the Production Admission Review

**Files:**
- Create: `docs/v2_mentor/R5_PRODUCTION_ADMISSION_DECISION.md`
- Modify: `docs/v2_mentor/R5_PRODUCTION_REASSESSMENT_2026-10-22.md`
- Modify: `docs/v2_mentor/RESIDUAL_RISKS.md`
- Modify: `README.md`
- Test: `tests/v2/test_production_admission_decision.py`

**Interfaces:**
- Consumes: P5 evidence, production claims, residual risks, incident runbook
  and risk acceptance.
- Produces: `admitted`, `admitted-with-conditions` or `not-admitted`.

- [ ] **Step 1: Write the failing decision test**

Reject `admitted` if any blocking risk lacks an owner, mitigation, evidence,
rollback or expiry date.

- [ ] **Step 2: Review all 15 residual risks**

Mark each as resolved, accepted-with-owner, conditional or blocking.

- [ ] **Step 3: Review production prerequisites**

Include identity/secret lifecycle, permissions, fencing, backup/restore,
monitoring, incident response and long-soak evidence.

- [ ] **Step 4: Decide release scope**

Admission must name supported environments, actions, document scopes and
exclusions. Do not convert a bounded admission into a project-wide safety claim.

- [ ] **Step 5: Final verification**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
node --check figma_bridge\code.js
```

Expected: all tests pass, evidence hashes are retained and no unresolved
critical blocker is silently accepted.

---

## Dependency Order

```text
Task 0
  -> Task 1
       -> Task 2 -> Task 3 -> Task 4
  -> Task 5
  -> Task 8 local-pilot backend
  -> Task 9 pilot backup/monitoring subset
  -> Task 10 P5 dry-run
  -> Task 11 P5 limited pilot

Production closure:
  Task 6 permission/takeover/collaboration
  Task 7 expected-state/region compensation
  Task 8 production backend
  Task 9 full operations/runbook
  -> Task 12 production verification + long soak
  -> Task 13 production admission review
```

Tasks 2-4, Task 5 and the pilot subset of Tasks 8-9 may be developed in
parallel after Task 0. Production-hardening Tasks 6-7 and full Task 9 may run
after the dry-run, but they cannot alter the frozen dry-run profile; a change
requires a new profile and a new run.

## Conditional Work

These do not block the fixed Chromium P5 pilot unless the product claim changes:

- Firefox parity;
- arbitrary variable-font axis precision;
- per-glyph fallback reconstruction;
- cross-browser DOM equivalence;
- general adaptive Auto Layout equivalence;
- multi-tenant/cross-host scaling beyond the admitted topology.

They remain production or claim-scope work when the corresponding promise is
made.

## Definition of Done

- P5 pilot is `pilot-verified-for` its frozen environment and registry.
- Production claims are bounded, reproducible and backed by evidence.
- Unknown writes never auto-resend.
- PARTIAL, unknown and rollback-incomplete remain visible.
- Exact job cleanup is verified.
- Backup/restore and incident response are exercised.
- No project-wide `verified=true` is claimed without evidence covering that
  full scope.
- No commit is made without explicit user approval.
