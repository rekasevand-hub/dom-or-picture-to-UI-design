# Teacher UI Agent Distillation

Date: 2026-11-04

## Evidence

The mentor agent output was inspected through the live Figma bridge after its
planning text incorrectly claimed that no image or node had been placed.

| Metric | Mentor output | Task 11 local SVG replay |
| --- | ---: | ---: |
| Figma node | `4:959` | `14:834` |
| Canvas | 1920x826 | 1920x826 |
| Layer count | 228 | 205 |
| Frames | 109 | 62 |
| Native text | 87 | 74 |
| Vectors | 27 | 25 |
| Image fills | 0 | 7 |
| Grayscale MAE | 4.646 | 5.669 |
| Bad-pixel ratio | 0.0369 | 0.0482 |
| Critical text recall | 1.000 | 1.000 |

The mentor artifact uses no full-screenshot underlay. Its visual result comes
from nested frames, native text, vector icons and exact font selection.

The local SVG replay passes the strict visual gate on the fresh pipeline run:
`MAE 5.592 < 6`, `bad-pixel 4.901% < 5%`, duplicate overlap `0`,
horizontal overflow `0`, explicit fonts `100%`, and native vectors `22`.

The live Figma E2E also passes the frozen product policy. Its exported frame has
`MAE 5.669`, `bad-pixel 4.815%`, and `95.185%` of pixels within the product's
30-level visual threshold. Text, structure, editability, reference-only asset
display, and visual dimensions all pass.

## Transferable Rules

1. Build a scene tree before rendering.
   - root page
   - header/sidebar/main content
   - form/table sections
   - rows, controls and independent labels

2. Separate fonts by script.
   - CJK: source-first `Microsoft YaHei` with `Noto Sans SC` fallback
   - Latin/numeric: source-first `Segoe UI` with `Arimo` fallback
   - preserve a semantic font choice for brand lettering when available

3. Use vector nodes for simple UI icons.
   - search, mail, calendar, menu, list, chevrons, clock, save, export/edit
   - reserve image fills for photos, avatars and genuinely complex artwork

4. Treat tables as structured data.
   - ask the model for `header_texts` and complete row arrays
   - detect visible grid boundaries from pixels
   - assign one text owner per cell
   - keep row order and column alignment independent of scattered OCR

5. Use raw OCR observations for control geometry.
   - an OCR label can be skipped as duplicate text but must still be available
     to snap its owning button or input
   - adjacent toolbar buttons must remain independent rectangles

6. Keep duplicate and overflow gates independent from content recall.
   - overlapping duplicate text: zero
   - horizontal text overflow: bounded
   - explicit font selection: required
   - MAE and bad-pixel ratio must meet the visual target

7. Calibrate to pixels, not just bounding boxes.
   - recover horizontal surface bands between large scene containers
   - trace small monochrome icons into native SVG paths
   - use visible ink boxes for input values and table cells
   - keep a one-pixel origin calibration where the model bbox is consistently
     offset from the rendered border

## Implemented Direction

The local implementation now adds:

- script-aware font stacks and line height;
- geometry-derived nested container frames;
- vector SVG icons for a common icon subset;
- structured table prompt/parser/PageGraph merge;
- image-grid-based table cell reconstruction;
- image-derived table text owners, grid lines and source-first font stacks;
- recovered surface bands and raster-traced native navigation vectors;
- visible ink-box recovery for inputs and table cells;
- table-search field recovery from placeholder text;
- sparse structured-response repair via a second structure call;
- raw OCR observation handoff into control snapping;
- scene-hygiene visual gate.

## Non-Claims

- The mentor agent's hidden reasoning was not observed and is not required.
- Its planning text was not authoritative; the Figma artifact contradicted it.
- Copying the mentor node tree is not a product solution.
- Both the SVG preview and live Figma export have passed their frozen gates.
