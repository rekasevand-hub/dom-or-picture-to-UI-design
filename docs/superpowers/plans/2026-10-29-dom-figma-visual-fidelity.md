# DOM to Figma Visual Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve TEXT construction, text layout, static layout, fonts, background images, pseudo-elements, SVG, image-fill coverage, and blank-area scoring while preserving the existing Python DOM-to-Figma architecture.

**Architecture:** Build on the P0 capture bundle and offline replay path. Normalize browser facts into a canonical text model and visual-asset ledger, improve DesignSpec construction through existing `direct_design`, `text_wrap`, `layout_infer`, and `layout_plan`, then verify the real Figma export with explicit structural and pixel metrics. No BuilderIO runtime or generic VLM geometry authority is introduced.

**Tech Stack:** Python 3.11, Playwright capture, PageGraph/DesignSpec, pytest, Pillow/NumPy, existing Figma bridge, existing browser-based SVG rasterization.

**Spec:** `docs/superpowers/plans/2026-10-29-dom-figma-capture-replay-hardening.md`, `docs/v2_mentor/OPEN_SOURCE_DOM_TO_FIGMA_NOTES_2026-10-28.md`, and the four-page BuilderIO benchmark under `output/_builderio_benchmark_20261029/`.

**Prerequisite:** Complete P0 Tasks 1-3 before production integration. P1 may be developed with fixture bundles, but default-route changes require validated P0 capture bundles.

## Global Constraints

- Do not add a JavaScript runtime or BuilderIO package dependency.
- Preserve browser-measured text lines and baselines as the highest-authority text facts.
- Do not infer static layout from a screenshot when the DOM already states `display`, flex/grid, absolute positioning, padding, or clipping.
- Every visual element must retain provenance: `dom:text`, `dom:background`, `dom:pseudo`, `dom:svg`, or `display-source-crop`.
- Do not silently replace unsupported CSS with pixels; record the unsupported property and the fallback reason.
- Fonts and SVG assets must be content-addressed and locally reproducible before Figma rendering.
- Image-fill and blank-area checks run on the real Figma export, not only on DesignSpec.
- New visual behavior must be feature-flagged until it passes the four regression pages and at least two unseen holdouts.
- Semantic navigation/card/list/button recognition is out of scope; it belongs to the P2 plan.
- Preserve old capture and DesignSpec output when the new flags are off.
- Keep the dirty worktree intact and stage only files named by the current task.

## Review Focus

- Mixed inline text with links, code, bold runs, whitespace, and CJK punctuation: one logical paragraph must not become overlapping fragments.
- Long Chinese headings and card descriptions: browser line breaks must survive Figma font substitution.
- Requested fonts absent in Figma: the renderer must choose a recorded fallback rather than silently changing family or weight.
- Background images, gradients, `::before`, and `::after`: decorative content must not disappear or become duplicated.
- Inline SVG with `<use>`, external references, or unsupported filters: safe vector materialization or an explicit raster fallback must be selected.
- A page with many image references but zero image fills: final visual scoring must fail even if text geometry looks correct.
- A mostly blank export from a content-rich source: blank-area scoring must fail independently of average pixel error.

---

## File Map

| File | Responsibility |
|---|---|
| `src/app/services/structure/text_model.py` | Canonical paragraph, line, span, and text-run model |
| `src/app/services/rendering/text_layout.py` | Deterministic text line and baseline layout over existing `text_wrap` |
| `src/app/services/structure/font_bundle.py` | Requested/resolved font manifest and local font cache |
| `src/app/services/structure/visual_assets.py` | Background, gradient, and pseudo-element materialization |
| `src/app/services/structure/svg_materialization.py` | SVG sanitization, source retention, and raster fallback |
| `src/app/services/evidence/dom_visual_quality.py` | Image-fill, blank-area, text, height, and pixel-quality metrics |
| `scripts/dom_visual_benchmark.py` | Four-page and holdout visual benchmark driver |
| `src/app/services/structure/capture.py` | Font resources, background layers, pseudo metadata, SVG source capture |
| `src/app/services/som/direct_design.py` | Consume visual assets and canonical text model |
| `src/app/services/rendering/text_wrap.py` | Delegate measurement-aware wrapping to `text_layout` |
| `src/app/services/rendering/adapter_base.py` | Render normalized line and run output |
| `src/app/services/rendering/figma_adapter.py` | Resolve fonts and expose image-fill/font readback |
| `figma_bridge/code.js` | `resolve_font` and final image-fill reporting |
| `tests/v2/test_dom_text_model.py` | Text model tests |
| `tests/v2/test_dom_text_layout.py` | Wrapping, CJK, and baseline tests |
| `tests/v2/test_dom_font_bundle.py` | Font provenance and fallback tests |
| `tests/v2/test_dom_visual_assets.py` | Background and pseudo-element tests |
| `tests/v2/test_dom_svg_materialization.py` | SVG policy tests |
| `tests/v2/test_dom_visual_quality.py` | Image-fill and blank-area tests |
| `tests/v2/test_dom_visual_benchmark.py` | Benchmark aggregation tests |

