# R5-P3 Write Ledger and Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the existing BridgeHub transaction journal and Figma ownership markers to a durable business job ledger that can classify, reconcile, and compensate R5 write jobs without blind replay.

**Architecture:** Treat BridgeHub's JSONL journal as the authoritative protocol idempotency store and add a separate business-level job ledger that references bridge transaction ids rather than duplicating protocol payloads. Owned create batches carry a globally unique job id, auto-read their ownership markers after unknown outcomes, and expose a conservative resume decision for an operator or higher-level workflow.

**Tech Stack:** Python 3.12 standard library, `unittest`/`pytest`, JSONL with `fsync`, existing `BridgeHub`, `FigmaBridgeAdapter`, Figma Plugin API plugin data.

**Spec:** `docs/v2_mentor/R5_PRODUCTION_REASSESSMENT_2026-10-22.md`, `docs/v2_mentor/R5_PRODUCTION_BACKLOG.md`, and `docs/v2_mentor/P4_WRITE_BACKPRESSURE.md`.

**Current Status:** `completed-for-current-scope` on 2026-10-22. The
client-scoped ownership namespace slice is implemented and deterministically
verified. Per-client token binding for the claimed `clientId` is implemented
when configured. Bridge server/default-client settings are file-backed in
`figma_bridge.config.json`. TLS transport and `/plugin` token handshake are
implemented current scope. Secret references, config ACL policy and atomic
rotation are implemented current scope. Production admission remains open for
automated certificate lifecycle, multiplayer attribution,
permission/rate-limit/user-takeover exercise, and R5-P4 storage policy. Ledger
retention, atomic terminal-history compaction, and explicit legacy
business-ledger migration are implemented current scope.

## Global Constraints

- `completed-for-current-scope` is not `verified` and is not production admission.
- An unknown sent write must never be automatically replayed.
- Ownership readback never promotes a bridge transaction to `committed`.
- `cleanup_owned_job` may remove only nodes whose owner and job id both match.
- Owned jobs use `r5job:v1:<base64url-client>:<base64url-raw>`; different
  `clientId` values must not produce the same plugin-visible job id.
- Bare ownership job ids fail closed by default. Legacy bridge, adapter, and
  ledger readers require an explicit `allow_legacy_job_ids` opt-in.
- Per-client tokens are authorization material and must never be written to
  command params, reports, or the bridge journal.
- Normal bridge startup reads `figma_bridge.config.json`; environment variables
  are ignored unless the file explicitly enables `allow_env_overrides`.
- BridgeHub remains the protocol idempotency authority; the business ledger stores references and decisions, not duplicate request payloads.
- Figma renderer memory and 24h/7d soak remain outside this plan and are deferred to the user's cloud server.
- Do not commit unless the user explicitly requests a commit.
- Do not revert unrelated modified, deleted, or untracked files already present in the worktree.

## Review Focus

- A timed-out create batch with complete markers must reconcile without resending.
- A timed-out create batch with partial or missing markers must require human reconciliation.
- A duplicate business job id with different content must fail closed.
- A torn final JSONL line must not destroy earlier ledger records.
- Cleanup must not remove same-name nodes, other-owner nodes, or nodes from another job.

---

### Task 1: Validate Marker Persistence Across Plugin Reload

**Files:**
- Use: `scripts/figma_ownership_marker_probe.py`
- Evidence: `output/_r5_ownership_marker_reload_round1/`
- Modify: `docs/v2_mentor/R5_PRODUCTION_REASSESSMENT_2026-10-22.md`
- Modify: `docs/v2_mentor/RESIDUAL_RISKS.md`

**Interfaces:**
- Consumes: `FigmaBridgeAdapter.ownership_report(job_id) -> dict`
- Consumes: `FigmaBridgeAdapter.cleanup_owned_job(job_id) -> dict`
- Produces: real evidence that plugin-data markers survive reload/reopen

- [x] **Step 1: Create retained owned nodes**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe `
  scripts\figma_ownership_marker_probe.py `
  --out output\_r5_ownership_marker_reload_round1 `
  --phase create `
  --job-id r5-ownership-reload-20261022
```

Expected: `status=pass`, `ownership.marker=plugin-data-v1`, `ownership.marked=2`.

- [x] **Step 2: Reload the Figma development plugin**

Keep the Figma document open and restart the development plugin from the Figma UI.

Expected: the bridge logs a new plugin connection and no write is sent during reload.

- [x] **Step 3: Verify markers after plugin reload**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe `
  scripts\figma_ownership_marker_probe.py `
  --out output\_r5_ownership_marker_reload_round1 `
  --phase verify `
  --job-id r5-ownership-reload-20261022
```

Expected: `status=pass`, two expected node ids are present, and marker owner/job fields match.

- [x] **Step 4: Clean up the owned job**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe `
  scripts\figma_ownership_marker_probe.py `
  --out output\_r5_ownership_marker_reload_round1 `
  --phase cleanup `
  --job-id r5-ownership-reload-20261022
```

Expected: `matched=2`, `removed=2`, `failed=0`, post-cleanup `matched=0`.

- [x] **Step 5: Record the persistence result**

Update the reassessment and residual risk with the exact report hashes. Do not mark multiplayer ownership or production admission complete.

- [x] **Step 6: Re-run Python and bridge tests**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
```

Expected: all tests pass.

**Completed persistence evidence (2026-10-22):**

- `output/_r5_ownership_marker_reload_round1/`: development-plugin reload,
  marker `2/2`, cleanup `2/2`;
- `output/_r5_ownership_marker_document_reopen_round1/`: document close/reopen,
  marker `2/2`, cleanup `2/2`, post-cleanup `0`.

---

### Task 2: Define the Business Write-Job Ledger Contract

