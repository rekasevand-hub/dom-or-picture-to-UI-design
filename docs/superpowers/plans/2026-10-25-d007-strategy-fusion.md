# D-007 Strategy Fusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement an ordered asset strategy-fusion contract that preserves
source identity while allowing screenshot and generated display fallbacks with
explicit provenance and no false original claim.

**Architecture:** A pure fusion module evaluates every asset use from the
D-006 record, keeps identity selection separate from display selection, and
returns deterministic candidates, fallback reasons and provenance. Direct
design carries the decision into DesignSpec, Figma acceptance treats generated
or missing display payloads as partial/fail, and an evidence report replays the
frozen corpus through the same policy.

**Tech Stack:** Python 3.12, existing D-006 asset ledger, `unittest`/pytest,
JSON, Playwright-verified frozen corpus evidence.

**Spec:** `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`

## Global Constraints

- Source precedence is verified DOM source, verified recovered network source,
  screenshot crop, generated approximation.
- Identity selection and display-payload selection remain separate.
- A generated candidate is never `original`, never replaceable and never
  satisfies the original-asset threshold.
- A generated candidate requires generator/model, input reference, prompt,
  prompt version and review status.
- Incomplete generated provenance fails closed and remains visible.
- A screenshot crop is `reference-only` and is preferred over generated output.
- Missing display regions remain in the denominator.
- Unknown text must not be filled from context.
- D-006 corpus/threshold hashes and data remain unchanged.
- Real Figma runtime remains D-008; D-007 reports a contract, not a runtime
  replacement pass.
- Do not modify deferred image, Axure, fault-matrix or production work.
- Preserve pre-existing worktree changes; do not commit or push.

## Review Focus

- A generated candidate must not override a better captured payload.
- A verified source identity must not be inferred from a generated display.
- A screenshot crop must not become replaceable because a source identity
  exists elsewhere.
- Generated provenance must be complete before the candidate is eligible.
- Missing display and missing source identity must be reported independently.
- Replaying the same inputs must produce stable candidate ordering.
- A contract-level fusion decision must not be called real Figma proof.

## Decision Contract

Each fusion result contains:

```text
identity:
  selected: verified-source | reference-only | missing | unavailable
  original, replaceable, source_tier
  provenance

display:
  selected: screenshot-crop | generated-approximation | missing
  original=false
  reference_only
  fallback_used
  provenance

candidates:
  ordered deterministic rows with kind, status, reason and payload hash

fallback_chain, status, diagnostics
```

---

### Task 1: Implement The Pure Fusion Contract

**Files:**
- Create: `src/app/services/structure/asset_fusion.py`
- Create: `tests/v2/test_asset_fusion.py`

**Interfaces:**
- Produces:
  `fuse_asset_record(record: Mapping, *, generated_candidates: Sequence[Mapping] = ()) -> dict`
- Consumes the D-006 `source_identity`, `display_payload`, `replacement`,
  `missing`, `asset_id` and `use` fields.

- [x] **Step 1: Write failing fusion tests**

Require:

- verified DOM/network source selects under its correct source tier;
- screenshot crop is selected for display and remains reference-only;
- reference-only/missing source identity does not block an available crop;
- a valid generated candidate is used only when screenshot display is missing;
- generated never becomes original/replaceable;
- incomplete generated provenance is rejected and reported;
- candidate order and fallback chains are deterministic.