---

### Task 1: Normalize the TEXT model before DesignSpec construction

**Files:**
- Create: `src/app/services/structure/text_model.py`
- Modify: `src/app/services/structure/capture.py:794-938`
- Modify: `src/app/services/som/direct_design.py:82-205`
- Modify: `src/config/settings.py`
- Create: `tests/v2/test_dom_text_model.py`

**Interfaces:**
- Consumes: `text`, `richRuns`, `textLines`, `textBox`, `textEmBox`, `textBaseline`, `pIdx`, and typography fields from `00_dom.json`.
- Produces:
  - `build_text_model(dom_nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]`
  - schema `dom-text-model/1.0`
  - DesignSpec fields `textModelId`, `textRuns`, `measuredLines`, `paragraphRole`

- [ ] **Step 1: Write failing normalization tests**

The test fixture includes:

- one paragraph with normal text, `<strong>`, `<em>`, `<code>`, and an inline link;
- an inline `<span>` inside that paragraph;
- one button label;
- one multi-line CJK paragraph;
- one paragraph containing an inline image.

Assert:

```python
model = build_text_model(nodes)
paragraph = model["blocks"]["text-0"]
assert [run["text"] for run in paragraph["runs"]] == [
    "Before ", "bold", " ", "italic", " ", "code", " link"
]
assert paragraph["runs"][1]["style"]["fontWeight"] == "700"
assert model["inlineConsumed"] == ["1", "2", "3", "4"]
assert model["blocks"]["text-1"]["role"] == "button-label"
assert model["blocks"]["text-2"]["measuredLineCount"] >= 2
assert model["blocks"]["text-3"]["runs"][1]["kind"] == "inline-image"
```

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_dom_text_model.py -v
```

Expected: FAIL because `text_model.py` does not exist.

- [ ] **Step 2: Implement the canonical text model**

`build_text_model` must:

- keep one logical block for mixed inline runs;
- mark inline children consumed so they do not emit overlapping TEXT layers;
- preserve whitespace between runs exactly;
- distinguish `paragraph`, `heading`, `button-label`, `input-value`, `list-marker`, and `caption`;
- retain browser measured lines and baselines;
- represent inline images as run boundaries rather than deleting surrounding text.

The model stores source DOM indices and source fields for every decision.

- [ ] **Step 3: Add capture fields needed by the model**

In `DOM_JS`, add only non-default fields:

```text
textRoleHint: heading | button-label | input-value | list-marker | caption
listMarker: { type: unordered | ordered, level: int }
inlineImageBoundary: true
```

Use semantic tag/role and ancestor context. Do not infer a heading from font size alone.

- [ ] **Step 4: Integrate behind `dom_text_model_v2`**

Add setting `dom_text_model_v2`, env `DOM_TEXT_MODEL_V2`, default `false`.

When enabled, `build_direct_design` consumes `build_text_model(dom_nodes)` and
emits one logical text element per block. When disabled, preserve the current
text assembly byte-for-byte.

- [ ] **Step 5: Run text-model and existing text tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_dom_text_model.py `
  tests/v2/test_dom_rich_text_runs.py `
  tests/v2/test_dom_text_bounds.py `
  tests/v2/test_dom_control_text_anchor.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit the text model**

```powershell
git add src/app/services/structure/text_model.py `
        src/app/services/structure/capture.py `
        src/app/services/som/direct_design.py `
        src/config/settings.py `
        tests/v2/test_dom_text_model.py
git commit -m "feat: normalize DOM text into a canonical model"
```

---

### Task 2: Make text layout use browser measurements first

