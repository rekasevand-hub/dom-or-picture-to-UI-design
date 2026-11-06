# Grounding High-Fidelity Acceptance

Date: 2026-11-05 (Asia/Shanghai)

Decision: **blocked; do not promote the high-fidelity mode**

The controller produces auditable evidence, one canonical ScenePlan, native
text, reference-only assets, and a real Figma readback/export. It completes all
three frozen samples, but it does not satisfy the strict content and regional
visual gates. `GROUNDING_FIDELITY_MODE=off` remains the default.

## Scope

The tested path is:

```text
source PNG
  -> real Grounding VLM
  -> evidence bundle
  -> content inventory
  -> geometry manifest
  -> ScenePlan
  -> DesignSpec
  -> live Figma write/readback/export
  -> content, native-structure, full-image and region acceptance
```

No sample used a full-screenshot underlay. Image and logo payloads remain
reference-only screenshot crops and do not claim original asset identity.

## Real E2E Method

- Runner: `scripts/image_figma_mvp.py`;
- route: `grounding`;
- `IMAGE_ENRICHMENT_MODE=apply`;
- `GROUNDING_FIDELITY_MODE=high`;
- Figma bridge: `ws://localhost:8765`;
- design and export size match the source image for all samples;
- temporary origin offsets were used only to keep test frames separate.

Evidence roots:

```text
output/_grounding_high_fidelity_2026-11-05/IMG-FLEXWEAVER-ADMIN-r6
output/_grounding_high_fidelity_2026-11-05/IMG-FLEXWEAVER-ADMIN-r8
output/_grounding_high_fidelity_2026-11-05/IMG-ACCTOKEN-API
output/_grounding_high_fidelity_2026-11-05/IMG-ARTICLE
```

## Results

| Sample | Acceptance | Critical text | Within-30 | Failed regions | Figma frame |
| --- | --- | ---: | ---: | ---: | --- |
| `IMG-FLEXWEAVER-ADMIN` | blocked-fail | 24 / 24 | 93.959% | 6 / 7 | `5:2` |
| `IMG-ACCTOKEN-API` | blocked-fail | 44 / 48 | 95.797% | 3 / 7 | `26:2726` |
| `IMG-ARTICLE` | blocked-fail | 22 / 43 | 92.030% | 10 / 12 | `26:2830` |

All three pass the frozen 90% full-image product metric, native-text edit
probe, reference-only asset probe, and full-screenshot-underlay block. The
strict regional gate is not hidden by those global passes.

### FlexWeaver

Passing dimensions:

- 24 / 24 critical texts;
- 17 controls with matching values and states;
- 5 / 5 table rows;
- 64 native text nodes and 5 reference-only image nodes;
- asset, edit, fidelity, full visual and repair-budget dimensions pass.

Failed regions:

| Region | Bad pixels |
| --- | ---: |
| header | 9.226% |
| table-section | 6.442% |
| table | 6.249% |
| main-content | 6.557% |
| page | 6.041% |
| form-section | 6.237% |

The latest local repair pass uses reference-only screenshot crops for chrome
icons, left-aligned text boxes for input values, a single ScenePlan owner for
table text, automatic removal of unowned table-model text, and relocation of
mis-snapped table-toolbar buttons. It keeps 24/24 critical content and native
editability, but header typography/icons and text-heavy form/table rendering
still exceed the region threshold.

The final ownership repair also removes 1px-offset unowned input shadows that
were covering real values, and resolves large icon-button mislabels back to
editable inputs. Those changes improve structural correctness even though the
strict region metric remains above threshold.

### Account Token API

Passing dimensions:

- asset, edit, fidelity, repair-budget and full visual.

Failed content:

- `数据看板`;
- `我的等级`;
- `状态: 全部`;
- `9月3日创建`.

Failed regions:

| Region | Bad pixels |
| --- | ---: |
| banner | 12.586% |
| table | 5.838% |
| table-container | 6.435% |

### Article

The long-page tiling path completed and wrote a 2544 x 6156 Figma frame.

Failed regions include:

| Region | Bad pixels |
| --- | ---: |
| community-card | 18.594% |
| search-suggestion | 17.854% |
| toc | 13.616% |
| sidebar (lower) | 12.572% |
| sidebar (upper) | 10.096% |
| page | 7.970% |

Eighteen critical texts remain missing, concentrated in the top navigation,
article metadata, early article body and lower recommendation rail. This is a
content-completeness failure, not an acceptable visual variant.

## Repair And Call Budget

The real runs used one initial Grounding pass and no additional local repair
calls because the evidence preflight reported complete ScenePlan ownership.

- repair rounds: `0`;
- extra calls: `0`;
- rejected patches: `0`;
- rolled-back patches: `0`.

Flex and Account Token each recorded one Grounding call, about 90 seconds and
about 8.6k total tokens in the provider observability record. The Article tiled
run does not expose one aggregate token/latency value in the current tiled
provenance shape; this remains an observability gap.

## Remaining Differences

1. Grounding still omits or misclassifies some content, especially the Article
   header/navigation and several Account Token labels.
2. Asset crop geometry can include neighboring header glyphs; reference-only
   status is correct, but the visible crop still needs local repair.
3. Control and table chrome remains visually approximate.
4. Region regression currently blocks acceptance even when the full-image
   product metric and all Flex content gates pass.
5. The local crop-repair backend and the live Figma acceptance loop are not yet
   joined into one automatic repair transaction.
6. Tiled runs need aggregate call, token and latency reporting.
7. One-shot deterministic compilation has reached its limit for text-heavy
   regions: further fixes require a live per-region patch/re-render/compare
   transaction instead of more global style heuristics.

## Promotion Rule

High-fidelity mode must remain disabled until a new run satisfies all of:

- 100% critical text, control, table, native-structure and asset gates;
- no additional visible rows or abbreviated values;
- every protected region within the 5% bad-pixel limit;
- repair/call/round evidence within the configured budget;
- no visible full-screenshot underlay.

Global visual similarity alone is not sufficient.

## Verification

- focused high-fidelity, ScenePlan, image-contract and acceptance tests:
  `95 passed`;
- full repository regression: `1143 passed in 80.32s`;
- touched Python files: Ruff and format checks pass;
- Figma bridge JavaScript: `node --check figma_bridge/code.js` passes;
- live Figma readback/export succeeded for all three samples.

The repository-wide Ruff command is not clean: it reports 39 pre-existing
findings in unrelated files. Those files were not changed or auto-fixed as
part of this benchmark.
