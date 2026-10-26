# D-008 Real Figma DOM Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce real Figma write, readback, PNG export and independent
visual/structure/edit/asset evidence for one representative frozen real-site
sample, without modifying existing user frames.

**Architecture:** Build a DesignSpec from the frozen DQ-R02 DOM capture and
screenshot, render it into a uniquely positioned `D008` Figma frame, read back
the complete owned frame, export PNG, run native-text and image-fill probes,
then evaluate the frozen thresholds. The report keeps visual, structure, edit,
asset and layout dimensions separate.

**Tech Stack:** Python 3.12, existing DOM provider/direct design, Figma bridge,
Playwright-frozen DQ-R02 capture, Pillow/OpenCV, `unittest`/pytest.

**Spec:** `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`

## Global Constraints

- Required sample: `DQ-R02` (`Dushu`) from `dom-quality-real-sites/1.0`.
- Use the existing frozen `00_dom.json`, `00_screenshot.png`, viewport and
  thresholds; do not recapture or modify the corpus.
- Create only a uniquely named `D008` frame at a non-overlapping coordinate.
- Never remove or mutate `P5-PILOT-ROOT` or unrelated user nodes.
- Do not use screenshot-only or generated assets as original evidence.
- Real write/readback/export must occur in the currently connected Figma
  document.
- Keep visual, content, geometry, text, edit, asset and layout independent.
- Preserve existing worktree changes; do not commit or push.
- If bridge/plugin availability fails, record `blocked-environment`; no
  simulated Figma success.

## Review Focus

- A real frame must be read back by node ID, not inferred from write payload.
- Export must come from that same frame after readback.
- Native text editing must modify and restore one real text node.
- Image replacement must preserve node type/fill mode and restore the payload.
- Missing/reference assets must remain partial, not pass as originals.
- Layout evidence must not claim parent propagation solely from a static frame.
- The report must not treat a large visual area as compensating for text or
  structure defects.
- Existing user frames must remain untouched.

---

### Task 1: Build Frozen DQ-R02 DesignSpec

**Files:**
- Create: `src/app/services/evidence/dom_figma_acceptance.py`
- Create: `tests/v2/test_dom_figma_acceptance.py`

**Interfaces:**
- Produces:
  `build_frozen_sample_design(corpus: Mapping, capture_root: Path,
  sample_id: str, output_dir: Path, canvas_origin=(1600, 0)) -> dict`.
- Produces an evidence manifest with source hashes, design hash, sample ID,
  dimensions, node counts and output artifact paths.

- [x] **Step 1: Write failing builder tests**

Require:

- DQ-R02 is selected from the frozen manifest;
- DOM provider -> SoM -> direct design path is used without network;
- the DesignSpec is uniquely named `D008 DQ-R02 ...`;
- canvas origin is non-overlapping;
- design contains native text and image elements;
- source DOM/screenshot hashes are retained;
- an unknown sample or missing artifact fails closed.

- [x] **Step 2: Run focused test to verify RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_dom_figma_acceptance.py -q
```

Expected: FAIL because the module does not exist.

- [x] **Step 3: Implement frozen design construction**

Reuse `DomProvider`, graph helpers, `annotate_som`, `build_direct_design`, and
existing crop/materialization behavior. Do not recapture the page.

- [x] **Step 4: Run focused test to verify GREEN**

Expected: PASS.

---

### Task 2: Respect Canvas Origin During Write

**Files:**
- Modify: `src/app/services/rendering/adapter_base.py`
- Modify: `tests/v2/test_dom_figma_acceptance.py`

**Interfaces:**
- `canvas.x` and `canvas.y` become optional frame origin fields; default remains
  `0,0` for compatibility.

- [x] **Step 1: Write failing origin test**

Require a recording adapter to receive the configured root frame x/y while
child absolute geometry is unchanged.

- [x] **Step 2: Run focused test to verify RED**

Expected: FAIL because `_render_page` hardcodes `0,0`.

- [x] **Step 3: Implement optional canvas origin**

Read `canvas.x/y` with zero defaults. No other rendering behavior changes.

- [x] **Step 4: Run focused test to verify GREEN**

Expected: PASS and existing rendering regressions remain green.

---

### Task 3: Execute Real Figma Write/Readback/Export And Probes

**Files:**
- Create: `scripts/dom_figma_acceptance.py`
- Modify: `tests/v2/test_dom_figma_acceptance.py`

**Interfaces:**
- CLI modes:
  `prepare` (offline DesignSpec), `run` (real Figma), `report` (offline
  acceptance from captured artifacts).
- Real run outputs:
  `design.json`, `readback.json`, `export.png`, `text_edit_probe.json`,
  `asset_probe.json`, `image_report.json`, `summary.json`.

- [x] **Step 1: Write failing orchestration tests**

Require:

- bridge unavailable becomes `blocked-environment`;
- frame ID is obtained from the actual created root;
- readback begins at that frame ID;
- export begins at that same frame ID;
- text probe changes one real text node and restores it;
- asset probe changes one real image fill and restores it;
- unrelated/user node IDs are never deletion targets.

- [x] **Step 2: Run focused test to verify RED**

Expected: FAIL because CLI/orchestration does not exist.

- [x] **Step 3: Implement the bounded real runner**

Use an explicit keep-alive adapter. Do not run prefix cleanup. Persist failures
and partial artifacts.

- [x] **Step 4: Run focused test to verify GREEN**

Expected: PASS.

---

### Task 4: Evaluate And Publish Real Evidence

**Files:**
- Create: `scripts/dom_figma_acceptance.py` report path
- Create: `docs/v2_mentor/DOM_FIGMA_ACCEPTANCE_2026-10-25.md`
- Modify: `docs/v2_mentor/DOM_QUALITY_GAP_REGISTER_2026-10-25.md`
- Modify: `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`

- [x] **Step 1: Prepare DQ-R02**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_figma_acceptance.py prepare `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --capture-root output\_dom_text_quality_capture_2026-10-25 `
  --sample-id DQ-R02 `
  --out output\_dom_figma_acceptance_2026-10-25
```

- [x] **Step 2: Run real Figma acceptance**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_figma_acceptance.py run `
  --sample-root output\_dom_figma_acceptance_2026-10-25 `
  --out output\_dom_figma_acceptance_2026-10-25
```

Expected: real D008 frame ID, full readback, PNG export and completed probes.

- [x] **Step 3: Report dimensions independently**

Evaluate:

- critical text/content;
- structure geometry;
- text content/linebreak/box/baseline/glyph-status;
- native text edit;
- asset display/source/replacement status;
- visual metrics;
- Auto Layout static/runtime status;
- export existence/size.

Do not use a composite score.

- [x] **Step 4: Update status and run mandatory verification**

Mark D-008 `complete-current-scope` only for a real run with artifacts. If the
quality gate is partial, record it and keep D-009 for the exit decision.

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
node --check figma_bridge\code.js
```

## Self-Review

- The selected frozen sample and exact hashes are preserved.
- Separate dimensions prevent visual masking.
- Real frame ID links write, readback, export and probes.
- No destructive cleanup of unrelated nodes.
- Missing environment is reported, not simulated.
- No commit or push step exists.
