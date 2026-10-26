# D-004 Text And Font Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure content, linebreak, text box, baseline and glyph identity as
independent dimensions on the frozen React/Dushu/Shoelace corpus, close
measurable capture gaps and keep unprovable identity claims explicitly open.

**Architecture:** A pure text-quality evaluator consumes captured DOM and a
new browser-derived baseline/font probe. DOM capture records baseline metrics
from browser Canvas font metrics and probes one representative node for each
unique computed font style. A report script applies the frozen thresholds and
never collapses dimensions into a composite score.

**Tech Stack:** Python 3.12, `unittest`/pytest, Chromium Playwright, CDP
platform-font API, JSON.

**Spec:** `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`

## Global Constraints

- Use the D-003 frozen corpus and its `2.0 px` text-box and `1.0 px` baseline
  thresholds; do not change them after observing results.
- Critical text remains a `100%` hard check.
- A Canvas-font-metric baseline is `derived`, not direct glyph-baseline truth.
- `platformFonts` proves browser-resolved faces and glyph counts, not final
  glyph-outline identity.
- Mixed-font nodes remain `ambiguous-platform-font`; do not pick one face.
- Final glyph identity remains `not-evaluated` unless a stronger source exists.
- No Figma quality claim; D-008 owns write/readback acceptance.
- Do not commit or push.
- Preserve all pre-existing worktree changes.

## Review Focus

- Removing all whitespace for content comparison must not hide changed letters.
- Joining browser lines must not invent or delete visible content.
- Text paint boxes extending above a small container must not be called a
  wrong text box without separating paint extent from layout box.
- A derived baseline must not be reported as measured source-glyph truth.
- Representative font probing must cover unique styles without assigning a
  multi-face result to one face.
- A missing probe must remain `not-evaluated`, not silently pass.
- Dynamic/critical text checks must stay independent of visual similarity.

---

### Task 1: Build The Five-Dimension Text Evaluator

**Files:**
- Create: `src/app/services/evidence/dom_text_quality.py`
- Create: `tests/v2/test_dom_text_quality.py`

**Interfaces:**
- Produces:
  - `evaluate_text_nodes(dom: list[dict], thresholds: dict) -> dict`
  - `canonical_text(value: str) -> str`

- [x] **Step 1: Write failing evaluator tests**

Tests must require independent keys:

```text
content
linebreak
box
baseline
glyph
```

and verify:

- whitespace-normalized complete content passes;
- missing/changed text fails content;
- multiple measured lines pass linebreak;
- a line joining mismatch fails linebreak even when content characters pass;
- text box within `2.0 px` passes and a larger box delta fails;
- Canvas-derived baseline inside the box is `derived`, not `pass`;
- a single `platformFonts` face is `face-observed`, multiple faces are
  `ambiguous`, absent evidence is `not-evaluated`;
- final glyph identity is always `not-evaluated` in this scope;
- no composite score exists.

- [x] **Step 2: Run focused test to verify RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_dom_text_quality.py -q
```

Expected: FAIL because the module does not exist.

- [x] **Step 3: Implement the evaluator**

Use canonical content that strips all whitespace for completeness, while
linebreak compares line-boundary signatures separately. Use `textEmBox` for
the layout box and keep `textLines[].box` as paint evidence. Baseline is
accepted only from `textBaseline.method == "canvas-font-metrics"`.

- [x] **Step 4: Run focused test to verify GREEN**

Expected: PASS.

---

### Task 2: Add Browser Baseline And Representative Font Evidence

**Files:**
- Modify: `src/app/services/structure/capture.py`
- Modify: `src/app/services/structure/font_provenance.py`
- Modify: `tests/v2/test_p1_dom_text_geometry.py`
- Modify: `tests/v2/test_p1_font_provenance.py`

**Interfaces:**
- Produces in captured text nodes:
  - `textBaseline`: Y, ascent, descent, method and line count;
  - representative `platformFonts` for one node per unique computed font
    style.

- [x] **Step 1: Write failing capture/font tests**

Test a local browser page with:

- two line boxes and a derived baseline inside both boxes;
- two different font style combinations, each represented once;
- generic-stack behavior preserved;
- mixed platform-font results still ambiguous.

- [x] **Step 2: Run focused tests to verify RED**

Expected: FAIL because `textBaseline` and representative style probes are
absent.

- [x] **Step 3: Implement capture evidence**

Use a browser Canvas context with the computed `font-style`, `font-weight`,
`font-size` and family stack to read `fontBoundingBoxAscent/Descent` with
`actualBoundingBox` fallback. Mark the result
`derived-browser-font-metrics`.

Mark only the first text node for each unique `style|weight|size|family`
combination for CDP platform-font lookup.

- [x] **Step 4: Run focused tests to verify GREEN**

Expected: PASS.

---

### Task 3: Measure The Frozen Corpus

**Files:**
- Create: `scripts/dom_text_quality.py`
- Create: `docs/v2_mentor/DOM_TEXT_FONT_QUALITY_2026-10-25.md`

- [x] **Step 1: Add a report CLI test**

The CLI must load the frozen corpus manifest, locate `00_dom.json` captures,
write a report and exit nonzero when a hard dimension fails.

- [x] **Step 2: Implement the CLI**

Inputs:

```text
--manifest tests/fixtures/dom_quality/real_site_corpus_v1.json
--capture-root output/_dom_quality_corpus_2026-10-25
--out output/_dom_text_quality_2026-10-25
```

- [x] **Step 3: Capture enhanced evidence**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_quality_corpus.py capture `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --out output\_dom_text_quality_capture_2026-10-25
```

Expected: all three samples remain stable `content`.

- [x] **Step 4: Run text quality measurement**

Run the CLI against the enhanced capture root.

Expected: content, linebreak and box report measured coverage; baseline report
is derived/partial; glyph identity remains explicitly not evaluated.

- [x] **Step 5: Fix only evidenced failures**

If content, linebreak or box fails on a required sample, add a focused
regression first and fix the responsible capture/wrap path. Do not change the
frozen thresholds.

---

### Task 4: Publish D-004 And Advance

**Files:**
- Modify: `docs/v2_mentor/DOM_QUALITY_GAP_REGISTER_2026-10-25.md`
- Modify: `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`

- [x] **Step 1: Publish the independent dimension report**

Document content, linebreak, box, baseline/derived and glyph/not-evaluated
coverage separately, including per-sample evidence paths.

- [x] **Step 2: Update gap statuses**

Close DOM-GAP-003 only for the frozen corpus if all hard checks pass.
Mark DOM-GAP-004 `complete-current-scope` only as derived baseline reporting,
not glyph-baseline proof. DOM-GAP-006 remains open for exact per-glyph identity.

- [x] **Step 3: Update master plan**

Set D-004 to `complete-current-scope`, activate D-005 and record exact
verification.

- [x] **Step 4: Run mandatory regression**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
node --check figma_bridge\code.js
```

Expected: all tests pass and syntax check exits 0.
