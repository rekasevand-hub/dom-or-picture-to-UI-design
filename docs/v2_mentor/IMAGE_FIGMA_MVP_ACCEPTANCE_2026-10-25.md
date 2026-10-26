# Image To Figma MVP Acceptance

**Task:** I-011  
**Status:** `pass-current-scope`  
**Date:** 2026-10-25  
**Sample:** `IMG-MVP-01`  
**Figma frame:** `77:4851`  
**Run root:** `output/_image_figma_mvp_2026-10-25_r4/`

## Decision

The owned single-screenshot sample completed the current-scope image-to-Figma
route with real Figma write, readback, export and edit probes.

The frozen product gate passes:

- `14/14` critical texts are present;
- native text edit and restore pass;
- reference-only image display replacement and restore pass;
- the real Figma export is `96.5331%` within-30 similarity, above the frozen
  `90%` product threshold;
- the exported frame is `1200x800`, matching the source screenshot;
- no original asset, original font, original DPR/viewport or adaptive-flow
  claim is made.

This is a current-scope pass for one owned screenshot and one real Figma
document. It is not an arbitrary-screenshot or production claim.

## Input

| Item | Value |
|---|---|
| Image | `tests/fixtures/image_mvp/simple_dashboard_v1.png` |
| Screenshot SHA-256 | `7f39efc5e69b9ba16367aa19a1ccb1e3ea1681824419c93f0f9a3478e5153df4` |
| Size | `1200x800` |
| Reference state | `faithful`, single visible frame |
| DPR / viewport / font identity | `unknown` |
| Product threshold | `90%` within-30, frozen before the final run |

The image pipeline receives only the PNG. The source HTML and truth manifest
are used to create and evaluate the owned sample; they are not fed to the
image parser.

## Strategy

```text
requested: auto
selected: grounding
fallback_used: false
policy: grounding-default-cv-only-when-unavailable
```

Presentation is deterministic:

```text
grounding-pixel-sampled-fixed-coordinate
```

Grounding supplies candidate geometry and text. Container fills, text colors,
control surfaces and image crops are sampled from source pixels. A text
supplement can add missing OCR candidates, but it does not change route:

```text
OCR supplement: no-change
OCR languages: en
OCR added: 0
image-region recovery: not-needed
```

The final run did not need either fallback. Earlier controlled runs exercised
the OCR/button/embedded-image recovery paths and exposed the defects that led
to their tests.

## Real Figma Evidence

| Check | Result |
|---|---|
| Write/readback/export exists | pass |
| Frame | `77:4851` |
| Canvas | `1200x800` |
| Readback nodes | `24` |
| Native text nodes | `16` |
| Image-fill nodes | `1` |
| Auto Layout nodes | `0` |
| Text edit/restore probe | pass, node `77:4856` |
| Image replace/restore probe | pass, node `77:4870` |
| Export bytes | `43836` |
| Export SHA-256 | `9092924e42d0c31426d5ff5b372387eb626fc8d0bc7bcabe1209a9c838f42def` |

The image fill report contains one payload of `4252` bytes. The design-side
crop payload SHA-256 is:

```text
17a9dd26f5efc4c91af75daf4c0309ef403b627d703b223a72277f1c27e89f91
```

The Figma runtime proves that the image node can be replaced and restored. It
does not prove that the screenshot crop is an original asset.

## Quality Dimensions

| Dimension | Result |
|---|---|
| Critical text | pass `14/14` |
| Native text editability | pass |
| Structure/content nodes | pass |
| Reference-only display replacement | pass |
| Visual within-30 | pass `96.533125%` >= `90%` |
| Size match | pass |
| Meaningful-difference ratio | `3.466875%` |
| Mean channel delta | `4.237964` |
| Ink mean delta | `9.972318` |

No composite score is used.

## Asset Provenance

The IR contains one image candidate:

```text
identity: unavailable
display: screenshot-crop
original: false
reference_only: true
generated: false
```

The source record remains `partial-unresolved-identity`. Display replacement is
reported separately from source identity and is allowed only for the Figma
display node under this current scope.

## Text Provenance

Grounding text remains `grounding-vlm-candidate`. Optional supplemental text
would remain `ocr-candidate`. The critical-text gate checks the written Figma
content against the owned truth manifest; it does not promote either source to
original DOM identity.

English word spacing is preserved by the acceptance matcher. A compact typo
such as `ImageMVP` for `Image MVP` fails the critical-text gate.

## Layout And Flow

The Figma design uses fixed source-pixel coordinates:

```text
flow value: fixed-coordinate
flow status: candidate
adaptive flow: not claimed
```

The run does not create Auto Layout. Unsupported responsive behavior remains
explicit.

## Evidence Hashes

| Artifact | SHA-256 |
|---|---|
| `pipeline/image_ir.json` | `b907619db5fb3d56975864070eb4c5d0cacd933be312d632efe4b74ed8c01017` |
| `figma_design.json` | `ee4b928e298639b2c4d8cc2546d30b013ca7b1a2ec728b7ed2ca809aadb3a73f` |
| `figma/readback.json` | `804468c5376fb9049537e6bd54ea8101b7152837fa5d71992e93f6904de94f8a` |
| `figma/text_edit_probe.json` | `c49ceb46c74b87247daa0c09e5795885dabf2e88a753ece9f9695b9de2d6a211` |
| `figma/asset_probe.json` | `9041d06fd1b365659db2124702e361e6eacdfb060d2cc4e778250e3e9b4b7a63` |
| `figma/export.png` | `9092924e42d0c31426d5ff5b372387eb626fc8d0bc7bcabe1209a9c838f42def` |
| `acceptance.json` | `0670d81e8176a9aa42f6aa2b9b6cd495d08fe07711fce7dee6316e7d69e61cd9` |

## Reproduce

Fresh preparation:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/image_figma_mvp.py `
  --image tests/fixtures/image_mvp/simple_dashboard_v1.png `
  --truth tests/fixtures/image_mvp/simple_dashboard_v1.truth.json `
  --out output/_image_figma_mvp_2026-10-25_next `
  --prepare-only
```

Real Figma run on the frozen prepared artifacts:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/image_figma_mvp.py `
  --image tests/fixtures/image_mvp/simple_dashboard_v1.png `
  --truth tests/fixtures/image_mvp/simple_dashboard_v1.truth.json `
  --out output/_image_figma_mvp_2026-10-25_next `
  --reuse-prepared `
  --origin-x 24000 `
  --origin-y 0
```

## Non-Claims

This report does not claim:

- arbitrary screenshot semantic reconstruction;
- original asset identity;
- original DPR, viewport or font identity;
- final glyph outline identity;
- adaptive Auto Layout;
- hidden-region recovery;
- project-wide `verified=true`;
- production admission;
- Axure support.
