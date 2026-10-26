# Image CV Fallback And Hybrid Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Verify the image CV availability fallback in real Figma and make an
evidence-backed adopt/reject decision for a Grounding + CV hybrid.

**Architecture:** Keep the existing Grounding default and deterministic image
presentation. Repair fallback provenance, preserve source authority in image
IR, add a conservative benchmark-only hybrid merge, and compare all strategies
through the same Figma write/readback/export/probe path.

**Tech Stack:** Python 3.12, unittest/pytest, OpenCV, EasyOCR/OmniParser,
existing Grounding provider, existing Figma bridge/adapter, JSON evidence.

**Spec:** `docs/superpowers/specs/2026-10-26-image-cv-hybrid-benchmark-design.md`

## Global Constraints

- Preserve all existing uncommitted changes.
- Do not commit or push.
- Freeze the corpus, thresholds, environment and baseline before behavior code.
- Grounding is the default image strategy.
- Automatic CV is eligible only for missing Grounding configuration or
  Grounding service unavailability.
- Ordinary Grounding parse/downstream errors must fail close.
- No composite score; report every dimension independently.
- No screenshot crop may become an original asset claim.
- No Axure evidence may stand in for Figma evidence.
- No hidden route switch or retrospective threshold change.

## Review Focus

- A missing VLM key must be recorded as a Grounding fallback attempt, not as a
  normal CV selection.
- Invalid Grounding JSON must not build or execute CV.
- CV-only IR must not label text or geometry as Grounding authority.
- Hybrid duplicate suppression must preserve all retained CV provenance.
- Figma probes and exports may fail the environment gate but must never be
  synthesized from SVG or reference pixels.

---

### Task 1: Freeze Corpus, Baseline And Decision Policy

**Files:**
- Create: `tests/fixtures/image_strategy_benchmark/manifest.json`
- Create: `output/_image_cv_hybrid_benchmark_2026-10-26/baseline.json`
- Create: `docs/superpowers/specs/2026-10-26-image-cv-hybrid-benchmark-design.md`
- Create: `docs/superpowers/plans/2026-10-26-image-cv-hybrid-benchmark.md`

**Interfaces:**
- Produces: frozen sample/truth hashes, policy values and environment identity.

- [x] Record the existing Grounding-only Figma baseline and its exact metrics
  before changing behavior code.
- [x] Freeze sample, viewport, thresholds, provenance requirements and
  adopt/reject gates.
- [x] Confirm no product behavior code has been changed during freeze.

### Task 2: Record Missing-Config Fallback Provenance

**Files:**
- Modify: `src/app/agents/precise_agent.py`
- Modify: `tests/v2/test_image_agent_integration.py`

**Interfaces:**
- Produces: image strategy attempts with
  `{strategy: grounding, status: unavailable, reason: grounding-config-missing}`
  before CV selection when image `auto` has no VLM key.

- [ ] **Step 1: Write the failing integration test**

```python
def test_image_auto_missing_vlm_config_records_grounding_fallback(self):
    ...
    self.assertEqual(
        manifest["imageMVP"]["strategy"]["attempts"],
        [
            {
                "strategy": "grounding",
                "status": "unavailable",
                "reason": "grounding-config-missing",
            },
            {"strategy": "cv", "status": "selected"},
        ],
    )
    self.assertTrue(manifest["imageMVP"]["strategy"]["fallback_used"])
```

- [ ] **Step 2: Run the test and verify RED**

Run:
`C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_agent_integration.py::ImageAgentIntegrationTests::test_image_auto_missing_vlm_config_records_grounding_fallback -q`

Expected: FAIL because current attempts contain only selected CV and
`fallback_used=false`.

- [ ] **Step 3: Implement the minimal provenance repair**

When image `auto` starts with CV solely because the VLM key is missing, append
the Grounding config-missing attempt and fallback event before selecting CV.
Do not alter explicit CV behavior or ordinary error handling.

- [ ] **Step 4: Run focused fallback tests and verify GREEN**

Run:
`C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_route_fallback.py tests/v2/test_image_agent_integration.py -q`

Expected: all pass.

### Task 3: Preserve Candidate Authority In Image IR

**Files:**
- Modify: `src/app/services/structure/image_contract.py`
- Modify: `tests/v2/test_image_contract.py`

**Interfaces:**
- Produces: source-derived `imageMVP.source`, text authority and IR authority
  for Grounding, CV and hybrid candidates.

- [ ] **Step 1: Write failing CV provenance tests**

