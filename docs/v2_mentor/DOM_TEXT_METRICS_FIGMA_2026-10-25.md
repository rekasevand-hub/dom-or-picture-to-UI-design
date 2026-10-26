# D-010 Figma Text Metrics Revalidation

**Task:** D-010  
**Status:** `complete-current-scope / text-metrics-pass / glyph-explicit-not-evaluated`  
**Date:** 2026-10-25  
**Sample:** `DQ-R02` Dushu  
**Frame:** `74:3303`  
**Run root:** `output/_dom_figma_text_metrics_placeholder_2026-10-25_r2/`

## Result

The Figma acceptance now evaluates `linebreak` and `baseline` independently
for the frozen DQ-R02 text elements:

| Dimension | Evaluated | Passed | Coverage | Status |
|---|---:|---:|---:|---|
| Content | 91/91 | 91 | 100% | pass |
| Linebreak | 91/91 | 91 | 100% | pass |
| Text box | 91/91 | 91 | 100% | pass |
| Baseline projection | 91/91 | 91 | 100% | pass |
| Glyph identity | 0/91 | 0 | 0% | not-evaluated |

No composite score is used.

The text dimensions now pass except for glyph identity, which the frozen
policy explicitly leaves not evaluated. Visual, structure and edit remain
`pass`; asset remains `partial`. The overall Figma acceptance is
`blocked-unknown`: the text side is blocked only by glyph identity, while the
asset dimension separately remains partial.

## Method

Linebreak:

- expected line count comes from retained `lines` or `textEmLines`;
- actual line count comes from explicit newline characters in Figma
  `characters`;
- when retained lines exist, their canonical text must match line by line;
- input placeholders retain their measured content line box and one-line count.

Baseline:

- the browser-derived `textBaseline` is preserved in DesignSpec;
- the Figma projected baseline is `node global y + browser ascent`;
- the frozen tolerance is `1.0 px`;
- this is labeled `projected-browser-baseline`, not Figma glyph-baseline truth.

Glyph identity:

- Figma font family/style is retained as supporting evidence;
- final glyph outline identity remains explicitly `not-evaluated`.

## Placeholder Gap Closed

The previous input-placeholder gap is closed by capture-side measurement rather
than acceptance-side inference. The DOM probe now records:

```text
textEmBox: [536, 65, 393, 24]
textEmLines: 1
textBaseline:
  y: 82
  ascent: 17
  descent: 4
  method: canvas-font-metrics
```

The recaptured frozen state has the same screenshot hash
`2f51949d84d0e88e13c5d7817703771afcaad83c559e7a03bebce401128b2f8c`
and the same structure/text fingerprints as the original capture. Only DOM
metadata changed.

## Real Figma Evidence

```text
origin: [18000, 0]
canvas: 1440x2544
readback nodes: 516
mean: 1.708378
ink mean: 9.291356
over-30: 2.463149%
bad pixels: 2.463149%
size match: pass
```

Artifact hashes:

```text
export.png:
add58115d9336bd450ba45483bbb53efa6b7538377a0287d65dbff847f3d7e8a

readback.json:
5ba5921f929e7365306e8a52964fe236ee8abf122deb4525aab5ef4167bc639e

design.json:
de8e48922debc254f34a25785f67864f7780afa4e65f387359f252a3ff8e4750

acceptance.json:
8d0eac20e044a41e209e82251450e71a3d0b3bc1e23590e765e37a8d5e01a742
```

## Implementation

- Baseline preservation:
  `src/app/services/som/direct_design.py`;
- placeholder line/baseline capture:
  `src/app/services/structure/capture.py`,
  `src/app/services/structure/providers/dom.py`;
- text-metric evaluator:
  `src/app/services/evidence/dom_figma_text_metrics.py`;
- acceptance integration:
  `src/app/services/evidence/dom_figma_acceptance.py`,
  `src/app/services/rendering/figma_acceptance.py`;
- tests:
  `tests/v2/test_dom_figma_text_metrics.py`,
  `tests/v2/test_dom_figma_acceptance.py`.

## Verification

```text
python -m pytest tests/v2 -q
639 passed in 55.57s

node --check figma_bridge/code.js
exit 0
```

Ruff format/check and `git diff --check` pass for the changed files.

## Non-Claims

This report does not claim:

- baseline glyph identity;
- final glyph outline identity;
- original asset identity;
- Stage 1 exit;
- image-phase admission.
