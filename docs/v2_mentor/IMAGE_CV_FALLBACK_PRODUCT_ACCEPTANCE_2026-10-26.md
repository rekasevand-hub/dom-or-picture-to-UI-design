# Image CV Fallback Product-Path Acceptance

**Task:** I-004-R2  
**Date:** 2026-10-26  
**Owned sample result:** `pass-current-scope`  
**Fresh holdout result:** `0/3 passed`, `blocked-fail`  
**Product decision:** keep CV only as an availability fallback; do not claim
general CV fallback quality.

## Intent

Close the gap between the isolated strategy benchmark and the real product
path. The product path is:

```text
image auto
  grounding missing or unavailable
  cv provider
  OCR supplement
  image-region recovery
  deterministic image presentation
  real Figma write/readback/export/probes
```

The prior CV benchmark stopped at the raw CV provider graph. This run exercises
the complete `PreciseAgent` path, including both recovery supplements.

## Routing Evidence

`VISION_API_KEY` was empty during preparation.

```text
requested=auto
attempt 1: grounding unavailable, grounding-config-missing
attempt 2: cv selected
fallback_used=true
selection_policy=grounding-default-cv-only-when-unavailable
```

No provider replacement, monkey patch, or explicit `--route cv` was used.
Ordinary Grounding errors still fail closed under the existing tests.

## Defects Closed By TDD

The first product-path run exposed four concrete issues:

1. OmniParser rectangle captions were rendered as native text, causing
   duplicate overlays.
2. OCR full-line recovery kept covered CV text fragments instead of replacing
   them.
3. CV graph IDs are not assigned before OCR merge. Identity-based deletion
   therefore removed unrelated elements. Replacement now uses a stable
   `source + bbox + text` key.
4. Non-text rectangle captions blocked real OCR text from being added. Only
   text-like nodes now count as text duplicate evidence.

All four behaviors have focused tests. The final implementation does not
promote CV captions to text and replaces covered fragments with the merged OCR
line.

## Owned Sample Result

Evidence root:
`output/_image_cv_fallback_product_2026-10-26_r5/`

| Check | Result |
|---|---|
| Route | `cv`, fallback reason `grounding-config-missing` |
| Figma runtime | observed |
| Frame | `2:62` |
| Critical text | `14/14` |
| Native text edit/restore | pass |
| Reference-only asset replace/restore | pass |
| Structure | pass |
| Visual within-30 | `96.518229%` |
| Size match | `1200x800` |
| OCR supplement | applied, 17 additions, 18 covered replacements |
| Image-region recovery | applied, 1 candidate |
| Original asset claim | false |

The frame is functionally acceptable under the frozen product gate.

Residual visual limitation: a small OCR paragraph fragment (`rt:`) remains
visible below the heading. The current acceptance dimensions do not include a
text-collision metric, so the numeric visual gate does not reject it. This
residual defect is reported rather than hidden.

## Fresh Holdout

Manifest:
`tests/fixtures/image_fallback_holdout_2026-10-26/manifest.json`

The three screenshots come from the frozen A-010 Axure holdout. They were not
used to tune this round's CV fixes. The manifest, thresholds and truth were
frozen before execution, and no post-run tuning was performed.

| Sample | Frame | Critical text | Native text | Asset | Visual | Status |
|---|---|---:|---|---|---:|---|
| `AX10-DOM-ASSETS` | `2:105` | `0/3` | pass | fail | `97.533651%` | `blocked-fail` |
| `AX10-DOM-TRANSPARENT-CROP` | `2:126` | `2/3` | pass | pass | `96.119683%` | `blocked-fail` |
| `AX10-DOM-NESTED-IFRAME` | `2:138` | `3/5` | pass | not-required | `95.470889%` | `blocked-fail` |

All three fit the source dimensions and all three exceed the 90% visual
threshold. They still fail because visual similarity cannot replace text or
structure correctness.

Observed failures:

- assets sample: long explanatory text is missing and only one of three expected
  assets is claimed;
- transparent-crop sample: the main explanatory sentence is incomplete;
- nested-iframe sample: both long explanatory sentences are incomplete;
- the rendered exports contain visible text-fragment and layout defects.

Machine-readable result:
`output/_image_fallback_holdout_2026-10-26/summary.json`

## Decision

1. CV fallback routing is verified on the real product path.
2. The owned `IMG-MVP-01` sample passes the frozen product gate after four TDD
   fixes.
3. CV fallback quality is not generalized: zero of three fresh holdout samples
   pass.
4. Keep CV only as an availability fallback. Do not promote it to the default
   image strategy.
5. Keep fail-closed reporting. A route that completes and exports is not a pass
   unless content, structure, editability, assets and visual gates pass.
6. Do not tune on these three holdout samples while claiming an unseen result.
   A later remediation requires a new frozen holdout.

## Artifact Hashes

| Artifact | SHA-256 |
|---|---|
| Owned design | `1393a04151d5b3e9a30c179c52fac420c5df3486d4dd39589b379f6103399abc` |
| Owned image IR | `378410a11694170351da6e2a51c79bc44c829cffb6dbf8efb808a3025a319ce8` |
| Owned readback | `2509d692a7a931c16feb2ecbc2cbec83b7f852aa446789e46b10fe8c03e4126d` |
| Owned export | `7e21d6011802c608575ec512f987fb734aa5ba0b2f75764cc1b899d815d4dcc8` |
| Owned acceptance | `3ea1d695f4b842b90bdbf375c3ee78a57c2af8d11d3ae7f4b9c0835da2fb31cf` |
| Assets holdout acceptance | `719a7c6e45f43ef626846d64ad0413b1eddc2673b378ca774c9cee117b89a2ed` |
| Transparent holdout acceptance | `0b227d2112c16282f8fd8642151c951479eef3b10b6e77ebf6e64ecefb62c02a` |
| Nested iframe acceptance | `4ae1bd16d1ba32e78bbb6d9a7b2f803badcf08b768893efaf25714d48f4b7160` |

## Non-Claims

- no arbitrary screenshot or production acceptance;
- no claim that a 90% visual score implies readable text;
- no original asset/font/DPR/viewport/hidden-state recovery;
- no adaptive layout;
- no Axure evidence substitution;
- no generalization from the owned passing sample;
- no hybrid adoption.

## Verification

```text
focused image tests: 27 passed
tests/v2: 755 passed
ruff check: pass
ruff format --check: pass
node --check figma_bridge/code.js: pass
bridge JS tests: 20 passed
git diff --check: pass
```
