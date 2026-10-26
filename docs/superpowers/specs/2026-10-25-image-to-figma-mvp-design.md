# Image To Figma MVP Design

**Date:** 2026-10-25  
**Status:** implemented-current-scope  
**Product route:** `image -> Figma`  
**Current scope:** one uploaded screenshot

**Implementation evidence:**
`docs/v2_mentor/IMAGE_FIGMA_MVP_ACCEPTANCE_2026-10-25.md`

## Intent

The first image product milestone must turn one uploaded screenshot into a real
Figma frame that preserves layout, component and content usability for at least
90% of the current owned sample. Exact pixel identity, original font identity
and final glyph outlines are not required.

The route must be honest about the limits of a flat image. A screenshot crop is
never promoted to an original asset. Hidden content, original DPR, original
viewport and original font identity remain unknown unless supplied.

## Current State

The repository already has:

- `GroundingProvider`, which returns bounding boxes and text from a screenshot;
- `CVProvider`, which returns visual candidates through OmniParser and OCR;
- PageGraph and SoM conversion;
- a generic VLM DesignSpec generator;
- a Figma adapter with write, readback, export, native-text and image-fill
  probes.

The missing product layer is not another provider. It is an image-specific
contract that:

1. records the screenshot as a faithful single-frame reference;
2. keeps Grounding/CV output as candidates with explicit provenance;
3. builds a deterministic DesignSpec from candidate geometry and sampled
   pixels;
4. marks image payloads as reference-only display crops;
5. records fixed-coordinate and flow-candidate limits;
6. connects the result to real Figma write/readback/export acceptance.

## Approaches Considered

### A. Generic VLM DesignSpec only

Reuse the current `grounding -> SoM -> VLM DesignSpec` chain unchanged.

Tradeoff: minimal code change, but the controlled probe showed the second VLM
can assign black backgrounds to text and alter bbox/type evidence. That makes
provenance and visual quality less deterministic.

### B. Deterministic pixel-sampled DesignSpec from Grounding geometry

Use Grounding for layout candidates, then sample container fills, text colors,
button fills and image crops directly from the source screenshot. Emit native
text and image-fill nodes with fixed coordinates.

Tradeoff: less semantic inference than a second VLM, but substantially more
stable, auditable and suitable for the simple MVP scope.

### C. Full screenshot underlay plus sparse editable overlays

Place the whole screenshot as an image layer and add a few native controls.

Tradeoff: high visual score, but it can mask structural failures and makes the
result less editable. This conflicts with the product priority on layout and
components.

## Chosen Approach

Use approach B for the MVP.

Grounding remains the default image parser. CV remains a fallback only when the
Grounding VLM service is unavailable or its required configuration is missing.
Ordinary malformed output or downstream failures do not trigger a silent route
switch.

The image presentation stage is deterministic:

- source-pixel coordinates are preserved;
- container and control fills are sampled from the source crop;
- text color is sampled from the text region;
- image/avatar nodes use screenshot crops explicitly marked
  `original=false`, `reference_only=true`;
- no generated asset is implied;
- no DPR, viewport, font or hidden-state fact is inferred;
- flow is `candidate` with fixed-coordinate positioning.

## Product Contract

### Input

- exactly one local image;
- PNG/JPEG/WebP readable by Pillow;
- no required viewport, DPR or font metadata.

### Required Output

- one Figma frame;
- native text for detected text candidates;
- critical content checked against an owned truth manifest;
- reference-only image nodes that can be replaced at the display level;
- readback and export evidence;
- explicit limitations for original asset identity, font identity and adaptive
  flow.

### Forbidden

- claiming a screenshot crop is an original asset;
- claiming OCR/Grounding text was manually verified when it was not;
- presenting fixed coordinates as an adaptive layout;
- claiming hidden regions from the screenshot;
- adding a full screenshot underlay to inflate the visual score while hiding
  structural failures;
- changing the 90% threshold after seeing the result.

## Acceptance

The owned MVP sample uses a frozen manifest containing critical texts and an
explicit 90% visual similarity threshold. The report keeps dimensions separate:

- critical text;
- native-text editability;
- reference-only asset display replacement;
- visual similarity;
- structure/component usability;
- Figma write/readback/export;
- provenance and non-claims.

Overall pass requires critical text correctness, a real Figma frame and export,
display replacement for claimed image nodes, and at least 90% within-30 pixel
similarity. Original source identity and adaptive flow remain non-blocking but
must be reported.

## Non-Goals

- arbitrary screenshot semantic reconstruction;
- original DPR or viewport recovery;
- original asset recovery from a flat screenshot;
- exact font/glyph reproduction;
- adaptive Auto Layout;
- multi-page image input;
- production admission;
- Axure generation.
