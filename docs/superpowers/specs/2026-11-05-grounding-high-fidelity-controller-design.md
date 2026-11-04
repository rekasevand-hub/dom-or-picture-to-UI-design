# Grounding High-Fidelity Controller Design

Date: 2026-11-05

## Intent

Grounding should reconstruct a screenshot as an image-constrained scene, not
redesign a similar interface. The primary failure modes to eliminate are
missing content, invented content, wrong row counts, abbreviated values,
incorrect geometry, approximate controls, and visually masking structural
errors.

The user has chosen fidelity over single-call latency. Additional localized
vision calls are allowed when a measured blocker identifies a specific region.
The system remains a controlled workflow: model calls are bounded, scoped,
validated, and reversible.

## Goals

1. Preserve every visible text, value, control state, table header, and table
   row.
2. Keep one canonical source-pixel coordinate space.
3. Produce a scene tree before rendering.
4. Use slice-to-image only as an internal evidence and asset-decomposition
   capability.
5. Verify content, geometry, visual similarity, and editability separately.
6. Repair only the regions that fail a concrete gate.
7. Keep the current single-pass behavior available as the default until the
   high-fidelity path demonstrates gains on the frozen benchmark.

## Non-Goals

- Do not use a whole-screenshot image as the final canvas underlay.
- Do not copy the mentor agent's node tree directly.
- Do not let an autonomous agent decide its own completion criteria.
- Do not send the entire page to a model repeatedly when a local crop is
  enough.
- Do not let `sliceAnalysis` create a second scene tree.
- Do not claim original asset identity from a flat screenshot.
- Do not replace readable native text with text outlines or image crops.

## Chosen Approach

Use a Grounding-first, evidence-driven pipeline with a bounded local repair
controller.

```text
source image
  -> initial Grounding pass
  -> evidence bundle
     - Grounding structure
     - OCR/CV geometry
     - tables
     - controls
     - slice asset candidates
  -> ContentInventory
  -> GeometryManifest
  -> ScenePlan
  -> DesignSpec
  -> SVG/Figma
  -> readback + full/region verification
  -> targeted repair patches
  -> recompile and reverify
```

The high-fidelity controller owns orchestration. It does not own pixel facts.
Pixel facts come from the original image, OCR/CV measurements, and explicit
provenance.

### Alternatives Rejected

1. Full-page model retries until a score passes.
   - Expensive.
   - Non-deterministic.
   - Can fix one area while regressing another.

2. Independent Grounding and slice pipelines merged at the end.
   - Creates duplicate assets and competing scene trees.
   - Makes ownership and rollback ambiguous.

3. Unbounded planner-agent execution.
   - Completion and call count are unpredictable.
   - Hard to reproduce and audit.

## Pipeline

### Stage 1: Evidence Collection

Collect:

- Grounding containers, elements, controls, and tables.
- Raw OCR observations and measured text ink boxes.
- CV grid, container, border, fill, and color evidence.
- Slice assets, backgrounds, overlays, and reference-only crops.
- Full-image reference metadata and source SHA-256.

Each evidence item records:

```json
{
  "id": "evidence-001",
  "kind": "text|control|table|container|asset|geometry",
  "status": "observed|derived|inferred",
  "authority": "source-pixel|grounding|ocr|cv|slice",
  "confidence": 1.0,
  "bbox": [0, 0, 0, 0],
  "payload_ref": "optional-artifact",
  "reason": ""
}
```

Evidence remains candidate data. It must not write directly into DesignSpec.

### Stage 2: Content Inventory

Build one deterministic inventory from the evidence bundle:

- All visible labels.
- All field values.
- All buttons and states.
- Every table header and each cell value.
- Visible row count and column count.
- Visible assets and embedded text.
- Explicit unknowns and ambiguities.

The inventory is the only allowed source for deciding what content may appear
in the final scene.

If the inventory is incomplete or contradictory, the controller emits a
specific repair request. It does not let the renderer invent content from a
generic layout prior.

### Stage 3: Geometry Manifest

Record source-pixel geometry for:

- Page, header, sidebar, main content.
- Form and table sections.
- Each control and text owner.
- Table columns, rows, and grid boundaries.
- Asset display boxes and reference-only crops.

All boxes use:

```json
{"x": 0, "y": 0, "width": 0, "height": 0}
```

Width and height must be positive and remain inside the source canvas.

### Stage 4: Scene Plan

The ScenePlan assigns each inventory item to exactly one rendered owner:

- Text owner.
- Control value owner.
- Checkbox label owner.
- Table cell owner.
- Vector icon.
- Reference-only image asset.

Rules:

- A control and a separate text item must not both render the same value.
- A checkbox label must not be centered inside a checkbox square.
- A table cell has exactly one text owner.
- Header text and body text may use different alignment rules.
- `sliceAnalysis.assets` can supply an asset payload but cannot create a second
  layout tree.

### Stage 5: Compile and Render