Assert that `cv:ocr` text becomes `cv-ocr-candidate`, `cv:omniparser` geometry
becomes `cv-omniparser-candidate`, and no CV node is labeled
`grounding-vlm-candidate`.

- [ ] **Step 2: Run the tests and verify RED**

Run:
`C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_contract.py -q`

Expected: FAIL on hardcoded Grounding authority.

- [ ] **Step 3: Implement source-derived candidate labels**

Keep existing Grounding labels unchanged. Map CV and hybrid sources to explicit
authority strings and preserve `verified=false`.

- [ ] **Step 4: Run focused image contract tests and verify GREEN**

Run:
`C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_contract.py -q`

Expected: all pass.

### Task 4: Add Conservative Hybrid Merge

**Files:**
- Create: `src/app/services/structure/image_strategy.py`
- Create: `tests/v2/test_image_strategy.py`

**Interfaces:**
- Produces: `merge_hybrid_graph(
    grounding_graph: Mapping[str, Any],
    cv_graph: Mapping[str, Any],
  ) -> tuple[dict[str, Any], dict[str, Any]]`

- [ ] **Step 1: Write failing hybrid tests**

Cover one missing CV text addition, one duplicate suppression, one
non-duplicate visual-box addition, and provenance retention for every added
candidate.

- [ ] **Step 2: Run the tests and verify RED**

Run:
`C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_strategy.py -q`

Expected: FAIL because the module/function does not exist.

- [ ] **Step 3: Implement the conservative merge**

Grounding remains the base. Add CV text only when normalized text and spatial
overlap do not duplicate an existing text candidate. Add CV non-text boxes only
when their overlap with existing visual boxes is below the frozen duplicate
threshold. Prefix retained sources with `hybrid:` and retain a report of
added/skipped candidates and ambiguity reasons.

- [ ] **Step 4: Run the tests and verify GREEN**

Run:
`C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_strategy.py -q`

Expected: all pass.

### Task 5: Build Three-Way Benchmark Evidence

**Files:**
- Create: `src/app/services/evidence/image_strategy_benchmark.py`
- Create: `scripts/image_strategy_benchmark.py`
- Create: `tests/v2/test_image_strategy_benchmark.py`

**Interfaces:**
- Produces: `evaluate_hybrid_decision(rows, policy) -> dict`
- Produces: `build_strategy_comparison(...) -> dict`
- CLI: `python scripts/image_strategy_benchmark.py --manifest ... --out ...`

- [ ] **Step 1: Write failing decision tests**

Cover all-adopt gates, critical-text regression, visual regression, missing
provenance, unbounded latency and absence of independent improvement.

- [ ] **Step 2: Run the tests and verify RED**

Run:
`C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_strategy_benchmark.py -q`

Expected: FAIL because the evaluator does not exist.

- [ ] **Step 3: Implement deterministic comparison and decision**

Emit separate per-strategy rows and gates. `adopt-hybrid` requires every
decision gate; otherwise emit `reject-hybrid` with named reasons. Do not create
a composite score.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:
`C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_strategy_benchmark.py -q`

Expected: all pass.

### Task 6: Prepare And Run The Frozen Three Strategies

**Files:**
- Output: `output/_image_cv_hybrid_benchmark_2026-10-26/strategies/*`

- [ ] **Step 1: Prepare Grounding-only and verify its design/IR/provenance.**
- [ ] **Step 2: Prepare CV fallback through missing-config automatic routing and
  verify the Grounding-unavailable event.**
- [ ] **Step 3: Prepare Grounding + CV hybrid from the same image and truth.**
- [ ] **Step 4: Run the real Figma write/readback/export/probe path separately
  for all three strategies in the same Figma document.**
- [ ] **Step 5: Build the comparison JSON and verify no composite score,
  real-runtime provenance and independent dimensions.**

### Task 7: Decision Report And Verification

**Files:**
- Create: `docs/v2_mentor/IMAGE_CV_HYBRID_BENCHMARK_2026-10-26.md`
- Modify: `docs/v2_mentor/IMAGE_FIGMA_MVP_LEDGER_2026-10-25.md`

- [ ] **Step 1: Write the adopt/reject report from measured JSON only.**
- [ ] **Step 2: Record n=1 limits, environment blocks, hashes and exact rerun
  commands.**
- [ ] **Step 3: Run focused tests, `pytest tests/v2 -q`, Ruff checks,
  JavaScript checks, and `git diff --check`.**
- [ ] **Step 4: Confirm no commit or push and preserve all dirty worktree
  changes.**
