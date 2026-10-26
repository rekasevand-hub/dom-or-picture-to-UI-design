# Axure Fresh Holdout A-008 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure Axure generalization on three frozen samples that were not
used by A-005, A-006 or A-007, without tuning product code before recording
the initial result.

**Architecture:** Reuse the existing DOM DesignSpec -> Axure route, object
graph comparator, Axure RP 8 publish script, Playwright screenshot capture
and independent published acceptance. Freeze all input hashes first, then run
each sample independently and report every gate without a composite score.

**Tech Stack:** Python 3.11, Playwright, Axure RP 8.0.0.3400, pytest,
PowerShell UI Automation.

**Spec:**
`docs/v2_mentor/AXURE_EXTRA_RECT_ATTRIBUTION_2026-10-25.md`

**Execution status:** `fail-unseen-holdout` on 2026-10-25.

## Global Constraints

- All three samples must be absent from A-005, A-006 and A-007 manifests.
- Freeze design, screenshot and truth hashes before generating `.rp` files.
- Record the initial result before any product-code remediation.
- Keep critical text, assets, object mapping, determinism, size and visual
  gates separate; no composite score.
- A-006 remains `fail-unseen-holdout`; A-007 remains remediation evidence.
- Do not overwrite prior holdout evidence.
- Do not commit or push.

## File Structure

- `tests/fixtures/axure_holdout_v3/holdout_v3.json` is the frozen manifest.
- `tests/v2/test_axure_holdout_v3_manifest.py` validates samples, exclusions,
  thresholds and every input hash.
- `output/_axure_holdout_v3_2026-10-25/` owns A-008 artifacts and acceptance.
- `docs/v2_mentor/AXURE_FRESH_HOLDOUT_A008_2026-10-25.md` owns the result.

## Review Focus

- A sample reused from prior Axure tuning must fail manifest validation.
- A stale design, screenshot or truth hash must fail before generation.
- A missing image placeholder must not be counted as an original/renderable
  asset without explicit evidence.
- A high visual score must not hide failed object mapping or critical text.
- Reopen publish evidence must distinguish page HTML identity from Axure's
  changing generation timestamp.

### Task 1: Freeze The Fresh Holdout

**Files:**
- Create: `tests/v2/test_axure_holdout_v3_manifest.py`
- Create: `tests/fixtures/axure_holdout_v3/holdout_v3.json`

**Interfaces:**
- Consumes: existing DesignSpec, screenshot and truth files.
- Produces: `axure-holdout/3.0` with exactly three sample records and frozen
  `design_sha256`, `screenshot_sha256` and `truth_sha256`.

- [x] **Step 1: Write the manifest test**

Assert exact sample IDs `AX8-DOM-IFRAME`,
`AX8-DOM-PARTIAL-ASSET`, `AX8-DOM-MOBILE320`; assert every prior Axure sample
is excluded; freeze thresholds at critical `1.0`, asset hash `1.0`, object
mapping `1.0`, deterministic bytes, exact size and visual `90.0`.