Compile ScenePlan into the existing DesignSpec and reuse the current SVG/Figma
adapters.

The renderer receives only:

- ScenePlan.
- DesignSpec.
- Explicit asset payloads.

It does not receive the full source image as a drawable backdrop.

### Stage 6: Verification

Run four independent checks:

#### Content

- Critical text recall equals 1.0.
- Control recall, value accuracy, and state accuracy equal 1.0.
- Table header recall and row recall equal 1.0.
- No extra visible rows.
- No abbreviated dates or values.

#### Geometry

- Critical container recall equals 1.0.
- Control and container IoU meet configured thresholds.
- Table boundaries match the measured grid.
- Text and controls remain inside their owning regions.

#### Visual

- Same canvas size.
- Strict full-image MAE and bad-pixel gates.
- Region-level metrics for header, sidebar, form, toolbar, and table.
- Region regression cannot be hidden by a better global score.

#### Editability and Provenance

- Native text count matches the planned text-owner count.
- Image-fill count matches the planned reference-only asset count.
- Vectors remain vectors.
- Full-screenshot underlay ratio is zero.
- Readback text can be edited.

## Local Repair Controller

Repair requests are emitted only for named blockers:

| Blocker | Local action |
| --- | --- |
| Missing or incomplete table | Re-read table crop and structured rows |
| Missing control | Re-read control-region crop |
| Wrong control value/state | Re-read the owning field or checkbox crop |
| Duplicate text owner | Re-plan ownership; no model call if deterministic |
| Low control/container IoU | Re-measure geometry; model call only if semantics are ambiguous |
| Asset crop incomplete | Re-run slice candidate selection on the asset crop |
| Region visual regression | Re-render and compare; call model only if structure is unresolved |

### Patch Contract

A repair call returns a patch, not a complete page:

```json
{
  "region_id": "form.status",
  "target_ids": ["control-29"],
  "reason": "checkbox label overlapped value",
  "operations": [
    {"op": "set_owner", "id": "control-29", "text_owner": "ocr-36"},
    {"op": "set_state", "id": "control-29", "value": "checked"}
  ]
}
```

The controller validates every operation against ContentInventory and
GeometryManifest. A patch is accepted only if:

1. It resolves or reduces the named blocker.
2. It does not reduce content recall.
3. It does not regress any protected region beyond tolerance.
4. It does not introduce underlay, duplicate text, or new image claims.

Patch application is transactional. Rejected patches are recorded and rolled
back.

### Call Policy

High-fidelity mode is explicit and bounded:

- One initial full-image Grounding pass.
- At most one table-specific repair.
- At most one control-region repair per failed form region.
- At most one asset/slice repair per failed asset group.
- At most three repair rounds.
- A configurable hard cap on additional calls, initially six.
- Stop early when blockers are resolved, the call cap is reached, or no patch
  produces measurable gain.

Identical crop, prompt, and schema calls are cached by source SHA-256.

## Configuration

Proposed settings:

```text
GROUNDING_FIDELITY_MODE=off|high
GROUNDING_REPAIR_MAX_ROUNDS=3
GROUNDING_REPAIR_MAX_EXTRA_CALLS=6
GROUNDING_REPAIR_MIN_REGION_GAIN=0.5
GROUNDING_REGION_REGRESSION_TOLERANCE=0.2
```

High-fidelity mode requires `IMAGE_ENRICHMENT_MODE=apply`. The default remains
`GROUNDING_FIDELITY_MODE=off` until benchmark results are accepted.

## Artifacts

Add:

```text
09_evidence_bundle.json
10_content_inventory.json
10_geometry_manifest.json
11_scene_plan.json
13_fidelity_report.json
14_repair_history.json
```

Keep existing artifacts:

```text
10_pagegraph.json
11_som.json
12_design.json
prototype.svg
render.png
```

`sliceAnalysis` remains a compatibility projection from the evidence bundle.
It is not a second canonical scene.

## Benchmark and Rollout

Evaluate on all frozen samples:

- IMG-FLEXWEAVER-ADMIN.
- IMG-ACCTOKEN-API.
- IMG-ARTICLE.

For each sample report:

- Content, geometry, visual, native-structure status.
- Full and regional MAE/bad-pixel metrics.
- Calls, rounds, latency, and token usage.
- Repair acceptance/rejection and rollback history.

Promotion requires:

1. No content or editability regression.
2. Strict visual gates pass.
3. Region metrics do not regress.
4. Cost and latency remain within configured limits.

## Acceptance Criteria

The design is successful when:

- Missing, abbreviated, invented, and duplicated content are hard failures.
- Fixed canvas size and source-pixel geometry are preserved.
- Visual scores cannot pass when content or structure fails.
- The same design produces native editable text and assets in Figma.
- High-fidelity mode can be enabled and disabled without changing legacy output
  when disabled.
- The repair controller never exceeds its call and round budgets.