**Files:**
- Create: `src/app/services/rendering/write_job_ledger.py`
- Create: `tests/v2/test_write_job_ledger.py`
- Modify: `src/app/services/rendering/__init__.py`

**Interfaces:**
- Produces: `WriteJobState` enum with `planned`, `inflight`, `committed`, `rejected`, `rolled-back`, `rollback-incomplete`, `unknown`, `resume-required`
- Produces: `ResumeAction` enum with `none`, `safe-retry`, `reconcile-no-resend`, `cleanup-only`, `manual-review`
- Produces: `WriteJobRecord.to_dict() -> dict[str, Any]`
- Produces: `ResumeDecision.to_dict() -> dict[str, Any]`
- Produces: `plan_resume(record: WriteJobRecord, ownership: dict | None) -> ResumeDecision`

- [x] **Step 1: Write failing state-transition tests**

Add tests covering:

```python
def test_unknown_complete_ownership_reconciles_without_resend(): ...
def test_unknown_partial_ownership_requires_manual_review(): ...
def test_unknown_absent_ownership_requires_manual_review(): ...
def test_planned_job_is_safe_to_retry(): ...
```

Assertions:

- complete unknown: `action=reconcile-no-resend`, `resend_allowed=False`
- partial/absent unknown: `action=manual-review`, `resend_allowed=False`
- planned: `action=safe-retry`, `resend_allowed=True`
- rollback-incomplete: `action=manual-review`

- [x] **Step 2: Run tests to verify failure**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe `
  -m pytest tests/v2/test_write_job_ledger.py -q
```

Expected: import or symbol failure.

- [x] **Step 3: Implement immutable models and `plan_resume`**

Use `dataclass(frozen=True, slots=True)` and deterministic `to_dict()` through the existing contract JSON projection or a local equivalent. Do not read files or call Figma in this step.

- [x] **Step 4: Run the focused test**

Expected: all ledger contract tests pass.

- [x] **Step 5: Run full tests**

Expected: no regression in `tests/v2`.

---

### Task 3: Add Atomic JSONL Job Persistence and Recovery

**Files:**
- Modify: `src/app/services/rendering/write_job_ledger.py`
- Modify: `tests/v2/test_write_job_ledger.py`

**Interfaces:**
- Produces: `WriteJobLedger(path: str | Path)`
- Produces: `begin_job(job_id, transaction_id, client_id, request_id, expected_created_nodes, fingerprint) -> WriteJobRecord`
- Produces: `mark_inflight(job_id) -> WriteJobRecord`
- Produces: `record_bridge_outcome(job_id, bridge_state, response=None) -> WriteJobRecord`
- Produces: `record_ownership(job_id, ownership_readback, classification) -> WriteJobRecord`
- Produces: `load(job_id) -> WriteJobRecord | None`

- [x] **Step 1: Write failing persistence tests**

Tests must cover:

- begin, inflight, terminal state survive a new ledger instance;
- duplicate job id with identical fingerprint replays the record;
- duplicate job id with another fingerprint raises `ValueError`;
- malformed trailing JSONL is ignored while earlier records load;
- every append is flushed and `fsync`ed.

- [x] **Step 2: Run tests to verify failure**

Expected: constructor or method missing.

- [x] **Step 3: Implement append-only event records**

Each event contains schema version, job id, transaction id, client/request ids,
state, fingerprint, expected count, reference hashes, timestamp, and reason.
Do not store action params, raw text, image bytes, or secrets.

- [x] **Step 4: Implement deterministic snapshot reconstruction**

Use last valid event per job id. Unknown event versions and invalid records are ignored with a warning; OSError while appending fails closed.

- [x] **Step 5: Run focused and full tests**

Expected: all pass.

---

### Task 4: Integrate Write-Ahead Job Creation with Owned Batches

**Files:**
- Modify: `src/app/services/rendering/write_job_ledger.py`
- Modify: `src/app/services/rendering/figma_adapter.py`
- Modify: `tests/v2/test_write_job_ledger.py`
- Modify: `tests/v2/test_figma_adapter_edits.py`

**Interfaces:**
- Produces: `OwnedBatchCoordinator(adapter: FigmaBridgeAdapter, ledger: WriteJobLedger)`
- Produces: `create_owned_batch(job_id, actions, request_id=None) -> WriteJobRecord`
- Consumes: `adapter.apply_batch(actions, transaction_id=job_id)`
- Consumes: `adapter.transaction_status(job_id)`

- [x] **Step 1: Write a failing fake-adapter test**

Assert the order:

```text
ledger planned -> adapter apply_batch -> ledger inflight/committed
```

Also assert that no adapter send occurs when ledger append fails.

- [x] **Step 2: Run the failing test**

Expected: coordinator missing.

- [x] **Step 3: Implement the coordinator**

Compute a canonical SHA-256 over the action list and job id. Append `planned`
before dispatch. Mark `inflight` immediately before calling the adapter. Map
bridge terminal states into ledger states without inventing success.

- [x] **Step 4: Test exception and timeout paths**

Expected:

- known committed response becomes `committed`;
- rejected/rolled-back responses preserve state;
- adapter exception without a bridge response becomes `unknown`;
- no second send occurs during state recording.

- [x] **Step 5: Run focused and full tests**

---

### Task 5: Integrate Unknown Resume with Ownership Readback

**Files:**
- Modify: `src/app/services/rendering/write_job_ledger.py`
- Modify: `tests/v2/test_write_job_ledger.py`
- Modify: `tests/v2/test_bridge_protocol.py`

**Interfaces:**
- Produces: `resume_job(ledger_id: str) -> ResumeDecision`
- Consumes: bridge transaction payload from `bridge_transaction_status`
- Consumes: `ownershipReadback` and `ownershipReconciliation`

