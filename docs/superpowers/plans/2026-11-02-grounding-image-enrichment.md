# Grounding Image Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the useful image decomposition, long-page analysis, asset recovery and background reconstruction techniques into the existing Grounding image route.

**Architecture:** Keep one Grounding product route. Add an internal
`IMAGE_ENRICHMENT_MODE=off|analyze|apply` pipeline that analyzes arbitrary-size
screenshots in overlapping tiles, merges candidate PageGraphs in source-page
coordinates, recovers observable assets and background masks, and feeds a
single DesignSpec into the existing HTML/Figma rendering path.

**Tech Stack:** Python 3.11, Pillow, numpy/OpenCV, EasyOCR, OpenAI-compatible
vision/image clients, existing PageGraph/image contract/Figma bridge, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-grounding-image-enrichment-design.md`

## Global Constraints

- Grounding remains the only image product route.
- Image To Slice is a source study target only; no JavaScript runtime or upstream API in production.
- Preserve image SHA-256 and source-pixel coordinates through every transformation.
- A screenshot of any dimension must be accepted; provider limits are handled by tiling.
- Generated pixels are never original pixels.
- Hidden-region reconstruction is a candidate and must remain identifiable.
- A visible full-screenshot underlay never counts as native reconstruction.
- Component/Instance reuse, root-level responsive reflow and an external
  provenance deliverable are explicit non-goals.
- `IMAGE_ENRICHMENT_MODE=off` preserves current output byte-for-byte.
- Critical text recall, critical asset accuracy and visual MAE are blocking metrics.
- Figma writes directly from DesignSpec; HTML DOM capture is not the canonical Figma path.
- Preserve the dirty worktree and stage only files named by the active task.

## Review Focus

- A 10,000-pixel-tall screenshot must not be silently truncated or shrunk into unreadable text.
- Overlapping tiles must not duplicate sticky navigation, sidebars or repeated cards.
- A blank reconstruction must fail even when its average image error is low.
- A generated asset must never be presented as an original asset.
- Figma must retain native text and image fills rather than converting the page to one bitmap.
- An image-backed result that appears close because the source screenshot remains
  underneath must fail the native-reconstruction acceptance gate.

---

### Task 1: Freeze the truth and metric contract

**Files:**
- Create: `src/app/services/structure/image_enrichment/__init__.py`
- Create: `src/app/services/structure/image_enrichment/contracts.py`
- Create: `tests/v2/test_image_enrichment_contracts.py`
- Create: `tests/fixtures/image_to_slice_benchmark_2026-11-02/truth/IMG-FLEXWEAVER-ADMIN.truth.json`
- Create: `tests/fixtures/image_to_slice_benchmark_2026-11-02/truth/IMG-ACCTOKEN-API.truth.json`
- Create: `tests/fixtures/image_to_slice_benchmark_2026-11-02/truth/IMG-ARTICLE.truth.json`

**Interfaces:**
- Produces: `validate_image_truth(value: object) -> dict`
- Produces: `asset_match_iou(expected_bbox: list[int], actual_bbox: list[int]) -> float`
- Truth assets contain `name`, `kind`, `bbox`, `critical`, and `minimum_iou`.
- Truth controls contain `name`, `type`, `bbox`, `value`, `state`, and
  `critical`.
- Truth containers contain `name`, `role`, `bbox`, and `critical`.
- Truth tables contain `header_texts`, `rows`, and `critical`.
- Truth backgrounds contain `id`, `bbox`, `critical`, `overlays`, and `allowed_substitutions`.

**Step 1: Write the failing truth contract test**

```python
from src.app.services.structure.image_enrichment.contracts import (
    asset_match_iou,
    validate_image_truth,
)


def test_truth_rejects_missing_critical_assets_and_clamps_iou():
    truth = {
        "sample_id": "sample",
        "image_sha256": "a" * 64,
        "image_size": [320, 240],
        "critical_texts": ["Submit"],
        "controls": [],
        "containers": [],
        "tables": [],
        "assets": [],
        "backgrounds": [],
        "visual_policy": {"mae_max": 20},
    }
    parsed = validate_image_truth(truth)
    assert parsed["critical_assets"] == []
    assert asset_match_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert asset_match_iou([0, 0, 10, 10], [20, 20, 10, 10]) == 0.0
