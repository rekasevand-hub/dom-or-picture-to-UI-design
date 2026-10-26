# Axure A-009 Rendered Region Repair

**Task:** A-009  
**Status:** `complete-current-scope`  
**Date:** 2026-10-25  
**Parent result:** A-008 remains `fail-unseen-holdout`  
**Evidence root:** `output/_axure_a009_2026-10-25/`

**Summary SHA-256:**
`ff7832afa438edc8fdcc72232eb526a182d096178c06ada629648908ab924dd8`

## Outcome

A-009 repairs the two validation gaps found by A-008 without claiming a new
untouched-holdout pass:

- the iframe sample is regenerated from the current DOM collector instead of
  reusing the stale `12_design.json`;
- Axure acceptance now verifies rendered critical regions by ink presence,
  not only widget labels and aggregate pixel similarity;
- the partial-asset contract now counts two declared and displayed image
  payloads, while retaining one missing-original provenance row.

No iframe-coordinate code change was needed. The collector already places
accessible iframe text at the host offset and its existing integration test
passes. A-008 failed because its frozen DesignSpec predated that correction.

## Iframe Input Repair

Current-source regeneration produced:

| Item | A-008 stale input | A-009 refreshed input |
|---|---|---|
| Accessible Text geometry | `(16,37)` | `(18,133)` |
| Placement | overlaps title | inside left iframe |
| DesignSpec SHA-256 | `3cf8f478...07193e9` | `72499117...5825df2` |
| Screenshot SHA-256 | `c8747961...fa13c6` | `c8747961...fa13c6` |

The screenshot remains unchanged. The repair is in the projected DOM
geometry, not the browser rendering or Axure writer.

The refreshed iframe artifact has:

- deterministic `.rp` SHA-256
  `029891f5c2c208dd109022f183281eec54c04e3ee2b6e2293b113a687666c9b3`;
- eight primary widgets and zero comparison mismatches;
- critical text `4/4`;
- assets `0/0`;
- visual within-30 `99.0969841269841%`;
- Axure conformance `c1=8/8`, `stores=7/7`, pages `1/1`.

## Rendered Region Gate

`evaluate_published_axure` now accepts `critical_regions`. Each region measures
grayscale ink (`<200`) in the reference and render screenshots and fails when:

- geometry is invalid;
- the screenshot pair is unavailable or unreadable;
- the reference region has less than `0.5%` ink;
- render/reference ink falls below `0.25`.

The CLI exposes repeated arguments:

```text
--critical-region name,x,y,width,height
```

This gate is separate from overall within-30 similarity. TDD added blank-region
and preserved-region tests plus CLI coverage.

For the repaired iframe region
`accessible-iframe-content (14,120,286,40)`:

| Measurement | Reference | Repaired render |
|---|---:|---:|
| Ink percentage | `7.01923076923077%` | `7.01923076923077%` |
| Render/reference ratio | - | `1.0` |

Replaying the A-008 old render through the same gate fails with
`critical-region-missing`: reference ink `7.01923076923077%`, render ink `0%`,
ratio `0`.

## Partial Asset Contract

The partial-asset truth declares two image elements with minimum one accepted
asset. Both elements have a display payload, including the missing-original
placeholder. A-009 records:

- declared asset count: `2`;
- expected renderable asset count: `2`;
- missing-original asset count: `1`.

The corrected contract passes under the same output:

- deterministic `.rp` SHA-256
  `d3e3d8a2a3cdeeb9c59fe8418466692288c7a958d8172ccfc083251e1e75b529`;
- critical text `2/2`;
- published images `2/2`;
- unexpected hashes `0`;
- within-30 `100%`;
- over-30 `0%`.

This does not edit the A-008 manifest or retroactively change its result.

## Publish Evidence

Both repaired artifacts were published twice with Axure RP 8.0.0.3400:

| Sample | Initial | Reopen | Page HTML | Normalized data.js |
|---|---|---|---|---|
| Iframe | `RESULT=OK files=153` | `RESULT=OK files=153` | identical | identical except generation date |
| Partial asset | `RESULT=OK files=155` | `RESULT=OK files=155` | identical | identical except generation date |

Axure conformance passes for both `.rp` files.

## Evidence

- Plan:
  `docs/superpowers/plans/2026-10-25-axure-a009-rendered-region-repair.md`
- Repaired manifest:
  `output/_axure_a009_2026-10-25/repaired_manifest.json`
- Refreshed iframe input:
  `output/_axure_a009_2026-10-25/prepared/samples/iframe/12_design.json`
- Iframe acceptance:
  `output/_axure_a009_2026-10-25/iframe/acceptance.json`
- Old-render region regression:
  `output/_axure_a009_2026-10-25/regression/a008-iframe-gate/acceptance.json`
- Partial asset contract:
  `output/_axure_a009_2026-10-25/partial-asset/contract.json`
- Partial asset acceptance:
  `output/_axure_a009_2026-10-25/partial-asset/acceptance.json`
- Reopen check:
  `output/_axure_a009_2026-10-25/reload_check.json`
- Machine summary:
  `output/_axure_a009_2026-10-25/summary.json`

## Verification

```text
Axure acceptance tests: 11 passed in 1.70s
tests/v2: 728 passed in 41.66s
Ruff check/format: pass
node --check figma_bridge/code.js: pass
JSON parsing: 6/6 pass
git diff --check: pass
Axure conformance: 2 files, c1 8/8, stores 7/7, pages 1/1, ok
```

## Claim Boundary

A-009 closes for the named repaired samples only. A-008 remains a failed
untouched holdout, and the repaired iframe input is not a new untouched sample.

A-010 must run a fresh untouched holdout before any Axure generalization
claim. Runtime image replacement, Auto Layout, clipping, native letter
spacing, interaction reconstruction and save-back mutation remain non-claims.