- [x] **Step 1: Write failing resume tests**

Use saved bridge transaction payloads for:

- unknown + complete ownership;
- unknown + partial ownership;
- unknown + absent ownership;
- rollback-incomplete;
- committed/rejected/rolled-back.

- [x] **Step 2: Run tests to verify failure**

Expected: resume method missing.

- [x] **Step 3: Implement conservative resume**

Rules:

- never resend unknown;
- complete ownership may produce `reconcile-no-resend`;
- missing/partial ownership requires manual review;
- committed/rejected/rolled-back produces `none`;
- planned produces `safe-retry`;
- rollback-incomplete produces `manual-review`.

- [x] **Step 4: Persist resume decisions**

Append a `resume-decision` event with action, reason, bridge state, ownership
classification, and timestamp. Keep the bridge transaction state unchanged.

- [x] **Step 5: Run focused and full tests**

---

### Task 6: Add Job-Scoped Compensation Records

**Files:**
- Modify: `src/app/services/rendering/write_job_ledger.py`
- Modify: `tests/v2/test_write_job_ledger.py`
- Use: `scripts/figma_ownership_marker_probe.py`

**Interfaces:**
- Produces: `plan_cleanup(job_id) -> dict`
- Produces: `record_cleanup(job_id, cleanup_result) -> WriteJobRecord`
- Consumes: `adapter.cleanup_owned_job(job_id)`

- [x] **Step 1: Write failing tests**

Assert:

- cleanup is allowed only for the exact job id;
- cleanup result matched/removed counts are persisted;
- failed cleanup leaves state `manual-review`;
- a different job's markers are never included.

- [x] **Step 2: Implement and test deterministic compensation**

Do not treat broad `remove_nodes_by_name` as ownership-based compensation.

- [x] **Step 3: Run focused and full tests**

---

### Task 7: Deterministic End-to-End R5-P3 Failure Injection

**Files:**
- Create: `scripts/r5_p3_resume_soak.py`
- Create: `tests/v2/test_r5_p3_resume_soak.py`
- Evidence: `output/_r5_p3_resume_round1/`

- [x] **Step 1: Build a deterministic fake plugin scenario**

Inject:

- successful create;
- timeout after send;
- restart/readback with complete markers;
- partial marker loss;
- cleanup success/failure;
- duplicate job id conflict.

- [x] **Step 2: Assert no blind resend**

Count plugin writes and require zero duplicate side effects for every unknown
or unclassified case.

- [x] **Step 3: Run the soak and retain a content-hashed report**

Report:

- jobs completed;
- unknowns reconciled without resend;
- manual-review cases;
- duplicate side effects;
- ledger restart recovery;
- cleanup outcomes.

- [x] **Step 4: Run full tests**

---

### Task 8: Real Figma R5-P3 Resume Probe

**Files:**
- Create: `scripts/figma_r5_p3_resume_probe.py`
- Evidence: `output/_r5_p3_real_resume_round1/`

**Interfaces:**
- Consumes: `OwnedBatchCoordinator`
- Consumes: bridge transaction status
- Consumes: ownership report/cleanup

- [x] **Step 1: Create an owned job and retain it**

Use a unique `job_id`; write ledger intent before plugin dispatch.

- [x] **Step 2: Inject a controlled client timeout without duplicating the plugin send**

An unknown response is required. Do not fake it as committed.

- [x] **Step 3: Restart/readback**

Verify marker state and persist the resume decision with no resend.

- [x] **Step 4: Clean up only the owned job**

Require post-cleanup marker count zero.

- [x] **Step 5: Record evidence and update residual risks**

Do not promote to production admission.

---

### Task 9: Production Gap Review

**Files:**
- Modify: `docs/v2_mentor/R5_PRODUCTION_BACKLOG.md`
- Modify: `docs/v2_mentor/RESIDUAL_RISKS.md`
- Modify: `docs/v2_mentor/R5_PRODUCTION_REASSESSMENT_2026-10-22.md`

**Interfaces:**
- Consumes: all previous task evidence
- Produces: explicit P3 admission decision

- [x] **Step 1: Review remaining blockers**

Review:

- global job namespace;
- multiplayer attribution;
- permission/rate-limit/user takeover;
- storage policy;
- job ledger retention and compaction.

- [x] **Step 2: Decide one of**

```text
current-scope-complete
partially-unblocked
blocked
```

Do not choose `verified` without independent external evidence.

- [x] **Step 3: Update docs and run final full tests**

Expected: all tests pass and unresolved risks remain visible.

**Task 8-9 completion evidence (2026-10-22):**

- real controlled timeout produced exactly one unknown transaction;
- normal bridge restart read ownership markers `1/1`;
- resume decision was `reconcile-no-resend`;
- journal contained exactly one `apply_batch` intent;
- duplicate side effects were zero;
- exact cleanup removed `1/1`;
- report: `output/_r5_p3_real_resume_round4/figma_r5_p3_resume.json`;
- final decision: `completed-for-current-scope`, not production admission.

### Task 10: Global Ownership Job Namespace and Conflict Protection

**Files:**
- Create: `src/app/services/job_namespace.py`
- Create: `tests/v2/test_job_namespace.py`
- Modify: `src/app/services/bridge_server.py`
- Modify: `src/app/services/rendering/figma_adapter.py`
- Modify: `src/app/services/rendering/write_job_ledger.py`
- Modify: `tests/v2/test_bridge_protocol.py`
- Modify: `tests/v2/test_write_job_ledger.py`
- Modify: `tests/v2/test_figma_adapter_edits.py`
- Modify: `scripts/r5_p3_resume_soak.py`
- Modify: `scripts/figma_r5_p3_resume_probe.py`
- Modify: `scripts/figma_ownership_marker_probe.py`
- Evidence: `output/_r5_p3_namespace_round1/`

