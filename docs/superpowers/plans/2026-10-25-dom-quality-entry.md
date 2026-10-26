# DOM Quality Entry (D-001..D-002) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the product route vocabulary for `D-001`, then produce a
deduplicated, evidence-linked DOM quality gap register for `D-002`.

**Architecture:** Product planning uses `input family x output target`.
Implementation-level `auto/dom/grounding/cv` names remain only as internal
strategy controls. The gap register consolidates R1, R2, R3-D, P1, P2 and P3
without upgrading fixture evidence into real-site or project-wide claims.

**Tech Stack:** Markdown, Python `unittest`/pytest, ripgrep, existing
`src.app.agents.route_select` module.

**Spec:** `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`

## Global Constraints

- Product inputs are DOM and image; product outputs are Figma and Axure.
- Grounding is the default image strategy; CV is fallback only when the
  Grounding VLM is unavailable.
- Do not advance `D-003`, `I-*`, `A-*` or deferred stability work.
- Do not mark any quality dimension `verified` beyond its named evidence scope.
- Do not commit or push; the user did not request either.
- Preserve all pre-existing worktree changes.

## Review Focus

- A user choosing `本地截图` must not be told that Grounding and CV are peer
  product routes.
- A user choosing CV must see that it is a fallback, not a default or primary
  product direction.
- A fixture-only pass must not appear as real-site proof.
- A bounded Figma probe must not appear as general Auto Layout coverage.
- A local asset payload hash must not appear as original SVG source identity.
- A real-site observation must not appear as a frozen canonical corpus.

---

### Task 1: Freeze Product Route Vocabulary (D-001)

**Files:**
- Modify: `README.md`
- Modify: `src/app/agents/route_select.py`
- Create: `tests/v2/test_route_taxonomy.py`
- Modify: `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`

**Interfaces:**
- Consumes: `G-001..G-007` and the canonical route model in the master plan.
- Produces: `INPUT_SOURCE_OPTIONS`, `ROUTE_HINTS` and product documentation
  whose visible vocabulary is input family plus output target.

- [x] **Step 1: Write the failing product vocabulary tests**

Add `tests/v2/test_route_taxonomy.py` with checks that:

```python
self.assertEqual(route_select.INPUT_SOURCE_OPTIONS, ("网页 URL", "本地截图"))
self.assertNotIn("grounding", " ".join(route_select.INPUT_SOURCE_OPTIONS).lower())
self.assertNotIn("cv", " ".join(route_select.INPUT_SOURCE_OPTIONS).lower())
self.assertIn("fallback", route_select.ROUTE_HINTS["cv"].lower())
self.assertNotIn("主处理方向", route_select.ROUTE_HINTS["cv"])
```

- [x] **Step 2: Run the focused test to verify RED**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_route_taxonomy.py -q
```

Expected: FAIL because `INPUT_SOURCE_OPTIONS` does not exist and the CV hint
still says it can be the main processing direction.

- [x] **Step 3: Implement the minimal vocabulary change**

Add `INPUT_SOURCE_OPTIONS`, use it for the interactive source choice, and
reword the route-select module and hints so Grounding/CV are explicitly
implementation strategies under image input. Update README product sections
to describe `DOM -> Figma`, `image -> Figma`, and deferred Axure targets;
retain implementation flags in a clearly labeled subsection.

- [x] **Step 4: Run focused and regression checks**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_route_taxonomy.py -q
rg -n -i "三条路线|三源路由|可直接作为主处理方向" README.md src tests
```

Expected: PASS, and the product-level forbidden phrasing has no remaining
matches. Matches inside the master plan that explicitly label the old model
as prohibited are allowed and excluded from this check by narrow scope.

- [x] **Step 5: Record D-001 evidence and status**

Update the master plan task register with `D-001` status, the evidence paths,
and the exact verification result. Do not mark `D-003` complete or start any
later task.

---

### Task 2: Produce The Deduplicated DOM Gap Register (D-002)

**Files:**
- Create: `docs/v2_mentor/DOM_QUALITY_GAP_REGISTER_2026-10-25.md`
- Create: `tests/v2/test_dom_quality_gap_register.py`
- Modify: `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`

**Interfaces:**
- Consumes: the frozen taxonomy and evidence from R1, R2, R3-D, P1, P2, P3.
- Produces: stable `DOM-GAP-NNN` IDs, one source coverage matrix, evidence
  links, status vocabulary and D-003 input recommendations.

- [x] **Step 1: Write the failing register contract test**

Add `tests/v2/test_dom_quality_gap_register.py` that:

1. requires `DOM-GAP-NNN` IDs used in exactly one gap section and summarized
   once in the index;
2. requires the source coverage header to contain `R1`, `R2`, `R3-D`, `P1`,
   `P2` and `P3`;
3. requires every status from the master plan gap vocabulary except the
   decision-only `frozen` value to appear;
4. requires evidence links for `README.md`,
   `docs/v2_mentor/R2_EXP_01_DOM_FLOW_PERTURBATION.md`,
   `docs/v2_mentor/P1_CANONICAL_OUTPUT_FIDELITY.md` and
   `docs/v2_mentor/P3_GRID_COMPLEX_HOLDOUT.md`.

- [x] **Step 2: Run the focused test to verify RED**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_dom_quality_gap_register.py -q
```

Expected: FAIL because the register does not exist.

- [x] **Step 3: Write the gap register**

Use one section per gap theme, not one section per source question. Each gap
must include:

```text
Status:
Evidence:
Missing evidence / implementation:
Current claim boundary:
Owning task:
D-003 corpus input:
```

At minimum deduplicate these themes across all six sources:

- frozen real-site corpus and reference state;
- text content, linebreak, box, baseline, mixed-run and glyph identity;
- font availability, variable axes and ambiguous platform fallback;
- Auto Layout L1/L2/L3, Grid, wrap, component and nested propagation;
- source order, grid clustering and slot semantics;
- asset source identity, crop/use instances and missing assets;
- explicit source/fallback provenance and generated approximation;
- stable identity and duplicate ambiguity;
- full-page, sticky and seam evidence;
- complex pseudo-elements, SVG and effect chains;
- real Figma write/readback/export proof and claim boundaries;
- real-site continuity, cross-browser and cross-document coverage.

Mark intentionally deferred or environment-blocked items explicitly. Do not
invent a test result, hash, URL or runtime measurement.

- [x] **Step 4: Run register and documentation checks**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_dom_quality_gap_register.py tests/v2/test_route_taxonomy.py -q
rg -n "DOM-GAP-[0-9]{3}" docs/v2_mentor/DOM_QUALITY_GAP_REGISTER_2026-10-25.md
```

Expected: PASS and unique IDs visible in the generated index and gap sections.

- [x] **Step 5: Update the master plan and record D-002 evidence**

Set `D-001` and `D-002` to `complete-current-scope`, activate `D-003`, and add
the register path, verification command and result. Keep `D-003` output
`planned` rather than claiming the corpus is frozen.

- [x] **Step 6: Run mandatory regression**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
node --check figma_bridge\code.js
```

Expected: all tests pass and `node --check` exits 0. If a pre-existing failure
appears, record it by name; do not weaken or delete the test.
