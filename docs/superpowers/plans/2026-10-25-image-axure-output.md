# Image To Axure RP 8 Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and independently verify a real Axure RP 8 artifact for the
owned image sample `IMG-MVP-01`, reusing the existing image strategy and
shared `design-ir/2.0` boundary.

**Architecture:** The image MVP's prepared DesignSpec remains the source of
pixel-sampled geometry, text and reference-only display bytes. The existing
Axure route planner projects the shared IR, reports runtime replacement as an
Axure capability gap, and the existing Axure writer creates the `.rp`.
Published HTML is accepted against the original screenshot and truth manifest
without using any Figma acceptance result.

**Tech Stack:** Python 3.11, image MVP DesignSpec, `design-ir/2.0`, existing
Axure c1/store/doc/writer code, Axure RP 8, Playwright.

**Spec:**

- `docs/v2_mentor/IMAGE_FIGMA_MVP_ACCEPTANCE_2026-10-25.md`
- `docs/v2_mentor/AXURE_SHARED_IR_BOUNDARY_2026-10-25.md`
- `docs/v2_mentor/AXURE_ROUTE_LEDGER_2026-10-25.md`

**Execution status:** `complete-current-scope` on 2026-10-25.

## Global Constraints

- Reuse the existing image-understanding and pixel-presentation layer.
- Do not infer a second image structure for Axure.
- Do not inherit Figma write, replacement or visual evidence.
- Do not claim runtime image replacement in Axure.
- The single image crop remains reference-only and non-original.
- Do not claim original DPR, viewport, font or asset identity.
- Preserve existing uncommitted changes; do not commit or push.

## Review Focus

- The image IR must bind all 21 source nodes and its one image use exactly.
- The generated Axure ImageBox must contain the selected crop bytes, not the
  original screenshot or a Figma response.
- Axure must report `runtime-image-replace` as unsupported while preserving
  creation-time image bytes.
- All 14 critical texts must be checked on Axure-published HTML.
- A passing image-to-Figma result must not satisfy any image-to-Axure check.

### Task 1: Freeze Image Route Semantics

**Files:**
- Modify: `tests/v2/test_axure_route.py`
- Modify: `src/app/services/rendering/axure_route.py` only if tests expose a
  generic route defect.

**Interfaces:**
- Consumes:
  `plan_axure_route(design, source_kind="image", ir=...)`.
- Asserts the image IR document, node/asset bindings and Axure degradation.

- [x] **Step 1: Write the failing image-route test**

Use an image fixture with one reference-only crop, one `runtime-image-replace`
requirement and image MVP flow metadata. Assert 2+ nodes and one asset bind,
`display_original=false`, `reference_only=true`, and
`runtime-image-replace->creation-only-image-box`.

- [x] **Step 2: Run the focused test and verify RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_axure_route.py -q
```

The new test must fail for the missing image-specific contract, not a fixture
typo.

- [x] **Step 3: Implement the minimal generic route behavior**

Do not add an Axure-specific image parser. Fix only binding, feature reporting
or provenance behavior exposed by the test.

- [x] **Step 4: Run focused tests to GREEN**

### Task 2: Image-Specific Axure Entry

**Files:**
- Create: `scripts/image_axure_mvp.py`
- Create: `tests/v2/test_image_axure_output.py`
- Reuse: `scripts/axure_dom_output.py`

**Interfaces:**
- CLI consumes `--design`, optional `--ir`, `--out`, `--page-name` and
  `--generate-twice`.
- Delegates artifact generation to the existing Axure output path with
  `source_kind=image`.

- [x] **Step 1: Write failing CLI tests**

Assert the wrapper writes `prototype.rp`, `artifact_report.json`,
`axure_design.json` and a two-run deterministic hash. Assert the route reports
image input and non-transferable Figma evidence.

- [x] **Step 2: Run focused test and verify RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_axure_output.py -q
```

- [x] **Step 3: Implement the thin image wrapper**

Reuse the existing artifact writer and route planner. Avoid duplicating `.rp`
assembly, GUID generation, inspection or acceptance logic.

- [x] **Step 4: Run focused tests to GREEN**

### Task 3: Image Axure Acceptance Inputs

**Files:**
- Modify: `tests/v2/test_axure_acceptance.py`
- Modify acceptance code only if the 14-text or unique-asset checks expose a
  defect.

**Interfaces:**
- `evaluate_published_axure(...)` consumes the image design, truth critical
  texts and original screenshot.

- [x] **Step 1: Write failing image acceptance test**

Use a controlled published fixture with an HTML-escaped label, one reference
crop and critical text. Assert the Axure-specific result never marks runtime
replacement or Figma evidence as transferable.

- [x] **Step 2: Run focused test and verify RED**

- [x] **Step 3: Implement only the missing generic acceptance behavior**

- [x] **Step 4: Run focused tests to GREEN**

### Task 4: IMG-MVP-01 Real Run And Evidence

**Files:**
- Create: `docs/v2_mentor/AXURE_IMAGE_ACCEPTANCE_2026-10-25.md`
- Modify: `docs/v2_mentor/AXURE_ROUTE_LEDGER_2026-10-25.md`
- Modify: `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`
- Modify: `README.md`
- Modify: `docs/v2_mentor/README.md`
- Update: `output/_axure_image_acceptance_2026-10-25_r1/`

- [x] **Step 1: Generate deterministic image-to-Axure artifacts**

Use:

```text
output/_image_figma_mvp_2026-10-25_r4/figma_design.json
output/_axure_shared_ir_2026-10-25_r1/IMG-MVP-01-figma.ir.json
tests/fixtures/image_mvp/simple_dashboard_v1.truth.json
```

- [x] **Step 2: Open, reopen and publish with Axure RP 8**

Use dedicated A-003 tags and retain first/reload comparison evidence.

- [x] **Step 3: Screenshot and independently accept**

Compare against:

```text
tests/fixtures/image_mvp/simple_dashboard_v1.png
```

Check 14/14 critical text, the one creation-time image payload, page identity,
widget mapping and visual within-30.

- [x] **Step 4: Update ledger, plan, global plan and acceptance report**

Record exact page GUID, paths, hashes, test commands, degradations and
non-claims. Do not transfer Figma frame `77:4851`.

- [x] **Step 5: Mandatory verification**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
C:\Users\lzq\.conda\envs\omni\python.exe -m ruff check <A-003 touched files>
C:\Users\lzq\.conda\envs\omni\python.exe -m ruff format --check <A-003 touched files>
node --check figma_bridge\code.js
git diff --check
C:\Users\lzq\.conda\envs\omni\python.exe scripts/axure_rp8_conform.py <final .rp>
```

The pre-existing whole-repo Ruff baseline remains separate from A-003.

**Final result:** `tests/v2` `703 passed in 40.81s`; Axure-focused regression
set `32 passed`; touched-file Ruff/format, Node syntax, diff-check and Axure
conformance pass. Whole-repo Ruff remains at 133 pre-existing findings outside
this task.
