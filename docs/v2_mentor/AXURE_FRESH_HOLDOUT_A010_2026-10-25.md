# Axure Fresh Holdout A-010

**Task:** A-010  
**Status:** `pass-unseen-holdout`  
**Date:** 2026-10-25  
**Manifest:** `tests/fixtures/axure_holdout_v4/holdout_v4.json`  
**Manifest SHA-256:**
`eae21d14cf44757943ccc94d9eff330af1664c2272c30a09e5582221b56a48db`  
**Evidence root:** `output/_axure_holdout_v4_2026-10-25/`

**Summary SHA-256:**
`7f181e626d1ea453d853cb4e5510bc3b7425ce172d07c28ac3a09a208a4ab17f`

## Result

A-010 froze three Axure-untouched samples before generation:

- `AX10-DOM-ASSETS`;
- `AX10-DOM-TRANSPARENT-CROP`;
- `AX10-DOM-NESTED-IFRAME`.

All three pass every frozen gate, including visible critical regions and
reference-image review. No product code was changed after the initial result.

| Sample | Object graph | Critical text | Assets | Regions | Within-30 | Result |
|---|---|---|---:|---:|---:|---|
| AX10-DOM-ASSETS | pass | `3/3` | `3/3` | `3/3` | `98.9707936507937%` | pass |
| AX10-DOM-TRANSPARENT-CROP | pass | `3/3` | `1/1` | `3/3` | `98.9557142857143%` | pass |
| AX10-DOM-NESTED-IFRAME | pass | `5/5` | `0/0` | `4/4` | `98.9097777777778%` | pass |

## Coverage

`AX10-DOM-ASSETS` verifies three distinct visual payloads:

- image element;
- CSS background image;
- inline SVG.

All three published hashes match the expected design payloads with no
unexpected hashes.

`AX10-DOM-TRANSPARENT-CROP` verifies:

- translucent image display;
- cropped source aspect ratio;
- native overlay text.

`AX10-DOM-NESTED-IFRAME` verifies two accessible srcdoc frame levels:

- root document text;
- first child frame;
- grandchild text;
- host-offset placement instead of child-local coordinates.

## Rendered Regions

The regions come from the frozen manifest and use the A-009 ink gate.

| Sample | Region | Reference ink | Render ink | Ratio |
|---|---|---:|---:|---:|
| Assets | heading | `12.32%` | `12.32%` | `1.00` |
| Assets | explanation | `12.71%` | `12.71%` | `1.00` |
| Assets | visual content | `34.38%` | `34.38%` | `1.00` |
| Transparent | overlay text | `85.87%` | `79.86%` | `0.93` |
| Transparent | cropped image | `94.12%` | `91.62%` | `0.97` |
| Transparent | explanation | `9.91%` | `9.91%` | `1.00` |
| Nested iframe | heading | `12.05%` | `12.05%` | `1.00` |
| Nested iframe | root explanation | `8.27%` | `8.27%` | `1.00` |
| Nested iframe | child content | `10.39%` | `10.39%` | `1.00` |
| Nested iframe | grandchild content | `15.54%` | `15.54%` | `1.00` |

Manual comparison of each Axure screenshot against the frozen reference also
passes. No missing iframe content or hidden blank region was found.

## Artifact And Publish Evidence

| Sample | `.rp` SHA-256 | Bytes | Repeat | Publish/reload |
|---|---|---:|---|---|
| Assets | `579ca3b587c4d646fb6427938f9a87845a31bf8f1adbe7a60de4bd5fd1816005` | `49905` | identical | 156 / 156 files |
| Transparent | `1b896e57391fa126f097e05b87305515554a5b0a9b5d1e2f750dd80aecb848e0` | `49633` | identical | 154 / 154 files |
| Nested iframe | `c2dd8dbc03916f03f60ecc67cebfb565cbe347a55746515aa68449f49cf3c5ae` | `48599` | identical | 153 / 153 files |

All six publish runs returned `RESULT=OK`.

For each sample:

- page HTML is byte-identical after reopen;
- normalized `data.js` is identical;
- the only changed payload value is Axure's `generationDate`;
- Axure RP 8 conformance is `c1=8/8`, `stores=7/7`, pages `1/1`.

## Evidence

- Plan:
  `docs/superpowers/plans/2026-10-25-axure-fresh-holdout-a010.md`
- Generation snapshot:
  `output/_axure_holdout_v4_2026-10-25/initial_generation.json`
- Reopen check:
  `output/_axure_holdout_v4_2026-10-25/reload_check.json`
- Machine summary:
  `output/_axure_holdout_v4_2026-10-25/summary.json`
- Per-sample artifacts and acceptance:
  `output/_axure_holdout_v4_2026-10-25/run/`

## Verification

```text
A-010 manifest tests: 4 passed in 0.08s
tests/v2: 732 passed in 40.43s
A-010 Ruff check/format: pass
node --check figma_bridge/code.js: pass
JSON parsing: 7/7 pass
git diff --check: pass
Axure conformance: 3 files, c1 8/8, stores 7/7, pages 1/1, ok
```

## Claim Boundary

A-010 supports a pass for this frozen three-sample unseen holdout. It does not
prove arbitrary DOM to Axure generalization, production readiness, runtime
image replacement, Auto Layout, clipping, native letter spacing, interaction
reconstruction or save-back mutation.

A-006 and A-008 remain historical failures. A-009 remains the repaired
input/acceptance scope. A-011 should perform a current-scope exit review and
decide whether the remaining non-claims require new implementation work.
