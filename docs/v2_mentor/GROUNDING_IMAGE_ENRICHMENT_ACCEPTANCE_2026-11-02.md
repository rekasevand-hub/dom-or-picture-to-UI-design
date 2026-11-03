# Grounding Image Enrichment Acceptance

Date: 2026-11-04 (Asia/Shanghai)

Decision: **candidate passes the frozen Flex gate; do not adopt across all samples yet**

## Scope

The target is a fixed source-size, editable reconstruction with native text and
image fills, no visible full-screenshot underlay, and no requirement for
Component/Instance reuse, root responsive reflow, or an external provenance
deliverable.

This update closes the Task 4, 5, 9 and 10 defects found by the frozen
`IMG-FLEXWEAVER-ADMIN` sample:

- `analyze`/`apply` no longer combine contradictory normalized-array and
  source-pixel bbox prompts;
- provider coordinates reported on a 1000-pixel axis are calibrated to source
  pixels before page-coordinate merge;
- same-tile adjacent text cells are no longer merged into one table row;
- visible controls are snapped to detected field/checkbox geometry and receive
  visible value/state semantics;
- disconnected logo marks are unioned into one visible crop;
- overlong merged OCR rows are replaced by precise cell candidates;
- search placeholders remain visible text rather than input values;
- duplicate shadow text and empty icon buttons are removed from the DesignSpec.

## Truth Corrections

Manual inspection found three truth defects:

- `TETUO AUTO` is embedded in the critical logo asset, not separate native text;
- the claimed first-history checkbox is absent from the frozen screenshot;
- the table bbox truncated the visible partial fifth row by two pixels.

The corrected truth is in
`tests/fixtures/image_to_slice_benchmark_2026-11-02/truth/IMG-FLEXWEAVER-ADMIN.truth.json`.

## Real E2E Method

The frozen real provider response was replayed through the current deterministic
post-processing, then written through the live Figma bridge and exported from
Figma.

- Figma bridge: `ws://localhost:8765`;
- Figma root node: `10:232`;
- design: `output/_grounding_recovery_replay_probe12/12_design.json`;
- readback: `output/_grounding_figma_e2e_final_2026-11-04/readback.json`;
- Figma export:
  `output/_grounding_figma_e2e_final_2026-11-04/figma_export.png`;
- quality:
  `output/_grounding_figma_e2e_final_2026-11-04/quality.json`.

## Result

Status: **pass**

| Gate | Result |
| --- | ---: |
| Critical text recall | 1.000 |
| Critical control recall | 1.000 |
| Control value accuracy | 1.000 |
| Control state accuracy | 1.000 |
| Control bbox mean IoU | 0.553 |
| Critical container recall | 1.000 |
| Table header recall | 1.000 |
| Table row recall | 1.000 |
| Critical asset recall | 1.000 |
| Critical asset bbox IoU | 0.892 |
| Native text readback | 80 / 80 |
| Image-fill readback | 16 / 16 |
| Grayscale MAE | 10.242 / 255 |
| Bad-pixel ratio | 0.0746 |
| Visible underlay ratio | 0.000 |
| Content coverage | 0.270 |

The Figma render report and independently queried node tree agree on native
text and image-fill counts. No generated asset is marked original.

## Remaining Risk

This pass covers one frozen sample. The exported Figma image still shows
provider-induced duplicated and overflowing text in a few regions even though
all blocking metrics pass. Visual review remains required, and the metric pass
is not a claim of arbitrary-image generalization.

`IMG-ARTICLE` and `IMG-ACCTOKEN-API` must be rerun under the corrected pipeline
before changing the default enrichment mode. `off` remains the default.

## Verification

- focused Grounding enrichment and image-contract tests: 78 passed;
- quality tests: 7 passed;
- full repository suite: 1047 passed;
- Ruff: clean on touched Python files;
- live Figma write/readback/export: passed.
