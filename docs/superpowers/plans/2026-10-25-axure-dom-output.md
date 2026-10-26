# DOM To Axure RP 8 Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and independently verify a deterministic Axure RP 8 `.rp`
from the existing DQ-R02 DOM design through the shared `design-ir/2.0`
boundary.

**Architecture:** The existing DesignSpec remains the source of captured
geometry, paint order and image bytes. A route planner builds or validates the
output-neutral IR, projects it for Axure, and fails closed unless every IR
node and asset maps back to the same source node. The existing AXure writer
renders the verified design. A separate `.rp` inspector validates the actual
page/widget/asset object graph before Axure RP 8 publishes it; published HTML
is then accepted independently from the Figma run.

**Tech Stack:** Python 3.11, existing DesignSpec, `design-ir/2.0`, existing
Axure c1/store/doc/writer code, Pillow thumbnails, Playwright screenshots,
Axure RP 8 UI Automation publish script.

**Spec:**

- `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`
- `docs/v2_mentor/AXURE_SHARED_IR_BOUNDARY_2026-10-25.md`
- `docs/v2_mentor/AXURE_ROUTE_LEDGER_2026-10-25.md`

**Execution status:** `complete-current-scope` on 2026-10-25.

## Global Constraints

- Preserve all existing uncommitted changes.
- Do not commit or push.
- Do not create a second input-understanding pipeline for Axure.
- Do not inherit or relabel any Figma acceptance result.
- Reference-only and generated display payloads remain non-original.
- Do not claim runtime image replacement, clip containers, Auto Layout,
  native letter spacing, shadows or gradients in Axure.
- Prefer layout, component, content and creation-time image bytes over
  unsupported fidelity features.
- Any real Axure evidence is limited to the named controlled sample.

## Review Focus

- A source node that lacks an IR node must stop the run rather than disappear.
- An IR node must not silently bind to the wrong source node by list position
  when a stable source ID is available.
- A generated or screenshot-crop display payload must not become an
  original/replaceable asset in route or acceptance evidence.
- The `.rp` image blob hash must be checked against display bytes, not only
  against IR asset metadata.
- Axure publish success and byte inspection must not be reported as visual or
  editability acceptance until the independent checks also run.

### Task 1: Shared-IR Route Planner

**Files:**
- Create: `src/app/services/rendering/axure_route.py`
- Create: `tests/v2/test_axure_route.py`

**Interfaces:**
- Produces:
  `plan_axure_route(design: Mapping[str, Any], *, source_kind: str, reference: Mapping[str, Any] | None = None, ir: Mapping[str, Any] | None = None) -> dict[str, Any]`
- The result retains `design`, `ir`, `projection`, `node_bindings`,
  `asset_bindings` and `limitations`.

- [x] **Step 1: Write failing tests proving node/asset binding and fail-closed behavior**

Tests must cover:

```python
def test_route_binds_every_ir_node_to_its_source_node(): ...
def test_route_fails_when_an_ir_source_node_is_missing(): ...
def test_route_preserves_generated_and_reference_only_asset_status(): ...
def test_route_reports_axure_degradations_without_transferring_figma_claims(): ...
```

The route test fixture uses two image uses with identical metadata shape but
different bytes, so binding cannot pass by matching payload hash alone.

- [x] **Step 2: Run focused tests and verify RED**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_axure_route.py -q
```

Expected: import failure because `axure_route.py` does not exist.

- [x] **Step 3: Implement the route planner**

Use `build_output_ir()` when no IR is supplied, `validate_output_ir()` on
supplied IR, and `project_for_output(..., "axure")`. Bind pages by frame order
and nodes by `source_node_id`, with list position only as a fallback when the
source ID is empty. Bind image bytes by source node and verify their SHA-256
against the selected display provenance hash. Return a deep-copied DesignSpec;
do not mutate the caller input.

- [x] **Step 4: Run focused tests and verify GREEN**

Run the same focused command. Expected: all route tests pass.

### Task 2: Actual `.rp` Object-Graph Inspector

**Files:**
- Create: `src/app/services/rendering/axure/evidence.py`
- Create: `tests/v2/test_axure_evidence.py`
- Modify: `scripts/axure_rp8_wired.py` only if a shared inspector can replace
  duplicated one-off parsing without changing its CLI behavior.

**Interfaces:**
- Produces: `inspect_rp(path: str | Path) -> dict[str, Any]`
- Produces:
  `compare_rp_to_design(report: Mapping[str, Any], design: Mapping[str, Any], *, route: Mapping[str, Any] | None = None) -> dict[str, Any]`

`inspect_rp()` reports page registry order, widget classes, labels, geometry,
native text content, library style names and image blob SHA-256 values.
`compare_rp_to_design()` compares multiset widget classes, geometry, native
content and exact bytes.

- [x] **Step 1: Write failing inspector tests**

Generate one small two-page `.rp` through `AxureRPAdapter`; assert page order,
`Text`/`Button`/`TextField`/`ImageBox` mapping, geometry readback and image
bytes. Add a mutation test that changes one expected image byte hash and must
produce a comparison failure.

- [x] **Step 2: Run focused tests and verify RED**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_axure_evidence.py -q
```

Expected: import failure because `evidence.py` does not exist.

- [x] **Step 3: Implement the inspector and comparator**

Reuse `c1`, `store`, `constants` and `model`; do not parse ZIP bytes with
regex. Resolve every widget's `MyStyle`, read `P_SIZE`, `P_LOCATION`,
`P_IMAGE`, `MatchInfo.Name`, `RichTextPanel` runs and `TextBox.TextBlock`.
Keep unknown objects in the report but exclude them from expected widget
comparisons. Return deterministic sorted records and explicit mismatch rows.