```

**Step 2: Run the test and confirm the module is missing**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_contracts.py -v`

Expected: FAIL because `image_enrichment.contracts` does not exist.

**Step 3: Implement validation and geometry helpers**

Validate image hash, positive dimensions, critical text strings, control values
and states, container roles, table rows, asset kinds, bboxes, occurrence counts
and background overlays. Reject truth files that contain no blocking metrics.

**Step 4: Author truth for the three frozen screenshots**

Use the source image and visible UI as authority. List critical text, controls,
containers, table headers/rows and assets; do not use an unreviewed model
response as truth. For the long article, store boxes in original 2544x6156 page
coordinates.

**Step 5: Add one background-capable input requirement**

Add a manifest entry `IMG-PHOTO-OVERLAY` with `status: required` and a recorded
placeholder path only when the user supplies the source file. Do not invent a
real screenshot or count the synthetic test fixture as product evidence.

**Step 6: Run tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_contracts.py -v`

Expected: PASS.

**Step 7: Commit**

```powershell
git add src/app/services/structure/image_enrichment tests/v2/test_image_enrichment_contracts.py `
        tests/fixtures/image_to_slice_benchmark_2026-11-02/truth
git commit -m "test: define Grounding image enrichment truth"
```

---

### Task 2: Implement provider-aware tiling

**Files:**
- Create: `src/app/services/structure/image_enrichment/tiling.py`
- Create: `tests/v2/test_image_enrichment_tiling.py`
- Modify: `src/config/settings.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `plan_image_tiles(width: int, height: int, *, max_tile_height: int = 4096, overlap: int = 256, break_y: list[int] | None = None) -> list[dict]`
- Produces: `crop_image_tile(image: Image.Image, tile: dict) -> Image.Image`
- Produces: `translate_bbox_to_page(bbox: list[float], tile: dict) -> list[int]`
- Config: `VISION_TILE_MAX_HEIGHT=4096`
- Config: `VISION_TILE_OVERLAP=256`

**Step 1: Write failing tests for long and ordinary images**

```python
from PIL import Image
from src.app.services.structure.image_enrichment.tiling import (
    crop_image_tile,
    plan_image_tiles,
    translate_bbox_to_page,
)


def test_long_image_is_fully_covered_without_changing_resolution():
    tiles = plan_image_tiles(1200, 9000, max_tile_height=4096, overlap=128)
    assert tiles[0]["source_rect"] == [0, 0, 1200, 4096]
    assert tiles[-1]["source_rect"][1] + tiles[-1]["source_rect"][3] == 9000
    assert all(
        current["source_rect"][1] <= previous["source_rect"][1] + previous["source_rect"][3]
        for previous, current in zip(tiles, tiles[1:])
    )
    assert translate_bbox_to_page([0.25, 0.5, 0.5, 1.0], tiles[1]) == [300, 4224, 600, 4096]


def test_tile_crop_preserves_source_pixels():
    image = Image.new("RGB", (8, 12), "white")
    tile = plan_image_tiles(8, 12, max_tile_height=8, overlap=2)[0]
    assert crop_image_tile(image, tile).size == (8, 8)
```

**Step 2: Run the failing tiling tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_tiling.py -v`

Expected: FAIL because tiling does not exist.

**Step 3: Implement deterministic tile planning**

Use original pixel coordinates. Clamp overlap to the tile size. Prefer
`break_y` section boundaries within the overlap window. Include every source
row exactly once in coverage while allowing overlapping context.

**Step 4: Add config and documentation**

Document that these values control provider transport and never reject the
original image.

**Step 5: Run tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_tiling.py -v`

Expected: PASS.

**Step 6: Commit**

```powershell
git add src/app/services/structure/image_enrichment/tiling.py tests/v2/test_image_enrichment_tiling.py `
        src/config/settings.py .env.example
git commit -m "feat: add provider-aware image tiling"
```

---

### Task 3: Port candidate parsers and prompts

**Files:**
- Create: `src/app/services/structure/image_enrichment/parsing.py`
- Create: `src/app/services/structure/image_enrichment/prompts.py`
- Create: `tests/v2/test_image_enrichment_parsing.py`

