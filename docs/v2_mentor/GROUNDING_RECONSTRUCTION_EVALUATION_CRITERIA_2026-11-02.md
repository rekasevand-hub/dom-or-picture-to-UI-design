# Grounding Reconstruction Evaluation Criteria

## Mentor Review Summary

The three reviewed outputs demonstrate different failure modes:

- A is visually closest because a complete source image remains underneath;
  rebuilt content is editable but the similarity is partly image-backed.
- B extracts many text candidates but misses controls, grid lines, icons and
  container relationships.
- C rebuilds more controls but changes the original layout, loses field values
  and reconstructs only two history rows.

None is a complete 1:1 editable reconstruction.

## Required Product Definition

A qualified result must satisfy all of these at once:

- no visible whole-screenshot underlay contributes to the score;
- key text and field values are complete and correct;
- the original control layout and relative geometry are preserved;
- input, checkbox, button, table and navigation states are represented;
- text, controls and assets are native and editable where applicable;
- the fixed source canvas size is preserved.

## Explicit Non-Goals

- Component and Instance reuse.
- Responsive root reflow at 2048, 1440 or mobile widths.
- A user-facing external provenance manifest.

These properties may be useful in a future design-system phase, but they are not
required for the current fixed-size 1:1 reconstruction product.

## Blocking Dimensions

### Content

- critical text recall;
- exact or safely normalized displayed field values;
- table header and expected row count;
- no silent character substitutions such as case corruption or wrong CJK glyphs.

### Layout

- critical control bbox/alignment;
- critical container bbox/alignment;
- relative left-label/right-input relationships;
- table and toolbar order;
- sidebar, header and content boundaries.

### Underlay

- visible whole-screenshot coverage after occlusion;
- whether one raster covers multiple unrelated UI regions.

A full-page source crop is classified as an underlay even if editable elements
are placed above it. A clean reconstructed background or a genuinely isolated
photo may span the page only when its provenance identifies it as a background
asset rather than the complete UI screenshot.

### Editability

- native text probe;
- image-fill probe;
- editable controls and values at their source positions.

### Visual

- grayscale MAE;
- max-channel bad-pixel ratio at threshold 30;
- content coverage, so a blank output cannot pass through low error alone.

## Interpretation of Existing Results

- A remains a useful upper-bound visual reference, but its underlay must be
  removed from the comparable score.
- B is a text/candidate baseline, not an editable-screen benchmark winner.
- C is a component-rebuild baseline, not a faithful-layout winner.
- Image To Slice algorithms may improve asset classification and background
  recovery, but its HTML/Figma result must be evaluated with the same underlay,
  content and structure gates.

## Acceptance Rule

Visual MAE is necessary but never sufficient. A run fails if any blocking
content, layout, underlay, editability or table-structure requirement is missed.
Component reuse, root responsiveness and an external provenance deliverable are
outside this acceptance decision.
The user makes the final product-adoption decision after reviewing the complete
reconstruction evidence.

## Versioned Visual Gates

`image-figma-mvp-product/1.0` remains frozen. It continues to evaluate the raw
same-size region bad-pixel ratios and must not be rewritten from later runs.

`image-figma-mvp-product/2.0` is opt-in and separates two independent visual
checks:

- `chrome_visual`: raw bad-pixel ratio after masking native-text ink, with the
  existing 5% region threshold.
- `native_text_visual`: critical native text owners must satisfy position,
  width/height, ink-coverage and edge-F1 thresholds.

The raw region result remains present as
`legacy_raw_region_visual` with `status` and `mode: informational`. A v2 run
cannot pass when the native-text gate fails. Baseline evidence is reported as
`not-evaluated` until a trusted glyph baseline source exists; it is never
inferred from the screenshot.

Run the explicit policy with:

```text
python scripts/image_figma_mvp.py ... --acceptance-policy 2.0
```

The default remains `1.0`, so historical acceptance results cannot change
implicitly.
