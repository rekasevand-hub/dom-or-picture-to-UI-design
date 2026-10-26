# Axure A-009 Rendered Region Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair A-008's stale iframe input and add a rendered critical-region
gate so missing visible text cannot pass on widget labels alone.

**Architecture:** Keep the existing frame-coordinate collector, which already
places accessible iframe text at the host offset. Regenerate the iframe
DesignSpec from source, extend Axure acceptance with region-level ink checks,
and verify the repaired route with a real publish. Treat the partial-asset
count as a manifest contract correction, not an output repair.

**Tech Stack:** Python 3.11, Playwright, OpenCV, Axure RP 8, pytest.

**Spec:** `docs/v2_mentor/AXURE_FRESH_HOLDOUT_A008_2026-10-25.md`

**Execution status:** `complete-current-scope` on 2026-10-25.

## Global Constraints

- Do not modify A-008 frozen evidence or change its result.
- A-009 repaired samples are not a new untouched holdout.
- Use TDD: add the failing region test before the acceptance implementation.
- If current frame coordinates already pass, record a stale-input repair rather
  than inventing an unnecessary source change.
- Keep label text and visible rendered region as separate evidence.
- Do not change composite thresholds or hide failures with overall pixel score.
- Do not commit or push.

## File Structure

- `src/app/services/structure/frames.py` owns frame-coordinate projection and
  remains unchanged unless a new failing regression disproves current tests.
- `src/app/services/evidence/axure_acceptance.py` owns region-level visibility
  acceptance.
- `scripts/axure_acceptance.py` exposes repeated region arguments.
- `tests/v2/test_axure_acceptance.py` owns positive and fail-closed region tests.
- `output/_axure_a009_2026-10-25/` owns refreshed inputs and repaired evidence.

## Review Focus

- A reference region with real ink and a blank render must fail even when total
  within-30 is above the normal visual threshold.
- A region check must use the supplied screenshot pair and fail closed on
  invalid geometry or unreadable images.
- Existing non-region acceptance tests must remain compatible.
- The refreshed iframe DesignSpec must place accessible child text at the host
  offset rather than the title.
- The partial asset contract must preserve two declared/displayed images and
  distinguish them from original-source identity.

### Task 1: Refresh The Iframe Input From Current Capture

**Files:**
- Create: `output/_axure_a009_2026-10-25/prepared/iframe_manifest.json`
- Create: `output/_axure_a009_2026-10-25/prepared/iframe/12_design.json`

**Interfaces:**
- Consumes: `scripts/p1_canonical_output_fidelity.py`.
- Produces: a current-source iframe DesignSpec and screenshot with frozen hashes.

- [x] **Step 1: Verify the current frame-coordinate regression**

Run the existing integration test for accessible iframe content after main
content. Expected: pass with `x≈18`, `y≈132`.

- [x] **Step 2: Generate the iframe sample from the current collector**

Use a one-sample canonical manifest and a new evidence root.

- [x] **Step 3: Assert the refreshed normalised text geometry**

Expected: `Accessible iframe content` is inside the left frame at approximately
`(18,132)`, not overlapping the title at `(16,37)`.

### Task 2: Add Rendered Critical-Region Verification

**Files:**
- Modify: `src/app/services/evidence/axure_acceptance.py`
- Modify: `scripts/axure_acceptance.py`
- Test: `tests/v2/test_axure_acceptance.py`

**Interfaces:**
- `evaluate_published_axure(..., critical_regions: Sequence[Mapping] = ())`
- Region input keys: `name`, `x`, `y`, `width`, `height`, optional
  `min_reference_ink_pct`, `min_render_to_reference_ink_ratio`.
- CLI: repeat `--critical-region name,x,y,width,height`.

- [x] **Step 1: Write the blank-region failing test**

Create a reference image with black text pixels in a region and a blank render.
Expect `critical-region-missing` and overall fail.

- [x] **Step 2: Run the focused test and verify RED**

Expected: `critical_regions` is not accepted or no region failure is produced.

- [x] **Step 3: Implement region ink measurement**

Use the same screenshot pair as visual acceptance. Measure grayscale ink
percentage using threshold `200`; require the render ink ratio to be at least
`0.25` of reference ink when reference ink is at least `0.5%`.

- [x] **Step 4: Add CLI parsing and preserve prior behavior**

Regions omitted from existing callers must produce `not-evaluated`, not failure.

- [x] **Step 5: Run focused acceptance tests**

Expected: all existing acceptance tests plus the new positive/negative region
tests pass.

### Task 3: Correct The Asset-Count Contract

**Files:**
- Test: `tests/v2/test_axure_holdout_v3_manifest.py`
- Create: `output/_axure_a009_2026-10-25/partial-asset/contract.json`

**Interfaces:**
- Consumes: P1 partial-asset truth and refreshed DesignSpec.
- Produces: `declared_asset_count=2`, `expected_renderable_asset_count=2`,
  `missing_original_asset_count=1`.

- [x] **Step 1: Freeze the corrected contract in A-009 evidence**

Do not edit the A-008 manifest. Record that the original A-008 expected count
was an evaluation mismatch.

- [x] **Step 2: Verify the refreshed design has two displayed image payloads**

Expected: two ImageBoxes, two published hashes, no unexpected hashes.

### Task 4: Re-run The Repaired Axure Evidence

**Files:**
- Create: `output/_axure_a009_2026-10-25/iframe/`
- Create: `output/_axure_a009_2026-10-25/partial-asset/`

- [x] **Step 1: Generate deterministic `.rp` artifacts twice**

- [x] **Step 2: Publish and reopen with Axure RP 8**

- [x] **Step 3: Capture screenshots and run acceptance with critical regions**

Expected iframe: visible iframe-content region passes instead of only label
text. Expected partial asset: exact two-asset contract passes with pixel match.

- [x] **Step 4: Run conformance and full regression**

### Task 5: Publish A-009 Evidence

**Files:**
- Create:
  `docs/v2_mentor/AXURE_A009_RENDERED_REGION_REPAIR_2026-10-25.md`
- Create: `output/_axure_a009_2026-10-25/summary.json`
- Modify:
  `docs/v2_mentor/AXURE_ROUTE_LEDGER_2026-10-25.md`
- Modify:
  `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`
- Modify: `README.md`
- Modify: `docs/v2_mentor/README.md`

- [x] **Step 1: State the repaired scope and remaining non-claims**

- [x] **Step 2: Require a new untouched holdout before any generalization claim**

**Final result:** `complete-current-scope`. Acceptance tests pass `11/11`;
the refreshed iframe DesignSpec places accessible text at `(18,133)`; the
repaired iframe and corrected partial-asset artifacts pass real publish,
reopen, conformance and acceptance. The new visible-region gate correctly
fails the stale A-008 render. `tests/v2` passes
`728 passed in 41.66s`; Ruff/format, Node, JSON, conformance and diff-check
pass. A-010 is required for a fresh untouched holdout.
