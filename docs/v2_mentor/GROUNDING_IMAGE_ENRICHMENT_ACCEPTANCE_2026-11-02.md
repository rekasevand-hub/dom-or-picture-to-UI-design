# Grounding Image Enrichment Acceptance

Date: 2026-11-04 (Asia/Shanghai)

Decision: **do not adopt yet**

## Scope

This run compares `IMAGE_ENRICHMENT_MODE=off`, `analyze` and `apply` on the
three frozen screenshots in
`tests/fixtures/image_to_slice_benchmark_2026-11-02/manifest.json`.

The product target remains:

- fixed source-size, 1:1 editable reconstruction;
- no Component or Instance reuse requirement;
- no root responsive reflow requirement;
- no external provenance deliverable requirement;
- no visible full-screenshot underlay in the native reconstruction score.

## Frozen Inputs

| Sample | Size | SHA-256 |
| --- | --- | --- |
| IMG-ARTICLE | 2544x6156 | `e6feadee97294d568d9d310a17c6902a825735fcadf728fba0375875ba09419d` |
| IMG-FLEXWEAVER-ADMIN | 1920x826 | `c01805877d68c86b2465d675c323f51e68a1ecd8226583dbdb129d5017eced55` |
| IMG-ACCTOKEN-API | 2544x1336 | `7c61218aceb8f1f7f39950e9250d23ed327eb79715fe965bab69c4bdcbb0f404` |

Truth files are under `tests/fixtures/image_to_slice_benchmark_2026-11-02/truth/`.
They were manually reviewed against the source screenshots. OCR was only used
to locate candidate boxes.

## Execution Method

Command:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\image_enrichment_acceptance.py `
  --manifest tests/fixtures/image_to_slice_benchmark_2026-11-02/manifest.json `
  --out output/_grounding_image_enrichment_2026-11-02
```

The runner produces real PageGraph, DesignSpec and SVG output. SVG output was
rasterized at the source canvas size for MAE and bad-pixel measurement.

No Figma readback or Figma export was available in this environment. Therefore
`native-readback` is an explicit blocker for every scored run. SVG similarity
was not treated as proof of Figma native text or image-fill editability.

After fixing an evaluator-only control-ranking defect, existing artifacts were
re-scored with:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\image_enrichment_acceptance.py `
  --manifest tests/fixtures/image_to_slice_benchmark_2026-11-02/manifest.json `
  --out output/_grounding_image_enrichment_2026-11-02 `
  --reuse-existing
```

This did not replace failed provider runs with synthetic successes.

Verification:

- quality unit tests: 7 passed;
- full repository suite: 1037 passed.

## Results

All nine runs are `blocked-fail`.

| Sample | Mode | Calls | Text recall | Control recall | Container recall | Asset recall | MAE | Bad px | Content | Underlay |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| IMG-ARTICLE | off | 2 | 0.953 | 0.714 | 0.000 | 0.000 | 16.072 | 0.091 | 0.982 | 0.000 |
| IMG-ARTICLE | analyze | n/a | blocked before DesignSpec | - | - | - | - | - | - | - |
| IMG-ARTICLE | apply | n/a | blocked before DesignSpec | - | - | - | - | - | - | - |
| IMG-FLEXWEAVER-ADMIN | off | 1 | 0.840 | 0.053 | 0.571 | 0.000 | 17.515 | 0.104 | 0.176 | 0.000 |
| IMG-FLEXWEAVER-ADMIN | analyze | 1 | 0.040 | 0.000 | 0.286 | 0.000 | 43.827 | 0.238 | 0.022 | 0.000 |
| IMG-FLEXWEAVER-ADMIN | apply | 1 | 0.040 | 0.000 | 0.286 | 0.000 | 43.498 | 0.236 | 0.024 | 0.000 |
| IMG-ACCTOKEN-API | off | 1 | 0.958 | 0.455 | 0.625 | 0.000 | 6.683 | 0.047 | 0.332 | 0.000 |
| IMG-ACCTOKEN-API | analyze | 1 | 0.042 | 0.000 | 0.250 | 0.000 | 8.717 | 0.041 | 0.005 | 0.000 |
| IMG-ACCTOKEN-API | apply | 1 | 0.042 | 0.000 | 0.250 | 0.000 | 8.717 | 0.041 | 0.005 | 0.000 |

Table header recall:

| Sample | Mode | Header recall | Row recall |
| --- | --- | ---: | ---: |
| IMG-FLEXWEAVER-ADMIN | off | 0.286 | 1.000 |
| IMG-FLEXWEAVER-ADMIN | analyze | 0.000 | 1.000 |
| IMG-FLEXWEAVER-ADMIN | apply | 0.000 | 1.000 |
| IMG-ACCTOKEN-API | off | 0.857 | 1.000 |
| IMG-ACCTOKEN-API | analyze | 0.000 | 1.000 |
| IMG-ACCTOKEN-API | apply | 0.000 | 1.000 |

Generated asset count is `0` for every run. No generated asset was marked
original. This does not rescue the failed content, structure, asset or native
readback gates.

## Blocking Findings

1. All evaluated runs miss the Figma native text/image-fill readback gate.
2. No run satisfies critical text recall, control state/value accuracy and
   critical asset recall together.
3. Critical container and table structure recall are incomplete.
4. `IMG-ARTICLE` analyze/apply fail before DesignSpec with
   `GroundingRequestError: Grounding returned no structure for a non-background tile`.
5. `analyze` and `apply` currently reduce text/content/visual quality on the two
   ordinary samples rather than improving the complete native reconstruction.
6. No run uses a visible full-screenshot underlay; underlay ratio is `0.000`
   for every scored run.

## Product Decision

Do not adopt `analyze` or `apply` as the Grounding default yet.

The implementation passes unit and integration gates, but the frozen-sample
acceptance result is a blocking failure. `off` remains the default.

## Outstanding Evidence

- A real Figma bridge run is required to measure native text editability,
  image-fill count and Figma export similarity.
- The long article enriched prompt needs a successful tile recovery path before
  analyze/apply can be compared with off on that sample.
- Controls, containers, tables and critical assets need material recall and
  geometry improvements.