**Interfaces:**
- Produces: `build_job_namespace(client_id, raw_job_id) -> str`
- Produces: `parse_job_namespace(job_id) -> ParsedJobNamespace`
- Produces: `validate_job_namespace(job_id, client_id=...)`
- Produces: `migrate_legacy_job_id(job_id, client_id=...)`

**Namespace contract:**

```text
r5job:v1:<base64url(canonical-clientId)>:<base64url(canonical-rawJobId)>
```

- The version, client bytes, and raw id bytes are decoded from canonical
  unpadded base64url.
- `clientId` and raw id are trimmed and limited to 128 and 256 characters.
- Parsing rejects wrong versions, padding, empty segments, and non-canonical
  encodings.

**Conflict and migration rules:**

1. `OwnedBatchCoordinator` always compiles a raw id into a client-scoped id
   before ledger append and plugin dispatch.
2. `WriteJobLedger` schema v2 records raw id and namespace version; v1 events
   remain readable.
3. Adapter and BridgeHub default to rejecting bare ownership ids.
4. Explicit legacy compatibility is available only through
   `allow_legacy_job_ids=True` and is intended for pre-namespace continuation,
   not new writes.
   The standalone bridge reads this from `server.allow_legacy_job_ids` in
   `figma_bridge.config.json`.
5. BridgeHub keeps `(clientId, requestId)` idempotency behavior and uses the
   canonical id as the global transaction key.
6. Max-length canonical ids use a stable SHA-256-derived bridge request id
   when they exceed the 256-character request-id limit.
7. Reusing an existing canonical transaction with a different request id
   returns `TRANSACTION_ID_CONFLICT` before plugin dispatch.

- [x] **Step 1: Write deterministic namespace and conflict tests**
- [x] **Step 2: Verify legacy ids fail before adapter or bridge dispatch**
- [x] **Step 3: Implement canonical encoding, schema v2, and explicit legacy opt-in**
- [x] **Step 4: Isolate same raw id across two clients in create, resume,
  cleanup, and journal replay**
- [x] **Step 5: Update reproducible probes and retain deterministic evidence**
- [x] **Step 6: Run full Python and bridge verification**

**Task 10 completion evidence (2026-10-22):**

- format/round-trip/client-mismatch/legacy tests pass;
- create, ledger, resume, cleanup, and journal replay use canonical ids;
- two clients using raw id `shared-raw` produced two distinct jobs, two
  bounded writes, and zero duplicate side effects;
- report:
  `output/_r5_p3_namespace_round1/r5_p3_resume_soak.json`;
- report content hash:
  `813428fe2c380a104650c1d1ab67d8951adcbb3b8a8cbe1d7ec8ca516a0f190e`;
- full Python suite: `367 passed`;
- bridge Node scripts: `15/15 passed`.

This slice closes accidental cross-client raw-id collisions when client
identities are distinct. Task 10 alone does not authenticate `clientId`;
Task 11 adds the configurable token-binding layer.

### Task 11: Authenticated Client Identity for Ownership Namespace

**Files:**
- Modify: `src/app/services/bridge_server.py`
- Modify: `src/app/services/rendering/figma_adapter.py`
- Modify: `tests/v2/test_bridge_protocol.py`
- Modify: `tests/v2/test_figma_adapter_edits.py`
- Create: `scripts/r5_p3_client_identity_probe.py`
- Create: `tests/v2/test_r5_p3_client_identity_probe.py`
- Evidence: `output/_r5_p3_client_identity_round1/`

**Configuration:**

```text
figma_bridge.config.json
  server.client_tokens = {"client-a":"<secret-a>","client-b":"<secret-b>"}
  client.client_id = client-a
  client.client_token = <matching-secret>
```

`FigmaBridgeAdapter` reads the `client` section by default and accepts explicit
`client_id` / `client_token` overrides. When a client token is configured, a
non-empty client id is required.

**Protocol headers:**

```text
X-Figma-Client-Id: <clientId>
X-Figma-Client-Token: <per-client-secret>
```

**Rules:**

1. The shared optional Bearer token remains supported independently.
2. If no per-client token mapping is configured, current anonymous local
   development behavior remains unchanged.
3. If a mapping is configured, every `/command` request requires matching
   identity headers before cache, namespace, write admission, or plugin use.
4. Missing headers -> `CLIENT_IDENTITY_REQUIRED`.
5. Header/payload `clientId` mismatch -> `CLIENT_IDENTITY_MISMATCH`.
6. Wrong token or unconfigured client -> `CLIENT_IDENTITY_INVALID`.
7. Token comparison uses `hmac.compare_digest`.
8. Tokens are not persisted in the bridge journal.

- [x] **Step 1: Write failing token-configuration and identity-boundary tests**
- [x] **Step 2: Add adapter identity headers and explicit client-id validation**
- [x] **Step 3: Add BridgeHub per-client token verification before dispatch**
- [x] **Step 4: Prove missing/wrong/mismatch/valid outcomes deterministically**
- [x] **Step 5: Prove secret absence from journal and retained report**
- [x] **Step 6: Run full Python and bridge verification**

**Task 11 completion evidence (2026-10-22):**

```text
status: pass
missing: CLIENT_IDENTITY_REQUIRED
wrong: CLIENT_IDENTITY_INVALID
mismatch: CLIENT_IDENTITY_MISMATCH
valid: true
journal secret absent: true
report content hash: 3289725b55042212dc6c9756db4cda06b6727e8155cc8ceffd337452ba3008e0
file SHA-256: 2cc9c8dc7dc7ceb5f248a556c961597cc0f1044be5bccaae5e7c1146f1ad5230
full Python suite: 376 passed
bridge Node scripts: 15/15 passed
```

