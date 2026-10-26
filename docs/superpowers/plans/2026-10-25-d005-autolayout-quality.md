# D-005 Auto Layout Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify the frozen real-site layout tree into L1 candidates, L2
static-replay evidence and L3 output-contract perturbations, with explicit
fixed-coordinate fallback reasons.

**Architecture:** A pure evidence module rebuilds the `pIdx` tree, calls the
existing `infer_container()` contract, verifies L2 only when static geometry
can replay, and simulates a bounded local child-growth perturbation for L3.
Unsupported Grid/wrap/order/geometry cases become explicit fixed-coordinate
decisions. Real Figma write/readback remains D-008.

**Tech Stack:** Python 3.12, existing `layout_infer`, `unittest`/pytest, JSON.

**Spec:** `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`

## Global Constraints

- Keep `layout_infer.GEOMETRY_TOLERANCE = 0.6 px`.
- Keep the frozen corpus acceptance geometry tolerance at `2.0 px`.
- L1 means a layout spec was inferred.
- L2 means static child geometry can be replayed by the existing inference.
- L3 in D-005 means a bounded local output-contract perturbation, not live
  Figma or source-browser truth.
- Grid, wrap, reverse/order, float, inline-flow failure, content overflow and
  non-replayable geometry default to fixed coordinates.
- Preserve absolute children as absolute overrides.
- Do not modify D-003 thresholds or D-004 text evidence.
- Do not commit or push.
- Preserve all pre-existing worktree changes.

## Review Focus

- A layout label must not be counted as true flow by itself.
- Geometry-source layouts must not imply CSS semantic behavior.
- Non-uniform gaps must not be called statically replayed.
- Grid/wrap failure must produce fixed fallback, not a guessed linear stack.
- Absolute children must not be pulled into the flow.
- Local sibling reflow must not be reported as parent-height propagation.
- A missing perturbation must remain `not-evaluated`.

---

### Task 1: Classify L1/L2 And Fixed Fallback

**Files:**
- Create: `src/app/services/evidence/dom_layout_quality.py`
- Create: `tests/v2/test_dom_layout_quality.py`

- [x] **Step 1: Write failing classification tests**

Tests must require:

- a vertical CSS flex container earns L1 and L2;
- a Grid container earns fixed fallback with reason `grid`;
- wrap and nonzero order earn fixed fallback reasons;
- a geometry-source non-uniform gap earns L1 but not L2;
- absolute children are excluded from flow members;
- no composite score exists.

- [x] **Step 2: Run focused test to verify RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_dom_layout_quality.py -q
```

Expected: FAIL because the module does not exist.

- [x] **Step 3: Implement L1/L2/fallback classification**

Use `infer_container()`, `uniform_gap()` and direct-child geometry. Return
stable decisions for every container with at least two direct children.

- [x] **Step 4: Run focused test to verify GREEN**

Expected: PASS.

---

### Task 2: Add Bounded L3 Output-Contract Perturbation

**Files:**
- Modify: `src/app/services/evidence/dom_layout_quality.py`
- Modify: `tests/v2/test_dom_layout_quality.py`

- [x] **Step 1: Write failing perturbation tests**

Tests must require:

- vertical local growth moves later siblings by the same delta;
- horizontal local growth moves later siblings on x;
- cross-axis geometry is unchanged;
- geometry-source layouts get `l3=not-evaluated`;
- missing L2 replay gets `l3=not-evaluated`;
- parent propagation remains explicitly `not-evaluated`.

- [x] **Step 2: Run focused test to verify RED**

Expected: FAIL because the simulation is absent.

- [x] **Step 3: Implement the bounded contract**

Use a synthetic `24 px` main-axis growth on the first flow child. Record
expected sibling deltas and actual spec-derived deltas. Do not claim engine
execution or parent resizing.

- [x] **Step 4: Run focused test to verify GREEN**

Expected: PASS.

---

### Task 3: Measure The Frozen Corpus And Freeze Fallback Rules

**Files:**
- Create: `scripts/dom_layout_quality.py`
- Create: `docs/v2_mentor/DOM_LAYOUT_QUALITY_2026-10-25.md`
- Modify: `tests/v2/test_dom_layout_quality.py`

- [x] **Step 1: Add failing report CLI tests**

Require three samples, per-level counts, fixed-fallback reasons and explicit
`figma_runtime=not-evaluated`.

- [x] **Step 2: Implement the CLI**

Read the D-004 enhanced capture root, classify each sample and write one JSON
report.

- [x] **Step 3: Run the report**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_layout_quality.py `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --capture-root output\_dom_text_quality_capture_2026-10-25 `
  --out output\_dom_layout_quality_2026-10-25
```

Expected: report all containers; no unsupported case silently becomes flow.

- [x] **Step 4: Publish the fixed-coordinate policy**

Document:

- L1/L2/L3 definitions;
- per-site and aggregate counts;
- source CSS vs geometry;
- fallback reasons;
- local L3 contract and non-claims;
- remaining real Figma/parent-propagation work for D-008.

---

### Task 4: Update Master Plan And Verify

**Files:**
- Modify: `docs/v2_mentor/DOM_QUALITY_GAP_REGISTER_2026-10-25.md`
- Modify: `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`

- [x] **Step 1: Update gap boundaries**

Record L1/L2 corpus coverage and L3 local output-contract evidence. Keep
DOM-GAP-007/008 open where real Figma/parent propagation remains unproven.

- [x] **Step 2: Update master plan**

Set D-005 to `complete-current-scope`, activate D-006 and record evidence.

- [x] **Step 3: Run mandatory regression**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
node --check figma_bridge\code.js
```

Expected: all tests pass and syntax check exits 0.
