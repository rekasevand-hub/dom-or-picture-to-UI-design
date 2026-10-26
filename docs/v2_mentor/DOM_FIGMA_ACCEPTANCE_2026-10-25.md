# DOM To Figma Real-Site Acceptance Report

**Task:** D-008  
**Status:** `pass-current-scope`  
**Date:** 2026-10-25  
**Sample:** `DQ-R02` Dushu  
**Corpus:** `dom-quality-real-sites/1.0`  
**Figma frame:** `76:4335`  
**Run root:** `output/_dom_figma_generated_icons_2026-10-25_r1/`

## Result

The frozen Dushu sample completed a real Figma route:

- DesignSpec prepared from frozen DOM and screenshot;
- real frame created in the connected `pilot` Figma document;
- readback obtained from the same frame ID;
- full-page PNG exported from the same frame ID;
- one native text edit/restore probe completed;
- one image-fill replacement/restore probe completed.

The final visual gate now passes:

| Dimension | Result |
|---|---|
| Figma write/readback/export existence | pass |
| Critical text presence | `3/3` pass |
| Visual | pass |
| Structure/content geometry | pass |
| Whole-text multiset content | pass |
| Text box | pass |
| Linebreak | pass `91/91` |
| Projected baseline | pass `91/91` |
| Final glyph identity | not-required / evidence not-evaluated |
| Native text edit/restore | pass |
| Image replace/restore | pass |
| Asset acceptance | pass under generated-icon policy |
| Auto Layout readback | observed; parent propagation not evaluated |

No composite score is used. The complete acceptance is `pass`: all
product-required dimensions pass and export is allowed.

## Frozen Inputs

```text
sample_id: DQ-R02
corpus_sha256:
edec396946c03755fabbdea70e6ab210d5a0516b3eef7034c218386f8e45f4ef

thresholds_sha256:
6dd4f29ed90041bb5fbd7912d8c772603279c27f114896dbc2c04f832251d8a2

design_sha256:
75d80c6b6eed3bacd396afec42e6ea60f358830f64309669348e7efe941ad2ad
```

The source document state is `1440×2544`, DPR 1, frozen Chromium,
`zh-CN`, `Asia/Shanghai`.

## Figma Write And Readback

The final frame:

```text
name: D008 DQ-R02 DOM Real Figma Acceptance
node id: 76:4335
origin: [22000, 0]
canvas: 1440×2544
readback nodes: 516
```

The user frame `P5-PILOT-ROOT` (`59:2`) was not modified or deleted.

Earlier D008 attempts and typography probes remain visible and are not counted
as the final acceptance:

- `71:2` stopped on an image element without a display payload; this exposed
  and fixed the missing-image crash;
- `71:198` used the viewport-height canvas and was rejected as clipped; this
  exposed and fixed the full-page canvas bug.
- `71:714` fixed the full-page canvas but still used the viewport height while
  cropping images, leaving assets missing below the fold.
- `71:1230` established the pre-remediation baseline at `2.6244%` over-30.
- `73:2271` established the visual-pass frame at `2.4616%` over-30.
- `74:2787` established the first partial linebreak/baseline evaluation.
- `74:3303` closed the input-placeholder line/baseline evidence gap.
- `75:3819` recovered all remote image URLs while iconfont crops still blocked
  the original-image denominator.
- `72:1746` and `73:1755` were controlled typography probes. They are
  diagnostic evidence only, not acceptance frames.

The final acceptance uses only `76:4335`.

## Export

```text
PNG size: 1440×2544
byte length: 714936
SHA-256:
05974f4ce4b6696883c5ce8c84f45d8a3402ac57b3eaf2ef8c1d959aa97d0e55
```

Export file:
`output/_dom_figma_generated_icons_2026-10-25_r1/export.png`.

Readback SHA-256:
`16b61b380439dd46b101ffb23b5c5c5daee81ea11cedf9d45a73aec2f5ff3a16`.