**Interfaces:**
- Produces: `parse_enrichment_response(raw: str, image_width: int, image_height: int) -> dict`
- Produces: `build_grounding_tile_prompt(tile: dict, page_context: dict) -> str`
- Produces: `build_background_mask_prompt(background: dict, overlays: list[dict]) -> str`

**Step 1: Write parser tests**

Downstream text should include asset clipping, overlay clipping, allowed
candidate kinds, confidence clamping, and omission of ordinary UI text from
asset candidates:

```python
def test_parser_keeps_assets_and_clips_background_overlays():
    raw = '{"assets":[{"name":"hero","kind":"illustration","bbox":{"x":-5,"y":4,"width":40,"height":30}}],"backgrounds":[{"id":"bg","bbox":{"x":0,"y":0,"width":320,"height":240},"overlays":[{"id":"nav","name":"Nav","kind":"code-overlay","bbox":{"x":-10,"y":2,"width":50,"height":20}}]}]}'
    parsed = parse_enrichment_response(raw, 100, 80)
    assert parsed["assets"][0]["bbox"] == [0, 4, 35, 30]
    assert parsed["backgrounds"][0]["overlays"][0]["bbox"] == [0, 2, 40, 20]
```

**Step 2: Run failing parser tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_parsing.py -v`

Expected: FAIL because the parser does not exist.

**Step 3: Port only the approved algorithms**

Copy the semantic rules and limits from the upstream parser/prompt modules.
Convert DOM/canvas-specific code to Python/Pillow. Preserve MIT attribution in
module docstrings and record the source commit.

**Step 4: Add malformed-output tests**

Assert readable errors for invalid JSON, invalid bbox forms, unsupported kinds
and oversized overlay lists.

**Step 5: Run tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_parsing.py -v`

Expected: PASS.

**Step 6: Commit**

```powershell
git add src/app/services/structure/image_enrichment/parsing.py `
        src/app/services/structure/image_enrichment/prompts.py `
        tests/v2/test_image_enrichment_parsing.py
git commit -m "feat: port image enrichment prompts and parsers"
```

---

### Task 4: Add tiled Grounding execution and global graph merge

**Files:**
- Create: `src/app/services/structure/image_enrichment/merge.py`
- Modify: `src/app/services/structure/backends/grounding_vlm.py`
- Modify: `src/app/services/structure/providers/grounding.py`
- Modify: `src/app/services/structure/graph.py`
- Create: `tests/v2/test_image_enrichment_tiling_runtime.py`
- Create: `tests/v2/test_image_enrichment_merge.py`

**Interfaces:**
- Produces: `merge_tiled_graphs(graphs: list[dict], width: int, height: int) -> tuple[dict, dict]`
- `GroundingProvider.run(ctx)` uses one tile for ordinary images and multiple tiles for provider-limited images.
- `graph["provenance"]["tiling"]` records tile ids, source rects and merge diagnostics.

**Step 1: Write failing merge tests**

Test sticky-header duplication, repeated sidebar text, overlapping controls and
adjacent text across a tile boundary. Assert that global reading order is
deterministic and ambiguous duplicates remain in the report.

**Step 2: Run the merge tests and confirm failure**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_merge.py -v`

Expected: FAIL because merge does not exist.

**Step 3: Implement merge and dedupe**

Translate all candidates to page coordinates. Merge text with normalized text
plus IoU/containment; merge visuals with IoU plus crop similarity; recognize
repeated fixed regions by stable relative geometry and repeated text fingerprint.
Preserve diagnostics for every rejected duplicate.

**Step 4: Implement tiled backend execution**

Call the existing VLM client per tile. On invalid JSON, make one JSON-repair
attempt, then one smaller-tile retry. Never return a successful graph from a tile
with no parsed structure unless the tile is empty by majority background.

**Step 5: Verify `off` behavior**

Add a test that an ordinary image under the tile limit sends one request and
produces the same graph shape as current Grounding.

**Step 6: Run tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_merge.py tests/v2/test_image_enrichment_tiling_runtime.py tests/v2/test_grounding_reliability.py -v`

Expected: PASS.

**Step 7: Commit**