Evidence:

- `output/_r5_p3_client_identity_round1/r5_p3_client_identity.json`

This binds a configured namespace identity to a server-known token. It does
not authenticate in the default anonymous mode, encrypt transport, authenticate
`/plugin`, or define production token rotation.

### Task 12: Central File-backed Bridge Configuration

**Files:**
- Create: `src/app/services/bridge_config.py`
- Create: `figma_bridge.config.json`
- Create: `tests/v2/test_bridge_config.py`
- Modify: `src/app/services/bridge_server.py`
- Modify: `src/app/services/rendering/figma_adapter.py`
- Modify: `src/config/settings.py`
- Modify: `scripts/figma_r5_p3_resume_probe.py`

**Goal:**

Normal bridge startup and the default Python client configuration must come
from one file, not from a long environment-variable startup command.

**Rules:**

1. `figma_bridge.config.json` contains server and default-client settings.
2. Config schema is `figma-bridge-config/1.0`.
3. Unknown fields, invalid types, empty tokens, invalid ports, and malformed
   paths fail startup closed.
4. Relative `journal_path` resolves against the config file directory.
5. Environment overrides are ignored by default.
6. `allow_env_overrides: true` is the explicit compatibility escape hatch.
7. `FIGMA_BRIDGE_CONFIG` may select another file, but normal startup needs no
   environment variables.
8. Real probe subprocesses generate sanitized per-run config files instead of
   relying on bridge environment variables.

- [x] **Step 1: Write failing schema, invalid-value, and path-resolution tests**
- [x] **Step 2: Implement immutable file-backed config dataclasses**
- [x] **Step 3: Construct BridgeHub from the `server` section**
- [x] **Step 4: Make FigmaBridgeAdapter consume the `client` section**
- [x] **Step 5: Make application default bridge URL file-backed**
- [x] **Step 6: Convert controlled-timeout subprocesses to sanitized config files**
- [x] **Step 7: Run full Python and bridge verification**

**Actual config contents:**

- listen host/port;
- command timeout and idempotency TTL;
- journal path, bounds, lock, and compaction threshold;
- shared Bearer token and per-client tokens;
- legacy ownership job opt-in;
- write pacing;
- default client URL, timeout, identity, auth, and legacy setting.

**Task 12 completion evidence (2026-10-22):**

- default config loads without bridge environment variables;
- adapter headers/URL come from the `client` section;
- server hub timeout/journal/tokens/pacing come from the `server` section;
- environment overrides require `allow_env_overrides: true`;
- full Python suite: `384 passed`.

### Task 13: Per-client Admission and Fair Write Dispatch

**Files:**
- Modify: `src/app/services/bridge_config.py`
- Modify: `src/app/services/bridge_server.py`
- Modify: `figma_bridge.config.json`
- Modify: `tests/v2/test_bridge_config.py`
- Modify: `tests/v2/test_bridge_protocol.py`
- Create: `scripts/r5_p3_client_fairness_probe.py`
- Create: `tests/v2/test_r5_p3_client_fairness_probe.py`
- Evidence: `output/_r5_p3_client_fairness_round1/`

**Goal:** prevent one authenticated client from monopolizing the global write
queue while preserving the single-plugin-writer and idempotency contracts.

**Contract:**

1. Per-client defaults and overrides live in the config file.
2. `max_inflight` caps admitted writes for one verified `clientId`.
3. Token bucket settings are `burst` and `min_interval_ms`.
4. Global write pacing still applies to every actual plugin dispatch.
5. A rate-limited request returns
   `BRIDGE_CLIENT_RATE_LIMITED/not-applied` with `retryAfterMs`.
6. Per-client rejection occurs before journal intent and plugin send.
7. A throttled client waits without holding the global dispatch lock.
8. Existing behavior is unchanged when the default cap equals the global queue
   and rate limiting is disabled.

**Config:**

```json
{
  "server": {
    "client_write_defaults": {
      "max_inflight": 4,
      "burst": 4,
      "min_interval_ms": 0
    },
    "client_write_limits": {
      "client-a": {
        "max_inflight": 2,
        "burst": 2,
        "min_interval_ms": 50
      }
    }
  }
}
```

- [x] **Step 1: Add failing config, admission, and fairness tests**
- [x] **Step 2: Implement per-client admitted-write counters**
- [x] **Step 3: Implement per-client token buckets outside the global lock**
- [x] **Step 4: Preserve global queue/interval and idempotent retry semantics**
- [x] **Step 5: Verify rejection occurs before intent/plugin dispatch**
- [x] **Step 6: Retain deterministic fairness evidence**

**Result:**

```text
status: pass
rate limit: BRIDGE_CLIENT_RATE_LIMITED/not-applied
other client completed: true
rejected before transaction intent: true
burst-limited client deferred while another client dispatched: true
content hash: 7e06cc0f77028842b9fa3553d2e3ffcdc3d934d59cead73c94525c9525ce3877
file SHA-256: eece42ad6824b06f575a6582be1e5375b007825e7cfd2b095945a4ded944380e
full Python suite: 387 passed
```

Evidence:

- `output/_r5_p3_client_fairness_round1/r5_p3_client_fairness.json`

This proves bounded per-client admission inside one bridge process. Internet
scale fairness, cross-host fairness, and real Figma rate-limit behavior remain
open.

### Task 14: Config-backed TLS and wss Transport

**Files:**
- Modify: `src/app/services/bridge_config.py`
- Modify: `src/app/services/bridge_server.py`
- Modify: `src/app/services/rendering/figma_adapter.py`
- Modify: `figma_bridge.config.json`
- Create: `tests/v2/test_bridge_tls.py`
- Create: `scripts/r5_p3_tls_probe.py`
- Create: `tests/v2/test_r5_p3_tls_probe.py`
- Evidence: `output/_r5_p3_tls_round1/`

