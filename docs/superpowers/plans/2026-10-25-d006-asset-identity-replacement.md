# D-006 Asset Identity And Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the current-scope DOM asset gap by separating original source
identity, display payload, screenshot crop, missing state and replacement
eligibility across the frozen React/Dushu/Shoelace corpus.

**Architecture:** A pure asset-record contract classifies every source and
display fact without treating a URL or screenshot crop as original bytes. DOM
metadata and direct design carry that record into the output path, while a
separate evidence report joins frozen screenshots, DOM uses and bounded source
probes. Real Figma replacement remains an explicit D-008 runtime check.

**Tech Stack:** Python 3.12, existing Playwright/Chromium capture, Pillow,
`unittest`/pytest, JSON.

**Spec:** `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`

## Global Constraints

- Use `dom-quality-real-sites/1.0` and the existing D-003 Chromium,
  `1440x900`, DPR 1, `zh-CN`, `Asia/Shanghai`, headless environment.
- Do not change `thresholds`, `thresholds_sha256` or `corpus_sha256`.
- A remote URL without verified bytes is `reference-only`, never original.
- A screenshot crop is always `reference-only`, even when its hash is valid.
- Generated or approximate pixels are outside D-006 and can never satisfy an
  original-asset requirement.
- Original status requires retained bytes, SHA-256, detected MIME and positive
  natural dimensions.
- Replacement eligibility requires verified original source bytes; a visually
  identical screenshot crop is insufficient.
- Missing assets remain visible as `partial-not-pass`, not silently dropped.
- Real Figma write/readback/replacement remains `not-evaluated` in D-006 and
  belongs to D-008.
- Preserve all pre-existing worktree changes; do not commit or push.

## Review Focus

- A valid screenshot-crop hash must never promote the crop to original.
- A source URL must never become an asset identity without retained bytes.
- Shared source bytes must produce one asset identity and multiple uses.
- Duplicate display boxes must not be mistaken for duplicate source assets.
- A fetched source whose MIME or dimensions conflict with the DOM observation
  must fail closed instead of becoming replaceable.
- A missing source or missing display region must remain in the denominator.
- Asset replacement must not be claimed from a contract test as real Figma
  runtime success.

## Record Contract

Every use returns one record with these stable sections:

```text
source_identity:
  status: verified-original | reference-only | unavailable | missing
  source_kind: data-uri | network-response | remote-url | inline-svg | none
  payload_sha256, mime, natural_size, bytes_present, provenance

display_payload:
  status: available | missing
  kind: screenshot-crop | none
  payload_sha256, screenshot_sha256, display_box, source_rect, object_fit
  original: false
  reference_only: true

replacement:
  allowed, mode, reason, figma_runtime=not-evaluated

missing:
  is_missing, status, reason, outcome

use:
  use_id, node_index, source_kind, display_box
```

`asset_id` is content-derived for verified source bytes and URL-derived for a
reference-only source. `use_id` is deterministic from the sample and DOM node.

---

### Task 1: Build The Asset Record Contract

**Files:**
- Modify: `src/app/services/structure/asset_metadata.py`
- Modify: `tests/v2/test_p1_asset_metadata.py`

**Interfaces:**
- Produces:
  `build_asset_record(*, sample_id: str, node_index: int, source_kind: str,
  source: str | None, natural_size, source_payload_sha256=None, mime=None,
  source_bytes_present=False, source_provenance=None, display_box=None,
  display_payload_sha256=None, screenshot_sha256=None, source_rect=None,
  object_fit="fill", load_status="loaded") -> dict`
- Produces:
  `deduplicate_asset_records(records: list[dict]) -> dict` with top-level
  `assets`, `uses`, `missing_uses` and `status_counts`.

- [x] **Step 1: Write failing record tests**

Require:

- a complete data URI is `verified-original` and replaceable;
- a remote URL alone is `reference-only` and not replaceable;
- a screenshot crop with a valid hash remains `reference-only` and non-original;
- an incomplete or MIME-conflicting source fails closed;
- a missing image source records `partial-not-pass`;
- two uses of one source hash share one `asset_id` but retain two `use_id`s.

- [x] **Step 2: Run focused test to verify RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_p1_asset_metadata.py -q
```

Expected: FAIL because `build_asset_record` and
`deduplicate_asset_records` do not exist.

- [x] **Step 3: Implement the minimal record contract**

Use retained source bytes plus MIME plus positive natural dimensions as the
only original-asset gate. Keep screenshot crop metadata in a separate
`display_payload` section. Preserve existing helper APIs.

- [x] **Step 4: Run focused test to verify GREEN**

Expected: PASS.

---

### Task 2: Carry Explicit Asset Provenance Through DOM And Direct Design

**Files:**
- Modify: `src/app/services/structure/providers/dom.py`
- Modify: `src/app/services/som/direct_design.py`
- Modify: `src/app/services/rendering/figma_acceptance.py`
- Modify: `tests/v2/test_p1_asset_metadata.py`
- Modify: `tests/v2/test_p1_figma_acceptance.py`

**Interfaces:**
- Consumes: `build_asset_record(...) -> dict`.
- Produces in DOM and DesignSpec:
  `assetIdentity.asset_record`, `displayPayload` and `replacement`.
- Preserves legacy `assetIdentity` fields and `sourceCrop`.

- [x] **Step 1: Write failing integration tests**

Require:

- a data-URI DOM node carries a verified source record;
- a remote DOM node carries a reference-only record;
- direct design records the actual screenshot crop hash as `reference-only`;
- acceptance does not mark a crop-only image as a complete original asset;
- acceptance may mark source-byte replacement eligibility separately from the
  screenshot display payload.

- [x] **Step 2: Run focused tests to verify RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_p1_asset_metadata.py tests/v2/test_p1_figma_acceptance.py -q
```