```powershell
git add src/app/services/structure/image_enrichment/merge.py `
        src/app/services/structure/backends/grounding_vlm.py `
        src/app/services/structure/providers/grounding.py `
        src/app/services/structure/graph.py `
        tests/v2/test_image_enrichment_merge.py `
        tests/v2/test_image_enrichment_tiling_runtime.py
git commit -m "feat: merge tiled Grounding candidates"
```

---

### Task 5: Recover visible assets and compact the screenshot layer

**Files:**
- Create: `src/app/services/structure/image_enrichment/assets.py`
- Modify: `src/app/services/structure/image_contract.py`
- Modify: `tests/v2/test_image_contract.py`
- Create: `tests/v2/test_image_enrichment_assets.py`

**Interfaces:**
- Produces: `recover_visible_assets(graph: dict, image_path: Path, *, work_dir: Path) -> tuple[dict, dict]`
- Produces: `build_asset_crop_request(asset: dict, source_image: Path, display_box: list[int]) -> dict`
- Each asset contains `visibleCrop`, `generatedApproximation`, `assetIdentity`, and `sourceResolution`.

**Step 1: Write failing asset tests**

Test one logo, one low-saturation photo, and one occluded product. Assert the
logo and photo produce reference-only crops with hashes, while the occluded
product records a missing/generated candidate state.

**Step 2: Run the failing asset tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_assets.py -v`

Expected: FAIL because the module does not exist.

**Step 3: Implement crop refinement and dedupe**

Use source bbox plus local connected components only to improve the visible
display rectangle. Do not infer transparent object boundaries from one flat
screenshot. Preserve the requested bbox as a candidate when refinement is
ambiguous.

**Step 4: Map observed assets into DesignSpec**

Emit image elements with source screenshot crop, display payload hash and
provenance. Ensure the Figma adapter receives `imageBase64`; do not rely on an
OCR-only image node.

Classify a crop as a full-screenshot underlay when it spans the page or contains
multiple unrelated critical text/control regions. `apply` mode must not emit that
node as a visible background. Keep it only as `reference-underlay` evidence.

**Step 5: Run tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_assets.py tests/v2/test_image_contract.py -v`

Expected: PASS.

**Step 6: Commit**

```powershell
git add src/app/services/structure/image_enrichment/assets.py `
        src/app/services/structure/image_contract.py `
        tests/v2/test_image_enrichment_assets.py tests/v2/test_image_contract.py
git commit -m "feat: recover visible image assets for Grounding"
```

---

### Task 6: Add background decomposition and mask construction

**Files:**
- Create: `src/app/services/structure/image_enrichment/backgrounds.py`
- Create: `src/app/services/structure/image_enrichment/repair.py`
- Create: `tests/v2/test_image_enrichment_backgrounds.py`
- Create: `tests/v2/test_image_enrichment_repair.py`

**Interfaces:**
- Produces: `build_background_mask(background: dict, overlays: list[dict], size: tuple[int, int]) -> bytes`
- Produces: `create_background_candidates(image: Image.Image, background: dict, overlays: list[dict], work_dir: Path) -> dict`
- Produces: `create_edge_blend_patch(image: Image.Image, placement: dict, *, band_ratio: float = 0.12) -> Image.Image`

**Step 1: Write mask and edge-blend tests**

Use a synthetic background with a white card and button. Assert the overlay mask
is white only inside selected overlays, the source crop remains unchanged, and
the blend patch preserves image size and edge colors.

**Step 2: Run failing tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_backgrounds.py tests/v2/test_image_enrichment_repair.py -v`

Expected: FAIL because the modules do not exist.

**Step 3: Implement deterministic crops and masks**

Build masks in original-image coordinates, clamp overlay boxes to the background,
write PNG masks with hashes, and retain the unmasked source crop.

**Step 4: Port the local edge blend algorithm**

Replace canvas/DOM operations with Pillow crops and numpy operations. Keep the
algorithm bounded to edge samples and preserve size/color.

**Step 5: Run tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_backgrounds.py tests/v2/test_image_enrichment_repair.py -v`

Expected: PASS.

**Step 6: Commit**

```powershell
git add src/app/services/structure/image_enrichment/backgrounds.py `
        src/app/services/structure/image_enrichment/repair.py `
        tests/v2/test_image_enrichment_backgrounds.py `
        tests/v2/test_image_enrichment_repair.py
git commit -m "feat: build background masks and edge repairs"
```

