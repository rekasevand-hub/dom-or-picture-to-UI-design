# Production Admission Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the existing Grounding and Figma production-admission paths,
produce auditable evidence for reliability, collaboration, security,
observability, and a one-hour soak, then reconcile the release decision without
overstating the tested environment.

**Architecture:** Add a bounded Grounding runtime around the existing
OpenAI-compatible backend, preserving the current `grounding -> cv` product
policy. Extend the existing `BridgeHub`, writer lease, write-job ledger, and
plugin ownership markers for collaboration and recovery evidence. Keep
fallback, security, and soak evidence as separate claims bound to commands,
hashes, environment, limitations, and non-claims.

**Tech Stack:** Python 3.12, `unittest`/`pytest`, OpenAI-compatible HTTP API,
asyncio WebSockets, existing `BridgeHub`/`FigmaBridgeAdapter`, JSONL
journals/ledgers, Figma Plugin API, Playwright/Chromium, psutil.

**Spec:**

- `docs/v2_mentor/R5_P5_PRODUCTION_ROADMAP_2026-10-22.md`
- `docs/v2_mentor/R5_GATE_MATRIX.md`
- `docs/v2_mentor/PRODUCTION_VERIFICATION_MATRIX.md`
- `docs/v2_mentor/R5_PRODUCTION_ADMISSION_DECISION.md`
- `docs/v2_mentor/P4_LONG_SOAK_BACKLOG.md`
- `docs/v2_mentor/P5_PILOT_RUNBOOK.md`
- `docs/v2_mentor/IMAGE_CV_FALLBACK_PRODUCT_ACCEPTANCE_2026-10-26.md`

## Global Constraints

- Grounding remains the default image strategy; CV remains availability-only.
- Hybrid is not entered by this work.
- No Axure, SVG, authored fixture, or mock result substitutes for a real Figma
  claim.
- Every behavior change starts with a test watched in RED, then reaches GREEN.
- Existing bridge lease, journal, business ledger, ownership markers, and
  unknown no-resend policy remain authoritative.
- Never read, print, persist, or commit a real token, `.env`, or `login_state`.
- Do not start local 24h/7d soak stages.
- A timeout or interrupted one-hour run saves partial evidence and reports
  `blocked`; it is never converted to a soak pass.
- No composite score and no project-wide `verified=true`.
- Do not commit or push.

## Review Focus

- Retries can become unbounded or replay a write after send.
- A circuit breaker can suppress a healthy endpoint or never recover.
- Grounding fallback can occur after ordinary parse/business failures.
- A cache hit can cross model/prompt/strategy/client namespaces.
- Authentication or request payloads can leak through logs.
- Plugin takeover can strand pending writes or cause duplicate dispatch.
- Reconnect readback can be mistaken for commit attribution.
- A short deterministic run can be mislabeled as one-hour soak evidence.
- A local result can be copied into a production claim without its
  environment and non-claims.

---

### Task 1: Add bounded Grounding failover, retry, breaker, and cache

**Files:**
- Create: `src/app/services/structure/backends/grounding_reliability.py`
- Modify: `src/app/services/structure/backends/grounding_vlm.py`
- Modify: `src/app/services/structure/providers/grounding.py`
- Modify: `src/app/services/structure/router.py`
- Modify: `src/config/settings.py`
- Test: `tests/v2/test_grounding_reliability.py`
- Test: `tests/v2/test_image_route_fallback.py`

**Interfaces:**
- Produces: `GroundingReliability.run(image_bytes, invoke, cache_key) ->
  GroundingInvocation`.
- Produces: `GroundingUnavailableError`, `GroundingRequestError`, and
  `GroundingRunReport`.
- Produces: stable cache key over image SHA-256, model, prompt SHA-256,
  strategy ID, and strategy version.
- Consumes: `vision_base_urls`, bounded retry/backoff/breaker/cache settings.

- [x] **Step 1: Write failing tests for endpoint failover and finite retry**

