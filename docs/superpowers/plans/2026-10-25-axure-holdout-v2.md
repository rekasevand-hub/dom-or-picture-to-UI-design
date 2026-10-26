# Axure Untouched Holdout V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a new Axure holdout whose failures are recorded before any
remediation, producing a clean generalization result for the frozen samples.

**Architecture:** Reuse the canonical DOM DesignSpecs, image MVP preparation,
shared IR, Axure writer and independent acceptance. No product code may be
changed in response to this holdout until its initial result is recorded.

**Tech Stack:** Python 3.11, canonical fixtures, image MVP, `design-ir/2.0`,
Axure RP 8, Playwright.

**Specs:**

- `docs/v2_mentor/AXURE_HOLDOUT_ACCEPTANCE_2026-10-25.md`;
- `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`.

**Execution status:** `complete-current-scope`, result
`fail-unseen-holdout` on 2026-10-25.

## Frozen Samples

- `AX6-DOM-TEXTFLOW`: canonical mixed text and explicit line flow;
- `AX6-DOM-FONTFALLBACK`: canonical missing-font fallback and multi-line text;
- `AX6-IMG-OVERLAY`: overlay screenshot, not used by A-003/A-005.

Excluded prior Axure samples:

```text
DQ-R02
IMG-MVP-01
DQ-R01
DQ-R03
AX-IMG-H01
```

The source image and thresholds are frozen before image preparation. Prepared
DesignSpec hashes are frozen before Axure generation.

## Thresholds

- critical text `100%`;
- expected image hash `100%`;
- expected asset count exact;
- page/package/object mapping `100%`;
- deterministic `.rp` byte equality;
- exact size match;
- visual within-30 `>=90%`;
- no sample substitution, threshold change or composite score.

## Review Focus

- The DOM samples are not aliases of prior Axure tuning samples.
- Image preparation is run once and frozen before Axure output.
- Failure is recorded before remediation; no post-result tuning in this task.
- No prior Figma evidence is used as Axure acceptance.
- Unsupported Axure features remain non-claims.

### Task 1: Freeze V2 Inputs

**Files:**
- Create: `tests/fixtures/axure_holdout_v2/holdout_v2.json`
- Create: `tests/fixtures/axure_holdout_v2/overlay.png`
- Create: `tests/fixtures/axure_holdout_v2/overlay.truth.json`
- Create: `tests/v2/test_axure_holdout_v2_manifest.py`

- [x] **Step 1: Write failing manifest tests**

Validate sample IDs, prior-sample exclusions, threshold values and input
hashes.

- [x] **Step 2: Freeze source fixtures and run focused tests**

- [x] **Step 3: Prepare AX6-IMG-OVERLAY once**

- [x] **Step 4: Record prepared DesignSpec hashes and rerun manifest tests**

### Task 2: Generate And Inspect Axure Artifacts

**Files:**
- Create runs under: `output/_axure_holdout_v2_2026-10-25/`

- [x] **Step 1: Generate all three `.rp` files twice**

- [x] **Step 2: Verify object graphs and deterministic hashes**

### Task 3: Publish And Independent Acceptance

- [x] **Step 1: Open each `.rp` and publish with Axure RP 8**

- [x] **Step 2: Reopen and republish each `.rp`**

- [x] **Step 3: Screenshot each published page**

- [x] **Step 4: Run independent acceptance and record failures before changes**

### Task 4: Report V2 Result

**Files:**
- Create: `docs/v2_mentor/AXURE_HOLDOUT_V2_ACCEPTANCE_2026-10-25.md`
- Modify: `docs/v2_mentor/AXURE_ROUTE_LEDGER_2026-10-25.md`
- Modify: `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`
- Modify: `README.md`
- Modify: `docs/v2_mentor/README.md`

- [x] **Step 1: Report every sample independently**

- [x] **Step 2: Record pass, partial or fail without remediation**

- [x] **Step 3: Run full verification**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
C:\Users\lzq\.conda\envs\omni\python.exe -m ruff check <touched files>
C:\Users\lzq\.conda\envs\omni\python.exe -m ruff format --check <touched files>
node --check figma_bridge\code.js
git diff --check
C:\Users\lzq\.conda\envs\omni\python.exe scripts/axure_rp8_conform.py <each .rp>
```

**Final result:** `tests/v2` `720 passed in 40.09s`; manifest tests
`3 passed`; touched-file Ruff/format, Node, diff-check and three-file Axure
conformance pass. Holdout result remains `fail-unseen-holdout`.