**Config:**

```json
{
  "server": {
    "tls": {
      "enabled": true,
      "certfile": "server.crt",
      "keyfile": "server.key",
      "ca_file": "",
      "require_client_cert": false
    }
  },
  "client": {
    "url": "wss://localhost:8765",
    "tls": {
      "enabled": true,
      "verify": true,
      "ca_file": "ca.crt",
      "certfile": "",
      "keyfile": ""
    }
  }
}
```

**Rules:**

1. TLS is disabled by default for local development.
2. Enabled server TLS requires existing cert/key files.
3. Client TLS requires `wss://`.
4. Client CA and mutual-TLS client cert/key are config-backed.
5. Certificate/key/CA paths are validated at config load.
6. Adapter uses websocket-client `sslopt`; server uses an `SSLContext`.
7. The probe performs a real local loopback handshake and round trip.

- [x] **Step 1: Write failing config and TLS handshake tests**
- [x] **Step 2: Implement server/client TLS config validation**
- [x] **Step 3: Construct the server SSL context from cert/key/CA**
- [x] **Step 4: Configure adapter wss sslopt**
- [x] **Step 5: Retain a local handshake evidence report**
- [x] **Step 6: Run full Python and bridge verification**

**Result:**

```text
status: pass
handshake: true
round trip: true
content hash: 9ce4eae23a2aaa5b131ecca7a30df04044952ee52ce98d663e249df633364a8c
file SHA-256: 8c1972d1e9e2e82563cb1bf60bf2419da7aa676c6abd73413bbb6428f10327f1
full Python suite: 391 passed
```

Evidence:

- `output/_r5_p3_tls_round1/r5_p3_tls_probe.json`

TLS transport is now implementable through the same config file. Certificate
provisioning/rotation, production trust-store integration and a TLS rerun of
the complete timeout/pacing matrix remain open. Plugin authentication follows
in Task 15.

### Task 15: Plugin Socket Authentication

**Files:**
- Modify: `src/app/services/bridge_config.py`
- Modify: `src/app/services/bridge_server.py`
- Modify: `figma_bridge/code.js`
- Modify: `figma_bridge/ui.html`
- Modify: `tests/v2/test_bridge_config.py`
- Modify: `tests/v2/test_bridge_protocol.py`
- Create: `tests/bridge/test_plugin_token_storage.js`
- Create: `scripts/r5_p3_plugin_auth_probe.py`
- Create: `tests/v2/test_r5_p3_plugin_auth_probe.py`
- Evidence: `output/_r5_p3_plugin_auth_round2/`

**Protocol:**

```json
{"type": "auth", "token": "<plugin-secret>"}
```

The token is sent as the first plugin WebSocket frame, never in the URL.
Successful authentication returns `{"type":"auth-ok"}`. A missing or wrong
token returns `PLUGIN_AUTH_FAILED` and closes with code `4003` before the socket
is attached as the active plugin.

**Configuration:**

- server token: `figma_bridge.config.json` -> `server.plugin_token`;
- plugin URL/token: Figma plugin UI, persisted with `figma.clientStorage`;
- empty `server.plugin_token` keeps local optional-auth behavior.

- [x] **Step 1: Write failing Python first-frame auth tests**
- [x] **Step 2: Add plugin config load/save through clientStorage**
- [x] **Step 3: Add URL/token UI without placing token in the URL**
- [x] **Step 4: Authenticate before attaching the plugin socket**
- [x] **Step 5: Reject missing/wrong token with close code 4003**
- [x] **Step 6: Retain deterministic auth evidence**

**Result:**

```text
status: pass
missing rejected: true
wrong rejected: true
valid accepted: true
wrong replacement preserves active plugin: true
old token rejected after rotation: true
new token accepted after rotation: true
content hash: 86a1859a1f17ca2588f7c27bf789d11fd8dcfab3630dd58a522876df86c80027
file SHA-256: 9afb37f9528f902d0ad53b4364dbffb78798fea32b2fbf59b175d10279069f4c
full Python suite: 397 passed
Node bridge: 16/16 passed
```

Evidence:

- `output/_r5_p3_plugin_auth_round2/r5_p3_plugin_auth.json`

Plugin authentication is now configurable, and new connections read the latest
token from the config file. Revocation rollout, stale-token recovery UX, real
Figma UI validation and TLS overlay remain open.

### Task 16: Revocation, TLS+Auth Reconnect, UI Reopen, Attribution Boundary

**Files:**
- Modify: `src/app/services/bridge_config.py`
- Modify: `src/app/services/bridge_server.py`
- Modify: `figma_bridge.config.json`
- Modify: `tests/v2/test_bridge_protocol.py`
- Modify: `tests/v2/test_bridge_tls.py`
- Create: `tests/v2/test_r5_p3_tls_plugin_auth_probe.py`
- Create: `scripts/r5_p3_tls_plugin_auth_probe.py`
- Create: `tests/v2/test_r5_p3_multiplayer_attribution_probe.py`
- Create: `scripts/r5_p3_multiplayer_attribution_probe.py`
- Evidence:
  - `output/_r5_p3_real_plugin_ui_round1/`
  - `output/_r5_p3_tls_plugin_auth_round2/`
  - `output/_r5_p3_multiplayer_attribution_round2/`

**Revocation contract:**

1. `server.plugin_token_recheck_seconds` controls token refresh polling.
2. An active plugin is compared against the latest config token.
3. Rotation/revocation closes the active socket with code `4004`.
4. A wrong new candidate cannot displace the current active plugin.
5. A valid new candidate takes over after successful authentication.

