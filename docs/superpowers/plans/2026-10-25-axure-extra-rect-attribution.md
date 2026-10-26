# Axure Extra Rect Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attribute the extra `360x96` Rect in `AX6-DOM-TEXTFLOW` to a real
renderer behavior and correct object comparison without changing visual
output.

**Architecture:** Keep the Axure writer unchanged. Extend the read-only
comparator so an unlabeled Rect is auxiliary only when it matches the outer
geometry of an already matched source Text widget and consumes that text's
single background allowance.

**Tech Stack:** Python 3.11, unittest/pytest, Axure RP 8 inspection,
DesignSpec, Playwright-produced acceptance evidence.

**Spec:**
`docs/v2_mentor/AXURE_HOLDOUT_V2_ACCEPTANCE_2026-10-25.md`

**Execution status:** `complete-current-scope` on 2026-10-25.

## Global Constraints

- A-006 remains `fail-unseen-holdout`; remediation cannot retroactively pass it.
- The extra Rect is a derived auxiliary layer, not a source DesignSpec node.
- Do not treat every unlabeled Rect as auxiliary.
- Do not change thresholds, source samples or the Axure writer.
- Do not overwrite A-006 evidence.
- Do not commit or push.
- A fresh untouched holdout is required before claiming generalization.

## File Structure

- `src/app/services/rendering/axure/evidence.py` owns object comparison and
  auxiliary-layer attribution.
- `tests/v2/test_axure_evidence.py` owns comparator regression behavior.
- `output/_axure_holdout_v2_2026-10-25/a007_retriage/AX6-DOM-TEXTFLOW/`
  owns independent A-007 artifact and comparator evidence.
- `docs/v2_mentor/AXURE_EXTRA_RECT_ATTRIBUTION_2026-10-25.md` owns the
  diagnosis, result and claim boundary.

## Review Focus

- An unlabeled near-miss Rect must remain `widget-extra`.
- Two unlabeled Rect widgets must not both consume one matched Text.
- A legitimate styled-text background must not hide a missing primary widget.
- Comparator repair must not change the `.rp` bytes or published pixels.
- A-006 must remain a recorded failure after A-007 is complete.

### Task 1: Reproduce The Classification Failure

**Files:**
- Test: `tests/v2/test_axure_evidence.py`

**Interfaces:**
- Consumes: `compare_rp_to_design(report, design, *, route=None) -> dict`
- Produces: a failing regression for styled Text with non-neutral
  `fillColor` and `borderWidth=1`, plus a negative regression for neutral Text.

- [x] **Step 1: Add the styled-text background test**

Assert `comparison["ok"] is True`,
`comparison["auxiliary_widget_count"] == 1`, and one
`comparison["auxiliary_widgets"]` row mapped to source label `Styled text`.

- [x] **Step 2: Run the focused test and verify RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_axure_evidence.py::AxureEvidenceTests::test_styled_text_background_rect_is_an_auxiliary_widget -q
```

Expected: fail because the unlabeled Rect is reported as `widget-extra`.

- [x] **Step 3: Add the neutral-text negative regression**

Append an unlabeled Rect matching the neutral `Title` outer geometry. Assert
that comparison stays false and the Rect remains `widget-extra`.

- [x] **Step 4: Verify the negative test is RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_axure_evidence.py::AxureEvidenceTests::test_unlabeled_rect_does_not_explain_neutral_text_background -q
```

Expected: fail because the initial attribution candidate list includes every
matched Text.

### Task 2: Implement Narrow Attribution

**Files:**
- Modify: `src/app/services/rendering/axure/evidence.py`

**Interfaces:**
- Produces: `_match_text_background(rect, candidates) -> str | None`.
- Produces: comparison field `auxiliary_widgets: list[dict]`.

- [x] **Step 1: Restrict candidates to renderable styled backgrounds**

Add an expected-widget flag only when the source Text has a non-neutral fill
matching `adapter_base`'s background emission condition.

- [x] **Step 2: Record matched Text outer geometry**

Add a candidate only after the corresponding Text widget has matched.

- [x] **Step 3: Match and consume one unlabeled Rect**

Accept only exact-in-tolerance `x`, `y`, `width` and `height` matches within
`0.5` px. Set the candidate to `None` after use.

- [x] **Step 4: Emit an auditable mapping**

Return `page`, `source_label`, `kind`, and `geometry` for each accepted
auxiliary widget.

- [x] **Step 5: Run the focused and evidence suites**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_axure_evidence.py -q
```

Expected: `10 passed`.

### Task 3: Recheck The Frozen A-006 Sample

**Files:**
- Create:
  `output/_axure_holdout_v2_2026-10-25/a007_retriage/AX6-DOM-TEXTFLOW/`

- [x] **Step 1: Regenerate independently**

Use the frozen `12_design.json`, page name
`A006 Mixed Text Flow Axure`, and `--generate-twice`.

- [x] **Step 2: Compare the artifact hash**

Expected: `acc356d7a5d30dcdc2b5d47294d1007e34e9bffc23d3c26ee6cbf15cc946913c`,
unchanged from A-006.

- [x] **Step 3: Inspect the corrected comparison**

Expected: `ok=true`, `auxiliary_widget_count=1`, no mismatches, and source
label `section "Flow block keeps na…"`.

- [x] **Step 4: Reuse published acceptance without republishing**

Evaluate the identical `.rp` against the existing A-006 publish directory.
Expected: `status=pass`, critical text `3/3`, visual status `measured`.

- [x] **Step 5: Verify Axure RP 8 conformance**

Expected: `c1=8/8`, `stores=7/7`, one registered page, `[ok]`.

### Task 4: Publish Evidence And Preserve Claim Boundary

**Files:**
- Create:
  `docs/v2_mentor/AXURE_EXTRA_RECT_ATTRIBUTION_2026-10-25.md`
- Modify:
  `docs/v2_mentor/AXURE_ROUTE_LEDGER_2026-10-25.md`
- Modify:
  `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`
- Modify: `README.md`
- Modify: `docs/v2_mentor/README.md`

- [x] **Step 1: Record root cause and fix**

- [x] **Step 2: Keep A-006 failed and name the fresh-holdout requirement**

- [x] **Step 3: Run final regression and artifact checks**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
C:\Users\lzq\.conda\envs\omni\python.exe -m ruff check src/app/services/rendering/axure/evidence.py tests/v2/test_axure_evidence.py
C:\Users\lzq\.conda\envs\omni\python.exe -m ruff format --check src/app/services/rendering/axure/evidence.py tests/v2/test_axure_evidence.py
node --check figma_bridge\code.js
git diff --check
```

- [x] **Step 4: Point the route ledger at A-008**

A-008 must use samples not used by A-006 or A-007 before making a
generalization claim.

**Final verification:** focused Axure evidence tests `10 passed`; `tests/v2`
`722 passed in 41.23s`; touched-file Ruff check/format, Node syntax,
`git diff --check` and one-file Axure RP 8 conformance pass.