**Files:**
- Create: `src/app/services/rendering/text_layout.py`
- Modify: `src/app/services/rendering/text_wrap.py`
- Modify: `src/app/services/rendering/adapter_base.py`
- Modify: `src/app/services/rendering/figma_adapter.py`
- Create: `tests/v2/test_dom_text_layout.py`

**Interfaces:**
- Consumes: canonical text model, `textLines`, `textBaseline`, font metrics, alignment, letter spacing, line height, and container width.
- Produces:
  - `layout_text(spec: Mapping[str, Any], *, measured_lines: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]`
  - keys `lines`, `lineBoxes`, `lineHeight`, `textAlign`, `source`, `baselineSource`

- [ ] **Step 1: Write failing layout tests**

Tests must cover:

```python
def test_browser_lines_win_over_estimated_wrap():
    result = layout_text(
        {"text": "中文，句子。以及EnglishMixedText", "width": 180, "fontSize": 18},
        measured_lines=[{"text": "中文，句子。", "box": [0, 0, 120, 26]}],
    )
    assert result["source"] == "browser-range"
    assert result["lines"] == ["中文，句子。"]


def test_cjk_and_ascii_share_original_line_break():
    result = layout_text(
        {"text": "小米 HyperOS 4", "width": 130, "fontSize": 20},
        measured_lines=[
            {"text": "小米", "box": [0, 0, 40, 28]},
            {"text": "HyperOS 4", "box": [0, 28, 110, 28]},
        ],
    )
    assert result["lines"] == ["小米", "HyperOS 4"]
    assert result["baselineSource"] == "browser-measured"
```

Also assert that an estimate fallback is explicitly marked
`source="estimated"` and its confidence is lower.

- [ ] **Step 2: Implement the measurement-first layout**

`layout_text` order of authority:

1. browser range lines;
2. browser `textEmBox` plus measured first-line baseline;
3. existing `text_wrap.wrap_for_spec`;
4. character width estimate.

Do not rewrap measured lines. Preserve trailing punctuation and inline-run
boundaries when a line can be mapped safely.

- [ ] **Step 3: Adapt existing renderers**

`adapter_base` passes canonical line boxes to both SVG and Figma adapters.
`figma_adapter._text_render_spec` uses the same first-line baseline and does not
apply a second vertical offset when `baselineSource="browser-measured"`.

- [ ] **Step 4: Add a mixed-run Figma fixture**

Render a paragraph with bold, italic, monospace, link, and CJK text. Verify:

- run order and text are unchanged;
- every line has one owning text node;
- no child run is emitted as an independent overlapping layer;
- bold/italic/monospace properties survive readback where available.

- [ ] **Step 5: Run text-layout regressions**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_dom_text_layout.py `
  tests/v2/test_p1_dom_text_geometry.py `
  tests/v2/test_dom_control_text_anchor.py `
  tests/v2/test_p1_border_style.py `
  tests/v2/test_p1_figma_acceptance.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit measurement-first text layout**

```powershell
git add src/app/services/rendering/text_layout.py `
        src/app/services/rendering/text_wrap.py `
        src/app/services/rendering/adapter_base.py `
        src/app/services/rendering/figma_adapter.py `
        tests/v2/test_dom_text_layout.py
git commit -m "feat: preserve browser text layout in renderers"
```

---

### Task 3: Add a local font manifest and Figma font-resolution handshake

**Files:**
- Create: `src/app/services/structure/font_bundle.py`
- Modify: `src/app/services/structure/capture.py:178-215`
- Modify: `src/app/services/rendering/figma_adapter.py:709-850`
- Modify: `figma_bridge/code.js:140-162`
- Create: `tests/v2/test_dom_font_bundle.py`

**Interfaces:**
- Consumes: `document.fonts`, loaded font resource URLs, platform font probes, and text-node font fields.
- Produces:
  - `build_font_manifest(font_resources: Sequence[Mapping[str, Any]], nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]`
  - `00_fonts.json`
  - bridge action `resolve_font`
  - adapter method `resolve_font(self, family: str, style: str, weight: str | int) -> dict[str, Any]`

- [ ] **Step 1: Write failing font-manifest tests**

Assert:

```python
manifest = build_font_manifest(resources, nodes)
assert manifest["schema_version"] == "dom-font-bundle/1.0"
assert manifest["faces"][0]["family"] == "Example Sans"
assert manifest["faces"][0]["source_url"].endswith(".woff2")
assert manifest["nodes"]["n4"]["requestedFamily"] == "sans-serif"
assert manifest["nodes"]["n4"]["resolvedFamily"] == "Microsoft YaHei"
assert manifest["nodes"]["n4"]["resolution"] == "browser-platform-font"
assert manifest["unresolved"] == []
```

