# D-008 Over-30 Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attribute the remaining DQ-R02 over-30 pixels to concrete nodes and
styles, then repair only a proven systemic rendering cause.

**Architecture:** An offline diagnostic module joins DesignSpec elements to
Figma readback nodes, compares local reference/render crops, and tests small
integer shifts. It reports node hotspots, text-style aggregates and shift
distributions without writing Figma. Only a confirmed root cause proceeds to a
TDD renderer fix and a new real Figma run.

**Tech Stack:** Python 3.12, OpenCV, NumPy, existing Figma acceptance matchers,
`unittest`/pytest, JSON.

**Spec:** `docs/v2_mentor/DOM_QUALITY_EXIT_REVIEW_2026-10-25.md`

## Global Constraints

- Frozen visual thresholds remain `mean <= 3.0`, `ink_mean <= 100`,
  `over-30 <= 2.5%`, bad-pixel ratio `<= 3%` and size match required.
- Do not mask, crop, blur or exclude diff regions to manufacture a pass.
- Do not change corpus v1 or its thresholds.
- Offline attribution performs no Figma writes.
- Any renderer fix requires a failing regression test first.
- Real reproof must use a new owned frame at a new origin.
- Preserve all pre-existing worktree changes; do not commit or push.

## Review Focus

- Pixel attribution must use actual image masks, not element counts.
- Shift sign must mean the observed render offset relative to reference.
- Aggregates must not hide large per-node failures.
- Text anti-aliasing must remain distinguishable from positional offset.
- Background residual pixels must not silently disappear from the denominator.
- A diagnostic result must not be presented as a quality pass.

---

### Task 1: Build Offline Diff Attribution

**Files:**
- Create: `src/app/services/evidence/dom_figma_diff_attribution.py`
- Create: `tests/v2/test_dom_figma_diff_attribution.py`

**Interfaces:**
- Produces:
  `build_diff_attribution(design, readback, reference_png, render_png,
  threshold=30, search_radius=2) -> dict`.
- Produces per-node `over30`, `ratio`, local `best_dx`, `best_dy`, style key and
  aggregate text-shift counts.

- [x] **Step 1: Write failing tests**

Require:

- one-pixel render shift reports `best_dx=1` or `best_dy=1`;
- identical crops report zero shift;
- per-style over-30 aggregates are independent;
- large per-node failures remain in the node list;
- thresholds and total denominator are retained;
- no Figma runtime claim is made.

- [x] **Step 2: Run focused test to verify RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_dom_figma_diff_attribution.py -q
```

- [x] **Step 3: Implement attribution**

Reuse acceptance matching/global-box helpers. Search `dx/dy` only inside the
declared radius and report negative results honestly.

- [x] **Step 4: Run focused test to verify GREEN**

Expected: PASS.

---

### Task 2: Analyze Real DQ-R02 Evidence

**Files:**
- Create: `scripts/dom_figma_diff_attribution.py`
- Create runtime output under `output/_dom_figma_over30_attribution/`

- [x] **Step 1: Add failing CLI test**

Require direct-script execution and JSON paths for design, readback, reference
and render.

- [x] **Step 2: Implement the CLI**

Write `summary.json` with total, per-node, per-style and shift summaries.

- [x] **Step 3: Run against frame `71:1230` evidence**

Expected: identify whether residual is positional, style-specific or
anti-aliasing-heavy.

---

### Task 3: Repair Only A Proven Root Cause

**Files:**
- Decide from diagnostic evidence; likely only one of:
  `src/app/services/rendering/adapter_base.py`,
  `figma_bridge/code.js`,
  `src/app/services/som/direct_design.py`
- Add the matching regression test.

- [x] **Step 1: Record the single hypothesis and affected pixels**
- [x] **Step 2: Write a failing test reproducing the cause**
- [x] **Step 3: Implement the smallest fix**
- [x] **Step 5: Run focused tests**
- [x] **Step 6: If a renderer fix exists, run a new real Figma acceptance at a
  new origin and compare frozen metrics**

If no honest systemic fix exists, retain `partial-not-pass` and document the
anti-aliasing limitation.

---

### Task 4: Final Verification And Status

- [x] **Step 1: Update D-008/D-009 reports with the attribution result**
- [x] **Step 2: Run `python -m pytest tests/v2 -q`**
- [x] **Step 3: Run `node --check figma_bridge\code.js`**
- [x] **Step 4: Record whether any claim or phase gate changed**

## Execution Evidence

Attribution:

```text
prior frame: 71:1230
total over-30: 96,142 / 3,663,360
ratio: 2.624421%
unmatched: 458
excess over allowance: about 4,558
all-node best-independent-shift ratio: 2.533221%
```

The best-shift upper bound still failed, and shifts were heterogeneous, so no
per-node fitting was applied.

Root cause and regression:

- single-line text received a browser-measured line-box origin and a second
  Figma pixel line-height offset;
- `tests/v2/test_figma_adapter_edits.py` first failed with `y=51` instead of
  measured `y=56`, then passed after the Figma-only line-box fix;
- multi-line text keeps explicit line height and line break behavior.

Real reproof:

```text
frame: 73:2271
origin: [12000, 0]
mean: 1.707225
ink mean: 9.288541
over-30: 2.461647%
bad-pixel ratio: 2.461647%
size: pass
```

The visual gate changed to pass. D-009 remains `partial-not-pass` because the
asset dimension is partial and linebreak, baseline and glyph identity remain
not evaluated. No threshold changed and the image phase remains not admitted.

Post-fix attribution:

```text
output: output/_dom_figma_over30_attribution_after_linebox/summary.json
over-30: 90,179
ratio: 2.461647%
unmatched: 2
text best shift 0,0: 72 / 91
```

## Self-Review

- The first stage is diagnostic only.
- No threshold changes or visual masking are planned.
- Shift sign and denominator are explicit.
- Renderer changes require RED→GREEN.
- No commit or push step exists.
