# D-010 Figma Text Metrics Revalidation

**Goal:** Replace the remaining Figma `linebreak` and `baseline` unknowns with
explicit, reproducible measurements while keeping glyph identity separate.

**Scope:** Frozen DQ-R02 design/readback/export evidence, text elements only.

## Constraints

- Keep frozen corpus thresholds unchanged.
- Do not infer a pass from pixels when source text evidence is missing.
- Linebreak compares expected browser line evidence with explicit Figma text.
- Baseline compares the browser-derived baseline with a Figma node-origin
  projection using the same browser ascent.
- Final glyph outline identity remains `not-evaluated`.
- Any missing denominator remains visible as `partial` or `not-evaluated`.
- A renderer change requires RED -> GREEN.
- A new real Figma frame is required before updating the Stage 1 decision.

## Task 1: Preserve Browser Baseline Evidence

- [x] Add a failing direct-design test for `textBaseline`.
- [x] Carry the baseline mapping into text elements.
- [x] Run the focused test GREEN.

## Task 2: Evaluate Figma Text Dimensions

- [x] Add failing tests for:
  - explicit multi-line text matching;
  - a linebreak mismatch;
  - baseline within and outside tolerance;
  - missing baseline evidence remaining partial;
  - glyph identity remaining not-evaluated.
- [x] Implement a text-metric module using existing Figma matching helpers.
- [x] Return per-node rows and independent summaries.

## Task 3: Integrate Acceptance

- [x] Pass computed text components into the existing four-dimensional gate.
- [x] Preserve content, linebreak, box, baseline and glyph as separate values.
- [x] Verify the existing DQ-R02 readback produces explicit coverage and rates.

## Task 4: Real Reproof And Status

- [x] Prepare and run a new DQ-R02 frame at a new origin.
- [x] Regenerate the acceptance report.
- [x] Update D-009 only to the status justified by the new denominators.
- [x] Run focused and full regression checks.

## Expected Current-Scope Result

Dushu provides line evidence for all 91 text elements after the placeholder
capture path records its measured content line box and Canvas-font baseline.

## Execution Evidence

```text
frame: 74:3303
origin: [18000, 0]
text elements: 91
linebreak: 91 evaluated, 91 pass, coverage 100%, status pass
baseline projection: 91 evaluated, 91 pass, coverage 100%, status pass
glyph identity: not-evaluated
overall acceptance: blocked-unknown
```

Placeholder evidence:

```text
element 13
textEmBox: [536, 65, 393, 24]
textEmLines: 1
textBaseline: canvas-font-metrics, y=82, ascent=17
```

Final checks:

```text
pytest tests/v2 -q
639 passed in 55.57s

ruff format/check: pass
node --check figma_bridge/code.js: exit 0
git diff --check: exit 0
```