- [x] **Step 2: Run the test and verify RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_axure_holdout_v3_manifest.py -q
```

Expected: fail because `holdout_v3.json` does not exist.

- [x] **Step 3: Create the manifest with frozen hashes**

Use:

```text
iframe design:        3cf8f478bb56291ee1551cc963b63dc88ba59f34904cfde000cb86e4e07193e9
iframe screenshot:    c87479613929cc504ac2f727b20843eea9fec18960fb88c2c9eeb19317fa13c6
iframe truth:         aab19b2deaa0a439ebb17febbb4ddc48cd99338af8680dd617c703800b42aaf4
partial design:       617e4d962248deefe10a881138120fcb3175688a842e7a1bf402fb4c6ea3af92
partial screenshot:   2ddad77a910f07567b4ea2ae03f10fea2c3abba0ddd0f9932faee7f891760451
partial truth:        03fd90bbdb1d66ce5947edbe0d9225fda87503605d7eccde2cab3908d3815778
mobile design:        2c63cf025bb17400f5f3bcfb605792a3053b53751bc9c36dd3682f5f04a17f22
mobile screenshot:    8f20c5f56a8c0805e20795cd881b3e443ca4dac5484b9b1d444ae6e6e4d124cd
mobile truth:         ff0217cf96acf7ba34dcf9b0b2d1a497ec10bf1f2d3cab8a5379b42457036dca
```

For `partial-asset`, retain both `declared_asset_count=2` and
`expected_asset_count=1`; the missing image placeholder is not a renderable
asset. Record this distinction in the sample metadata.

- [x] **Step 4: Run the manifest test to verify GREEN**

Expected: `3 passed`.

### Task 2: Generate Frozen Axure Artifacts

**Files:**
- Create: `output/_axure_holdout_v3_2026-10-25/run/<sample>/`

- [x] **Step 1: Generate each sample twice**

Use `scripts/axure_dom_output.py` with `--generate-twice` and the frozen page
name from the manifest.

- [x] **Step 2: Verify object graph and deterministic bytes**

Expected per sample: `comparison_ok=true`, repeat SHA-256 equals primary
SHA-256, no page-order mismatch and zero `widget-extra` rows.

- [x] **Step 3: Run Axure RP 8 conformance**

Expected per `.rp`: `c1=8/8`, `stores=7/7`, one registered page, `[ok]`.

### Task 3: Publish, Reopen And Accept

**Files:**
- Create: `output/_axure_holdout_v3_2026-10-25/run/<sample>/published/`
- Create: `output/_axure_holdout_v3_2026-10-25/run/<sample>/published_reload/`
- Create: `output/_axure_holdout_v3_2026-10-25/run/<sample>/shots/`
- Create: `output/_axure_holdout_v3_2026-10-25/run/<sample>/acceptance.json`

- [x] **Step 1: Publish each `.rp` with Axure RP 8**

Use `scripts/axure_publish_html.ps1`; require `RESULT=OK` and copy the
generated HTML tree into the evidence directory.

- [x] **Step 2: Reopen and republish**

Run the same publish command again and copy the output into
`published_reload/`. Record page HTML equality and the Axure generation date
difference separately.

- [x] **Step 3: Screenshot each published page**

Use `scripts/axure_shoot_html.py` with the manifest width and height.

- [x] **Step 4: Run independent acceptance**

Use `scripts/axure_acceptance.py` with all frozen critical texts, the
renderable expected asset count, reference screenshot and captured render.

- [x] **Step 5: Record the initial result before any remediation**

Write per-sample pass/fail and the aggregate decision. Product-code changes
after this step require a new task.

### Task 4: Publish A-008 Evidence

**Files:**
- Create:
  `docs/v2_mentor/AXURE_FRESH_HOLDOUT_A008_2026-10-25.md`
- Create: `output/_axure_holdout_v3_2026-10-25/summary.json`
- Modify:
  `docs/v2_mentor/AXURE_ROUTE_LEDGER_2026-10-25.md`
- Modify:
  `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`
- Modify: `README.md`
- Modify: `docs/v2_mentor/README.md`

- [x] **Step 1: Report every gate independently**

- [x] **Step 2: State whether a generalization claim is allowed**

- [x] **Step 3: Run final verification**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
C:\Users\lzq\.conda\envs\omni\python.exe -m ruff check <touched Python files>
C:\Users\lzq\.conda\envs\omni\python.exe -m ruff format --check <touched Python files>
node --check figma_bridge\code.js
git diff --check
```

- [x] **Step 4: Point the ledger at the next task or blocker**

**Final result:** `fail-unseen-holdout`. The manifest tests pass `4/4`;
`tests/v2` passes `726 passed in 40.70s`; touched-file Ruff check/format,
Node syntax, JSON parsing, artifact conformance and `git diff --check` pass.
Mobile is a clean pass. Iframe exposes a full-route source-coordinate and
visible-content failure hidden by label-only critical-text acceptance.
Partial-asset exposes a frozen asset-count contract conflict. No product code
was changed after the initial result.