Add a case where generic font evidence is ambiguous and
`resolution="ambiguous-platform-font"`.

- [ ] **Step 2: Capture font resources and faces**

Extend browser capture to record:

```text
document.fonts face family/style/weight/status
font resource URL
transfer size when exposed
initiator and resource timing when available
```

Do not access cross-origin CSS rules directly. Use `document.fonts`,
Performance Resource Timing, and the network layer as independent evidence.

- [ ] **Step 3: Materialize verified font bytes**

For each remote font URL:

- use the P0 asset transport;
- retain SHA-256 and MIME;
- reject HTML/error responses;
- mark unverified fonts `reference-only`;
- never claim that a requested font is the actual rendered glyph face without
  platform-font evidence.

Write `00_fonts.json` and add it to the bundle artifact table.

- [ ] **Step 4: Implement the Figma font handshake**

Add a bridge action that accepts requested family, style, and weight and returns:

```json
{
  "requested": {"family": "...", "style": "Regular", "weight": 400},
  "selected": {"family": "...", "style": "Regular"},
  "status": "exact",
  "candidateCount": 1
}
```

Statuses are `exact`, `family-fallback`, `style-fallback`, and `blocked`.
The adapter records the selected font on each TEXT spec before creation.

- [ ] **Step 5: Add a fallback fixture**

Request an unavailable family and assert:

- the returned status is `family-fallback`;
- the fallback is deterministic from the manifest order;
- the DesignSpec/readback retains requested and selected families separately;
- no weight/style mismatch is hidden.

- [ ] **Step 6: Run font tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_dom_font_bundle.py `
  tests/v2/test_p1_font_provenance.py `
  tests/v2/test_figma_bridge_text_metrics.py `
  tests/v2/test_p1_figma_acceptance.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit font bundling**

```powershell
git add src/app/services/structure/font_bundle.py `
        src/app/services/structure/capture.py `
        src/app/services/rendering/figma_adapter.py `
        figma_bridge/code.js `
        tests/v2/test_dom_font_bundle.py
git commit -m "feat: add local font bundles and Figma font resolution"
```

---

### Task 4: Materialize background layers and pseudo-elements

**Files:**
- Create: `src/app/services/structure/visual_assets.py`
- Modify: `src/app/services/structure/capture.py:671-728`
- Modify: `src/app/services/som/direct_design.py:630-1118`
- Create: `tests/v2/test_dom_visual_assets.py`

**Interfaces:**
- Consumes: `backgroundLayers`, `pseudoBefore`, `pseudoAfter`, local asset paths, and element boxes.
- Produces:
  - `build_visual_assets(dom_nodes: Sequence[Mapping[str, Any]], asset_manifest: Mapping[str, Any]) -> dict[str, Any]`
  - DesignSpec elements for images, gradients, pseudo text, or pixel fallback
  - `visualAssetId` and `visualFallbackReason` provenance fields

- [ ] **Step 1: Write failing background and pseudo tests**

Fixture cases:

- one `background-image: url(...)`;
- one two-color linear gradient;
- one `::before` bullet;
- one `::after` search icon;
- one background image on a node that also has text.

Assert:

```python
assets = build_visual_assets(nodes, manifest)
assert assets["byDom"][0]["kind"] == "background-image"
assert assets["byDom"][0]["displayMode"] == "image-fill"
assert assets["byDom"][1]["gradient"]["stops"] == ["#ffffff", "#112233"]
assert assets["byDom"][2]["pseudo"] == "before"
assert assets["byDom"][2]["kind"] == "text"
assert assets["byDom"][3]["kind"] == "mask"
assert assets["byDom"][4]["displayMode"] == "source-crop"
```

- [ ] **Step 2: Capture structured background layers**

Replace boolean-only background-image capture with a bounded list:

```json
{
  "kind": "image",
  "source": "https://...",
  "size": "cover",
  "position": "50% 50%",
  "repeat": "no-repeat"
}
```

Emit `kind="gradient"` with parsed stops for simple linear/radial gradients.
If parsing fails, record the full CSS value and select screenshot-crop fallback.

- [ ] **Step 3: Capture pseudo-element metadata and geometry policy**

Record pseudo content and styles from P0. Add a box only when it can be measured
without inventing geometry:

- CSS mask/chrome rendering may supply a measured browser rect;
- otherwise use the owning element box as an explicit approximation and mark
  `geometrySource="owning-element-approximation"`.

Do not silently treat an unmeasured icon as a centered full-size text node.

- [ ] **Step 4: Materialize supported visuals**

In `build_direct_design`:

- verified background images become `type="image"` with image fill;
- simple gradients become rectangles or Figma gradient fills;
- text pseudo-elements become `type="text"` with `source="dom:pseudo"`;
- unsupported visuals become screenshot crops marked `display-source-crop`;
- `zIndex` and paint order stay anchored to the originating DOM node.

- [ ] **Step 5: Add a real Figma image-fill test**

Verify that background image and pseudo icon elements produce nonzero image
fills or native pseudo text in readback. Reject the implementation if all
visuals degrade to source crops without a recorded reason.

- [ ] **Step 6: Run visual-asset tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_dom_visual_assets.py `
  tests/v2/test_dom_asset_quality.py `
  tests/v2/test_dom_figma_acceptance.py `
  tests/v2/test_generated_icon_recovery.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit visual assets**