**Combined transport/auth contract:**

- real local wss handshake;
- first-frame plugin auth;
- command round trip through the authenticated plugin;
- old token revoked after rotation;
- new token reconnects and repeats the command round trip.

**Real Figma UI result:**

The test token was entered in the Figma plugin UI, saved through
`figma.clientStorage`, connected, the plugin window was closed, and the plugin
was reopened through Figma quick actions. The saved token restored and the
plugin reconnected. Bridge logs recorded 3 connection opens and 1 plugin
disconnect.

```text
status: pass
content hash: ca22cb3475c5d641231db7a7d6e1ca3cffe98e66402c0797d637f22a77a73d64
file SHA-256: ffdc87cbdf66aac7a6b7f717616b70be60dd85bf4f07613d48b0c7172e085072
screenshot SHA-256: 8a757499bfd7cb2b211c2e44ac47ae16c9c5e58cc0d87110add65e620e441c38
cleared-token screenshot SHA-256: a06abaccffe167398409566bec0c91a9dd90891e63db16a896afb5d6aaf70103
```

The test token was cleared from both config and Figma clientStorage afterward.

**Combined TLS+auth result:**

```text
status: pass
tls handshake: true
plugin auth: true
command round trip: true
old token revoked: true
new token reconnected: true
content hash: 86151a9ef89b4f05904cadbedd218ae863be1420736ddeb242459df26b92b722
file SHA-256: 9f72ca1c5596b7553705e0bbafd6034b6d399423756877078ee7fd5c992660f2
```

Evidence:

- `output/_r5_p3_tls_plugin_auth_round2/r5_p3_tls_plugin_auth.json`

**Multiplayer attribution result:**

The transaction envelope now states:

```json
{
  "attribution": {
    "status": "unavailable",
    "actor": "unknown",
    "revision": "unknown"
  }
}
```

Current-state readback can match intent, but it cannot prove which collaborator
performed the write. The transaction remains unknown and is never auto-replayed.
`src/app/services/attribution.py` provides an `AttributionProvider` extension
point. The default `UnavailableAttributionProvider` never fabricates actor or
revision; provider errors also fail closed to unavailable.

```text
status: pass
attribution: unavailable
transaction stays unknown: true
auto resend: false
content hash: 284022e78d14a3951e0402abc0004b92adace1d6f04b5f6164873ae0e2a1f164
file SHA-256: 22299b5b6cd298a4caabfb77c7a313cc617fa17fced9cd44ead05732a3399a41
full Python suite: 405 passed
```

Evidence:

- `output/_r5_p3_multiplayer_attribution_round2/r5_p3_multiplayer_attribution.json`

Real two-human collaborator attribution remains unavailable because the Figma
Plugin API does not expose an authoritative actor/revision source.

### Task 17: Operator Revocation UX and Secret Lifecycle

**Files:**
- Modify: `src/app/services/bridge_config.py`
- Modify: `src/app/services/bridge_server.py`
- Modify: `figma_bridge.config.json`
- Modify: `figma_bridge/ui.html`
- Create: `scripts/rotate_figma_bridge_config.py`
- Create: `tests/v2/test_secret_lifecycle.py`
- Create: `tests/bridge/test_plugin_ui_revocation.js`
- Evidence: `output/_r5_p3_real_plugin_revocation_round2/`

**Secret references:**

- `env:VARIABLE` resolves an environment value without storing it in config.
- `file:relative-or-absolute-path` reads a secret file relative to the config
  file directory.
- `security.require_secret_references=true` rejects direct secret literals.
- `security.require_secure_file_permissions=true` checks config/secret-file
  permissions. POSIX checks mode bits; Windows uses conservative `icacls`
  inspection and fails closed when broad user access is detected.

**Atomic rotation:**

1. create a same-directory temp file with private mode;
2. write and `fsync`;
3. validate the complete new config;
4. atomically `os.replace`;
5. retain the old file unchanged on any validation/IO failure;
6. report only updated field names and the file hash.

**UI revocation behavior:**

- close code `4004` shows "Token rotated or revoked";
- automatic reconnect with the old token stops;
- the user must enter/save a new token;
- `4003` shows authentication failure and also stops automatic retry;
- ordinary disconnect retains bounded 5-second reconnect.

**Real Figma revocation/recovery result:**

1. old token connected;
2. the running bridge config was atomically rotated with the new script;
3. active plugin was closed with `4004`;
4. UI showed revoked and did not retry the old token;
5. new token saved in the Figma UI;
6. plugin reconnected;
7. test token was cleared from config and clientStorage.

```text
status: pass
content hash: 18a460f0f1f2666bc1b3d95e819958bbdd8d89fb539bb70b3c5d1cac0db12af0
file SHA-256: 432a231f6105ef8ffa862c54cf822274cd292a0d5e3650fa937bf1aa56b7f8b7
full Python suite: 412 passed
Node bridge: 17/17 passed
```

Evidence:

- `output/_r5_p3_real_plugin_revocation_round2/figma_ui_revocation_probe.json`

### Task 18: Write Job Ledger Retention, Compaction and Legacy Migration

**Files:**
- Modify: `src/app/services/bridge_config.py`
- Modify: `src/app/services/rendering/write_job_ledger.py`
- Modify: `src/app/services/rendering/__init__.py`
- Modify: `figma_bridge.config.json`
- Modify: `tests/v2/test_bridge_config.py`
- Modify: `tests/v2/test_bridge_tls.py`
- Create: `tests/v2/test_write_job_ledger_lifecycle.py`
- Create: `tests/v2/test_migrate_write_job_ledger_cli.py`
- Create: `tests/v2/test_r5_p3_ledger_lifecycle_probe.py`
- Create: `scripts/migrate_write_job_ledger.py`
- Create: `scripts/r5_p3_ledger_lifecycle_probe.py`
- Evidence: `output/_r5_p3_ledger_lifecycle_round1/`