---

### Task 7: Add reference-guided generated asset and background reconstruction

**Files:**
- Create: `src/app/services/structure/image_enrichment/generation.py`
- Modify: `src/app/services/structure/generated_icon_recovery.py`
- Create: `tests/v2/test_image_enrichment_generation.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `generate_asset_approximation(request: dict, cfg: Config) -> dict`
- Produces: `restore_background(image: Image.Image, mask_png: bytes, prompt: str, cfg: Config) -> dict`
- Generated results contain `generator`, `model`, `input_reference`, `prompt`, `prompt_version`, `review_status`, `payload_sha256`, and `bytes_present`.

**Step 1: Write provider-contract tests**

Use fake clients to verify:

- reference image bytes are sent when the provider supports reference editing;
- a mask is sent when supported;
- unsupported-mask errors produce a degraded candidate with an explicit method;
- all generated candidates remain `original=false`.

**Step 2: Run failing tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_generation.py -v`

Expected: FAIL because the generation module does not exist.

**Step 3: Implement capability-aware generation**

Use the capabilities recorded in
`docs/v2_mentor/IMAGE_PROVIDER_CAPABILITIES_2026-11-02.md`. Preferred order:

1. reference edit with mask;
2. reference edit without mask;
3. deterministic local edge/reference fallback.

Use `POST /v1/images/edits` with multipart `image[]`. Add the native `mask` field
when supported. Prepare inpaint requests at `1024x1024`, `1536x1024` or
`1024x1536`; do not send sub-921,600-pixel edits. Never use an unrelated
text-only generated image when a reference is required and unsupported.

**Step 4: Integrate background and asset candidates**

Store observed and generated payloads separately. Composite generated regions
only where the mask is selected, and record the composite hash and method.

**Step 5: Run tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_generation.py -v`

Expected: PASS.

**Step 6: Commit**

```powershell
git add src/app/services/structure/image_enrichment/generation.py `
        src/app/services/structure/generated_icon_recovery.py `
        tests/v2/test_image_enrichment_generation.py .env.example
git commit -m "feat: add reference-guided generated image recovery"
```

---

### Task 8: Produce complete DesignSpec with HTML and direct Figma output

**Files:**
- Create: `src/app/services/rendering/html_adapter.py`
- Modify: `src/app/services/rendering/adapter_factory.py`
- Modify: `src/app/services/rendering/figma_adapter.py`
- Modify: `src/app/services/structure/image_contract.py`
- Create: `tests/v2/test_image_enrichment_html_adapter.py`
- Modify: `tests/v2/test_figma_adapter_edits.py`

**Interfaces:**
- Produces: `HTMLAdapter.render_design(design: dict) -> None`
- `HTMLAdapter` writes `prototype.html`, `styles.css` and `assets/`.
- Figma output keeps native text and image fills from the same DesignSpec.

**Step 1: Write HTML and Figma parity tests**

Assert that:

- every text element appears as editable text HTML;
- every image element references a local asset;
- generated assets carry `data-generated="true"`;
- z-order and full page dimensions match DesignSpec;
- Figma receives image payloads for image elements.

**Step 2: Run failing tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_html_adapter.py tests/v2/test_figma_adapter_edits.py -v`

Expected: FAIL because the HTML adapter does not exist.

**Step 3: Implement the HTML adapter**

Render a fixed-size screen with absolute-positioned semantic elements, native
text nodes, image assets, local CSS and deterministic escaping. Use hidden
overflow only where the DesignSpec says so.

**Step 4: Implement direct Figma mapping**

Preserve text content and image payloads from DesignSpec. Add a readback
assertion that the generated image count and native text count match the design.

Add a negative test where a source screenshot is used as the frame background.
The HTML and Figma outputs may keep it only in reference mode; native
reconstruction must reject it.

**Step 5: Run tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_html_adapter.py tests/v2/test_figma_adapter_edits.py -v`

Expected: PASS.

**Step 6: Commit**

```powershell
git add src/app/services/rendering/html_adapter.py `
        src/app/services/rendering/adapter_factory.py `
        src/app/services/rendering/figma_adapter.py `
        src/app/services/structure/image_contract.py `
        tests/v2/test_image_enrichment_html_adapter.py tests/v2/test_figma_adapter_edits.py