```powershell
git add src/app/services/structure/visual_assets.py `
        src/app/services/structure/capture.py `
        src/app/services/som/direct_design.py `
        tests/v2/test_dom_visual_assets.py
git commit -m "feat: materialize DOM backgrounds and pseudo-elements"
```

---

### Task 5: Add a deterministic SVG materialization policy

**Files:**
- Create: `src/app/services/structure/svg_materialization.py`
- Modify: `src/app/services/structure/asset_metadata.py`
- Modify: `src/app/services/som/direct_design.py`
- Create: `tests/v2/test_dom_svg_materialization.py`

**Interfaces:**
- Consumes: inline SVG source, data URI SVG, remote SVG bytes, `<use>`, `viewBox`, and external references.
- Produces:
  - `classify_svg_source(svg_bytes: bytes, *, page_url: str) -> dict[str, Any]`
  - `materialize_svg_assets(dom_nodes: Sequence[Mapping[str, Any]], output_dir: Path) -> dict[str, Any]`
  - retained original SVG plus PNG display payload

- [ ] **Step 1: Write failing SVG policy tests**

Assert the exact classifications:

```python
assert classify_svg_source(simple_path_svg, page_url=page) ["mode"] == "vector-preferred"
assert classify_svg_source(internal_symbol_use_svg, page_url=page)["mode"] == "sanitized-vector"
assert classify_svg_source(external_image_svg, page_url=page)["mode"] == "raster-required"
assert classify_svg_source(script_svg, page_url=page)["mode"] == "blocked"
```

Add a `viewBox` with no width/height and assert natural size comes from the box
or owning DOM element.

- [ ] **Step 2: Implement sanitization and classification**

The sanitizer must:

- parse XML with a bounded size limit;
- remove scripts, event handlers, external `<image>`, external `<use>`, and
  unsafe CSS URLs;
- resolve same-document `<use href="#id">`;
- preserve `viewBox`, paths, fills, strokes, gradients, clip paths, and masks
  that do not depend on external resources;
- return deterministic SHA-256 for the original and sanitized forms.

- [ ] **Step 3: Materialize the Figma display payload**

Figma receives an honest display payload:

- retain original/sanitized SVG in `assets/<sha256>.svg`;
- when Figma cannot reliably create an SVG image directly, rasterize the
  sanitized SVG with `src.app.utils.svg_raster.rasterize_svg`;
- retain `assets/<png-sha256>.png` and point `imageBase64` at that PNG;
- record `originalVectorPath`, `displayPayloadPath`, and
  `displayMode="svg-rasterized"`.

Never label the PNG as the original SVG identity.

- [ ] **Step 4: Integrate with DesignSpec**

Inline `<svg>` and SVG assets use the same materialization result.
Complex SVG that cannot be sanitized safely uses the screenshot crop and sets
`visualFallbackReason`.

- [ ] **Step 5: Run SVG and image tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_dom_svg_materialization.py `
  tests/v2/test_p1_asset_metadata.py `
  tests/v2/test_capture_browser_engine.py `
  tests/v2/test_dom_figma_acceptance.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit SVG materialization**

```powershell
git add src/app/services/structure/svg_materialization.py `
        src/app/services/structure/asset_metadata.py `
        src/app/services/som/direct_design.py `
        tests/v2/test_dom_svg_materialization.py