Acceptance JSON SHA-256:
`4068aa213175bdecb7ac7eb2eab83532a379b5fcd684d110d435ed8a32714fb0`.

Design JSON SHA-256:
`75e6673d3b6a6c433016a91d291c5eed2382fbbaf01cd9243cd9422f45b15b53`.

## Visual

| Metric | Result | Frozen threshold |
|---|---:|---:|
| Mean channel difference | `1.7279` | `<= 3.0` |
| Ink mean | `9.3781` | `<= 100.0` |
| Over-30 pixels | `2.4862%` | `<= 2.5%` |
| Bad-pixel ratio | `2.4862%` | `<= 3%` |
| Size match | pass | required |

Visual status: `pass`. All frozen visual thresholds pass without masking,
cropping, blurring or changing the denominator.

The prior frame `71:1230` measured mean `1.9211`, ink mean `10.0912`, and
over-30 `2.6244%`. Offline attribution found `96,142` over-30 pixels, with
only about `4,558` above the threshold allowance. Independent best local shifts
for every text node still yielded `2.5332%`, so per-node fitting was not a
valid path.

The confirmed root cause was single-line Figma text receiving both the
browser-measured line box origin and a second pixel `lineHeight` offset. The
renderer now uses `textEmBox.y` and Figma's automatic single-line metrics.
Multi-line text retains explicit CSS line height and explicit line breaks.
After the fix, attribution found `90,179` over-30 pixels with only `2`
unmatched pixels; `72/91` text nodes now have zero as their best local shift.

## Critical Text And Text Dimensions

Critical text is checked independently:

- `读书好，好读书，读好书！`: present;
- `在线读书`: present;
- `出版图书`: present.

Critical text result: `3/3 pass`.

The all-text multiset comparison passes after ignoring layout-inserted
whitespace. Text box passes after alignment-aware geometry comparison.
Linebreak and projected baseline now pass `91/91`, including the measured
input placeholder. Final glyph identity remains `not-evaluated`. See
`DOM_TEXT_METRICS_FIGMA_2026-10-25.md`.

Native text probe:

```text
node: 76:4567
type/font preserved: pass
characters updated: pass
geometry updated: pass
restored: pass
parent propagation: not-evaluated
```

The font report was derived from the current Figma page and is therefore
page-wide, not exclusive to frame `76:4335`. Its 91 evaluated rows pass.

## Assets

Asset source/display decisions remained explicit:

| Status | Elements |
|---|---:|
| Verified original identity | 44 |
| Source unavailable iconfont crops | 10 |
| Reference-only identity | 0 |
| Screenshot-crop display | 54 |
| Missing display | 0 |
| Original assets | 44 |
| Replaceable assets | 44 |
| Generated display | 0 |

Image fill replacement probe:

```text
node: 76:4372
node type preserved: pass
image hash changed: pass
scale mode preserved: pass
restored: pass
```

The asset dimension passes under the approved product policy. All 54 uses keep
screenshot evidence; 44 network images have retained verified source bytes and
are replaceable, and 10 iconfont uses display generated similar icons with
complete provenance. Generated icons remain non-original and non-replaceable.

## Layout

Readback contains 102 Auto Layout nodes:

- HORIZONTAL: 43;
- VERTICAL: 59.

Parent height/width propagation and source-browser perturbation remain
`not-evaluated`.

## Implementation

- Frozen DesignSpec builder:
  `src/app/services/evidence/dom_figma_acceptance.py`;
- real runner and probes:
  `scripts/dom_figma_acceptance.py`;
- offline over-30 attribution:
  `scripts/dom_figma_diff_attribution.py`,
  `src/app/services/evidence/dom_figma_diff_attribution.py`;
- full-page/origin/placeholder fixes:
  `src/app/services/evidence/dom_figma_acceptance.py`,
  `src/app/services/rendering/adapter_base.py`;
- single-line measured-line-box fix:
  `src/app/services/rendering/figma_adapter.py`;
