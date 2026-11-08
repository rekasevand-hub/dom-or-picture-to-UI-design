# Grounding Image Enrichment Design

## Intent

Improve the existing image-to-Figma product route by absorbing the useful
algorithms and behaviors demonstrated by `50kg/image-to-slice`. Grounding
remains the only image product route. Image To Slice is a source of techniques,
not a runtime dependency and not a selectable product route.

## Evidence

The current comparison established:

- Grounding and Image To Slice both create editable Figma text.
- On FlexWeaver, Image To Slice produced 109 nodes, 47 Text nodes, 4 image
  fills and grayscale MAE 13.796.
- Current Grounding produced 62 nodes, 51 Text nodes, 0 image fills and
  grayscale MAE 17.690.
- Image To Slice loses most content on long-page segments while returning
  HTTP 200.
- Current Grounding rejects one long-page segment because the model returns
  invalid structure JSON.
- None of the three comparison screenshots triggers a background candidate.

## Goals

- Accept source screenshots of arbitrary width and height without imposing an
  application-level image dimension limit.
- Recover critical text, layout hierarchy, raster assets and background/overlay
  candidates from long pages.
- Preserve the source canvas size and produce a fixed-size editable result.
- Produce a standalone HTML deliverable and a directly writable Figma
  DesignSpec.
- Meet blocking user-facing metrics for critical text recall, asset accuracy
  and visual MAE before the user accepts the reconstruction.

## Non-Goals

- Do not add an Image To Slice product route.
- Do not run the upstream JavaScript application, local API or Figma plugin in
  production.
- Do not count a full screenshot underlay as successful native reconstruction.
- Do not claim a generated approximation is an original asset.
- Do not reconstruct hidden regions as observed truth.
- Do not use HTML import as the canonical Figma write path. The DesignSpec must
  remain the source of truth.
- Do not build Component or Instance reuse in this scope.
- Do not make the root Frame responsive or test 2048/1440/mobile reflow.
- Do not create an external provenance deliverable. Existing internal source
  checks may remain for correctness and cache identity.

## Product Boundary

The product has one image route: Grounding. The new work is an internal
enrichment capability inside that route.

Rollout modes:

- `off`: existing Grounding behavior remains byte-identical.
- `analyze`: attach enrichment candidates and benchmark evidence, but do not
  rewrite the final DesignSpec.
- `apply`: use approved candidates and generated approximations in HTML and
  Figma output.

The config name is `IMAGE_ENRICHMENT_MODE`. It defaults to `off` while the
implementation is evaluated. The user decides when product adoption is
acceptable.

## Pipeline

### 1. Image planning

The original screenshot remains the source of truth. The pipeline records its
dimensions and SHA-256, then creates overlapping analysis tiles. Tiling is an
input-transport strategy, not a user-facing image-size restriction.

Every tile records:

- source rectangle;
- page-space origin;
- overlap with its predecessor;
- stable tile id;
- reason for its boundary: configured height, detected section boundary, or
  provider retry.

No tile output is accepted without translation back to source-page pixels.

### 2. Grounding pass

The first pass extracts containers, text, controls and visible image candidates.
A reduced full-page context image identifies page sections and repeated regions;
detailed tiles provide local geometry and reading order.

Each tile response is validated, parsed and attached to its originating tile.
Invalid JSON receives one bounded repair request and then one smaller-tile retry.
The pipeline fails closed if neither result is structurally valid.

### 3. Merge pass

Tile graphs are translated into global coordinates and merged using:

- exact and fuzzy text duplicates;
- IoU-based visual duplicates;
- repeated sticky header/footer/sidebar fingerprints;
- container intersection and parent inference;
- deterministic reading order and paint order.

Ambiguous duplicates remain in diagnostics rather than being silently dropped.

### 4. Asset analysis

The semantic model proposes visible assets with name, kind, bbox, confidence,
embedding-text status and reason. The Python pipeline:

- crops the exact visible source pixels;
- refines the bbox with local color/edge components;
- deduplicates repeated assets across tiles;
- records screenshot SHA-256 and payload SHA-256;
- creates a generated approximation only when an asset is occluded, missing or
  explicitly selected for approximation.

Observed visible pixels take precedence over generated pixels. Generated output
is used only for unavailable regions and is always marked `generated=true` and
`original=false`.

