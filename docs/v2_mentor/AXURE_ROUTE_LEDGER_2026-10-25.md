# Axure Route Ledger

**Status:** A-011 Axure current scope `pass-current-scope`  
**Next task:** await user priority decision: capability expansion or production admission  
**Date:** 2026-10-25

## Task Status

| ID | Status | Evidence |
|---|---|---|
| A-001 | complete-current-scope | `AXURE_SHARED_IR_BOUNDARY_2026-10-25.md`; `output/_axure_shared_ir_2026-10-25_r1/summary.json` |
| A-002 | complete-current-scope | `AXURE_DOM_ACCEPTANCE_2026-10-25.md`; `output/_axure_dom_acceptance_2026-10-25_r2/` |
| A-003 | complete-current-scope | `AXURE_IMAGE_ACCEPTANCE_2026-10-25.md`; `output/_axure_image_acceptance_2026-10-25_r2/` |
| A-004 | complete-current-scope | independent DOM and image Axure acceptance reports and JSON |
| A-005 | partial-post-holdout-tuning | `AXURE_HOLDOUT_ACCEPTANCE_2026-10-25.md`; `output/_axure_holdout_2026-10-25/summary.json` |
| A-006 | fail-unseen-holdout | `AXURE_HOLDOUT_V2_ACCEPTANCE_2026-10-25.md`; `output/_axure_holdout_v2_2026-10-25/summary.json` |
| A-007 | complete-current-scope | `AXURE_EXTRA_RECT_ATTRIBUTION_2026-10-25.md`; `output/_axure_holdout_v2_2026-10-25/a007_retriage/AX6-DOM-TEXTFLOW/` |
| A-008 | fail-unseen-holdout | `AXURE_FRESH_HOLDOUT_A008_2026-10-25.md`; `output/_axure_holdout_v3_2026-10-25/summary.json` |
| A-009 | complete-current-scope | `AXURE_A009_RENDERED_REGION_REPAIR_2026-10-25.md`; `output/_axure_a009_2026-10-25/summary.json` |
| A-010 | pass-unseen-holdout | `AXURE_FRESH_HOLDOUT_A010_2026-10-25.md`; `output/_axure_holdout_v4_2026-10-25/summary.json` |
| A-011 | pass-current-scope | `AXURE_CURRENT_SCOPE_EXIT_REVIEW_2026-10-25.md`; `output/_axure_current_scope_exit_2026-10-25/summary.json` |

## A-001 Evidence

- Contract: `src/app/services/contracts/output_ir.py`
- Probe: `scripts/axure_shared_ir_probe.py`
- Report: `docs/v2_mentor/AXURE_SHARED_IR_BOUNDARY_2026-10-25.md`
- Evidence root: `output/_axure_shared_ir_2026-10-25_r1/`

| Case | Frames | Nodes | Assets | Axure unsupported |
|---|---:|---:|---:|---|
| `IMG-MVP-01-figma` | 1 | 21 | 1 | `runtime-image-replace` |
| `DQ-R02-figma` | 1 | 440 | 54 | `letter-spacing` |

- IR validation issues: `0` for both cases.
- Source identity and display identity are separate; verified original bytes
  may coexist with a reference-only display crop.
- Axure projections set `figma_evidence_transferable=false` and
  `image_figma_evidence_transferable=false`.
- Summary content hash:
  `5784de5527dc3fe214bb2c8b63bcd40b060f031e4626201bda5525a75d41b04c`.

## A-001 Verification

```text
focused output IR tests: 12 passed in 0.71s
tests/v2: 683 passed in 39.05s
ruff check: all checks passed
node --check figma_bridge/code.js: exit 0
git diff --check: pass
```

## A-002 Evidence

- Report: `docs/v2_mentor/AXURE_DOM_ACCEPTANCE_2026-10-25.md`
- Route: `src/app/services/rendering/axure_route.py`
- Object-graph inspector: `src/app/services/rendering/axure/evidence.py`
- Publish acceptance: `src/app/services/evidence/axure_acceptance.py`
- Probe: `scripts/axure_dom_output.py`
- Acceptance CLI: `scripts/axure_acceptance.py`
- Evidence root: `output/_axure_dom_acceptance_2026-10-25_r2/`

