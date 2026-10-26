# DOM Auto Layout Quality Report

**Task:** D-005  
**Status:** `complete-current-scope / partial-report`  
**Date:** 2026-10-25  
**Corpus:** `dom-quality-real-sites/1.0`  
**Capture:** `output/_dom_text_quality_capture_2026-10-25/`  
**Report:** `output/_dom_layout_quality_2026-10-25/summary.json`

## Level Definitions

| Level | Meaning in D-005 |
|---|---|
| L1 | A HORIZONTAL or VERTICAL layout spec was inferred by `layout_infer`. |
| L2 | Static child geometry can be replayed by the existing inference contract. |
| L3 | A bounded local output-contract perturbation simulates `24 px` first-child growth and sibling reflow. |

L3 does not mean live Figma execution, source-browser behavioral truth or
parent-height propagation.

## Aggregate Result

The frozen corpus contains `448` containers with at least two direct
children:

| Level | Count | Coverage |
|---|---:|---:|
| L1 inferred candidate | 308 | `68.75%` |
| L2 static replay | 225 | `50.22%` |
| L3 local output contract | 115 | `25.67%` |

L1 source:

- CSS semantics: `214`;
- geometry-only fallback: `94`.

No composite score is used.

## Per-Site Result

| Site | Containers | L1 | L2 | L3 | CSS | Geometry |
|---|---:|---:|---:|---:|---:|---:|
| React | 312 | 203 | 171 | 82 | 170 | 33 |
| Dushu | 72 | 56 | 24 | 15 | 18 | 38 |
| Shoelace | 64 | 49 | 30 | 18 | 26 | 23 |

## Fixed-Coordinate Fallbacks

| Reason | Count | Rule |
|---|---:|---|
| `inline-flow` | 75 | Fixed coordinates; mixed inline behavior is not collapsed into a guessed stack. |
| `geometry-mismatch` | 39 | Fixed coordinates; rejected layout cannot replay observed geometry. |
| `non-uniform-gap` | 10 | Fixed coordinates when no uniform spacing contract exists. |
| `float` | 10 | Fixed coordinates; float semantics are not inferred. |
| `wrap` | 2 | Fixed coordinates; prevent Grid/wrap two-dimensional behavior from becoming a linear stack. |
| `grid` | 1 | Fixed coordinates; Grid is not converted into a guessed linear stack. |
| `order` | 1 | Fixed coordinates; visual order differs from source child order. |
| `content-overflow` | 1 | Fixed coordinates; a stack would relocate or clip overflow content. |
| `unsupported-display` | 1 | Fixed coordinates for unsupported table-like display. |

After D-005, Grid, wrap and reverse layouts no longer continue into the
one-dimensional geometry fallback. Their subtrees remain at fixed
coordinates.

Geometry-source candidates remain allowed only where their observed geometry
can be replayed. They are labeled `source=geometry` and never promoted to CSS
semantic flow.

## L2 Static Replay

L2 passes only when:

- a layout spec exists;
- CSS-source specs already pass the inference geometry replay; or
- geometry-source specs have uniform gaps and pass the same replay contract.

Non-uniform geometry-source candidates remain L1 only. They are not counted
as L2.

Absolute/fixed-position direct children are removed from the flow member
count and retained as absolute overrides.

## L3 Local Contract

L3 applies only to CSS-source L2 layouts with:

- HORIZONTAL or VERTICAL mode;
- `MIN` primary alignment;
- `MIN` counter alignment;
- at least two flow children.

The synthetic mutation grows the first child by `24 px` on the main axis.
The contract checks:

- subsequent sibling positions move by the expected delta;
- cross-axis positions remain unchanged;
- maximum local deviation stays within the frozen `2.0 px` tolerance.

The result is `output-contract-simulated`, not engine-verified.

Not evaluated:

- `83` L2 layouts whose source/alignment cannot use this local contract;
- `51` candidates without two eligible CSS flow children;
- parent frame height/width propagation;
- real Figma Auto Layout participation;
- source-browser content perturbation.

L3 pass count: `115/448 = 25.67%`.

## Implementation

- Evidence module:
  `src/app/services/evidence/dom_layout_quality.py`;
- report CLI: `scripts/dom_layout_quality.py`;
- layout policy change: `src/app/services/rendering/layout_infer.py`;
- tests: `tests/v2/test_dom_layout_quality.py`.

The fixed fallback rule is conservative: no HORIZONTAL/VERTICAL layout spec is
created for Grid, wrap or reverse semantics when their CSS path fails.

## Reproduce

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_layout_quality.py `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --capture-root output\_dom_text_quality_capture_2026-10-25 `
  --out output\_dom_layout_quality_2026-10-25
```

## Verification

```text
python -m pytest tests/v2 -q
569 passed in 32.71s

python -m ruff check ...
All checks passed

python -m ruff format --check ...
3 files already formatted

node --check figma_bridge/code.js
exit 0
```

## Remaining Boundaries

- Real Figma `set_layout_flow`, readback and rollback remain D-008 work.
- Parent sizing/propagation is not evaluated.
- Grid/wrap are explicitly fixed-fallback in this corpus, not completed
  native layouts.
- Source-browser perturbation remains separate from the local L3 contract.
- Dushu's 38 geometry-source candidates carry static geometry, not CSS
  semantic flow.
- No production admission or project-wide Auto Layout claim is made.

## Non-Claims

This report does not claim:

- general adaptive Auto Layout;
- real Figma behavior for the 115 L3 contracts;
- parent propagation;
- Grid/wrap completion;
- source-browser reflow equivalence;
- cross-version, collaboration or undo/redo behavior.
