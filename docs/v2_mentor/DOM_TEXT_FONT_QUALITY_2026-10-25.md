# DOM Text And Font Quality Report

**Task:** D-004  
**Status:** `complete-current-scope / partial-report`  
**Date:** 2026-10-25  
**Corpus:** `dom-quality-real-sites/1.0`  
**Manifest:** `tests/fixtures/dom_quality/real_site_corpus_v1.json`  
**Capture summary:** `output/_dom_text_quality_capture_2026-10-25/summary.json`  
**Text report:** `output/_dom_text_quality_2026-10-25/summary.json`

## Result

The five text dimensions are now reported independently:

| Dimension | React | Dushu | Shoelace | Aggregate |
|---|---|---|---|---|
| Critical text | pass | pass | pass | `3/3` required samples |
| Content | pass `529/529` | pass `165/165` | pass `220/220` | `914/914` |
| Linebreak | partial `509/529` covered | pass `165/165` | partial `211/220` covered | `885/914` covered, measured rows `885/885` pass |
| Text box | pass `529/529` | pass `165/165` | pass `220/220` | `914/914` |
| Baseline | derived `529/529` | derived `165/165` | derived `220/220` | `914/914` derived |
| Glyph identity | partial | partial | partial | faces observed; final identity `not-evaluated` |

The hard content/linebreak/box gate passes. The overall report remains
`partial` because 29 mixed-content nodes lack per-line text, baseline is
browser-derived rather than source-glyph truth, and final glyph identity was
not evaluated.

No composite score is used.

## Capture

The enhanced capture reran the frozen three-site state under the D-003
environment:

```text
status: pass
required samples: 3/3
React:    1415 nodes, 529 text nodes
Dushu:     487 nodes, 165 text nodes
Shoelace:  463 nodes, 220 text nodes
```

Each text node now carries:

- `textEmBox` and `textEmLines`;
- browser-line boxes where available;
- `textBaseline` derived from Canvas font metrics;
- representative `platformFonts` evidence for its computed font style.

## Content

Content comparison removes layout whitespace but preserves case, punctuation
and visible characters. All `914` text nodes reconstruct their captured text
without missing or changed characters.

Critical text also passed independently:

- React: `React`, `The library for web and native user interfaces`,
  `Learn React`;
- Dushu: `读书好，好读书，读好书！`, `在线读书`, `出版图书`;
- Shoelace: `Shoelace`, `web components`, `Web Awesome`.

## Linebreak

The evaluator separates:

- multi-line rows from `textLines`;
- measured single-line rows from `textEmLines=1`;
- missing multi-line text evidence, which remains `not-evaluated`.

Measured rows: `885/885` pass.

Coverage: `885/914 = 96.83%`.

The missing 29 rows are mixed-content nodes where `textEmLines` reports
multiple lines but the capture does not retain every per-line string:

- React: `20`;
- Dushu: `0`;
- Shoelace: `9`.

These are not counted as linebreak passes or failures.

## Text Box

The first browser-measured text box is compared on the horizontal axis with
the frozen `2.0 px` tolerance. Vertical font paint overflow is recorded
separately from layout-box misplacement.

Result: `914/914` pass.

The initial strict evaluator flagged nine nodes because glyph paint extended
3–4 px above the element box:

- eight React 52px headings;
- one Shoelace 16px search label.

The DOM text still overlapped its element box and its horizontal geometry was
within tolerance. The evaluator now records
`vertical_paint_overflow_top/bottom` independently instead of treating font
paint extent as horizontal box error.

## Baseline

`914/914` text nodes now have a browser-derived baseline:

```text
method: canvas-font-metrics
formula: line-box top + fontBoundingBoxAscent
fallback: actualBoundingBoxAscent/Descent
```

Baseline status is `derived`, not `pass`.

This proves the pipeline records a reproducible browser-metric baseline for
the frozen environment. It does not prove the final glyph outline or Figma
baseline identity.

## Glyph And Font Evidence

Platform font probing is performed once per unique computed
`style|weight|stretch|size|family` combination. Nodes sharing that style reuse
the representative face evidence.

Frozen corpus totals:

| Evidence | Count |
|---|---:|
| Text nodes | 914 |
| Direct CDP face observations | 33 |
| Representative face inheritance | 805 |
| Ambiguous/mixed faces | 21 |
| Missing face evidence | 55 |
| Face-evidence coverage | `859/914 = 93.98%` |

Per sample:

| Sample | Direct | Representative | Ambiguous | Missing | Coverage |
|---|---:|---:|---:|---:|---:|
| React | 14 | 439 | 21 | 55 | 89.6% |
| Dushu | 7 | 158 | 0 | 0 | 100% |
| Shoelace | 12 | 208 | 0 | 0 | 100% |

Final glyph-outline identity:

```text
evaluated: 0
status: not-evaluated
```

CDP `platformFonts` proves browser-resolved face names and glyph counts for a
representative style. It does not prove that a downstream renderer used the
same outline or that mixed glyph runs share one face.

## Implementation

- Independent evaluator:
  `src/app/services/evidence/dom_text_quality.py`;
- report CLI: `scripts/dom_text_quality.py`;
- DOM baseline and representative style probe:
  `src/app/services/structure/capture.py`;
- evaluator tests: `tests/v2/test_dom_text_quality.py`;
- DOM probe tests: `tests/v2/test_p1_dom_text_geometry.py`.

## Reproduce

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_quality_corpus.py capture `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --out output\_dom_text_quality_capture_2026-10-25

C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_text_quality.py `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --capture-root output\_dom_text_quality_capture_2026-10-25 `
  --out output\_dom_text_quality_2026-10-25
```

## Verification

```text
python -m pytest tests/v2 -q
558 passed in 32.57s

python -m ruff check ...
All checks passed

python -m ruff format --check ...
5 files already formatted

node --check figma_bridge/code.js
exit 0
```

## Remaining Boundaries

- Mixed-content per-line coverage remains partial.
- Baseline is derived from browser font metrics, not glyph-baseline truth.
- Final glyph-outline identity remains DOM-GAP-006 open work.
- React still has 55 text nodes without representative face evidence.
- Visual similarity cannot compensate for text, linebreak or box failure.
- No Figma write/readback or cross-browser claim is made.

## Non-Claims

This report does not claim:

- all text is pixel-identical;
- baseline glyph identity is verified;
- all mixed font runs resolve to one face;
- arbitrary variable axes are reproduced;
- the full DOM-to-Figma text path passes;
- project-wide `verified=true`.