Expected: FAIL because the new provenance fields are absent.

- [x] **Step 3: Implement provenance carrying without changing geometry**

Attach the record in the DOM provider, update it after screenshot cropping in
direct design, and prefer the explicit record in acceptance. Fall back to the
legacy identity interpretation when older inputs lack the record.

- [x] **Step 4: Run focused tests to verify GREEN**

Expected: PASS with existing image geometry tests unchanged.

---

### Task 3: Build The Frozen-Corpus Asset Evidence Report

**Files:**
- Create: `src/app/services/evidence/dom_asset_quality.py`
- Create: `scripts/dom_asset_quality.py`
- Create: `tests/v2/test_dom_asset_quality.py`

**Interfaces:**
- Produces:
  `collect_asset_uses(dom: list[dict]) -> list[dict]`.
- Produces:
  `build_asset_quality_report(corpus: dict, capture_root: Path,
  source_probes: dict[str, dict]) -> dict`.
- Produces CLI subcommands:
  `probe` for bounded public source-byte acquisition, and `report` for the
  independent corpus ledger.

- [x] **Step 1: Write failing report tests**

Require:

- each frozen sample contributes one per-site row;
- remote source bytes and screenshot crop hashes are reported separately;
- an unverified remote URL and an inline SVG are reference/crop-only;
- a missing `<img>` remains `partial-not-pass`;
- repeated source URLs produce one asset identity and multiple uses;
- the report records unchanged corpus and threshold hashes;
- no composite score, real Figma replacement or generated-asset claim appears.

- [x] **Step 2: Run focused test to verify RED**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_dom_asset_quality.py -q
```

Expected: FAIL because the evidence module and CLI do not exist.

- [x] **Step 3: Implement use collection and report aggregation**

Hash actual screenshot crops with Pillow. Treat source probes as verified only
when bytes, MIME and natural dimensions are present and consistent. Keep
missing uses in the denominator and emit independent asset dimensions.

- [x] **Step 4: Implement bounded source probing**

Reuse `AssetDownloadPolicy` and `download_asset`; enforce per-asset, total-byte,
count and timeout limits. Persist only validated image bytes plus JSON
provenance. A failed probe remains `reference-only`.

- [x] **Step 5: Run focused test to verify GREEN**

Expected: PASS.

---

### Task 4: Produce Real Corpus Evidence And Close Current Scope

**Files:**
- Create: `docs/v2_mentor/DOM_ASSET_QUALITY_2026-10-25.md`
- Create runtime evidence under `output/_dom_asset_quality_2026-10-25/`
- Modify: `docs/v2_mentor/DOM_QUALITY_GAP_REGISTER_2026-10-25.md`
- Modify: `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`

- [x] **Step 1: Run the bounded real-corpus probe**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_asset_quality.py probe `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --capture-root output\_dom_text_quality_capture_2026-10-25 `
  --out output\_dom_asset_quality_2026-10-25
```

Expected: a validated `source_probes.json`; failed network sources remain
explicitly reference-only.

- [x] **Step 2: Build the independent report**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_asset_quality.py report `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --capture-root output\_dom_text_quality_capture_2026-10-25 `
  --source-probes output\_dom_asset_quality_2026-10-25\source_probes.json `
  --out output\_dom_asset_quality_2026-10-25
```

Expected: per-site source, display, missing, deduplication and replacement-mode
counts with six independent dimension statuses.

- [x] **Step 3: Publish the evidence report**

Record exact counts, verified source hashes, crop hashes, failed probes,
missing uses, shared-use counts, replacement modes and all non-claims.

- [x] **Step 4: Update the gap register and master plan**

Close DOM-GAP-010/011/012 only to the evidenced current scope. Keep real Figma
replacement, complex SVG/effect preservation and generated fallback in their
own tasks. Mark D-006 `complete-current-scope` and D-007 `active` only after the
report and mandatory regression pass.

- [x] **Step 5: Run mandatory verification**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
node --check figma_bridge\code.js
```

Expected: all tests pass and syntax check exits 0.

## Self-Review

- Source identity, display payload, crop, missing state and replacement are
  separate in the record and tests.
- Reference-only and screenshot crops cannot satisfy original-asset status.
- Shared assets and duplicate uses have distinct stable identities.
- The frozen manifest and thresholds are read-only inputs.
- Real Figma behavior remains outside D-006 and is named for D-008.
- No commit or push step exists because the user explicitly prohibited both.
