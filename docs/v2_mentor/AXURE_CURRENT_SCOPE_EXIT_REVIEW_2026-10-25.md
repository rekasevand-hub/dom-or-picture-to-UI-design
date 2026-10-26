# Axure Current-Scope Exit Review

**Task:** A-011  
**Status:** `pass-current-scope`  
**Date:** 2026-10-25  
**Evidence root:** `output/_axure_current_scope_exit_2026-10-25/`

**Summary SHA-256:**
`944d406bda542247b6597d78a93b88b3ccad786cc20ba61973bdb1245830409b`

## Decision

A-011 closes the Axure product-route work for the named current scope:

- `DOM -> Axure` is supported for controlled DesignSpec input after A-010
  passed three fresh frozen samples without post-result remediation.
- `image -> Axure` is supported for the named controlled image samples from
  A-003 and A-006, using creation-time image boxes.
- Both routes have independent published acceptance, deterministic `.rp`
  generation, Axure RP 8 open/reopen publish and declared non-claims.

This is not an Axure production-readiness decision. It does not generalize to
arbitrary DOM, arbitrary screenshots, unsupported Axure features or
save-back mutation.

## Route Evidence

| Area | Evidence | Decision |
|---|---|---|
| Shared IR boundary | A-001, `design-ir/2.0` | pass-current-scope |
| Controlled DOM route | A-002, DQ-R02 | pass-current-scope |
| Controlled image route | A-003/A-004, IMG-MVP-01 | pass-current-scope |
| Post-tuning holdout | A-005 | partial-post-holdout-tuning |
| First untouched holdout | A-006 | historical fail |
| Extra Rect attribution | A-007 | complete-current-scope |
| Second untouched holdout | A-008 | historical fail |
| Rendered-region/input repair | A-009 | complete-current-scope |
| Fresh holdout after repair | A-010 | pass-unseen-holdout |

## A-010 Fresh Holdout

A-010 is the controlling generalization evidence for DOM input:

| Sample | Critical | Assets | Regions | Within-30 | Result |
|---|---:|---:|---:|---:|---|
| Assets | `3/3` | `3/3` | `3/3` | `98.9707936507937%` | pass |
| Transparent crop | `3/3` | `1/1` | `3/3` | `98.9557142857143%` | pass |
| Nested iframe | `5/5` | `0/0` | `4/4` | `98.9097777777778%` | pass |

All three samples:

- have deterministic `.rp` bytes;
- pass Axure RP 8 conformance;
- publish with `RESULT=OK`;
- publish identically after reopen apart from Axure `generationDate`;
- pass object, critical text, visible-region, visual and reference review.

The manifest was frozen before generation. No product code changed after the
result.

## Image Route Boundary

The image route is supported only for the named controlled samples:

- `IMG-MVP-01`, A-003, 14/14 critical text, 1/1 reference-only image display,
  within-30 `96.57197916666667%`;
- `AX6-IMG-OVERLAY`, A-006, 3/3 critical text, 1/1 asset,
  within-30 `97.60984126984127%`.

Axure stores the selected display crop in a creation-time ImageBox. Runtime
image replacement, original image identity and original DPR/font/viewport
identity are not available.

The A-009 rendered-region gate was not retroactively applied to the older
image run. This is retained as a coverage limitation, not a capability
upgrade: image route evidence remains limited to the named controlled samples.

## Historical Failure Resolution

| Failure | Resolution | Remaining status |
|---|---|---|
| A-005 sample failures | TDD fixes and post-tuning pass | partial evidence, not unseen |
| A-006 extra Rect | A-007 derived auxiliary background attribution | A-006 remains historical fail |
| A-008 stale iframe input | A-009 regenerated from current collector | A-008 remains historical fail |
| A-008 label-only acceptance gap | A-009 visible-region ink gate | closed for new runs |
| A-008 partial asset count conflict | A-009 corrected declared/displayed contract | A-008 remains historical fail |
| Generalization after repair | A-010 fresh untouched pass | closed for frozen three samples |

Historical failures are retained rather than rewritten. Their remediations
are supported by separate evidence.

## Current-Scope Gate

| Gate | Current result |
|---|---|
| Verified input family | controlled DesignSpec; named image samples |
| Shared IR | pass |
| Deterministic `.rp` | pass |
| Object mapping | pass |
| Critical text | pass |
| Image payload/hash | pass for declared samples |
| Visible critical regions | pass on A-010 |
| Visual within-30 | pass |
| Independent acceptance | pass |
| Axure open/reopen publish | pass |
| Page HTML identity after reopen | pass |
| Figma evidence transfer | forbidden |
| Production admission | not claimed |

## Retained Non-Claims

The current scope does not claim:

- arbitrary DOM -> Axure fidelity;
- arbitrary screenshot -> Axure reconstruction;
- production readiness or production storage;
- runtime image replacement in Axure;
- general Auto Layout behavior;
- clipping support;
- native letter-spacing support;
- shadows or gradients as native editable capabilities;
- component-instance equivalence beyond the documented approximation;
- interaction or multi-state reconstruction;
- save-back editing or persisted mutation;
- original asset identity;
- final font/glyph identity;
- deterministic fresh Grounding preparation;
- transfer of Figma acceptance evidence.

## Next-Priority Decision

No further Axure implementation is admitted automatically. The next phase
requires an explicit priority decision:

1. expand Axure capability, for example Auto Layout, runtime replacement,
   clipping or interactions; or
2. move to a separate production-admission phase with environment,
   collaboration, security and long-run evidence.

Both options require new scope and acceptance gates. The current pass must not
be reused as production admission.

## Verification

```text
Focused Axure/IR/manifest set: 28 passed in 1.95s
tests/v2: 732 passed in 41.51s
git diff --check: pass
Product code changed in A-011: no
```

## Evidence

- Route ledger: `docs/v2_mentor/AXURE_ROUTE_LEDGER_2026-10-25.md`
- Fresh holdout: `docs/v2_mentor/AXURE_FRESH_HOLDOUT_A010_2026-10-25.md`
- Image acceptance: `docs/v2_mentor/AXURE_IMAGE_ACCEPTANCE_2026-10-25.md`
- Holdout v2: `docs/v2_mentor/AXURE_HOLDOUT_V2_ACCEPTANCE_2026-10-25.md`
- Rendered-region repair:
  `docs/v2_mentor/AXURE_A009_RENDERED_REGION_REPAIR_2026-10-25.md`
- Capability contract: `src/app/services/contracts/output_ir.py`
- Machine summary:
  `output/_axure_current_scope_exit_2026-10-25/summary.json`