### 5. Background decomposition

The semantic model proposes full-background boxes, scored overlays and baked
visual regions. The Python pipeline converts overlays into masks and creates
two background deliverables:

- an observed source crop;
- a clean reconstruction candidate.

The clean candidate uses reference-guided image editing when supported. If the
provider cannot accept a mask, the pipeline may use a reference-guided whole
crop, edge extension and local compositing, but records the degraded method.
Observed and generated images are never merged into one unqualified hash.

### 6. Design and outputs

The enriched PageGraph is converted into a fixed-coordinate DesignSpec. A new
HTML adapter renders a standalone static document with local assets, semantic
containers, native text and image references. The Figma adapter writes the same
DesignSpec directly, preserving native text and image fills.

HTML import is not used because it loses input values and can alter text
semantics during DOM capture.

The `apply` mode must not place the complete source screenshot as a visible
underlay. A legitimate full-bleed background image is allowed only when it is
represented as a background asset and the foreground controls/text are separate.
A screenshot crop spanning the complete UI, or covering multiple unrelated
controls, is classified as an underlay and fails the native-reconstruction gate.

## Quality Contract

Every frozen sample has a truth file containing:

- image SHA-256 and dimensions;
- critical text strings;
- critical controls with type, bbox, displayed value and state;
- critical containers with role and bbox;
- expected table headers and row count;
- expected critical assets with bbox, kind and occurrence count;
- expected background regions and overlays;
- allowed generated or reference-only substitutions;
- visual metric policy.

Blocking metrics:

- critical text recall;
- critical control recall and bbox alignment;
- critical container recall and bbox alignment;
- table header and row recall;
- critical asset recall and bbox IoU, with an explicit minimum;
- full-page visual mean absolute error;
- bad-pixel ratio (`max-channel delta > 30`);
- visible full-screenshot underlay ratio;
- Figma native-text and image-fill probes.

Content-loss detection is also blocking. A visually blank output must fail even
if its MAE is low.

The underlay gate computes visible raster coverage after paint-order occlusion.
A full-screenshot image that contributes only to reference display is kept in a
separate `reference-underlay` artifact and never counted as a native
reconstruction result.

Visual similarity alone is insufficient. A passing result must demonstrate:

- no visible whole-screenshot underlay;
- complete and correctly valued critical controls;
- faithful relative layout and container hierarchy;
- complete table headers and expected row count;
- native text and available image fills at the original canvas size.

## Provider Capability Status

Controlled probes on 2026-11-02 established:

- `seedream-5.0-flash` accepts a reference image through
  `POST /v1/images/edits`;
- the same endpoint accepts a native `mask` field;
- the native mask convention is transparent pixels editable, opaque pixels
  protected;
- generic image edits require at least 921,600 pixels;
- the inpaint adapter's `1024x1024`, `1536x1024` and `1024x1536` preparations
  satisfy the tested provider;
- `qwen3-vl-plus` accepted both 8192x1024 and 2544x6156 synthetic inputs;
- 12px synthetic labels remained readable at all tested top/middle/bottom
  positions;
- image-token counts stayed near 2,500, so native-resolution reading is not
  proven.

The production Grounding configuration has no image-generation endpoint or key.
The successful edit probes belong to the separately configured Image To Slice
benchmark instance. Production must configure an image-generation endpoint
explicitly before generated assets can be enabled.

Public ACCTOKEN documentation covers the OpenAI-compatible base URL but does not
document vision preprocessing, native-resolution limits or universal mask
semantics. Those documentation gaps remain residual unknowns. They do not block
the local adapter that records observed capabilities and fails closed.

## Technical Decisions

- Use provider-aware overlapping tiles even if the application accepts
  unlimited dimensions.
- Use direct DesignSpec-to-Figma writes, not upstream HTML capture.
- Use visible screenshot crops as the primary display payload when available.
- Keep generated approximations separate internally from observed crops, without
  requiring a user-facing provenance manifest.
- Use deterministic geometry merging plus OCR/Grounding reconciliation rather
  than trusting one model response for a long page.
- Treat malformed model JSON as a recoverable tile-level failure, never as a
  successful partial page.
- Keep the root canvas fixed at the source dimensions. Local layout grouping is
  optional and exists only when it improves visual fidelity or editability.