Use a deterministic fake clock/sleeper/caller. Assert the second endpoint is
used after a transient first-endpoint error, total calls never exceed
`max_attempts`, backoff sleeps are bounded and jittered, and a success resets
the endpoint breaker.

- [x] **Step 2: Verify RED**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\v2\test_grounding_reliability.py -q
```

Expected: FAIL because the reliability module/API does not exist.

- [x] **Step 3: Write failing tests for circuit-open/half-open recovery, cache**

Assert an open breaker skips its endpoint until cooldown, a half-open probe can
close it, cached results avoid invocation, cache keys differ on every required
dimension, TTL/LRU bounds hold, and returned results cannot mutate cached state.

- [x] **Step 4: Verify RED**

Run the focused test. Expected: FAIL on missing breaker/cache behavior.

- [x] **Step 5: Write failing classification and integration tests**

Assert:

- connection, timeout, 429, 5xx, and auth exhaustion map to
  `grounding-service-unavailable`;
- malformed/empty JSON maps to a non-fallback request error;
- `GroundingVLM` passes image bytes/model/prompt/strategy/version to cache;
- graph provenance contains attempts, final endpoint index, retry count,
  breaker state, latency, token usage, and cache status.

- [x] **Step 6: Verify RED**

Run the grounding tests and existing route fallback tests. Expected: FAIL on
missing telemetry and typed errors.

- [x] **Step 7: Implement the bounded runtime and integrate it**

Use a finite loop, transient-only retry, per-endpoint consecutive-failure
breaker, cooldown half-open probe, bounded TTL LRU cache, and deep-copy
boundaries. Add safe defaults:

```text
max_attempts=3
base_backoff_ms=250
max_backoff_ms=4000
jitter_ratio=0.25
breaker_failure_threshold=3
breaker_cooldown_seconds=30
cache_max_entries=64
cache_ttl_seconds=300
```

- [x] **Step 8: Verify GREEN and regression**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\v2\test_grounding_reliability.py tests\v2\test_image_route_fallback.py tests\v2\test_route_taxonomy.py -q
```

Expected: PASS. Malformed data still does not trigger CV.

---

### Task 2: Collect fallback observability before any design write

**Files:**
- Create: `src/app/services/observability/fallback_metrics.py`
- Create: `tests/v2/test_fallback_metrics.py`
- Modify: `src/app/agents/precise_agent.py`
- Modify: `tests/v2/test_image_agent_integration.py`

**Interfaces:**
- Produces: `FallbackObservation` with trigger, acceptance, latency, usage,
  cost status, stage, and `write_before_decision`.
- Produces: `<output>/fallback_observability.json`, written immediately after
  provider selection and before `_design_and_render`.
- Consumes: `GroundingRunReport` when available.

- [x] **Step 1: Write failing contract tests**

Assert unavailable/config-missing triggers produce one observation, successful
CV selection records `selection_accepted=true`, write-before-decision is false,
and token/cost values remain unknown rather than invented.

- [x] **Step 2: Verify RED**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\v2\test_fallback_metrics.py tests\v2\test_image_agent_integration.py -q
```

Expected: FAIL because the artifact/contract is absent.

- [x] **Step 3: Implement and emit the pre-write artifact**

Keep the existing route taxonomy and manifest fields compatible. Do not call
CV for malformed Grounding output.

- [x] **Step 4: Verify GREEN**

Run the focused tests. Expected: PASS.

---

### Task 3: Prove collaboration, takeover, idempotency, and unknown recovery

**Files:**
- Modify: `src/app/services/bridge_server.py`
- Create: `scripts/p5_collaboration_bridge_probe.py`
- Create: `tests/v2/test_p5_collaboration_bridge_probe.py`
- Modify: `tests/v2/test_bridge_protocol.py`
- Modify: `tests/v2/test_bridge_fencing.py`

**Interfaces:**
- Produces: a deterministic end-to-end probe over the real `BridgeHub` and
  writer lease using fake transport only.
- Produces: evidence for two clients, concurrent writes, plugin takeover,
  same-request retry, timeout unknown, reconnect readback, no resend, and exact
  frame/job ownership readback.
- Consumes: existing `WriterLeaseStore`, journal, ownership namespace, and
  reconciliation policy.

- [x] **Step 1: Write a failing duplicate-dispatch test**

Drive two clients concurrently with one plugin; assert serialized writes,
distinct transaction namespaces, and one plugin send per accepted request.

- [x] **Step 2: Write a failing takeover/recovery test**

Replace the plugin while one write is pending; assert old takeover closes with
4002, pending outcome is explicit, a retry with the same request id does not
dispatch twice, reconnect triggers ownership readback, and unknown state stays
manual/no-resend.

- [x] **Step 3: Verify RED**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\v2\test_p5_collaboration_bridge_probe.py tests\v2\test_bridge_fencing.py -q
```