| Item | Result |
|---|---|
| Shared IR | `design-ir/2.0`, document `fbc635...a8ed` |
| Axure page | `A002 DQ-R02 DOM Axure` |
| Page package GUID | `8f1cd483-2b3b-47f2-afd1-4d4b937b6e3e` |
| Canvas | `1440 x 2544` |
| `.rp` SHA-256 | `4a18721adb6d6a709b2050b9f14f0a3624f7b9c75ffa845a7bbf65296a011944` |
| Repeat `.rp` | byte-identical |
| Widgets | `469`; Button 119, Image 54, Rect 204, Text 91, TextField 1 |
| Image uses | `54`; 44 reference crops, 10 generated approximations |
| Published unique assets | `30/30` hashes matched |
| Critical text | `3/3` |
| Axure open/reopen publish | both `RESULT=OK`, 183 files each |
| Published page HTML | byte-identical across reopen |
| Axure visual within-30 | `99.37718378756114%` against original DOM screenshot |

Axure-specific non-claims remain: runtime image replacement, native
letter-spacing, Auto Layout, clipping, component instances and interaction
reconstruction. Four letter-spacing nodes use the captured hard-line
workaround. Generated icon bytes are not original assets.

## A-002 Verification

```text
A-002 focused tests: 15 passed in 2.57s
tests/v2: 698 passed in 40.47s
A-002 touched-file Ruff check/format: pass
whole-repo Ruff baseline: 133 existing findings outside this task
node --check figma_bridge/code.js: pass
git diff --check: pass
Axure conformance: c1 8/8, stores 7/7, pages 1/1, ok
```

## A-003 And A-004 Evidence

- Report: `docs/v2_mentor/AXURE_IMAGE_ACCEPTANCE_2026-10-25.md`
- Image CLI: `scripts/image_axure_mvp.py`
- Evidence root: `output/_axure_image_acceptance_2026-10-25_r2/`

| Item | Result |
|---|---|
| Input | `IMG-MVP-01`, original screenshot SHA-256 `7f39ef...3df4` |
| Shared IR | `design-ir/2.0`, document `63470f...02ff` |
| Axure page | `A003 IMG-MVP-01 Image Axure` |
| Page package GUID | `12bce8ac-d8f0-46c8-9da0-213fbf460010` |
| Canvas | `1200 x 800` |
| `.rp` SHA-256 | `c48b3b076de70229af81cf26602e2b305b8375f9377fd7f1b6d82fb9f849a6b1` |
| Repeat `.rp` | byte-identical |
| Widgets | `22`; Text 14, Button 2, Image 1, Rect 5 |
| Critical text | `14/14` |
| Published image | `1/1`, reference-only crop |
| Axure open/reopen publish | both `RESULT=OK`, 154 files each |
| Published page HTML | byte-identical across reopen |
| Axure visual within-30 | `96.57197916666667%` against original screenshot |
| Runtime image replacement | unsupported; creation-only ImageBox |

```text
Axure-focused regression set: 32 passed in 2.63s
tests/v2: 703 passed in 40.81s
A-003/A-004 touched-file Ruff check/format: pass
whole-repo Ruff baseline: 133 existing findings outside this task
node --check figma_bridge/code.js: pass
git diff --check: pass
Axure conformance: c1 8/8, stores 7/7, pages 1/1, ok
```

A-004 is closed for the controlled DOM and image samples because both routes
have independently parsed Axure page/widget/asset evidence and published HTML
acceptance. General Axure capability and production-readiness claims remain
false.

## A-005 Evidence

- Report: `docs/v2_mentor/AXURE_HOLDOUT_ACCEPTANCE_2026-10-25.md`
- Manifest: `tests/fixtures/axure_holdout/holdout_v1.json`
- Evidence root: `output/_axure_holdout_2026-10-25/`

The frozen samples were DQ-R01 React, DQ-R03 Shoelace and AX-IMG-H01.
Initial results exposed DQ-R01 asset binding, DQ-R03
`89.69745030511753%` visual and AX-IMG-H01 `1/3` critical text / `1/3`
assets.

TDD fixes produced final post-tuning passes:

| Sample | Critical | Assets | Within-30 | `.rp` SHA-256 |
|---|---:|---:|---:|---|
| DQ-R01 | `3/3` | `80/80` | `93.7288067818298%` | `43ab92de...99b7c` |
| DQ-R03 | `3/3` | `29/29` | `90.2025368557791%` | `e1459c55...e5be` |
| AX-IMG-H01 | `3/3` | `3/3` | `97.24269841269842%` | `b7709b8c...fa8e3` |

The same holdout drove remediation, so the result is not clean unseen
generalization. Fresh Grounding preparation also varied across repeated image
runs; final image evidence is tied to the frozen `AX-IMG-H01_v2` prepared
DesignSpec.