- text baseline preservation and Figma text metrics:
  `src/app/services/som/direct_design.py`,
  `src/app/services/evidence/dom_figma_text_metrics.py`;
- placeholder line/baseline capture:
  `src/app/services/structure/capture.py`,
  `src/app/services/structure/providers/dom.py`;
- browser-context asset recovery:
  `src/app/services/structure/network_asset_recovery.py`,
  `src/app/services/structure/asset_metadata.py`;
- generated icon recovery and icon-crop fusion:
  `src/app/services/structure/generated_icon_recovery.py`,
  `src/app/services/structure/asset_fusion.py`;
- tests:
  `tests/v2/test_dom_figma_acceptance.py`,
  `tests/v2/test_dom_figma_diff_attribution.py`,
  `tests/v2/test_dom_figma_text_metrics.py`,
  `tests/v2/test_generated_icon_recovery.py`,
  `tests/v2/test_asset_fusion.py`,
  `tests/v2/test_network_asset_recovery.py`,
  `tests/v2/test_p1_asset_metadata.py`,
  `tests/v2/test_figma_adapter_edits.py`.

During the real run, two fail-closed/geometry defects were fixed by TDD:

1. missing image payload now becomes a transparent placeholder instead of
   aborting `create_image`;
2. full-page frozen screenshots now define canvas height instead of using the
   `1440×900` viewport height.

Repair rounds also fixed:

3. full-page screenshots are supplied as the crop canvas before DesignSpec
   image backfill, yielding `54/54` screenshot-crop displays;
4. content and font matching ignore layout-inserted whitespace;
5. text geometry compares the configured horizontal alignment;
6. overlapping paint order follows the shared renderer `paint_order` and only
   compares siblings with the same parent;
7. non-text controls own native text counts and content keys;
8. image/icon placeholders carry explicit missing-display fusion records.
9. single-line text uses the browser-measured line box without duplicating
   CSS line height; this was introduced by a failing regression test.

## Reproduce

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_figma_acceptance.py prepare `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --capture-root output\_dom_text_quality_capture_placeholder_2026-10-25 `
  --sample-id DQ-R02 `
  --out output\_dom_figma_generated_icons_2026-10-25_r1 `
  --origin-x 22000 `
  --recover-network-assets `
  --generate-icon-approximations

C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_figma_acceptance.py run `
  --sample-root output\_dom_figma_generated_icons_2026-10-25_r1 `
  --out output\_dom_figma_generated_icons_2026-10-25_r1

C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_figma_acceptance.py report `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --sample-root output\_dom_figma_generated_icons_2026-10-25_r1 `
  --out output\_dom_figma_generated_icons_2026-10-25_r1
```

## Verification

```text
python -m pytest tests/v2 -q
648 passed in 39.01s

node --check figma_bridge/code.js
exit 0
```

## Remaining Boundaries

- One real-site sample does not prove arbitrary DOM fidelity.
- The visual, structure, edit, critical text, whole-text content and text-box
  gates pass for this sample.
- The overall acceptance is `pass-current-scope`; 44 image uses have verified
  original source bytes.
- Linebreak and projected baseline pass `91/91` text elements.
- The 10 iconfont uses display generated similar icons with explicit
  provenance; no display is missing.
- Projected baseline is not Figma glyph-baseline truth, and final glyph
  identity remains not evaluated.
- Parent Auto Layout propagation remains not evaluated and is scoped
  non-blocking by the approved product policy.
- The 44 network image uses have original source bytes; the 10 generated icon
  uses remain non-original.
- Page-wide font reporting is not a per-frame-only font claim.
- No real cleanup/deletion was performed; earlier D008 trial frames remain.

## Non-Claims

This report does not claim:

- DOM to Figma quality pass beyond the frozen DQ-R02 current scope;
- arbitrary real-site fidelity;
- original asset identity for generated icons;
- final glyph identity;
- parent Auto Layout propagation;
- production admission;
- cross-browser or cross-document equivalence;
- project-wide `verified=true`.