Expected: FAIL on the missing probe or a real dispatch/recovery defect.

- [x] **Step 4: Implement only the minimal fix revealed by RED**

Preserve the existing lease/ledger protocol. Add bridge counter snapshots only
where required for auditable reconnect/write/unknown metrics.

- [x] **Step 5: Verify GREEN**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_collaboration_bridge_probe.py --out output\_p5_collaboration_bridge_round1
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\v2\test_p5_collaboration_bridge_probe.py tests\v2\test_bridge_fencing.py tests\v2\test_write_lease.py tests\v2\test_write_job_ledger.py -q
```

Expected: focused tests and probe pass; the report remains `current-scope`
unless real-callaborator evidence is supplied.

---

### Task 4: Close security evidence for tokens, redaction, bounds, and cache isolation

**Files:**
- Create: `src/app/utils/redaction.py`
- Create: `tests/v2/test_security_redaction.py`
- Create: `scripts/p5_security_probe.py`
- Create: `tests/v2/test_p5_security_probe.py`
- Modify: `src/app/services/llm/llm_service.py`
- Modify: `src/app/services/bridge_server.py`
- Modify: `src/app/services/structure/backends/grounding_vlm.py`

**Interfaces:**
- Produces: `redact_sensitive_text`, `redact_url`, and
  `safe_exception_message`.
- Produces: redacted logs for Grounding and bridge failures.
- Produces: evidence for auth rejection, request byte/depth limits, token
  absence from journal/output, and cache namespace isolation.

- [x] **Step 1: Write failing redaction tests**

Inject sentinel bearer/client/plugin tokens, URL userinfo/query values, action
text, and API keys through exceptions. Assert no sentinel appears in captured
logs, responses, or evidence JSON.

- [x] **Step 2: Verify RED**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\v2\test_security_redaction.py tests\v2\test_p5_security_probe.py -q
```

Expected: FAIL on missing redaction/probe.

- [x] **Step 3: Implement minimal redaction and evidence collection**

Do not read real secret stores in the probe. Use generated canaries only.
Keep authentication fail-closed and avoid logging payloads.

- [x] **Step 4: Verify GREEN**

Run the focused tests plus bridge auth/TLS/config tests:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_security_probe.py --out output\_p5_security_round1
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\v2\test_security_redaction.py tests\v2\test_p5_security_probe.py tests\v2\test_bridge_tls.py tests\v2\test_secret_lifecycle.py -q
```

Expected: PASS for the local controlled security scope only.

---

### Task 5: Extend observability and execute a one-hour controlled soak

**Files:**
- Modify: `scripts/p4_observability_probe.py`
- Modify: `tests/v2/test_p4_observability_probe.py`
- Create: `scripts/production_admission_soak.py`
- Create: `tests/v2/test_production_admission_soak.py`
- Modify: `docs/v2_mentor/P4_OPERATIONS_RUNBOOK.md`
- Evidence: `output/_production_admission_soak_1h_<timestamp>/`

**Interfaces:**
- Produces metrics: `grounding_unavailable_total`,
  `fallback_trigger_total`, `fallback_selection_accepted_total`,
  `fallback_write_before_block_total`, `fallback_latency_ms_p50/p95/p99`,
  `fallback_token_usage_total`, and existing bridge metrics.
- Produces checkpoints and a partial report on interruption.
- Consumes: real `BridgeHub`, writer lease, fake transport for controlled
  failure injection, and the Grounding reliability runtime.

- [x] **Step 1: Write failing observability tests**

Assert the new fallback metrics are present, ordered, zero-disclosure,
alertable, and backed by fresh collected values rather than only fixtures.

- [x] **Step 2: Write failing soak-report tests**

Assert a dry run, missing duration, or interrupted run cannot pass; 5xx/429 and
disconnect counters must be explicit; checkpoints must cover at least
5/15/30/60 minutes; unknown outcomes must reconcile without resend.

- [x] **Step 3: Verify RED**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\v2\test_p4_observability_probe.py tests\v2\test_production_admission_soak.py -q
```