- [x] **Step 2: Run focused test to verify RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_asset_fusion.py -q
```

Expected: FAIL because `asset_fusion.py` does not exist.

- [x] **Step 3: Implement the minimal pure contract**

Validate hashes/provenance with structured dictionaries only. Do not upload,
generate or mutate bytes.

- [x] **Step 4: Run focused test to verify GREEN**

Expected: PASS.

---

### Task 2: Carry Fusion Decisions Into Design And Acceptance

**Files:**
- Modify: `src/app/services/som/direct_design.py`
- Modify: `src/app/services/rendering/figma_acceptance.py`
- Modify: `tests/v2/test_p1_asset_metadata.py`
- Modify: `tests/v2/test_p1_figma_acceptance.py`

**Interfaces:**
- Consumes: `fuse_asset_record(...) -> dict`.
- Produces: `sourceResolution` on DesignSpec image elements.
- Extends acceptance identity rows with fusion status, generated usage and
  fallback reason.

- [x] **Step 1: Write failing integration tests**

Require:

- direct design attaches a fusion decision to the actual cropped image;
- generated display makes the asset dimension partial even when the node looks
  visually complete;
- screenshot crop remains preferred over generated output;
- missing display remains a fail;
- source/replacement provenance remains independent from display fallback.

- [x] **Step 2: Run focused tests to verify RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_p1_asset_metadata.py tests/v2/test_p1_figma_acceptance.py -q
```

Expected: FAIL because `sourceResolution` and generated-aware acceptance are
absent.

- [x] **Step 3: Implement DesignSpec and acceptance integration**

Run fusion only after the actual screenshot crop hash is attached. Preserve all
legacy fields and geometry.

- [x] **Step 4: Run focused tests to verify GREEN**

Expected: PASS.

---

### Task 3: Replay Frozen Corpus Through Fusion

**Files:**
- Create: `src/app/services/evidence/dom_strategy_fusion.py`
- Create: `scripts/dom_strategy_fusion.py`
- Create: `tests/v2/test_dom_strategy_fusion.py`

**Interfaces:**
- Produces:
  `build_fusion_report(asset_report: Mapping) -> dict`.
- CLI consumes the D-006 `summary.json` and writes one report without network
  access.

- [x] **Step 1: Write failing report tests**

Require:

- independent counts for verified source, reference-only identity, unavailable
  source, screenshot display, generated fallback and missing display;
- every D-006 use remains in the denominator exactly once;
- generated approximations are zero when no generated candidates exist;
- D-006 corpus/threshold hashes are carried unchanged;
- no composite score or Figma runtime claim appears.

- [x] **Step 2: Run focused test to verify RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_dom_strategy_fusion.py -q
```

Expected: FAIL because the evidence module and CLI do not exist.

- [x] **Step 3: Implement report aggregation and CLI**

Join D-006 uses to asset identities, call the production fusion function and
emit candidate/fallback counts. Keep generated candidates empty by default.

- [x] **Step 4: Run focused test to verify GREEN**

Expected: PASS.

---

### Task 4: Publish Evidence And Update Plan Status

**Files:**
- Create: `docs/v2_mentor/DOM_STRATEGY_FUSION_2026-10-25.md`
- Create runtime report under `output/_dom_strategy_fusion_2026-10-25/`
- Modify: `docs/v2_mentor/DOM_QUALITY_GAP_REGISTER_2026-10-25.md`
- Modify: `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`

- [x] **Step 1: Run the frozen D-006 report through fusion**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_strategy_fusion.py `
  --asset-report output\_dom_asset_quality_2026-10-25\summary.json `
  --out output\_dom_strategy_fusion_2026-10-25
```

Expected: all 227 uses accounted for independently; generated fallback is `0`
unless an explicit generated candidate exists.

- [x] **Step 2: Publish the report**

Record exact source/display/fallback counts, policy ordering, generated
provenance requirements, failures and non-claims.

- [x] **Step 3: Update gap registration and master plan**

Close DOM-GAP-018 only to the evidenced current scope. Keep real Figma runtime
in D-008 and image-generated fusion in the image phase. Mark D-007
`complete-current-scope` and D-008 `active` only after verification.

- [x] **Step 4: Run mandatory verification**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
node --check figma_bridge\code.js
```

Expected: all tests pass and syntax check exits 0.

## Self-Review

- Source identity and display fallback are separate in every test.
- Generated output never satisfies original/replaceable semantics.
- Screenshot capture outranks generated output.
- Generated provenance is complete or rejected.
- Frozen corpus replay uses the production fusion function.
- No commit or push step exists because the user prohibited both.
