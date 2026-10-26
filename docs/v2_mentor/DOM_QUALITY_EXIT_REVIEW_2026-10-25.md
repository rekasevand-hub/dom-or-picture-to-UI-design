# DOM Quality Exit Review

**Task:** D-009  
**Status:** `pass-current-scope`  
**Decision:** `pass-current-scope`  
**Date:** 2026-10-25  
**Stage 1:** `pass-current-scope`  
**Image phase:** admitted; not started

## Decision

The DOM quality program has enough evidence to close its individual
measurement, text, layout, asset, fusion and real-Figma execution tasks for the
current controlled scope.

It passes the Stage 1 gate for the frozen DQ-R02 current scope under the
user-approved product policy. The representative real-site Figma sample
completed real write/readback/export and edit probes. Layout, components,
content, linebreak, text box and projected baseline are usable. Generated
icons fill the 10 iconfont gaps with explicit provenance. Final glyph outline
identity remains not evaluated but is `not-required` for this scope.

The image product phase is admitted under G-007 but has not been started.

## Evidence Reviewed

| Task | Evidence | Current result |
|---|---|---|
| D-003 | `DOM_QUALITY_CORPUS_2026-10-25.md` | React/Dushu/Shoelace frozen and replayed `3/3` |
| D-004 | `DOM_TEXT_FONT_QUALITY_2026-10-25.md` | content and box pass; linebreak partial; glyph identity not evaluated |
| D-005 | `DOM_LAYOUT_QUALITY_2026-10-25.md` | L1/L2/L3-local evidence; real Figma propagation not evaluated |
| D-006 | `DOM_ASSET_QUALITY_2026-10-25.md` | 42 verified sources; 26 reference-only; incomplete asset coverage |
| D-007 | `DOM_STRATEGY_FUSION_2026-10-25.md` | `227/227` uses accounted for; no generated fallback exercised |
| D-008 | `DOM_FIGMA_ACCEPTANCE_2026-10-25.md` | real frame/export/probes pass; visual/structure/edit/content/box pass; asset partial |
| D-010 | `DOM_TEXT_METRICS_FIGMA_2026-10-25.md` | linebreak and projected baseline `91/91`; glyph identity explicitly not evaluated |
| D-011 | `DOM_ASSET_RECOVERY_2026-10-25.md` | 24/24 URLs recovered; 44 verified/replaceable uses; 10 iconfont crops remain unavailable |
| D-012 | `DOM_GENERATED_ICONS_2026-10-25.md` | 10 generated icon uses; asset/text/visual/structure/edit pass; overall Figma acceptance pass |

## Exit Gate

### 1. Frozen Real-Site Canonical Corpus

Status: pass.

- three required sites frozen;
- one exclusion recorded;
- environment and thresholds hashed;
- independent replay passed;
- no thresholds changed after measurement.

### 2. Independent Quality Dimensions

Status: pass-current-scope.

The reports keep separate:

- text content;
- linebreak;
- text box;
- baseline;
- glyph identity;
- Auto Layout L1/L2/L3-local;
- source identity;
- display payload;
- screenshot crop;
- missing state;
- replacement mode;
- visual, structure, edit and asset Figma dimensions.

All required Figma dimensions pass for the named current scope. The report
still keeps non-required and not-evaluated details separate.

### 3. Known Typography And Layout Gaps

Status: explicitly scoped for the approved product policy.

- 29 mixed-content text nodes lack per-line text;
- measured linebreak coverage is `96.83%`;
- final glyph identity is not evaluated and is `not-required`;
- baseline is browser-derived, not Figma glyph truth;
- Figma linebreak and projected baseline pass `91/91` DQ-R02 text elements;
- final glyph outline identity remains explicitly not evaluated;
- L1 is `308/448`, L2 `225/448`, L3-local `115/448`;
- real parent propagation and source-browser perturbation are not evaluated.

### 4. Missing-Asset And Fusion Policy

Status: contract pass, asset quality partial.