git commit -m "feat: materialize safe SVG display assets"
```

---

### Task 6: Score real Figma exports for image fill, blank area, text, and height

**Files:**
- Create: `src/app/services/evidence/dom_visual_quality.py`
- Create: `scripts/dom_visual_benchmark.py`
- Modify: `src/app/services/rendering/figma_adapter.py:826-850`
- Create: `tests/v2/test_dom_visual_quality.py`
- Create: `tests/v2/test_dom_visual_benchmark.py`

**Interfaces:**
- Consumes: source screenshot, real Figma export PNG, DesignSpec, readback tree, and asset/font manifests.
- Produces:
  - `evaluate_dom_visual_quality(reference_png: Path, rendered_png: Path, design: Mapping[str, Any], readback: Mapping[str, Any]) -> dict[str, Any]`
  - `visual-quality.json`
  - metrics `image_fill_rate`, `blank_area_ratio`, `content_coverage_delta`, `height_drift_px`, `text_box_error`, `bad_pixel_ratio`

- [ ] **Step 1: Write failing metric tests**

Use synthetic images for:

- source with 30% content and render almost blank;
- source with images and readback with zero image fills;
- matching content with small antialiasing differences;
- rendered height differing by more than 5%.

Assert:

```python
assert blank["checks"]["blank_area"]["status"] == "fail"
assert image_loss["metrics"]["image_fill_rate"] == 0.0
assert image_loss["checks"]["image_fill"]["status"] == "fail"
assert matching["checks"]["visual_diff"]["status"] == "pass"
assert height_drift["checks"]["height"]["status"] == "warn"
```

- [ ] **Step 2: Implement deterministic visual metrics**

Blank/content coverage:

- estimate the source background color from edge-pixel mode;
- mark a pixel as content when any RGB channel differs by at least 10;
- `content_coverage = content_pixels / total_pixels`;
- `blank_area_ratio = 1 - render_content_coverage`;
- fail when source coverage is at least 10% and rendered coverage is below
  25% of source coverage.

Image fill rate:

- count expected visual image/background elements from DesignSpec;
- count matching image fills from Figma readback;
- `image_fill_rate = matched / expected`;
- fail when expected is nonzero and rate is zero; warn below 50%.

Height and pixel metrics reuse the existing image size and pixel comparison
utilities rather than introducing a second diff implementation.

- [ ] **Step 3: Add final Figma readback**

After rendering and exporting the Figma frame, call:

```python
readback = adapter._send("get_node_tree", {"nodeId": frame_id, "depth": 20})
image_report = adapter.image_fill_report(frame_id)
visual = evaluate_dom_visual_quality(
    reference_png,
    rendered_png,
    design,
    {**readback, "imageFillReport": image_report},
)
```

Persist `visual-quality.json` beside the export.

- [ ] **Step 4: Implement the benchmark driver**

`scripts/dom_visual_benchmark.py` accepts:

```text
--case name=bundle-dir=figma-export-dir
--thresholds tests/fixtures/dom_visual_quality/thresholds.json
--out output/_dom_visual_benchmark/result.json
```

It emits per-page and aggregate metrics with no composite score that can hide a
failed dimension.

- [ ] **Step 5: Run visual-quality tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_dom_visual_quality.py `
  tests/v2/test_dom_visual_benchmark.py `
  tests/v2/test_p1_canonical_output_fidelity.py `
  tests/v2/test_dom_figma_acceptance.py -v
```

Expected: all pass.

- [ ] **Step 6: Run the four regression pages and two unseen holdouts**

Run the benchmark on frozen captures for:

```text
IT之家
21ic
国家数据
小米
```

Then run two unseen pages. A default-enable proposal is accepted only when:

- no page regresses in text coverage or image-fill count;
- country-data-style blank exports are marked fail;
- Xiaomi-style redirects are caught by P0 before visual scoring;
- 21ic and IT之家 bad-pixel ratio does not increase.

- [ ] **Step 7: Commit visual metrics**

```powershell
git add src/app/services/evidence/dom_visual_quality.py `
        scripts/dom_visual_benchmark.py `
        src/app/services/rendering/figma_adapter.py `
        tests/v2/test_dom_visual_quality.py `
        tests/v2/test_dom_visual_benchmark.py
git commit -m "feat: score real DOM to Figma visual exports"
```
