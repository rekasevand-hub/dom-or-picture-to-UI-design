# Axure Untouched Holdout V2 Acceptance

**Task:** A-006  
**Status:** `fail-unseen-holdout`  
**Date:** 2026-10-25  
**Holdout:** `axure-holdout/2.0`  
**Evidence root:** `output/_axure_holdout_v2_2026-10-25/`

## Decision

A-006 fails the frozen holdout gate on page/object mapping.

- `AX6-DOM-FONTFALLBACK`: pass.
- `AX6-IMG-OVERLAY`: pass.
- `AX6-DOM-TEXTFLOW`: published acceptance passes, but the `.rp` object
  graph contains one unexpected Rect, so the required 100% object mapping
  gate fails.

No remediation was performed after observing this result. The extra Rect is
left as the defect for a separate triage task.

## Frozen Samples

The manifest was frozen before Axure generation:

```text
tests/fixtures/axure_holdout_v2/holdout_v2.json
sha256=564622bd83f4348e2b351400b8eaad55deb7ef1986edf83356c366e8f8ed5719
```

Prior Axure samples were excluded:

```text
DQ-R02
IMG-MVP-01
DQ-R01
DQ-R03
AX-IMG-H01
```

| Sample | Input | Design SHA-256 |
|---|---|---|
| AX6-DOM-TEXTFLOW | canonical mixed text flow | `a8630c1b...b4327` |
| AX6-DOM-FONTFALLBACK | canonical missing-font fallback | `ff24c12b...f14223` |
| AX6-IMG-OVERLAY | frozen overlay screenshot | prepared `2da1cbf0...1ef067` |

The image sample was prepared once before Axure generation. Its screenshot SHA-256 is:

```text
ac8fd6ee2af97f1cd8eb42c43f332d4b52793e349feaa78aaa70e463f3bdc2a7
```

Frozen thresholds:

- critical/asset/page/object mapping `100%`;
- expected asset count exact;
- deterministic `.rp` byte equality;
- exact size match;
- visual within-30 `>=90%`;
- no sample substitution or composite score.

## Results

| Sample | Object graph | Critical | Assets | Within-30 | Sample result |
|---|---|---:|---:|---:|---|
| AX6-DOM-TEXTFLOW | fail | `3/3` | `0/0` | `99.34079365079364%` | fail |
| AX6-DOM-FONTFALLBACK | pass | `3/3` | `0/0` | `96.15206349206349%` | pass |
| AX6-IMG-OVERLAY | pass | `3/3` | `1/1` | `97.60984126984127%` | pass |

### AX6-DOM-TEXTFLOW Failure

Page HTML, critical text, asset count and visual checks pass. The actual
`.rp` contains one unmatched top-level widget:

```text
kind: Rect
label: ""
x/y: 24, 178
size: 360 x 96
```

Observed comparison:

```text
primary_widget_count=6
actual_widget_count=7
mismatch=widget-extra
```

The extra Rect is not represented by the frozen DesignSpec projection. Its
source and intended behavior remain unknown until A-007 triage.

## Real Artifacts

| Sample | Page | Package GUID | Widgets | `.rp` SHA-256 |
|---|---|---|---:|---|
| AX6-DOM-TEXTFLOW | `A006 Mixed Text Flow Axure` | `46670f6f-46c0-4c55-8c35-644ab9f4431c` | 7 | `acc356d7a5d30dcdc2b5d47294d1007e34e9bffc23d3c26ee6cbf15cc946913c` |
| AX6-DOM-FONTFALLBACK | `A006 Font Fallback Axure` | `4d3cbfb8-5a79-4503-a8f3-dabaf6d96fd5` | 4 | `14004071c705d68d4184e1dca819baf3926ebdcedfd63ba535775aa0cb4ffdee` |
| AX6-IMG-OVERLAY | `A006 Overlay Image Axure` | `f1e4b298-9e94-4c77-93c3-89c34a6ddf7a` | 6 | `7915c5ff3d04ec39acc3a960679b633afd84bcff4f9bd33c720352daaf31884b` |

Each `.rp` was generated twice with identical bytes, opened and reopened in
Axure RP 8.0.0.3400 and published successfully. For each sample, page HTML is
identical across reopen; only Axure `data.js` generationDate changes.

| Sample | Published files | Page HTML SHA-256 |
|---|---:|---|
| AX6-DOM-TEXTFLOW | 153 | `f070f021e18b173bc98b3a6b7e3bc37bc30340394ee52025aeddf81f1698b14e` |
| AX6-DOM-FONTFALLBACK | 153 | `ba3396dcbdc385b069d9473bd2ee7b98990b9c6a4d49a52001147e8826e31531` |
| AX6-IMG-OVERLAY | 154 | `5b2f1199c9406a0f6b9781d665c675e339272f7fbd78fe1a4041f88e3865b5de` |

## Evidence

- `summary.json`
- `run/AX6-DOM-TEXTFLOW/`
- `run/AX6-DOM-FONTFALLBACK/`
- `run/AX6-IMG-OVERLAY/`

No thresholds or sample IDs were changed after measurement.

## Next Action

A-007 should triage the extra empty Rect against the frozen DesignSpec. It
must determine whether it is:

- a legitimate auxiliary paint layer omitted from evidence mapping;
- a duplicated/ghost container from the adapter;
- or a foreign object from the Axure template.

After A-007, a new untouched holdout A-008 is required before claiming
generalization.

## Verification

```text
A-006 manifest tests: 3 passed in 0.06s
tests/v2: 720 passed in 40.09s
A-006 touched-file Ruff check/format: pass
node --check figma_bridge/code.js: pass
git diff --check: pass
Axure conformance: 3 files, c1 8/8, stores 7/7, pages 1/1 each
```

## Non-Claims

This task does not claim:

- Axure holdout generalization;
- arbitrary DOM or image fidelity;
- deterministic fresh Grounding preparation;
- original asset identity;
- runtime image replacement, Auto Layout, clipping, native letter spacing or
  interaction reconstruction;
- save-back persistence or production readiness.