```text
A-005 focused regression set: 54 passed in 2.79s
tests/v2: 717 passed in 41.63s
A-005 touched-file Ruff check/format: pass
whole-repo Ruff baseline: 133 existing findings outside this task
node --check figma_bridge/code.js: pass
git diff --check: pass
Axure conformance: 3 files, all pass
```

## A-006 Evidence

- Report: `docs/v2_mentor/AXURE_HOLDOUT_V2_ACCEPTANCE_2026-10-25.md`
- Manifest: `tests/fixtures/axure_holdout_v2/holdout_v2.json`
- Evidence root: `output/_axure_holdout_v2_2026-10-25/`

| Sample | Object graph | Critical | Assets | Within-30 | Result |
|---|---|---|---:|---:|---|
| AX6-DOM-TEXTFLOW | fail | `3/3` | `0/0` | `99.34079365079364%` | fail |
| AX6-DOM-FONTFALLBACK | pass | `3/3` | `0/0` | `96.15206349206349%` | pass |
| AX6-IMG-OVERLAY | pass | `3/3` | `1/1` | `97.60984126984127%` | pass |

AX6-DOM-TEXTFLOW's `.rp` contains 7 widgets against 6 projected primary
widgets. The extra object is an empty Rect at `(24,178)`, size `360x96`.
Its source was not resolved in A-006. No code or threshold changed after the
result.

```text
A-006 manifest tests: 3 passed in 0.06s
tests/v2: 720 passed in 40.09s
A-006 touched-file Ruff check/format: pass
node --check figma_bridge/code.js: pass
git diff --check: pass
Axure conformance: 3 files, all pass
```

## A-007 Evidence

- Report: `docs/v2_mentor/AXURE_EXTRA_RECT_ATTRIBUTION_2026-10-25.md`
- Plan:
  `docs/superpowers/plans/2026-10-25-axure-extra-rect-attribution.md`
- Comparator: `src/app/services/rendering/axure/evidence.py`
- Regression: `tests/v2/test_axure_evidence.py`
- Evidence root:
  `output/_axure_holdout_v2_2026-10-25/a007_retriage/AX6-DOM-TEXTFLOW/`
- Summary SHA-256:
  `b07100be364b8bcbfcc89ec9d646bb1c25a05ebb0c10cf1752d7bc94ecb58e4f`

The extra Rect is a legitimate derived background for the styled source Text.
`adapter_base._render_page` emits it with the source outer box because the
text has non-neutral fill and a border. Axure emits the editable Text with the
border content box:

| Object | Geometry | Attribution |
|---|---|---|
| Unlabeled Rect | `(24,178)`, `360x96` | auxiliary background |
| Source Text | `(25,179)`, `358x96` | matched primary Text |

The comparator now accepts an unlabeled Rect only after a Text has matched,
when Rect geometry equals that Text's source outer geometry within `0.5 px`,
and consumes the Text's single background allowance. It records the mapping in
`auxiliary_widgets`.

| Item | Result |
|---|---|
| A-006 and A-007 `.rp` SHA-256 | `acc356d7a5d30dcdc2b5d47294d1007e34e9bffc23d3c26ee6cbf15cc946913c` |
| Artifact size | `48,440` bytes |
| Deterministic repeat | byte-identical |
| Widgets | `7`; primary `6`; auxiliary `1`; extra `0` |
| Comparison mismatches | `[]` |
| Comparison | `ok=true` |
| Auxiliary source | `section "Flow block keeps na…"` |
| Published acceptance | pass; `3/3` critical; assets `0/0`; within-30 `99.34079365079364%` |
| Publish in A-007 | none; existing A-006 publish reused because bytes are identical |
| Axure conformance | `c1=8/8`, `stores=7/7`, pages `1/1`, ok |

```text
A-007 focused evidence tests: 10 passed in 1.58s
tests/v2: 722 passed in 41.23s
A-007 touched-file Ruff check/format: pass
node --check figma_bridge/code.js: pass
git diff --check: pass
Axure conformance: 1 file, c1 8/8, stores 7/7, pages 1/1, ok
```

A-006 remains a clean unseen-holdout failure. A-007 is remediation evidence,
not a retroactive pass. A-008 must use a new untouched holdout before claiming
generalization.

## A-008 Evidence

- Report: `docs/v2_mentor/AXURE_FRESH_HOLDOUT_A008_2026-10-25.md`
- Plan: `docs/superpowers/plans/2026-10-25-axure-fresh-holdout-a008.md`
- Manifest: `tests/fixtures/axure_holdout_v3/holdout_v3.json`
- Manifest SHA-256:
  `ade70fe927cb028e462a503131ece6c0f355d60117237a41d773fe6c60f967f4`