git commit -m "feat: render enriched images to HTML and Figma"
```

---

### Task 9: Integrate enrichment modes into Grounding

**Files:**
- Modify: `src/app/services/structure/providers/grounding.py`
- Modify: `src/app/agents/precise_agent.py`
- Modify: `src/config/settings.py`
- Modify: `.env.example`
- Create: `tests/v2/test_image_enrichment_integration.py`
- Modify: `tests/v2/test_image_route_fallback.py`

**Interfaces:**
- Config: `IMAGE_ENRICHMENT_MODE=off|analyze|apply`, default `off`.
- `off`: no new calls and byte-identical image artifacts.
- `analyze`: `sliceAnalysis` and provenance are added; final elements remain unchanged.
- `apply`: assets/background candidates feed DesignSpec elements.

**Step 1: Write routing tests**

Use fake providers to count calls and artifact fields. Assert `off` produces no
new fields and no additional OCR/asset calls, while `analyze` preserves the
original element list.

**Step 2: Run failing integration tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_integration.py tests/v2/test_image_route_fallback.py -v`

Expected: FAIL because the mode is not wired.

**Step 3: Wire the enrichment stage**

Attach `graph["imageEnrichment"]` with tiling, assets, backgrounds, generated
payloads and diagnostics. Do not create a new route or alter `effective_route`
away from `grounding`.

In `apply` mode, run the underlay detector before rendering. If an image node is
classified as a full-screenshot underlay, mark the run
`blocked-full-screenshot-underlay` and fail closed instead of presenting it as a
native design.

**Step 4: Verify default behavior**

Run the existing image acceptance tests without the new mode and compare the
serialized artifacts byte-for-byte.

**Step 5: Run tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_integration.py tests/v2/test_image_route_fallback.py tests/v2/test_image_agent_integration.py -v`

Expected: PASS.

**Step 6: Commit**

```powershell
git add src/app/services/structure/providers/grounding.py `
        src/app/agents/precise_agent.py src/config/settings.py .env.example `
        tests/v2/test_image_enrichment_integration.py tests/v2/test_image_route_fallback.py
git commit -m "feat: integrate image enrichment into Grounding"
```

---

### Task 10: Add full-page quality gates and acceptance report

**Files:**
- Create: `src/app/services/evidence/image_enrichment_quality.py`
- Create: `scripts/image_enrichment_acceptance.py`
- Create: `tests/v2/test_image_enrichment_quality.py`
- Create: `docs/v2_mentor/GROUNDING_IMAGE_ENRICHMENT_ACCEPTANCE_2026-11-02.md`

**Interfaces:**
- Produces: `evaluate_image_enrichment(truth: dict, design: dict, readback: dict, rendered_png: Path) -> dict`
- Produces: `write_image_enrichment_report(runs: list[dict], output: Path) -> dict`

**Step 1: Write failing quality tests**

Create a blank output with a very low MAE-like score and assert the quality gate
fails because critical text and content coverage are missing. Create a complete
fixture and assert all blockers clear.

**Step 2: Run failing tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_quality.py -v`

Expected: FAIL because the evaluator does not exist.

**Step 3: Implement metrics**

Compute:

- critical text recall;
- critical control recall, value accuracy, state accuracy and bbox IoU;
- critical container recall and bbox IoU;
- table header and row recall;
- critical asset recall with bbox IoU;
- native text and image-fill readback counts;
- grayscale MAE;
- max-channel bad-pixel ratio;
- occlusion-aware visible full-screenshot underlay ratio;
- content coverage by non-background pixel ratio;
- generated-vs-observed counts for diagnostics only.

The gate fails on any missing critical text, missing critical asset, generated
asset falsely marked original, missing or wrong critical control value/state,
missing container structure, missing table headers/rows, visible full-screenshot
underlay, blank content or visual metrics over policy. Component/Instance reuse,
root responsive behavior and an external provenance file are not gates.

**Step 4: Run the three frozen samples in `analyze` and `apply`**

Run each sample through both modes and write raw observations. Keep failed
samples in place; never replace a failed sample with a better one.

**Step 5: Build the acceptance report**

