# D-003 Real-Site DOM Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze a three-site real DOM corpus under an explicit Chromium,
viewport, DPR, locale, timezone, font and threshold profile, with reproducible
capture and drift verification.

**Architecture:** A JSON manifest owns the frozen environment, independent
thresholds, sample states and baseline fingerprints. A pure Python evidence
module validates the contract and evaluates capture fingerprints; a CLI
captures, freezes and verifies real sites without changing the product render
path.

**Tech Stack:** Python 3.12, `unittest`/pytest, Playwright Chromium, existing
capture pipeline, JSON.

**Spec:** `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`

## Global Constraints

- Product route remains `DOM -> Figma`; no image, Axure, production or
  cross-browser claim is opened.
- The corpus uses three required real sites: React, Dushu and Shoelace.
- W3Schools iframe remains a documented exclusion because it previously
  produced `state-unstable / inconclusive`.
- Viewport is `1440x900`, DPR is `1`, locale is `zh-CN`, timezone is
  `Asia/Shanghai`, headless is `true`.
- Thresholds and truth files must be complete before measurement and must not
  be changed after observing results.
- No composite score and no `verified` upgrade in D-003.
- Do not commit or push.
- Preserve all pre-existing worktree changes.

## Review Focus

- A live site changing structure must fail drift verification rather than
  silently rewriting its baseline.
- A login/challenge page must not count as corpus content.
- Dynamic document text must not be mistaken for a stable critical string.
- A bounded Grid/font/asset probe must not become a project-wide claim.
- An excluded W3Schools sample must not remain in the quality denominator.
- Environment fields declared as frozen must be configured in the browser,
  not merely written into JSON.

---

### Task 1: Define And Validate The Draft Corpus

**Files:**
- Create: `src/app/services/evidence/dom_quality_corpus.py`
- Create: `tests/v2/test_dom_quality_corpus.py`
- Create: `tests/fixtures/dom_quality/real_site_corpus_v1.json`

**Interfaces:**
- Consumes: existing `capture_state_signature()` semantics.
- Produces:
  - `load_corpus(path: str | Path) -> dict[str, Any]`
  - `validate_corpus(document: dict[str, Any]) -> tuple[str, ...]`
  - `thresholds_sha256(document: dict[str, Any]) -> str`

- [x] **Step 1: Write failing draft-validation tests**

Tests must require:

- exact schema `dom-quality-real-site-corpus/1.0`;
- exactly three required samples with unique IDs;
- React, Dushu and Shoelace HTTPS URLs;
- explicit environment and every independent threshold;
- critical text, required markers and known exclusions;
- W3Schools present only under `excluded_sites`.

- [x] **Step 2: Run focused test to verify RED**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_dom_quality_corpus.py -q
```

Expected: FAIL because the module and manifest do not exist.

- [x] **Step 3: Implement minimal validation and draft manifest**

Use frozen values:

```text
viewport: 1440x900
DPR: 1
locale: zh-CN
timezone: Asia/Shanghai
critical text rate: 1.0
required object rate: 1.0
linebreak rate: 0.98
text box tolerance: 2.0 px
baseline tolerance: 1.0 px
structure geometry tolerance: 2.0 px
visual mean max: 3.0
visual ink mean max: 100.0
visual over30 max: 2.5%
visual bad-pixel ratio max: 0.03
```

The manifest starts as `status=draft`; frozen-only fingerprint checks are
added in Task 2.

- [x] **Step 4: Run focused test to verify GREEN**

Run the same focused command.

Expected: PASS.

---

### Task 2: Configure And Fingerprint The Frozen Environment

**Files:**
- Modify: `src/config/settings.py`
- Modify: `src/app/services/structure/capture.py`
- Modify: `tests/v2/test_dom_quality_corpus.py`
- Modify: `src/app/services/evidence/dom_quality_corpus.py`

**Interfaces:**
- Produces:
  - `Config.playwright_locale: str`
  - `Config.playwright_timezone: str`
  - `capture._browser_context_options(cfg, viewport) -> dict[str, Any]`
  - `build_capture_fingerprint(capture_dir) -> dict[str, Any]`
  - `evaluate_capture(sample, capture_dir, thresholds) -> dict[str, Any]`

- [x] **Step 1: Write failing configuration and fingerprint tests**

Tests must require:

- context options carry locale and timezone;
- fingerprint records raw DOM/page-state/screenshot SHA-256 plus
  `capture_state_signature`;
- critical text and marker minima pass on a matching capture;
- forbidden login text, page-state mismatch, unstable capture, node-count
  drift and text-count drift each fail independently.

- [x] **Step 2: Run focused test to verify RED**

Expected: FAIL because config fields and evidence helpers are absent.

- [x] **Step 3: Implement configuration and fingerprint evaluation**

Extend capture contexts to pass `locale` and `timezone_id` from `Config`.
Defaults preserve `zh-CN` and `Asia/Shanghai`.
Do not add timezone/locale fields only to reports.

- [x] **Step 4: Run focused test to verify GREEN**

Expected: PASS.

---

### Task 3: Add Capture, Freeze And Verify CLI

**Files:**
- Create: `scripts/dom_quality_corpus.py`
- Modify: `tests/v2/test_dom_quality_corpus.py`

**Interfaces:**
- Consumes: the Task 1/2 module functions and
  `capture_page_with_fallback()`.
- Produces:
  - `capture` command: writes fresh capture evidence and a summary;
  - `freeze` command: captures and writes environment, thresholds and sample
    fingerprints into a draft manifest;
  - `verify` command: captures and compares against the frozen manifest.

- [x] **Step 1: Write failing CLI contract test**

Test parser/commands and require explicit modes, manifest path, output path,
and overwrite protection for an existing non-empty output.

- [x] **Step 2: Run focused test to verify RED**

Expected: FAIL because the script does not exist.

- [x] **Step 3: Implement the script**

Use one Chromium capture per sample with:

```text
headless=true
allow_real_session=false
capture_attempts=2
requested_route=auto
wait_networkidle_timeout=30000
```

The script may write `--out`, but must refuse to modify a frozen manifest
unless the explicit `freeze` command is used.

- [x] **Step 4: Run focused test to verify GREEN**

Expected: PASS.

---

### Task 4: Freeze Real-Site Evidence And Publish The Corpus

**Files:**
- Modify: `tests/fixtures/dom_quality/real_site_corpus_v1.json`
- Create: `docs/v2_mentor/DOM_QUALITY_CORPUS_2026-10-25.md`
- Modify: `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`

- [x] **Step 1: Capture and freeze the three required sites**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_quality_corpus.py freeze `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --out output\_dom_quality_corpus_2026-10-25
```

Expected: all three samples have `content` page state, stable capture,
complete fingerprints and no forbidden text.

- [x] **Step 2: Verify frozen drift measurement**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_quality_corpus.py verify `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --out output\_dom_quality_corpus_verify_2026-10-25
```

Expected: status `pass`; if a real site has changed, retain the failure and
do not rewrite the frozen baseline.

- [x] **Step 3: Publish evidence boundaries**

Document:

- corpus ID and freeze date;
- environment hashes;
- required and excluded sites;
- state/threshold definitions;
- sample fingerprints and output evidence paths;
- known non-claims and remaining DOM gaps.

- [x] **Step 4: Update master plan**

Set `D-003` to `complete-current-scope`, activate `D-004`, and point to the
manifest, capture summary, verification summary and corpus document.

- [x] **Step 5: Run mandatory regression**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
node --check figma_bridge\code.js
```

Expected: all tests pass and syntax check exits 0.
