# Axure Fresh Holdout A-008

**Task:** A-008  
**Status:** `fail-unseen-holdout`  
**Date:** 2026-10-25  
**Manifest:** `tests/fixtures/axure_holdout_v3/holdout_v3.json`  
**Manifest SHA-256:**
`ade70fe927cb028e462a503131ece6c0f355d60117237a41d773fe6c60f967f4`  
**Evidence root:** `output/_axure_holdout_v3_2026-10-25/`

**Summary SHA-256:**
`ee54c12fa126131357d15500b487a56cf0c36eb9302e6bd311aceda58936dbc9`

## Result

A-008 froze three samples not used by A-005, A-006 or A-007:

- `AX8-DOM-IFRAME`;
- `AX8-DOM-PARTIAL-ASSET`;
- `AX8-DOM-MOBILE320`.

The aggregate result is `fail-unseen-holdout`. One sample passes cleanly,
one exposes a rendered-content failure, and one is inconclusive because the
frozen asset-count expectation conflicts with the sample truth.

No product code was changed after the initial result was observed.

| Sample | Object graph | Critical text | Assets | Within-30 | Automated | Reference review |
|---|---|---|---:|---:|---|---|
| AX8-DOM-IFRAME | pass | `4/4` | `0/0` | `97.9419047619048%` | pass | fail |
| AX8-DOM-PARTIAL-ASSET | pass | `2/2` | `2/2` | `100%` | fail | match |
| AX8-DOM-MOBILE320 | pass | `5/5` | `1/1` | `98.55859375%` | pass | pass |

## AX8-DOM-IFRAME Failure

The `.rp` is deterministic, conformance-valid and contains all eight primary
widgets with no extra or missing object. The automated critical-text gate also
finds all four strings as widget text. Those checks do not prove that the
text is rendered at the correct location.

The actual screenshot shows:

- the page title and `Accessible iframe content` overlapping near the top;
- no visible accessible iframe content inside the left frame.

The right sandboxed frame is also blank, but the fixture truth explicitly
marks `Sandboxed iframe content` as expected-absent, so that blank is not a
failure.

The source DesignSpec already places the accessible iframe Text at
`(16,37)`, overlapping the title, instead of inside the left frame. The Axure
writer faithfully reproduces that incorrect source geometry. This is an
upstream DOM/frame-coordinate failure in the full route, not a new Axure
writer regression.

A pixel-region check of the expected iframe-content block
`(14,120)-(300,160)` reports `8.278%` ink in the reference and `0%` ink in the
Axure render. Overall within-30 remains `97.9419%` because the missing content
occupies little page area. This confirms the need to keep reference review
separate from aggregate pixel scores.

## AX8-DOM-PARTIAL-ASSET Contract Conflict

The published output is pixel-identical to the reference:

- within-30 `100%`;
- over-30 `0%`;
- critical text `2/2`;
- published images `2/2` with no unexpected hash.

The sample truth declares two image elements with a minimum accepted count of
one. The frozen A-008 manifest instead expected one renderable asset. The
acceptance CLI therefore records `asset-count: expected 1, actual 2`.

This sample cannot prove an output failure or a clean pass under the frozen
manifest. Its classification is `evaluation-contract-inconclusive`. The
manifest must not be changed after observation; a later task must clarify the
declared-versus-renderable asset contract before using this input again.

## AX8-DOM-MOBILE320 Pass

The narrow `320x800` sample has nine primary widgets, five native Text
widgets, one local image and no comparison mismatch. The screenshot preserves
wrapping, the card, image and footer. Visual metrics are:

- within-30 `98.55859375%`;
- over-30 `1.44140625%`;
- exact size match.

## Artifact And Reopen Evidence

| Sample | `.rp` SHA-256 | Bytes | Repeat | Publish | Reload publish |
|---|---|---:|---|---|---|
| AX8-DOM-IFRAME | `59bcb8a0953246ecfbcf64dac68f80522da253395f9489630ca9c656b6bf3f98` | `48380` | identical | 153 files | 153 files |
| AX8-DOM-PARTIAL-ASSET | `4997639847c6ace2181544eb8d346508fd482991f278f3013a29623d95646edf` | `49721` | identical | 155 files | 155 files |
| AX8-DOM-MOBILE320 | `28cc605ada11c1bacc5848fbc4939a80ab0ef2085efba979ee4a48927caf0b65` | `49974` | identical | 154 files | 154 files |

All six Axure publish runs returned `RESULT=OK`. For every sample:

- the published page HTML is byte-identical across reopen;
- normalized `data.js` is identical;
- only line 5 changes, solely in Axure's `generationDate`.

## Evidence

- Frozen manifest:
  `tests/fixtures/axure_holdout_v3/holdout_v3.json`
- Manifest test:
  `tests/v2/test_axure_holdout_v3_manifest.py`
- Generation snapshot:
  `output/_axure_holdout_v3_2026-10-25/initial_generation.json`
- Reopen comparison:
  `output/_axure_holdout_v3_2026-10-25/reload_check.json`
- Machine summary:
  `output/_axure_holdout_v3_2026-10-25/summary.json`
- Per-sample artifacts and acceptance:
  `output/_axure_holdout_v3_2026-10-25/run/`

## Verification

```text
A-008 manifest tests: 4 passed in 0.08s
tests/v2: 726 passed in 40.70s
A-008 touched-file Ruff check/format: pass
JSON parsing: 4/4 pass
node --check figma_bridge/code.js: pass
git diff --check: pass
Axure conformance: 3 files, c1 8/8, stores 7/7, pages 1/1, ok
```

## Claim Boundary

A-008 does not establish Axure generalization. It shows one clean narrow-page
pass, one real full-route iframe placement failure that automated text labels
did not catch, and one acceptance-contract conflict.

A-006 remains `fail-unseen-holdout`. A-007 remains completed remediation
evidence but does not turn A-006 into a pass. A-009 must:

1. reproduce and repair iframe child-coordinate placement through TDD;
2. add rendered critical-region verification so visible absence cannot hide
   behind a label-only text check;
3. clarify the partial-asset declared versus renderable asset contract;
4. use a new untouched holdout before making a generalization claim.

Runtime image replacement, Auto Layout, clipping, native letter spacing,
interaction reconstruction and save-back mutation remain non-claims.
