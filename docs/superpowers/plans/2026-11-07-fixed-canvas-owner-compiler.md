# Fixed-Canvas Owner Compiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make fixed-canvas high-fidelity reconstruction use one occurrence-level owner manifest, dynamic style evidence, and valid fixed-size native text.

**Architecture:** First separate native editability from auto-resize. Then add a style resolver and container manifest contract. Finally compile the high-fidelity DesignSpec from those contracts instead of appending text through competing recovery passes.

**Tech Stack:** Python 3.11, Pillow/OpenCV, pytest, existing Figma bridge and acceptance probes.

**Spec:** `docs/superpowers/specs/2026-11-07-fixed-canvas-owner-compiler-design.md`

## Global Constraints

- Fixed canvas is source pixel size.
- Authoring and source geometry are distinct fields.
- Fixed-size native text is accepted.
- Required display text cannot be rasterized.
- Full-screenshot underlay is prohibited.
- Font and color values are resolved per image, not globally hardcoded.
- Existing DOM route behavior remains unchanged.
- High-fidelity remains opt-in.

## Review Focus

- Fixed-size text must pass editability when style survives, even if geometry
  does not grow.
- Equal strings in different cells must remain distinct owners.
- Authoring frames may be root-sized without being mistaken for source regions.
- Font fallback must be explicit when exact font identity is unavailable.
- Exact whitespace and punctuation must not be normalized away in content
  acceptance.

---

### Task 1: Fixed-Canvas Native Text Policy

**Files:**
- Modify: `src/app/services/evidence/dom_figma_acceptance.py`
- Modify: `src/app/services/evidence/image_figma_acceptance.py`
- Test: `tests/v2/test_image_figma_acceptance.py`

**Interfaces:**
- Produces: `run_text_edit_probe(..., require_geometry_update: bool = True) -> dict`
- Image evidence calls it with `require_geometry_update=False`.

- [x] **Step 1: Write the failing test**

Add a test with a fake TEXT node whose characters update and restore while its
geometry stays fixed. Assert status is `pass`, `geometry_updated` is `False`,
and `geometry_policy` is `fixed-allowed` when the geometry requirement is
disabled.

- [x] **Step 2: Run the test and verify failure**

Run the new test. Expected: the probe still returns `fail`.

- [x] **Step 3: Implement the policy flag**

Keep the default `True` for DOM compatibility. Exclude geometry growth from the
pass condition when false.

- [x] **Step 4: Verify tests**

Run the new test plus `tests/v2/test_image_figma_acceptance.py`. Expected: pass.

- [x] **Step 5: Commit**

Commit only Task 1 files.

---

### Task 2: Container Manifest Source/Authoring Geometry

**Files:**
- Create: `src/app/services/structure/fidelity/container_manifest.py`
- Test: `tests/v2/test_grounding_container_manifest.py`

**Interfaces:**
- Produces: `build_container_manifest(scene_plan: Mapping[str, Any], authoring_frames: Mapping[str, Mapping[str, Any]] | None = None) -> dict`

- [ ] **Step 1: Write failing tests for root-sized authoring frames and authoring geometry**

Assert source and authoring bboxes remain distinct and local child transforms
are derived from absolute source geometry.

- [ ] **Step 2: Run tests and verify module failure**

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the manifest**

Emit `owner_id`, `parent_id`, `source_bbox`, `authoring_bbox`, `layout_mode`,
and `children`.

- [ ] **Step 4: Verify tests**

Run the new tests. Expected: pass.

- [ ] **Step 5: Commit**

Commit only container-manifest files.

---

### Task 3: Dynamic Text Style Evidence

**Files:**
- Create: `src/app/services/structure/fidelity/style_resolver.py`
- Test: `tests/v2/test_grounding_style_resolver.py`

**Interfaces:**
- Produces: `resolve_text_style(image_path: str | Path, text: str, bbox: Sequence[int], *, parent_bbox: Sequence[int] | None = None, role: str = "") -> dict`

Result fields:

`fontFamily`, `fontSize`, `fontWeight`, `textColor`, `textAlign`,
`lineHeightPolicy`, `confidence`, `evidence`.

- [ ] **Step 1: Write failing tests**

Cover dark text on light background, light text on dark background, CJK versus
Latin family candidates, header alignment, and explicit fallback confidence.

- [ ] **Step 2: Run tests and verify failure**

Expected: module missing.

- [ ] **Step 3: Implement deterministic sampling and candidate ranking**

Use ink/background clustering, ink height and advance width for size, CJK/Latin
script routing for family candidates, and parent-relative geometry for
alignment.

- [ ] **Step 4: Verify tests**

Run style-resolver and image-contract tests. Expected: pass.

- [ ] **Step 5: Commit**

Commit only style-resolver files.

---

### Task 4: Compile High-Fidelity Text Through StyleEvidence

**Files:**
- Modify: `src/app/services/structure/image_contract.py`
- Test: `tests/v2/test_grounding_scene_compile.py`

**Interfaces:**
- Consumes: `resolve_text_style(...)`.
- Scene-plan text and table text use resolved style evidence.

- [ ] **Step 1: Write failing compiler tests**

Assert planner text no longer uses a hardcoded table font size/line height, and
style evidence is retained on the design element.

- [ ] **Step 2: Run tests and verify failure**

Expected: style evidence fields absent.

- [ ] **Step 3: Wire the resolver**

Apply it to scene-plan text owners while preserving the existing geometry.

- [ ] **Step 4: Verify tests and focused image suite**

Expected: pass.

- [ ] **Step 5: Commit**

Commit compiler integration files.

---

### Task 5: Golden Mentor Sample Regression

**Files:**
- Create: `tests/v2/test_fixed_canvas_mentor_contract.py`
- Create: `docs/v2_mentor/FIXED_CANVAS_OWNER_COMPILER_2026-11-07.md`

**Interfaces:**
- Consumes: audit JSON and live readback stored under the distillation output.

- [ ] **Step 1: Add contract assertions**

Assert the golden sample keeps 138/138 owner mapping, 79 native TEXT nodes,
42 table text owners, zero duplicate overlaps, and all truth regions below the
configured threshold.

- [ ] **Step 2: Run the golden contract tests**

Expected: pass against the retained evidence.

- [ ] **Step 3: Document adopted and rejected mechanisms**

Record fixed text policy, dual geometry, dynamic style resolution, and the
remaining exact-whitespace issue.

- [ ] **Step 4: Run full verification**

Run the full pytest suite, touched-file Ruff, formatting, and Node syntax.

- [ ] **Step 5: Commit**

Commit the golden regression and documentation.