- source/display/crop/missing/replacement are separate;
- screenshot crops never become originals;
- generated candidates require complete provenance and remain non-original;
- 26 references, 132 source-unavailable inline SVG uses and 3 missing image
  identities remain explicit.

The policy is implemented, but incomplete asset recovery still prevents a
complete Figma asset claim.

D-011 recovered all 24 referenced remote image URLs through the page browser
context. Raw bytes total `254,162`, covering 44 image uses. The remaining 10
uses are iconfont `::before` glyphs, not unresolved image URLs.

### 5. Representative Real-Site Figma Gate

Status: `pass-current-scope`.

DQ-R02 final frame `76:4335`:

| Check | Result |
|---|---|
| Figma write/readback/export exists | pass |
| Critical text | `3/3` pass |
| Native text edit/restore | pass |
| Image fill replace/restore | pass |
| Visual bad-pixel ratio | pass `2.4862%` <= `3%` |
| Visual mean | pass `1.7279` <= `3.0` |
| Over-30 pixels | pass `2.4862%` <= `2.5%` |
| Structure/content | pass |
| Text box | pass |
| Linebreak | pass `91/91` |
| Projected baseline | pass `91/91` within `1 px` |
| Asset acceptance | pass under generated-icon policy |
| Verified original image uses | `44` |
| Generated icon uses | `10` |
| Replaceable original image uses | `44` |
| Glyph identity | `not-required` / evidence `not-evaluated` |
| Parent Auto Layout propagation | scoped-nonblocking |

The Stage 1 condition requiring a representative real-site sample is met.
Overall Figma acceptance is `pass`, export is allowed, and within-30 pixel
similarity is `97.5138%`, above the approved 90% product bar.

## Final Status Table

| Dimension | Status |
|---|---|
| Corpus reproducibility | `current-scope-pass` |
| Critical text on frozen corpus | `pass` |
| Whole text content / box | `pass` |
| Linebreak | `pass-current-scope` |
| Baseline projection | `pass-current-scope` |
| Final glyph identity | `not-required`; evidence `not-evaluated` |
| Layout local evidence | `partial-current-scope` |
| Layout runtime propagation | `scoped-nonblocking` |
| Source identity | `44 original + 10 generated icons` |
| Display crop / missing provenance | `pass-current-scope` |
| Figma write/readback/export | `verified-bounded-fixture` |
| Figma visual gate | `pass-current-scope` |
| Figma quality gate | `pass-current-scope` |
| Stage 1 exit | `pass-current-scope` |
| Image phase admission | `admitted` |

No composite score is used.

## Required Remediation Before Re-Review

No blocking remediation remains for the frozen DQ-R02 current scope.

Deferred improvements:

1. expand corpus coverage beyond the single representative Figma pass;
2. evaluate adaptive Auto Layout parent propagation;
3. improve generated icon fidelity and replaceability without changing the
   current non-original classification;
4. keep final glyph identity non-required and never report it as verified.

Completed remediation:

- DQ-R02 over-30 moved from `2.6244%` to `2.4616%` on new frame `73:2271`;
- the single-line measured-line-box fix is covered by a failing regression test;
- D-010 measured linebreak and projected baseline at `91/91` on frame
  `74:3303`, including the input placeholder;
- D-011 recovered 24/24 remote image URLs and verified 44/54 image uses on
  frame `75:3819`;
- D-012 generated 10 similar icon uses with complete provenance and mapped
  final glyph identity to `not-required` on frame `76:4335`;
- no visual threshold, mask or crop changed; the required-original denominator
  change is the explicit approved icon-crop scoping.

Parent propagation and final glyph identity may remain separately scoped, but
they cannot be reported as verified.

## Non-Claims

This review does not claim:

- project-wide Figma fidelity;
- arbitrary real-site support;
- final glyph identity;
- complete original assets;
- generated icons are original assets;
- adaptive Auto Layout propagation;
- production admission;
- `verified=true`.