- Evidence root: `output/_axure_holdout_v3_2026-10-25/`
- Generation snapshot:
  `output/_axure_holdout_v3_2026-10-25/initial_generation.json`
- Reopen check:
  `output/_axure_holdout_v3_2026-10-25/reload_check.json`
- Summary:
  `output/_axure_holdout_v3_2026-10-25/summary.json`
- Summary SHA-256:
  `ee54c12fa126131357d15500b487a56cf0c36eb9302e6bd311aceda58936dbc9`

| Sample | Object mapping | Critical labels | Assets | Within-30 | Initial result |
|---|---|---|---:|---:|---|
| AX8-DOM-IFRAME | pass | `4/4` | `0/0` | `97.9419047619048%` | visual semantic fail |
| AX8-DOM-PARTIAL-ASSET | pass | `2/2` | `2/2` | `100%` | manifest contract conflict |
| AX8-DOM-MOBILE320 | pass | `5/5` | `1/1` | `98.55859375%` | pass |

All three `.rp` files are deterministic and conformance-valid. All six Axure
publish runs returned `RESULT=OK`; page HTML is byte-identical across reopen
and normalized `data.js` differs only in `generationDate`.

The iframe source DesignSpec places `Accessible iframe content` at `(16,37)`
over the title instead of inside the left frame. The reference iframe-content
region contains `8.278%` ink while the Axure render contains `0%`. The
automated critical-text gate passes because it checks widget labels, not
visible rendered regions. This is a full-route upstream placement failure.

The partial-asset output is pixel-identical to the reference and matches both
published image hashes. The truth declares two image elements with minimum
one accepted asset, while the frozen A-008 manifest expected exactly one. The
sample is retained as `evaluation-contract-inconclusive`; the manifest is not
changed after observation.

```text
A-008 manifest tests: 4 passed in 0.08s
tests/v2: 726 passed in 40.70s
A-008 .rp conformance: 3 files, c1 8/8, stores 7/7, pages 1/1, ok
A-008 publish/reload: 6 RESULT=OK, 153/155/154 files
A-008 automated acceptance: iframe pass, partial asset-count fail, mobile pass
A-008 aggregate: fail-unseen-holdout
A-008 touched-file Ruff/format, Node, JSON and diff-check: pass
```

## A-009 Evidence

- Report: `docs/v2_mentor/AXURE_A009_RENDERED_REGION_REPAIR_2026-10-25.md`
- Plan:
  `docs/superpowers/plans/2026-10-25-axure-a009-rendered-region-repair.md`
- Evidence root: `output/_axure_a009_2026-10-25/`
- Repaired manifest:
  `output/_axure_a009_2026-10-25/repaired_manifest.json`
- Summary SHA-256:
  `ff7832afa438edc8fdcc72232eb526a182d096178c06ada629648908ab924dd8`
- Refreshed iframe input:
  `output/_axure_a009_2026-10-25/prepared/samples/iframe/12_design.json`
- Acceptance tests: `11 passed`

The iframe failure was caused by A-008 using a stale DesignSpec. Current
frame capture already places `Accessible iframe content` at `(18,133)`.
Regenerating from source changed the DesignSpec hash from
`3cf8f478...07193e9` to `72499117...5825df2` while leaving the reference
screenshot unchanged.

`evaluate_published_axure` now accepts critical rendered regions and measures
reference/render ink at threshold `<200`. A region fails when the screenshot
pair is unavailable, geometry is invalid, reference ink is below `0.5%`, or
render/reference ink is below `0.25`.

| Sample | `.rp` SHA-256 | Critical | Assets | Within-30 | Region |
|---|---|---|---:|---:|---|
| Repaired iframe | `029891f5...666c9b3` | `4/4` | `0/0` | `99.0969841269841%` | inked, pass |
| Repaired partial asset | `d3e3d8a2...75b529` | `2/2` | `2/2` | `100%` | not required |

The repaired iframe region `(14,120,286,40)` has reference/render ink
`7.01923076923077% / 7.01923076923077%`, ratio `1.0`. Replaying the A-008 old
render fails with `critical-region-missing` at `7.01923076923077% / 0%`.

The partial-asset contract now records two declared/displayed assets and one
missing-original asset. Both published image hashes match with zero unexpected
hashes.

Both repaired artifacts are deterministic, conformance-valid and
`RESULT=OK` across initial/reopen publish. Page HTML is identical; normalized
`data.js` differs only in `generationDate`.

