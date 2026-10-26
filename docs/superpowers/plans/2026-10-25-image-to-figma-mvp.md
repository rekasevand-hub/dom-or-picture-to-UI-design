# Image To Figma MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce one real, reproducible screenshot-to-Figma MVP result with at
least 90% current-scope usability, explicit provenance and honest limitations.

**Architecture:** Grounding supplies candidate structure. A deterministic image
presentation layer samples visible colors and image crops, emits native text
where detectable, and records fixed-coordinate/candidate-flow status. The
existing Figma adapter writes, reads back and exports the owned sample.

**Tech Stack:** Python 3.12, Pillow, OpenCV, existing Grounding VLM abstraction,
existing PageGraph/SoM/DesignSpec renderer, existing Figma WebSocket adapter.

**Spec:** `docs/superpowers/specs/2026-10-25-image-to-figma-mvp-design.md`

**Execution status:** `complete-current-scope` on 2026-10-25. Evidence is in
`docs/v2_mentor/IMAGE_FIGMA_MVP_ACCEPTANCE_2026-10-25.md`.

## Global Constraints

- Preserve all existing uncommitted work.
- Do not commit, push or rewrite unrelated files.
- Grounding is the default image strategy.
- CV fallback is eligible only for missing VLM configuration or an unavailable
  Grounding service.
- A screenshot crop is `original=false` and `reference_only=true`.
- Do not claim original font, DPR, viewport, hidden state or adaptive flow.
- Use source-pixel coordinates.
- A passing unit test is not an image-quality acceptance result.
- The owned visual threshold is frozen before the real run.

## Review Focus

- A Grounding JSON/schema error must not silently run CV.
- A reference-only screenshot crop must not become an "original" asset in the
  report.
- Critical strings must be checked exactly after normalization.
- The absence of a second VLM must not erase text or image editability.
- The final report must retain fixed-coordinate and flow-candidate limits even
  when the overall product gate passes.

---

### Task 1: Freeze Image Reference And Fallback Contract

**Files:**
- Create: `src/app/services/structure/image_contract.py`
- Modify: `src/app/services/structure/router.py`
- Test: `tests/v2/test_image_contract.py`
- Test: `tests/v2/test_image_route_fallback.py`

**Interfaces:**
- Produces: `inspect_image_reference(image_path, *, reference_id=None) -> dict`
- Produces: `grounding_fallback_reason(exc) -> str | None`
- Produces: `route_order(input_kind, requested, cfg, have_dom) -> list[str]`

- [x] Write failing tests for image hash/dimensions, faithful state and explicit
  unknown DPR/viewport/font fields.
- [x] Write failing tests that network/timeout/rate-limit exceptions allow
  fallback while malformed JSON and ordinary downstream errors do not.
- [x] Run the focused tests and confirm expected failures.
- [x] Implement the reference contract and image route candidate order.
- [x] Run focused tests to green.

### Task 2: Build Deterministic Image Design

**Files:**
- Modify: `src/app/services/structure/image_contract.py`
- Test: `tests/v2/test_image_contract.py`

**Interfaces:**
- Produces: `build_image_design(graph, reference, *, sample_id) -> dict`
- Produces: `build_image_ir(graph, design, reference, strategy) -> dict`

- [x] Write a failing synthetic-image test proving background/header/card/button
  colors are sampled and text elements do not acquire opaque backgrounds.
- [x] Write a failing test proving image nodes receive reference-only display
  provenance and no generated/original claim.
- [x] Write a failing test proving IR fields mark Grounding text as candidates
  and flow as `candidate` / fixed-coordinate.
- [x] Run tests and confirm failure.
- [x] Implement deterministic geometry, color sampling, text sizing, asset
  records and image IR.
- [x] Run focused tests to green.

### Task 3: Integrate The Image MVP Into PreciseAgent

**Files:**
- Modify: `src/app/agents/precise_agent.py`
- Test: `tests/v2/test_image_agent_integration.py`
- Fixture: `tests/fixtures/image_mvp/simple_dashboard_v1.html`
- Fixture: `tests/fixtures/image_mvp/simple_dashboard_v1.truth.json`

- [x] Write failing tests proving image input marks provenance as `image`,
  selects deterministic image presentation and writes `image_ir.json`.
- [x] Write a failing test proving ordinary Grounding failure is re-raised for
  auto image input.
- [x] Run focused tests and confirm failure.
- [x] Integrate the reference, strategy decision, design builder and IR into
  the existing output directory without changing DOM behavior.
- [x] Capture the owned screenshot with Playwright.
- [x] Run focused tests to green.

### Task 4: Add Image Acceptance And Reproducible CLI

**Files:**
- Create: `src/app/services/evidence/image_figma_acceptance.py`
- Create: `scripts/image_figma_mvp.py`
- Test: `tests/v2/test_image_figma_acceptance.py`

**Interfaces:**
- Produces: `evaluate_image_mvp(...) -> dict`
- Produces: `visual_similarity_metrics(reference_path, render_path) -> dict`
- CLI: `python scripts/image_figma_mvp.py run --image ... --truth ... --out ...`

- [x] Write failing tests for a passing reference-only image result and for a
  critical-text failure.
- [x] Write a failing test proving the 90% threshold is retained in the report.
- [x] Implement acceptance dimensions, non-claims and CLI orchestration.
- [x] Run focused tests to green.

### Task 5: Run Real Figma Evidence

**Files:**
- Update: `docs/v2_mentor/IMAGE_FIGMA_MVP_LEDGER_2026-10-25.md`
- Create: `docs/v2_mentor/IMAGE_FIGMA_MVP_ACCEPTANCE_2026-10-25.md`
- Evidence root: `output/_image_figma_mvp_2026-10-25/`

- [x] Run the frozen owned screenshot through Grounding and deterministic
  presentation.
- [x] Verify text content, image display payload provenance and IR statuses.
- [x] Write to real Figma, read back, export and run text/image replacement
  probes.
- [x] Evaluate the frozen 90% product gate without changing the threshold.
- [x] Record frame ID, hashes, limitations and exact rerun commands.

### Task 6: Regression And Handoff

**Files:**
- Modify: `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`
- Modify: `README.md`
- Modify as needed: `docs/v2_mentor/IMAGE_FIGMA_MVP_LEDGER_2026-10-25.md`

- [x] Run focused image tests.
- [x] Run `pytest tests/v2 -q`.
- [x] Run `ruff check` and `ruff format --check` on touched Python files.
- [x] Run `node --check figma_bridge/code.js`.
- [x] Update task statuses, evidence paths and the next queue.
- [x] Confirm no commit or push was performed.
