# Fixed-Canvas Owner Compiler

Date: 2026-11-07

## Decision

Adopt the mentor-agent sample's fixed-canvas mechanism:

- one occurrence-level owner per visible content item;
- source-pixel absolute geometry;
- native fixed-size text;
- isolated image fills for artwork;
- structural table cell identity;
- authoring Frames independent from source regions.

Do not copy its implementation blindly. Reuse the decisions as contracts and
resolve styles dynamically for each new screenshot.

## Mentor Sample Result

| Metric | Result |
| --- | ---: |
| Declared owners mapped | 138 / 138 |
| Native TEXT owners | 79 / 79 |
| Text value mismatches | 0 |
| Table | 7 headers, 5 rows, 35 body cells |
| Overlapping duplicate text owners | 0 |
| Within-30 similarity | 97.202% |
| MAE | 2.564 |
| Bad-pixel ratio | 2.798% |
| Truth container regions | all below 5% |
| Image fills | logo and avatar only |
| Full screenshot underlay | none |

The notes control contains an exact whitespace mismatch and must not pass an
exact-content gate until it is corrected.

## Geometry Contract

`source_bbox` is the visible source region. `authoring_bbox` is the Figma Frame
used for layer organization. A root-sized authoring Frame is valid for fixed
canvas reconstruction when children use absolute source coordinates.

## Text Contract

Fixed-size native text is valid. Native editability means characters and style
can change and restore while the node remains TEXT. Auto Resize and geometry
growth are not required.

## Style Contract

Mentor values are priors:

- `Noto Sans SC` for CJK candidates;
- `Open Sans` for Latin candidates;
- `#555555` common UI text color;
- table headers bold and centered;
- table body text regular and left aligned.

For every new image, StyleResolver samples background/foreground, ink geometry,
font size, weight, script family and parent-relative alignment. Unknown font
identity remains explicit.

## Rejected Oversights

- Treating root-sized authoring Frames as source-region geometry.
- Requiring text geometry growth after editing.
- Using string equality as table row or owner identity.
- Appending OCR text after a semantic control or table owner already claimed
  the same occurrence.

## Live Grounding Regression

The `IMG-FLEXWEAVER-ADMIN` pipeline now carries source-pixel evidence through
the same owner compiler used for the final DesignSpec:

- chrome/icon candidates are attached before ScenePlan construction;
- brand and user identity marks are isolated reference-only assets;
- icon-only controls and checked boxes use source crops;
- control value geometry is taken from local OCR evidence;
- table grid boundaries come from the geometry manifest;
- table toolbar regions are reconciled from their visible controls;
- header bottom separator bands are sampled and trimmed from pixels.
- control text receives one bounded font-width calibration from rendered
  Figma TEXT bounds against source ink width.
- table-cell frames receive a position-only calibration from rendered bounds;
  font family and size remain unchanged.

Latest real Figma acceptance:

| Metric | Before owner cleanup | Latest |
| --- | ---: | ---: |
| Within-30 similarity | 90.987% | 94.498% |
| Page bad-pixel ratio | 9.013% | 5.502% |
| Header bad-pixel ratio | 9.684% | 3.000% |
| Sidebar bad-pixel ratio | 2.334% | 2.057% |
| Critical text | 23 / 24 | 24 / 24 |
| Duplicate owner overlap | present | none observed |

The full region gate is still blocked by `form-section`, `table-section`,
`table`, and the corrected toolbar/search regions. Do not describe this
snapshot as passed high-fidelity reconstruction.