```text
A-009 Axure acceptance tests: 11 passed in 1.70s
A-009 tests/v2: 728 passed in 41.66s
A-009 repaired artifacts: 2 deterministic, conformance 2/2
A-009 publish/reopen: 4 RESULT=OK, 153/155 files
A-009 Ruff/format, Node, JSON and diff-check: pass
```

A-009 is not a new untouched holdout and does not retroactively pass A-008.
A-010 is required before claiming generalization.

## A-010 Evidence

- Report: `docs/v2_mentor/AXURE_FRESH_HOLDOUT_A010_2026-10-25.md`
- Plan: `docs/superpowers/plans/2026-10-25-axure-fresh-holdout-a010.md`
- Manifest: `tests/fixtures/axure_holdout_v4/holdout_v4.json`
- Manifest SHA-256:
  `eae21d14cf44757943ccc94d9eff330af1664c2272c30a09e5582221b56a48db`
- Evidence root: `output/_axure_holdout_v4_2026-10-25/`
- Summary SHA-256:
  `7f181e626d1ea453d853cb4e5510bc3b7425ce172d07c28ac3a09a208a4ab17f`

| Sample | Object mapping | Critical text | Assets | Regions | Within-30 |
|---|---|---|---:|---:|---:|
| AX10-DOM-ASSETS | pass | `3/3` | `3/3` | `3/3` | `98.9707936507937%` |
| AX10-DOM-TRANSPARENT-CROP | pass | `3/3` | `1/1` | `3/3` | `98.9557142857143%` |
| AX10-DOM-NESTED-IFRAME | pass | `5/5` | `0/0` | `4/4` | `98.9097777777778%` |

All three screenshots pass manual reference review. All three `.rp` files are
deterministic and conformance-valid; six publish runs returned `RESULT=OK`,
and page HTML is identical after reopen with only `generationDate` changing in
normalized `data.js`.

The result is a clean pass for the frozen three-sample holdout. It does not
upgrade arbitrary DOM -> Axure, production, Auto Layout, runtime replacement,
clipping, native letter spacing, interaction or save-back claims.

```text
A-010 manifest tests: 4 passed in 0.08s
A-010 tests/v2: 732 passed in 40.43s
A-010 artifacts: 3 deterministic, conformance 3/3
A-010 publish/reload: 6 RESULT=OK, 156/154/153 files
A-010 Ruff/format, Node, JSON and diff-check: pass
```

## A-011 Exit Review

- Report: `docs/v2_mentor/AXURE_CURRENT_SCOPE_EXIT_REVIEW_2026-10-25.md`
- Plan:
  `docs/superpowers/plans/2026-10-25-axure-current-scope-exit-review.md`
- Summary:
  `output/_axure_current_scope_exit_2026-10-25/summary.json`
- Summary SHA-256:
  `944d406bda542247b6597d78a93b88b3ccad786cc20ba61973bdb1245830409b`

Decision: `pass-current-scope`.

| Scope | Decision |
|---|---|
| `DOM -> Axure` controlled DesignSpec | pass-current-scope |
| `image -> Axure` named controls | pass-current-scope |
| Independent published acceptance | pass |
| Deterministic open/reopen publish | pass |
| Arbitrary DOM/image generalization | not claimed |
| Production admission | not claimed |

A-010 controls the fresh DOM-holdout decision. A-003 and A-006 control the
named image samples. A-006/A-008 remain historical failures with A-007/A-009
remediation evidence retained separately.

The image route was not rerun with the A-009 visible-region gate. This remains
a coverage limitation but does not upgrade or invalidate the named
current-scope samples.

No further Axure implementation is admitted automatically. The next step
requires the user to choose:

1. Axure capability expansion; or
2. a separate production-admission phase.

## Claim Boundary

Both current Axure routes have real `.rp` write, Axure RP 8 open/reopen
publish and independent published acceptance for controlled samples. A-005
is post-tuning evidence. A-006 and A-008 are clean unseen holdout failures.
A-007 attributes A-006's extra object and repairs the comparator for that
behavior. A-008 exposes a separate iframe placement/verification failure and
an asset-contract ambiguity. A-009 repairs the stale iframe input, adds a
rendered-region gate and corrects the asset contract, but its samples are not
a new untouched holdout. A-010 then passes three new frozen samples, supporting
a holdout-scoped generalization result only. A-011 closes the named controlled
Axure current scope. It does not transfer into production admission.

Figma acceptance remains non-transferable. Runtime image replacement, native
letter-spacing, Auto Layout, clipping, component instances, interaction
reconstruction, deterministic fresh Grounding preparation and save-back
mutation remain explicit non-claims.