**Unified ledger configuration:**

```json
{
  "ledger": {
    "path": "output/_bridge_state/write-jobs.jsonl",
    "max_events": 4096,
    "terminal_retention_days": 30,
    "compact_min_events": 256,
    "allow_legacy_read": false
  }
}
```

The root section is strict: missing/unknown fields, non-positive bounds,
negative retention, non-boolean legacy reads, and
`compact_min_events > max_events` fail configuration loading. Relative paths
resolve against the config file directory. `WriteJobLedger.from_bridge_config`
uses the same values.

**Retention and compaction contract:**

1. `committed`, `rejected`, and `rolled-back` are terminal and become eligible
   for history collapse after `terminal_retention_days`.
2. `planned`, `inflight`, `unknown`, `resume-required`, and
   `rollback-incomplete` events are never automatically removed.
3. Terminal collapse retains the latest snapshot, including fingerprint,
   ownership classification, resume decision, node ids, and cleanup receipt.
4. Torn trailing JSONL is ignored; corruption before the trailing tail fails
   closed.
5. Compaction writes a same-directory temporary file, flushes and fsyncs,
   reparses the complete candidate, validates reconstructed states, then uses
   `os.replace`; any failure preserves the old ledger.
6. `max_events` is the automatic compaction trigger. Protected state can keep
   the file above that trigger rather than delete an unknown/nonterminal event.

**Legacy migration contract:**

- mapping format is an explicit JSON object from legacy `client_id` to target
  `client_id`;
- dry-run is the default and never creates the target;
- migration groups by `(legacy client_id, raw job id)`, so two clients may
  migrate the same raw id into distinct namespaces;
- missing mapping, aliases that collide on one target namespace, conflicting
  fingerprints, torn source tails, invalid states, and existing targets without
  explicit overwrite fail closed;
- apply uses a validated same-directory temporary file and `os.replace`;
- reports emit only field names, counts, and source/candidate/report hashes;
  action payloads, text, secrets, raw job ids, and source client ids are omitted.

**Verification result:**

```text
ledger lifecycle focused tests: 19 passed
full Python suite: 431 passed
bridge Node scripts: 17/17 passed
node --check figma_bridge/code.js: pass
py_compile changed Python modules/scripts: pass
evidence status: pass
migration: dry-run + atomic apply
migration source events: 8
migrated jobs: 6
compaction events: 8 -> 7
protected jobs: 5
cross-client same raw id distinct: true
cleanup receipt preserved: true
duplicate fingerprint conflict preserved: true
report content hash: cd6dcef35fab8bde8eef3a74eb8cafab7cc77ff24e428edf8f7f851b5ab86cb3
report file SHA-256: 33ce9cfb0aca98a672155bffb255590a5fa868bd80f94c97cfca0000054c7c85
evidence-set SHA-256: 3d85f72202bcf3c51dacd5a8aebb4f3548a89b904628b7d674b9904ff0ef5161
```

This closes deterministic retention/compaction and business-ledger migration
for the current single-process scope. It does not migrate plugin markers or the
bridge journal, provide cross-process ledger fencing, define a terminal purge
policy, or enter R5-P5.

## Execution Order

1. Task 1: real marker persistence across plugin reload, requiring Figma UI.
2. Tasks 2-3: ledger contract and durable sidecar.
3. Task 4: write-ahead owned-batch integration.
4. Task 5: conservative resume.
5. Task 6: job-scoped compensation.
6. Task 7: deterministic failure injection.
7. Task 8: real Figma resume probe.
8. Task 9: admission review.
9. Task 10: global ownership job namespace and conflict protection.
10. Task 11: authenticated client identity for ownership namespace.
11. Task 12: central file-backed bridge configuration.
12. Task 13: per-client admission and fair write dispatch.
13. Task 14: config-backed TLS and wss transport.
14. Task 15: plugin socket authentication.
15. Task 16: revocation, TLS+auth reconnect, real UI reopen and attribution
    boundary.
16. Task 17: operator revocation UX, secret references/ACL and atomic rotation.
17. Task 18: ledger retention/compaction and legacy business-ledger migration.

Tasks 2-7 can proceed while Task 1 awaits a human Figma reload. Task 8
depends on Tasks 4-7 and a live Figma plugin.

## Completion Definition

R5-P3 may be called current-scope complete only when:

- marker persistence across reload/reopen is proven;
- planned intent is durable before dispatch;
- unknown outcomes never auto-resend;
- complete ownership can reconcile without resend;
- partial/missing ownership requires manual review;
- exact job cleanup is recorded;
- duplicate job ids and torn ledger tails fail closed;
- bare ownership ids fail closed unless legacy compatibility is explicit;
- distinct clients cannot collide on the same raw id;
- configured per-client tokens bind the claimed client id before dispatch;
- normal bridge/client operation can be configured through one JSON file;
- one client cannot monopolize all admitted write slots;
- server/client transport can be upgraded to configured wss with cert
  validation;
- configured plugin sockets authenticate before becoming active;
- active plugin sockets are revoked when the configured token changes;
- TLS+auth rotation reconnect is exercised end to end;
- collaborator attribution is explicitly `unavailable`, never fabricated;
- direct secrets can be rejected in favor of env/file references;
- config rotation is atomic and UI revocation stops stale-token retry;
- terminal ledger history compacts atomically while nonterminal/unknown state is
  retained;
- legacy non-namespace jobs migrate only with explicit client mapping and
  conflict-safe atomic apply;
- deterministic and real evidence are retained.