- [x] **Step 4: Run focused tests and verify GREEN**

Run the same focused command plus:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_output_ir_boundary.py -q
```

Expected: both suites pass.

### Task 3: Deterministic DOM Route Probe

**Files:**
- Create: `scripts/axure_dom_output.py`
- Create: `tests/v2/test_axure_dom_output.py`

**Interfaces:**
- CLI consumes `--design`, optional `--ir`, `--out`, `--source-kind` and
  `--generate-twice`.
- Writes:
  `prototype.rp`,
  `design.ir.json`,
  `route.json`,
  `artifact_report.json`.

- [x] **Step 1: Write failing end-to-end tests**

Use a temporary DesignSpec with two pages and two images. Assert the CLI
writes all four files, performs integrity checks, and writes byte-identical
`.rp` files when `--generate-twice` is enabled. Assert the artifact report does
not contain Figma acceptance transfer flags set to true.

- [x] **Step 2: Run focused tests and verify RED**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_axure_dom_output.py -q
```

Expected: script module or main entry is missing.

- [x] **Step 3: Implement the probe**

Call the route planner, render through `AxureRPAdapter` using the existing
factory/config path, inspect the generated `.rp`, run `writer.self_check()`
and `writer.integrity_check()`, then hash both runs. Report source/IR/artifact
hashes, page/widget/asset counts, mismatches and non-claims.

- [x] **Step 4: Run focused tests and verify GREEN**

Run the focused test. Expected: pass with deterministic hashes.

### Task 4: Axure RP 8 Publish And Independent Acceptance

**Files:**
- Create: `src/app/services/evidence/axure_acceptance.py`
- Create: `tests/v2/test_axure_acceptance.py`
- Create: `scripts/axure_acceptance.py`
- Optionally modify: `scripts/axure_publish_html.ps1` only for a
  non-destructive, parameterized close policy or a second-open/reload check.

**Interfaces:**
- Produces:
  `evaluate_published_axure(publish_dir, *, design, rp_report, reference_screenshot=None, render_screenshot=None) -> dict[str, Any]`
- CLI consumes `--publish-dir`, `--design`, `--rp`, optional screenshots and
  writes `acceptance.json` plus screenshot paths.

- [x] **Step 1: Write failing published-artifact tests**

Use a controlled published fixture with two pages. Assert page order/names,
critical text, labels, exact image-byte multiset and explicit failure when a
page is missing. Keep visual scoring independent and `partial` when a
screenshot is absent.

- [x] **Step 2: Run focused tests and verify RED**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_axure_acceptance.py -q
```

Expected: evaluator module is missing.

- [x] **Step 3: Implement artifact acceptance**

Derive page URLs from `data/document.js`; inspect each page HTML,
`files/<page>/data.js` and `styles.css`. Verify page names, labels, critical
text and image byte hashes. Compute visual similarity only when both
screenshots exist, with separate Axure-specific scope and no Figma fields.

- [x] **Step 4: Run focused tests and verify GREEN**

Run the same focused test. Expected: all pass.

### Task 5: DQ-R02 Real Run, Reload/Publish, And Evidence Sync

**Files:**
- Create: `docs/v2_mentor/AXURE_DOM_ACCEPTANCE_2026-10-25.md`
- Modify: `docs/v2_mentor/AXURE_ROUTE_LEDGER_2026-10-25.md`
- Modify: `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`
- Modify: `README.md`
- Update evidence under:
  `output/_axure_dom_acceptance_2026-10-25_r1/`

- [x] **Step 1: Generate the named DQ-R02 artifact twice**

Run the probe against:

```text
output/_dom_figma_generated_icons_2026-10-25_r1/design.json
output/_axure_shared_ir_2026-10-25_r1/DQ-R02-figma.ir.json
```

Record both artifact hashes and exact page/widget/asset mappings.

- [x] **Step 2: Open/reload in Axure RP 8 and publish**

Use the installed:

```text
D:\Program File\Axure\Axure RP 8\AxureRP8.exe
```

Run `scripts/axure_publish_html.ps1` with a dedicated A-002 tag. If the script
cannot observe a first and second open, report `open-only` or
`publish-only`; do not invent a reload result.

- [x] **Step 3: Capture and evaluate the published page**

Use `scripts/axure_shoot_html.py` through local HTTP. Compare the Axure
screenshot to the original DQ-R02 `00_screenshot.png`. Record within-30,
mean/ink metrics, content, page, component and asset checks separately.

- [x] **Step 4: Write acceptance and ledger updates**

State `pass-current-scope`, `partial`, or `blocked` based on actual checks.
Record real frame/page, output paths, SHA-256 values, verification commands,
route degradations and non-claims. A Figma frame ID may be referenced only as
source provenance, never as Axure evidence.

- [x] **Step 5: Run mandatory verification**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
C:\Users\lzq\.conda\envs\omni\python.exe -m ruff check src tests scripts
C:\Users\lzq\.conda\envs\omni\python.exe -m ruff format --check src tests scripts
node --check figma_bridge\code.js
git diff --check
```

Also run the A-002 probe and `scripts/axure_rp8_conform.py` on the final
`.rp`. Record exact results; do not claim completion if any required check
fails.

**Ruling:** Ruff completion is scoped to files touched by A-002 because the
pre-existing repository baseline reports 133 findings across unrelated legacy
scripts and source files. The full baseline result is recorded in the
acceptance report. Cost if wrong: a repository-wide lint claim remains false
even though the new Axure modules pass.
