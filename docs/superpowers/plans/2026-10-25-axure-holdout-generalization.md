# Axure Holdout Generalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate both Axure routes on samples not used for A-002/A-003
tuning, with frozen inputs and thresholds.

**Architecture:** Reuse the existing DOM capture corpus, image MVP strategy,
shared IR, Axure writer and independent published acceptance. Add only a
holdout manifest/runner and fix defects exposed by holdout execution.

**Tech Stack:** Python 3.11, frozen DOM captures, image MVP DesignSpec, Axure
RP 8, Playwright, `design-ir/2.0`.

**Specs:**

- `docs/v2_mentor/AXURE_DOM_ACCEPTANCE_2026-10-25.md`;
- `docs/v2_mentor/AXURE_IMAGE_ACCEPTANCE_2026-10-25.md`;
- `docs/v2_mentor/DOM_QUALITY_CORPUS_2026-10-25.md`.

**Execution status:** `complete-current-scope`, result
`partial-post-holdout-tuning` on 2026-10-25.

## Frozen Holdout

- DOM `DQ-R01` React: not used for Axure tuning.
- DOM `DQ-R03` Shoelace: not used for Axure tuning.
- Image `AX-IMG-H01`: asset-evidence screenshot, not IMG-MVP-01.
- Excluded tuning samples: `DQ-R02`, `IMG-MVP-01`.
- No threshold or sample substitution after seeing Axure results.

Thresholds:

- critical text: `100%`;
- page/package/object mapping: `100%`;
- expected image hashes: `100%`;
- deterministic `.rp`: byte-identical;
- size match: required;
- visual within-30: `>=90%` per sample.

## Review Focus

- The holdout must not silently fall back to a tuning sample.
- DOM DesignSpec preparation must use only frozen captures.
- Image holdout must traverse the existing image strategy, not DOM fixtures.
- A single sample failure must remain visible; no average hides it.
- Unsupported Axure capabilities cannot be upgraded by holdout success.

### Task 1: Freeze Manifest And Validation

**Files:**
- Create: `tests/fixtures/axure_holdout/holdout_v1.json`
- Create: `tests/fixtures/axure_holdout/image_asset_evidence.png`
- Create: `tests/fixtures/axure_holdout/image_asset_evidence.truth.json`
- Create: `tests/v2/test_axure_holdout_manifest.py`

- [x] **Step 1: Write failing manifest tests**

Assert:

- exactly DQ-R01, DQ-R03 and AX-IMG-H01 are required;
- DQ-R02 and IMG-MVP-01 are explicitly excluded;
- 90% visual and 100% critical/asset thresholds are frozen;
- every input path exists and every declared SHA-256 matches.

- [x] **Step 2: Run RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_axure_holdout_manifest.py -q
```

- [x] **Step 3: Create the frozen image fixture and manifest**

Copy the existing asset-evidence screenshot into the holdout fixture directory
before measuring Axure output. Build the truth manifest from visible critical
text and measured image size/hash.

- [x] **Step 4: Run focused tests to GREEN**

### Task 2: Prepare Holdout Designs

**Files:**
- Reuse: `scripts/dom_figma_acceptance.py prepare`
- Reuse: `scripts/image_figma_mvp.py --prepare-only`
- Update: `output/_axure_holdout_2026-10-25/`

- [x] **Step 1: Prepare DQ-R01 and DQ-R03**

Use only:

```text
tests/fixtures/dom_quality/real_site_corpus_v1.json
output/_dom_quality_corpus_verify_2026-10-25/
```

- [x] **Step 2: Prepare AX-IMG-H01**

Run the existing image MVP preparation on the frozen screenshot and truth.
If Grounding is unavailable, mark the image holdout `blocked-environment`; do
not substitute DOM design data.

- [x] **Step 3: Freeze prepared DesignSpec hashes**

Record every prepared design hash before Axure measurement.

### Task 3: Run Axure Holdouts

**Files:**
- Reuse: `scripts/axure_dom_output.py`
- Reuse: `scripts/image_axure_mvp.py`
- Reuse: `scripts/axure_acceptance.py`
- Update: `output/_axure_holdout_2026-10-25/`

- [x] **Step 1: Generate each deterministic `.rp` twice**

- [x] **Step 2: Inspect actual object graphs**

Record page GUID, widget classes, geometry and image hashes.

- [x] **Step 3: Open, reopen and publish each `.rp` in Axure RP 8**

- [x] **Step 4: Screenshot and independently accept each sample**

Retain per-sample results and failures. Do not calculate a masking composite.

### Task 4: Fix Holdout Defects By TDD

**Files:**
- Modify only the route, writer, adapter or acceptance modules implicated by
  failures.
- Add a regression test for each behavioral fix.

- [x] **Step 1: Reproduce each failed holdout with a focused test**

- [x] **Step 2: Implement the minimal fix**

- [x] **Step 3: Re-run the failed sample and regression test**

- [x] **Step 4: Stop changing thresholds or sample membership**

### Task 5: Acceptance And Documentation

**Files:**
- Create: `docs/v2_mentor/AXURE_HOLDOUT_ACCEPTANCE_2026-10-25.md`
- Modify: `docs/v2_mentor/AXURE_ROUTE_LEDGER_2026-10-25.md`
- Modify: `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`
- Modify: `README.md`
- Modify: `docs/v2_mentor/README.md`

- [x] **Step 1: Report each sample independently**

- [x] **Step 2: State holdout pass, partial or fail**

- [x] **Step 3: Run full verification**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
C:\Users\lzq\.conda\envs\omni\python.exe -m ruff check <A-005 touched files>
C:\Users\lzq\.conda\envs\omni\python.exe -m ruff format --check <A-005 touched files>
node --check figma_bridge\code.js
git diff --check
C:\Users\lzq\.conda\envs\omni\python.exe scripts/axure_rp8_conform.py <each final .rp>
```