Expected: FAIL on missing metrics/harness.

- [x] **Step 4: Implement the harness and run a short rehearsal**

Use controlled transport only. Preserve request/outcome classification,
checkpoint resources, queue depth, latency, reconnects, 429/5xx classification,
and unknown reconciliation. Label the boundary `real_figma=false`.

- [x] **Step 5: Execute the one-hour controlled soak**

Run with duration `3600`, checkpoints at 300-second intervals, and a saved
partial report path. Do not terminate early without materializing partial
evidence.

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\production_admission_soak.py --duration 3600 --checkpoint-every 300 --out output\_production_admission_soak_1h_<timestamp>
```

Expected: `status=pass-current-scope` only when all bounds and reconciliation
checks hold. Otherwise retain `blocked` with the failing checks.

- [x] **Step 6: Attempt the real Figma one-hour probe only if available**

Check the fixed bridge/plugin session and use the existing
`figma_bridge_soak_probe.py`. If no live plugin session or fixed pilot inputs
exist, record `blocked-environment` and do not substitute the controlled run.

- [x] **Step 7: Verify GREEN**

Run the focused tests and validate evidence content hashes/file hashes.
Expected: PASS or explicit `blocked`, never a fabricated 24h/7d claim.

---

### Task 6: Reconcile gates, matrix, ledger, and admission decision

**Files:**
- Modify: `docs/v2_mentor/PRODUCTION_VERIFICATION_MATRIX.md`
- Modify: `docs/v2_mentor/R5_GATE_MATRIX.md`
- Modify: `docs/v2_mentor/R5_PRODUCTION_BACKLOG.md`
- Modify: `docs/v2_mentor/R5_PRODUCTION_ADMISSION_DECISION.md`
- Modify: `docs/v2_mentor/RESIDUAL_RISKS.md`
- Modify: `README.md`
- Test: `tests/v2/test_production_verification_matrix.py`
- Test: `tests/v2/test_production_admission_decision.py`
- Test: `tests/v2/test_r5_gate_matrix.py`

**Interfaces:**
- Produces: one row per claim with pass/fail/blocked status, command, code and
  plugin hashes, environment, thresholds, evidence hash, limitation, and
  non-claims.
- Produces: an explicit admission decision and next trigger.

- [x] **Step 1: Write failing matrix tests for this round’s claims**

Assert the new Grounding, fallback observability, security, collaboration, and
soak rows exist with no composite score. Assert every passed row has a real
hash and every blocked row names its environment gap.

- [x] **Step 2: Verify RED**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\v2\test_production_verification_matrix.py tests\v2\test_r5_gate_matrix.py tests\v2\test_production_admission_decision.py -q
```

Expected: FAIL on missing rows/evidence binding.

- [x] **Step 3: Update evidence and decision documents**

Keep 24h/7d blocked unless actually run. Keep real collaborator and production
secret-manager/TLS lifecycle claims blocked unless the real environment was
exercised in this round.

- [x] **Step 4: Run final verification**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\v2 -q
node --check figma_bridge\code.js
C:\Users\lzq\.conda\envs\omni\python.exe -m compileall -q src scripts
git diff --check
git status --short
```

Expected: all tests pass, no secrets appear in the diff/evidence, and the final
decision accurately distinguishes current-scope evidence from production.

