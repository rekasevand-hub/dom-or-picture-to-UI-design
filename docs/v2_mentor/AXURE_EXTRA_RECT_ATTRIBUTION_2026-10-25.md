# Axure Extra Rect Attribution

**Task:** A-007  
**Status:** `complete-current-scope`  
**Date:** 2026-10-25  
**Source holdout:** A-006 `AX6-DOM-TEXTFLOW`  
**A-006 result remains:** `fail-unseen-holdout`

## Question

Why did `AX6-DOM-TEXTFLOW` contain seven widgets when the source projection
had six primary widgets, and was the extra empty `360x96` Rect at `(24,178)`
a ghost object?

## Root Cause

The Rect is not a ghost or foreign template node. It is a derived auxiliary
background emitted for a styled native Text widget.

The frozen source DesignSpec contains two overlapping elements:

- container `C6` at `(24,178)`, size `360x96`, fill `#eef5ff`, border
  `#2f6fed`;
- Text `id=3` with the same outer geometry and paint.

`adapter_base._render_page` emits an unlabeled Rect for a Text whose fill is
non-neutral. The Axure adapter then emits the editable Text using the border
content box:

| Object | Geometry | Mapping |
|---|---|---|
| Unlabeled Rect | `(24,178)`, `360x96` | auxiliary background |
| Source Text | `(25,179)`, `358x96` | matched primary Text |

The old comparator considered an unmatched Rect auxiliary only when the Rect
label matched a text label. This derived background has no label, so the
correct auxiliary layer was reported as `widget-extra`.

## Fix

`compare_rp_to_design` now permits an unlabeled Rect only when:

1. a source Text widget has already matched its actual Text;
2. Rect `x`, `y`, `width` and `height` match that Text's source outer geometry
   within `0.5` px;
3. the Text's one auxiliary-background allowance has not already been used.

The comparator consumes the allowance, so two unlabeled Rects cannot both be
attributed to one Text. The result now records an auditable
`auxiliary_widgets` row with page, source label, kind and geometry.

No Axure writer, source sample, threshold or published artifact was changed.

## TDD Evidence

The regression
`test_styled_text_background_rect_is_an_auxiliary_widget` first failed with
`comparison["ok"] == False`. The same test passed after the comparator fix.
The negative regression
`test_unlabeled_rect_does_not_explain_neutral_text_background` then failed
because every matched Text initially received an attribution allowance. It
passed after candidates were restricted to source Text with a non-neutral
fill.

```text
focused before fix: 1 failed
focused after fix: 1 passed
tests/v2/test_axure_evidence.py: 10 passed
```

## Frozen-Sample Recheck

- Source DesignSpec SHA-256:
  `a8630c1bd475c72a72f9878f6b6b93b9478aa4ff23a483af0e574f7ba48b4327`
- A-006 and A-007 `.rp` SHA-256:
  `acc356d7a5d30dcdc2b5d47294d1007e34e9bffc23d3c26ee6cbf15cc946913c`
- Artifact size: `48,440` bytes
- Deterministic repeat: byte-identical
- Widgets: `7`; primary `6`; auxiliary `1`; extra `0`
- Auxiliary source label: `section "Flow block keeps na…"`
- Content mismatches: `0`
- Comparison mismatches: `[]`
- Comparison: `ok=true`
- Axure RP 8 conformance: `c1=8/8`, `stores=7/7`, pages `1/1`, `[ok]`
- Full regression: `tests/v2` `722 passed in 41.23s`
- Touched-file Ruff check/format, Node syntax and `git diff --check`: pass

Existing A-006 published acceptance was reused against the identical `.rp`
bytes:

- status `pass`;
- critical text `3/3`;
- assets `0/0`;
- visual within-30 `99.34079365079364%`;
- no new Axure publish or screenshot run occurred in A-007.

Reusing the published run is valid here because the regenerated A-007
artifact is byte-identical to the published A-006 artifact. It is not
evidence of a new publish attempt.

## Evidence

- Plan:
  `docs/superpowers/plans/2026-10-25-axure-extra-rect-attribution.md`
- Comparator:
  `src/app/services/rendering/axure/evidence.py`
- Regression test:
  `tests/v2/test_axure_evidence.py`
- A-007 artifact report:
  `output/_axure_holdout_v2_2026-10-25/a007_retriage/AX6-DOM-TEXTFLOW/artifact_report.json`
- A-007 acceptance:
  `output/_axure_holdout_v2_2026-10-25/a007_retriage/AX6-DOM-TEXTFLOW/acceptance.json`
- A-006 evidence remains under:
  `output/_axure_holdout_v2_2026-10-25/run/AX6-DOM-TEXTFLOW/`
- Summary SHA-256:
  `b07100be364b8bcbfcc89ec9d646bb1c25a05ebb0c10cf1752d7bc94ecb58e4f`
- Artifact report SHA-256:
  `b73ed5dea3134c5399cbbe18ce7832dd5ef90ba5833423dd00a6b5d27778d0bf`
- Acceptance JSON SHA-256:
  `f12de7516e8e52cf9116127b80ff0eba40d2efc94ba4ff882cd2b5334ee07c25`

## Claim Boundary

A-006 remains a clean unseen-holdout failure because its original comparator
recorded the extra object before remediation. A-007 explains that failure and
fixes object attribution for this concrete renderer behavior.

A-007 does not establish arbitrary Axure generalization. A new untouched
holdout with samples not used by A-006 or A-007, recorded as A-008, is
required before making that claim.

Runtime image replacement, Auto Layout, clipping, native letter spacing,
interaction reconstruction and save-back mutation remain non-claims.
