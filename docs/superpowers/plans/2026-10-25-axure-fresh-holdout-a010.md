# Axure Fresh Holdout A-010 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a fresh untouched Axure holdout after A-009 remediation, covering
multi-asset, transparent-crop and nested-iframe behavior.

**Architecture:** Freeze three DesignSpecs, screenshots, truths and visible
critical regions before generation. Reuse the repaired Axure acceptance gate,
generate deterministic artifacts, publish twice with Axure RP 8, screenshot
each page and record every gate independently.

**Tech Stack:** Python 3.11, Playwright, Axure RP 8.0.0.3400, pytest.

**Spec:** `docs/v2_mentor/AXURE_A009_RENDERED_REGION_REPAIR_2026-10-25.md`

**Execution status:** `pass-unseen-holdout` on 2026-10-25.

## Global Constraints

- None of the three samples may appear in A-005 through A-009 Axure manifests.
- Freeze every input hash before Axure generation.
- Record the initial result before product-code remediation.
- Keep label text, visible critical regions, assets, object mapping,
  determinism and overall visual score separate.
- No composite score or post-observation threshold change.
- Do not overwrite prior holdout evidence.
- Do not commit or push.

## Review Focus

- A reusable image crop must not be counted as an original source when it is
  only a display payload.
- Transparent-crop text must remain visibly present over the image region.
- Recursive iframe text must use host offsets instead of child-local
  coordinates.
- A high overall pixel score must not mask a blank critical region.
- Reopen publish equality must exclude only Axure's generation timestamp.

### Task 1: Freeze Fresh Inputs

**Files:**
- Create: `tests/fixtures/axure_holdout_v4/holdout_v4.json`
- Create: `tests/v2/test_axure_holdout_v4_manifest.py`

**Interfaces:**
- Produces: `axure-holdout/4.0` with three frozen sample records.

- [x] **Step 1: Write the failing manifest test**

Assert sample IDs `AX10-DOM-ASSETS`, `AX10-DOM-TRANSPARENT-CROP` and
`AX10-DOM-NESTED-IFRAME`, prior-sample exclusions, thresholds and input hashes.

- [x] **Step 2: Run the test and verify RED**

Expected: missing `holdout_v4.json`.

- [x] **Step 3: Create the frozen manifest**

Use the recorded hashes, truth critical texts and explicit visual regions.

- [x] **Step 4: Run the manifest test to verify GREEN**

Expected: `3 passed`.

### Task 2: Generate And Inspect

**Files:**
- Create: `output/_axure_holdout_v4_2026-10-25/run/<sample>/`

- [x] **Step 1: Generate each sample twice**

- [x] **Step 2: Verify comparison, assets and deterministic bytes**

- [x] **Step 3: Run Axure RP 8 conformance**

### Task 3: Publish And Accept

**Files:**
- Create: `output/_axure_holdout_v4_2026-10-25/run/<sample>/published/`
- Create: `output/_axure_holdout_v4_2026-10-25/run/<sample>/published_reload/`
- Create: `output/_axure_holdout_v4_2026-10-25/run/<sample>/shots/`
- Create: `output/_axure_holdout_v4_2026-10-25/run/<sample>/acceptance.json`

- [x] **Step 1: Publish and reopen-publish all samples**

- [x] **Step 2: Screenshot at the manifest viewport**

- [x] **Step 3: Accept with critical texts, asset counts and critical regions**

- [x] **Step 4: Record initial result before remediation**

### Task 4: Report A-010

**Files:**
- Create:
  `docs/v2_mentor/AXURE_FRESH_HOLDOUT_A010_2026-10-25.md`
- Create: `output/_axure_holdout_v4_2026-10-25/summary.json`
- Modify:
  `docs/v2_mentor/AXURE_ROUTE_LEDGER_2026-10-25.md`
- Modify:
  `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`
- Modify: `README.md`
- Modify: `docs/v2_mentor/README.md`

- [x] **Step 1: Report every gate independently**

- [x] **Step 2: State the exact generalization claim allowed**

- [x] **Step 3: Run full verification**

**Final result:** `pass-unseen-holdout`. All three frozen samples pass object,
critical text, assets, visible regions, visual and reopen gates. The claim is
limited to this frozen holdout; A-011 should review the remaining
current-scope non-claims. Manifest tests pass `4/4`; `tests/v2` passes
`732 passed in 40.43s`; Ruff/format, Node, JSON, conformance and diff-check
pass.
