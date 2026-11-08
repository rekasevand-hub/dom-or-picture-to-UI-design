# Image To Slice Source Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Study and port the useful image decomposition algorithms from `50kg/image-to-slice` into the Python image route without calling the JavaScript project, its local API, or its Figma plugin at runtime.

**Architecture:** Add an optional Python image-slicing analysis layer that produces candidate slice assets, covered-background regions, code overlays, and provenance. Keep Grounding as the default image strategy. Feed only validated candidates into the existing PageGraph, image contract, and DesignSpec/Figma write path.

**Tech Stack:** Python 3.11, Pillow/numpy where already available, OpenAI-compatible vision client, pytest, existing image contract and Figma adapter.

**Spec:** `docs/superpowers/specs/2026-10-25-image-to-figma-mvp-design.md`

**Prerequisite:** Complete
`docs/superpowers/plans/2026-10-28-cross-project-figma-effect-benchmark.md`
with a `source-study-approved` decision before starting Task 1 of this plan.

## Global Constraints

- Use upstream commit `ecc184c982a000c815796864ecce034fc0030c31`.
- Do not add npm, Node, `sharp`, `@reflow`, or a JavaScript runtime dependency.
- Do not use the upstream Figma plugin, `.fig` exporter, local API, or HTML-to-Figma importer at runtime.
- Preserve MIT attribution for copied algorithms and comments.
- Keep Grounding as the default image strategy. New behavior is optional and disabled by default.
- Never label inpainted or generated pixels as original assets.
- Maintain `reference_only`, `generated`, `original=false`, and authority fields in the image contract.
- Do not claim hidden-region recovery is observed truth; it is a candidate reconstruction.
- Preserve the dirty worktree and stage only files named by the active task.

---

### Task 1: Freeze the upstream source and record the port boundary

**Files:**
- Create: `docs/v2_mentor/IMAGE_TO_SLICE_SOURCE_INVENTORY_2026-10-28.md`

**Interfaces:**
- Consumes: upstream source at `ecc184c982a000c815796864ecce034fc0030c31`.
- Produces: exact file map, license, port candidates, and explicit non-port list.

- [ ] **Step 1: Create the source snapshot**

```powershell
$root = Join-Path $env:TEMP 'codex-image-to-slice-study'
git clone https://github.com/50kg/image-to-slice.git $root
git -C $root checkout ecc184c982a000c815796864ecce034fc0030c31
```

Expected: checkout succeeds.

- [ ] **Step 2: Verify the source identity**

```powershell
$root = Join-Path $env:TEMP 'codex-image-to-slice-study'
git -C $root rev-parse HEAD
Get-Content -LiteralPath (Join-Path $root 'LICENSE')
```

Expected: commit `ecc184c982a000c815796864ecce034fc0030c31` and MIT license text.

- [ ] **Step 3: Write the port boundary**

Create `docs/v2_mentor/IMAGE_TO_SLICE_SOURCE_INVENTORY_2026-10-28.md` with:

```markdown
# Image To Slice Source Inventory

- Repository: https://github.com/50kg/image-to-slice
- Commit: ecc184c982a000c815796864ecce034fc0030c31
- License: MIT
- Runtime policy: port algorithms into Python; no JavaScript runtime

## Port candidates

- `src/core/slice-detection/constants.js`
- `src/core/slice-detection/prompt-builder.js`
- `src/core/slice-detection/result-parser.js`
- `src/core/slice-asset-name.js`
- `src/core/background-decomposition/constants.js`
- `src/core/background-decomposition/prompt-builder.js`
- `src/core/background-decomposition/result-parser.js`
- `src/ui/services/slice-geometry.js`
- `src/ui/services/slice-repair.js`
- `src/ui/services/editable-reference-assets.js`

## Reference only

- `server.js`
- `src/server/services/ai-inpaint.js`
- `src/server/services/fast-editable-html.js`
- `src/server/services/fast-html-sanitizer.js`
- `src/server/services/playwright-figma-capture.js`
- `src/plugin/*`
- `src/fig-export/*`
- `dist/*`

## Current Python integration points

- `src/app/services/structure/backends/grounding_vlm.py`
- `src/app/services/structure/graph.py`
- `src/app/services/structure/image_contract.py`
- `src/app/services/structure/asset_fusion.py`
- `src/app/services/structure/image_strategy.py`
- `src/app/services/rendering/figma_adapter.py`
```

- [ ] **Step 4: Verify every port-candidate file exists**

```powershell
$root = Join-Path $env:TEMP 'codex-image-to-slice-study'
@(
  'src/core/slice-detection/result-parser.js',
  'src/core/background-decomposition/result-parser.js',
  'src/ui/services/slice-geometry.js',
  'src/ui/services/slice-repair.js'
) | ForEach-Object { if (-not (Test-Path (Join-Path $root $_))) { throw $_ } }
```

Expected: no exception.

- [ ] **Step 5: Commit the inventory only**

```powershell
git add docs/v2_mentor/IMAGE_TO_SLICE_SOURCE_INVENTORY_2026-10-28.md
git commit -m "docs: record Image To Slice source boundary"
```

---

### Task 2: Port the pure candidate parsers to Python

**Files:**
- Create: `src/app/services/structure/image_slicing/__init__.py`
- Create: `src/app/services/structure/image_slicing/contracts.py`
- Create: `tests/v2/test_image_slicing_contracts.py`

**Interfaces:**
- Produces: `normalize_slice_asset_name(value, index) -> str`
- Produces: `parse_slice_assets(raw, image_width, image_height) -> dict`
- Produces: `parse_background_decomposition(raw, image_width, image_height) -> dict`

- [ ] **Step 1: Write the failing parser tests**

Create `tests/v2/test_image_slicing_contracts.py`:

```python
from src.app.services.structure.image_slicing.contracts import (
    normalize_slice_asset_name,
    parse_background_decomposition,
    parse_slice_assets,
)


def test_normalizes_semantic_asset_name():
    assert normalize_slice_asset_name(" Hero Image.PNG ", 1) == "hero_image"
    assert normalize_slice_asset_name("主图", 3) == "slice_03"


def test_slice_parser_clamps_boxes_and_drops_tiny_assets():
    raw = """{"assets":[
  {"name":"Hero Image","kind":"illustration","bbox":{"x":-5,"y":10,"width":200,"height":100},"confidence":0.9},
  {"name":"dot","kind":"icon","bbox":{"x":2,"y":2,"width":3,"height":3}}
]}"""
    parsed = parse_slice_assets(raw, 100, 80)
    assert parsed["assets"] == [{
        "name": "hero_image",
        "kind": "illustration",
        "bbox": [0, 10, 100, 70],
        "confidence": 0.9,
        "contains_embedded_text": False,
        "reason": "",
    }]


def test_background_parser_clips_overlays_to_parent_background():
    raw = """{"backgrounds":[{"id":"bg","name":"Hero Background","bbox":{"x":0,"y":0,"width":500,"height":400},"overlays":[{"id":"nav","name":"Nav","kind":"code-overlay","bbox":{"x":-20,"y":1,"width":100,"height":40}}]}]}"""
    parsed = parse_background_decomposition(raw, 320, 240)
    background = parsed["backgrounds"][0]
    assert background["bbox"] == [0, 0, 320, 240]
    assert background["overlays"][0]["bbox"] == [0, 1, 80, 40]
```

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_slicing_contracts.py -v
```

Expected: FAIL because the module does not exist.

- [ ] **Step 2: Implement source-derived constants**

Create `contracts.py` with:

```python
ALLOWED_SLICE_ASSET_KINDS = {
    "icon",
    "illustration",
    "product",
    "person",
    "texture",
    "photo",
    "logo",
    "art_text",
    "other",
}
ALLOWED_BACKGROUND_OVERLAY_KINDS = {"code-overlay", "raster-overlay"}
MIN_SLICE_ASSET_SIZE = 8
MAX_BACKGROUND_CANDIDATES = 6
MAX_BACKGROUND_OVERLAYS = 48
MIN_BACKGROUND_SIZE = 24
MIN_OVERLAY_SIZE = 4
```

- [ ] **Step 3: Implement asset naming**

Port `src/core/slice-asset-name.js`:

```python
import re
import unicodedata


def normalize_slice_asset_name(value: object, index: int = 1) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()[:64]
    return text if re.search(r"[a-z]", text) else f"slice_{index:02d}"
```

- [ ] **Step 4: Implement bbox normalization and parsers**

Use the same constraints as upstream:

- normalize x/y/width/height against original image bounds;
- round after clamping;
- negative width or height is normalized before clamping;
- drop boxes below the minimum size;
- preserve asset order;
- cap backgrounds and overlays;
- restrict allowed kinds;
- clamp overlay bbox to its parent background bbox;
- cap confidence to `[0, 1]`;
- truncate names to 120 characters and reasons to 300.

The public return shape is:

```python
{
    "assets": [
        {
            "name": str,
            "kind": str,
            "bbox": [int, int, int, int],
            "confidence": float,
            "contains_embedded_text": bool,
            "reason": str,
        }
    ]
}
```

and:

```python
{
    "backgrounds": [
        {
            "id": str,
            "name": str,
            "bbox": [int, int, int, int],
            "confidence": float,
            "reason": str,
            "baked_visuals": [str],
            "overlays": [
                {
                    "id": str,
                    "name": str,
                    "kind": str,
                    "bbox": [int, int, int, int],
                    "confidence": float,
                    "reason": str,
                }
            ],
        }
    ]
}
```

- [ ] **Step 5: Run the parser tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_slicing_contracts.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit the pure parser module**

```powershell
git add src/app/services/structure/image_slicing `
        tests/v2/test_image_slicing_contracts.py
git commit -m "feat: port image slicing candidate parsers"
```

---

### Task 3: Port prompt builders and request contracts

**Files:**
- Create: `src/app/services/structure/image_slicing/prompts.py`
- Create: `tests/v2/test_image_slicing_prompts.py`

**Interfaces:**
- Produces: `build_slice_prompt(width, height) -> str`
- Produces: `build_background_prompt(width, height) -> str`
- Produces: `build_json_repair_prompt(raw_text) -> str`

- [ ] **Step 1: Write failing prompt tests**

```python
from src.app.services.structure.image_slicing.prompts import (
    build_background_prompt,
    build_slice_prompt,
)


def test_slice_prompt_uses_original_pixel_coordinates():
    prompt = build_slice_prompt(1080, 1440)
    assert "1080x1440" in prompt
    assert "Do not return ordinary UI text" in prompt
    assert "snake_case" in prompt


def test_background_prompt_requires_code_and_raster_overlay_kinds():
    prompt = build_background_prompt(750, 1334)
    assert "code-overlay" in prompt
    assert "raster-overlay" in prompt
    assert "Each overlay bbox must intersect its parent background bbox" in prompt
```

- [ ] **Step 2: Port the prompt text**

Copy the semantic rules from upstream:

- `src/core/slice-detection/prompt-builder.js`
- `src/core/background-decomposition/prompt-builder.js`

Preserve the original pixel-coordinate instructions, ordinary-UI exclusion rules, semantic English snake_case naming, and background overlay classification.

- [ ] **Step 3: Run the tests**

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add src/app/services/structure/image_slicing/prompts.py `
        tests/v2/test_image_slicing_prompts.py
git commit -m "feat: port image slicing prompts"
```

---

### Task 4: Port the local edge-blend repair algorithm

**Files:**
- Create: `src/app/services/structure/image_slicing/repair.py`
- Create: `tests/v2/test_image_slicing_repair.py`

**Interfaces:**
- Produces: `create_edge_blend_patch(image, placement, *, band_ratio=0.12) -> PIL.Image.Image`
- Produces: `sample_placement_edges(image, placement, *, band_ratio=0.12) -> dict`

- [ ] **Step 1: Write a synthetic image test**

```python
from PIL import Image
from src.app.services.structure.image_slicing.repair import create_edge_blend_patch


def test_edge_blend_patch_preserves_size_and_neutral_color():
    image = Image.new("RGB", (100, 80), (240, 240, 240))
    patch = create_edge_blend_patch(image, {"x": 20, "y": 10, "width": 40, "height": 30})
    assert patch.size == (40, 30)
    red, green, blue = patch.getpixel((20, 15))
    assert 230 <= red <= 245
    assert 230 <= green <= 245
    assert 230 <= blue <= 245
```

- [ ] **Step 2: Port sampling and blending**

Use `PIL.Image.crop` for side samples:

- top sample extends upward by `band`;
- right sample extends right;
- bottom sample extends down;
- left sample extends left;
- sample about 160 pixels per side with a stride derived from area;
- average each side and all sides;
- blend horizontal and vertical gradients;
- center weight is clamped to at most `0.32`;
- output PNG-compatible RGB image.

Do not carry over DOM canvas or browser-specific code.

- [ ] **Step 3: Run the tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_slicing_repair.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add src/app/services/structure/image_slicing/repair.py `
        tests/v2/test_image_slicing_repair.py
git commit -m "feat: port image edge blend repair"
```

---

### Task 5: Extend PageGraph with slice and background candidates

**Files:**
- Modify: `src/app/services/structure/graph.py`
- Modify: `tests/v2/test_image_route_fallback.py`
- Create: `tests/v2/test_image_slicing_graph.py`

**Interfaces:**
- Produces: `graph["sliceAnalysis"] = {"assets": [], "backgrounds": [], "provenance": {...}}`
- Preserves: existing `containers`, `elements`, `provenance`, and route fields.

- [ ] **Step 1: Write the failing graph test**

```python
from src.app.services.structure.graph import new_graph
from src.app.services.structure.image_slicing.contracts import attach_slice_analysis


def test_slice_analysis_is_candidate_only():
    graph = new_graph("page.png", 320, 240, "grounding")
    attach_slice_analysis(
        graph,
        assets=[{"name": "hero", "kind": "illustration", "bbox": [0, 0, 40, 40]}],
        backgrounds=[],
        source="image-to-slice-port",
    )
    assert graph["sliceAnalysis"]["provenance"]["authority"] == "candidate"
    assert graph["sliceAnalysis"]["assets"][0]["original"] is False
    assert graph["sliceAnalysis"]["assets"][0]["reference_only"] is True
```

- [ ] **Step 2: Implement `attach_slice_analysis`**

Place it in `contracts.py`; normalize empty values and keep candidate provenance:

```python
def attach_slice_analysis(graph, *, assets, backgrounds, source):
    graph["sliceAnalysis"] = {
        "assets": assets,
        "backgrounds": backgrounds,
        "provenance": {
            "source": source,
            "authority": "candidate",
            "originalAssets": False,
            "hiddenRegionRecovery": "candidate-only",
            "fallbacks": [],
        },
    }
```

- [ ] **Step 3: Preserve byte-identical behavior when absent**

Add a regression assertion to `test_image_route_fallback.py` that a graph without `sliceAnalysis` serializes exactly as before.

- [ ] **Step 4: Run**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_image_route_fallback.py `
  tests/v2/test_image_slicing_graph.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/app/services/structure/graph.py `
        src/app/services/structure/image_slicing/contracts.py `
        tests/v2/test_image_route_fallback.py `
        tests/v2/test_image_slicing_graph.py
git commit -m "feat: add candidate slice analysis to PageGraph"
```

---

### Task 6: Add an optional Python image-slicing backend

**Files:**
- Create: `src/app/services/structure/backends/image_slice_vlm.py`
- Modify: `src/app/services/structure/backends/__init__.py`
- Modify: `src/app/services/structure/router.py`
- Modify: `src/config/settings.py`
- Modify: `.env.example`
- Create: `tests/v2/test_image_slice_vlm.py`

**Interfaces:**
- Produces: `ImageSliceVLM.ground(image_path, image_w, image_h) -> dict`
- Config: `IMAGE_SLICE_MODE=off|analyze`, default `off`
- Uses the existing `VISION_*` OpenAI-compatible configuration.

- [ ] **Step 1: Write the offline parser test**

```python
from src.app.services.structure.backends.image_slice_vlm import parse_image_slice_response


def test_combined_response_returns_assets_and_backgrounds():
    raw = '{"assets":[],"backgrounds":[{"id":"bg","name":"bg","bbox":{"x":0,"y":0,"width":10,"height":10}}]}'
    result = parse_image_slice_response(raw, 10, 10)
    assert len(result["backgrounds"]) == 1
    assert result["assets"] == []
```

- [ ] **Step 2: Implement the backend**

The backend must:

- use the existing OpenAI client and reliability wrapper;
- issue one structured JSON request;
- include both slice and background prompt requirements;
- parse with the ported parser;
- set `graph.provenance.strategy="image-slice-vlm"`;
- attach candidates with `attach_slice_analysis`;
- leave Grounding output untouched on parser failure and fail closed.

- [ ] **Step 3: Keep the default route unchanged**

`IMAGE_SLICE_MODE=off` must produce byte-identical image artifacts.

`IMAGE_SLICE_MODE=analyze` may add `sliceAnalysis` but must not yet rewrite elements or assets.

- [ ] **Step 4: Test routing**

Cases:

- off: no new call, no new field;
- analyze: one call, candidate field present;
- invalid JSON: route failure, no partial write;
- Grounding unavailable + analyze off: existing CV fallback remains unchanged.

- [ ] **Step 5: Run**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_image_slice_vlm.py `
  tests/v2/test_image_route_fallback.py `
  tests/v2/test_grounding_reliability.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/app/services/structure/backends/image_slice_vlm.py `
        src/app/services/structure/router.py `
        src/config/settings.py `
        .env.example `
        tests/v2/test_image_slice_vlm.py
git commit -m "feat: add optional image slicing analysis backend"
```

---

### Task 7: Map acceptable candidates into DesignSpec and asset provenance

**Files:**
- Modify: `src/app/services/structure/image_contract.py`
- Modify: `src/app/services/structure/asset_fusion.py`
- Create: `tests/v2/test_image_slicing_design_mapping.py`

- [ ] **Step 1: Write the failing mapping test**

```python
import pytest
from PIL import Image

from src.app.services.structure.image_slicing.contracts import attach_slice_analysis
from src.app.services.structure.graph import new_graph
from src.app.services.structure.image_contract import (
    build_image_design,
    inspect_image_reference,
)


@pytest.fixture
def minimal_image_reference(tmp_path):
    path = tmp_path / "fixture.png"
    Image.new("RGB", (320, 240), (240, 240, 240)).save(path)
    return inspect_image_reference(path, reference_id="fixture")


def test_background_candidate_is_not_claimed_as_original(minimal_image_reference):
    graph = new_graph(
        minimal_image_reference["input"]["path"],
        320,
        240,
        "grounding",
    )
    attach_slice_analysis(
        graph,
        assets=[],
        backgrounds=[{
            "id": "bg",
            "name": "hero_background",
            "bbox": [0, 0, 320, 240],
            "confidence": 0.8,
            "overlays": [],
        }],
        source="image-to-slice-port",
    )
    design = build_image_design(graph, minimal_image_reference)
    element = next(item for item in design["elements"] if item["id"] == "bg")
    assert element["imageMVP"]["generated"] is True
    assert element["imageMVP"]["originalAssetClaimed"] is False
    assert element["assetProvenance"]["kind"] == "inpainted-background-candidate"
```

- [ ] **Step 2: Map background candidates**

For each background candidate:

- crop the visible background region from the source screenshot;
- store the original candidate crop as `reference-only`;
- create an inpaint request candidate only when explicitly enabled;
- never replace the source crop with the regenerated background without recording both hashes;
- mark generated output `generated=true`, `original=false`.

- [ ] **Step 3: Map slice assets**

For each slice asset:

- crop exact bbox from the source screenshot;
- store source screenshot SHA-256 and payload SHA-256;
- mark `reference_only=true` and `original=false`;
- keep asset name, kind, confidence, and reason in element metadata.

- [ ] **Step 4: Map code overlays**

Add overlay bounding boxes to graph candidates:

- `code-overlay` remains a native-node candidate;
- `raster-overlay` remains a raster candidate;
- no overlay is rendered twice as both native and raster.

- [ ] **Step 5: Verify no provenance regression**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_image_slicing_design_mapping.py `
  tests/v2/test_layout_hierarchy_frames.py `
  tests/v2/test_figma_adapter_edits.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/app/services/structure/image_contract.py `
        src/app/services/structure/asset_fusion.py `
        tests/v2/test_image_slicing_design_mapping.py
git commit -m "feat: map image slicing candidates with provenance"
```

---

### Task 8: Evaluate against the current image route on a frozen holdout

**Files:**
- Create: `tests/fixtures/image_to_slice_holdout/manifest.json`
- Create: `scripts/image_to_slice_compare.py`
- Create: `tests/v2/test_image_to_slice_compare.py`
- Create: `docs/v2_mentor/IMAGE_TO_SLICE_ADOPTION_RESULT_2026-10-28.md`

- [ ] **Step 1: Freeze six image samples**

Use six unseen images:

1. ordinary form;
2. card dashboard;
3. text over photographic background;
4. product image with occluding buttons;
5. AI-generated decorative landing page;
6. dense navigation with assets and clip paths.

Record input SHA-256, dimensions, expected text regions, expected asset count, and environment.

- [ ] **Step 2: Run three strategies**

```text
grounding
grounding + IMAGE_SLICE_MODE=analyze
cv fallback
```

The comparison report must include:

- critical text recall;
- native text count;
- asset candidate precision;
- original/reference/generated provenance mismatches;
- background recovery visual delta;
- Figma readback editability;
- wall time and model calls.

- [ ] **Step 3: Fail closed on provenance**

The comparison script must fail if:

- generated pixels are marked original;
- a slice asset lacks a screenshot or payload hash;
- a hidden-region reconstruction is reported as observed;
- an overlay is counted in both native and raster denominators.

- [ ] **Step 4: Run**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_to_slice_compare.py -v
```

Expected: PASS.

- [ ] **Step 5: Write the result and stop short of a default change**

The final document must decide:

- keep as research only;
- enable `analyze` for selected complex images;
- promote to active candidate mapping.

It must not change the default Grounding route in this plan.

- [ ] **Step 6: Commit**

```powershell
git add tests/fixtures/image_to_slice_holdout `
        scripts/image_to_slice_compare.py `
        tests/v2/test_image_to_slice_compare.py `
        docs/v2_mentor/IMAGE_TO_SLICE_ADOPTION_RESULT_2026-10-28.md
git commit -m "test: evaluate Image To Slice source adoption"
```