Compare `off`, `analyze` and `apply` using the same frozen inputs. Record:

- text and asset recall;
- Figma native-text and image-fill counts;
- control/container/table structure recall;
- MAE and bad-pixel ratio;
- visible full-screenshot underlay ratio;
- long-page content coverage;
- call count, latency and generated-asset count;
- the user-facing pass/fail decision.

**Step 6: Run tests and acceptance**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_enrichment_quality.py -v`

Run: `C:\Users\lzq\.conda\envs\omni\python.exe scripts\image_enrichment_acceptance.py --manifest tests/fixtures/image_to_slice_benchmark_2026-11-02/manifest.json --out output/_grounding_image_enrichment_2026-11-02`

Expected: test PASS; each sample has an explicit pass or blocking failure.

**Step 7: Commit**

```powershell
git add src/app/services/evidence/image_enrichment_quality.py `
        scripts/image_enrichment_acceptance.py tests/v2/test_image_enrichment_quality.py `
        docs/v2_mentor/GROUNDING_IMAGE_ENRICHMENT_ACCEPTANCE_2026-11-02.md
git commit -m "test: evaluate Grounding image enrichment"
```

---

### Task 11: Codify provider capabilities and production configuration

**Files:**
- Create: `scripts/image_provider_capability_probe.py`
- Create: `tests/v2/test_image_provider_capability_probe.py`
- Create: `docs/v2_mentor/IMAGE_PROVIDER_CAPABILITIES_2026-11-02.md`

**Interfaces:**
- Probe records `vision_observed_dimensions`, `vision_native_resolution`,
  `image_edit_reference`, `image_edit_mask`, `image_edit_min_area`, and
  `provider_model`.
- Production config requires `IMAGE_GENERATION_BASE_URL`,
  `IMAGE_GENERATION_API_KEY`, and `IMAGE_GENERATION_MODEL` before generated
  assets may run.
- The probe never logs API keys or base64 image bodies.

**Step 1: Write a probe parsing test**

Given fake provider capability responses, classify `native`, `downscaled`,
`rejected`, `reference-edit-supported` and `mask-edit-supported`.

**Step 2: Run failing tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_provider_capability_probe.py -v`

Expected: FAIL because the probe does not exist.

**Step 3: Implement opt-in probes from the recorded evidence**

Do not downgrade the successful 1024x1024 reference edit or native-mask findings
to guesses. Keep the probe opt-in because it makes paid calls. Include the
8192x1024 and 2544x6156 vision cases, the minimum-area failure, one successful
reference edit and one successful native-mask edit.

**Step 4: Write the provider capability record**

Record:

- observed vision acceptance at 8192x1024 and 2544x6156;
- that native-resolution reading remains unproven;
- successful reference editing with `seedream-5.0-flash`;
- successful native-mask repair with `maskMode=native-mask`;
- the 921,600-pixel minimum area for the tested model;
- that the production image-generation endpoint is not yet configured.

If a future model rejects native mask editing, mark background reconstruction as
reference-guided approximation and do not claim region-exact inpainting.

**Step 5: Run tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_provider_capability_probe.py -v`

Expected: PASS.

**Step 6: Commit**

```powershell
git add scripts/image_provider_capability_probe.py `
        tests/v2/test_image_provider_capability_probe.py `
        docs/v2_mentor/IMAGE_PROVIDER_CAPABILITIES_2026-11-02.md
git commit -m "test: record image provider capabilities"
```

## Self-Review

- Spec coverage: long images, merged Grounding, assets, backgrounds, generated
  approximations, HTML/Figma output, truth and metrics all have owning tasks.
- Default preservation: Task 9 pins `off` behavior.
- Internal source integrity: Tasks 5, 6 and 7 keep observed and generated pixels
  distinguishable; no external provenance deliverable is required.
- Underlay integrity: Tasks 5, 8, 9 and 10 detect and reject a visible
  full-screenshot underlay from the native-reconstruction score.
- Structural fidelity: Tasks 1 and 10 pin controls, containers, table headers
  and expected row counts.
- Output parity: Task 8 pins HTML and direct Figma writes from one DesignSpec.
- External uncertainty: Task 11 confines unknown provider capabilities to one
  probe instead of scattering assumptions through the implementation.
