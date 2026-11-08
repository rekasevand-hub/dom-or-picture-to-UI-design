# DOM to Figma Capture and Replay Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing browser capture into a versioned, replayable DOM capture bundle with cached assets and measurable route-quality gates, without adding a BuilderIO or JavaScript runtime dependency.

**Architecture:** Preserve the current pipeline `Playwright capture -> 00_dom.json -> PageGraph -> DesignSpec -> Figma`. Add a canonical bundle manifest around the existing artifacts, a hierarchy/layer-tree view over the flat DOM table, an offline replay path that never opens a browser, a local asset materialization step before Figma, and a four-page quality gate that detects redirect, image-loss, clipping, and blank-import failures.

**Tech Stack:** Python 3.11, Playwright, pytest, existing PageGraph/DesignSpec/Figma bridge modules, Pillow, JSON Schema-compatible dictionaries.

**Spec:** `HANDOFF_2026-10-27_dom_figma_crosssite_holdout.md`, `docs/v2_mentor/OPEN_SOURCE_DOM_TO_FIGMA_NOTES_2026-10-28.md`, and the 2026-10-29 BuilderIO four-page benchmark under `output/_builderio_benchmark_20261029/`.

## Scope Boundary

This is the P0 infrastructure plan only.

- It owns capture serialization, hashes, hierarchy, offline replay, local assets, redirect checks, and basic image-reference checks.
- It does not own detailed text layout parity, font bundling, pseudo-element materialization, background-image fidelity, SVG policy, final Figma blank-area scoring, or semantic component recognition.
- Visual fidelity work is defined in `docs/superpowers/plans/2026-10-29-dom-figma-visual-fidelity.md`.
- Semantic navigation/card/list/button recognition is defined in `docs/superpowers/plans/2026-10-29-dom-figma-semantic-components.md`.
- P0 may expose fields consumed by P1/P2, but it must not promote inferred semantics or claim final visual fidelity.

## Global Constraints

- Do not add `@builder.io/html-to-figma`, npm, Node, or a JavaScript subprocess to the production path.
- Treat `00_dom.json` as the browser-observed node table, not as a second renderer-specific design format.
- Every capture bundle must include `schema_version`, requested URL, final URL, viewport, DPR, canvas size, artifact hashes, and capture warnings.
- Never persist cookies, authorization headers, storage-state contents, passwords, or tokens in a capture bundle.
- Capture time and environment facts may be recorded, but replay must not depend on network access or wall-clock time.
- Old capture directories without the new manifest must continue through the current code path unchanged.
- New behavior must be feature-flagged until the four-page regression and a fresh unseen holdout show no regression.
- Remote images are references until verified bytes are materialized locally; unresolved images must be reported as `reference-only`, not silently treated as rendered originals.
- `requested_route=dom`, `effective_route=dom`, and no automatic fallback apply to DOM reproducibility tests.
- Keep the dirty worktree intact and stage only files named by the task being executed.

## Review Focus

- A page redirects to a different regional or support domain: capture completes but the wrong page is rendered.
- The DOM has image references but the DesignSpec or Figma readback has no image fills: report a route-quality failure.
- A wrapper frame clips or hides nested content: replay must preserve clipping facts and expose a height/coverage warning.
- A capture artifact is missing or modified after capture: bundle loading must fail closed instead of rendering partial evidence.
- Old capture directories are replayed: existing behavior must remain byte-compatible unless the new opt-in path is selected.

---

## File Map

| File | Responsibility |
|---|---|
| `src/app/services/structure/capture_bundle.py` | Build, write, load, validate, and hash `00_capture_bundle.json` |
| `src/app/services/structure/layer_tree.py` | Convert the flat `00_dom.json` table into a canonical hierarchy |
| `src/app/services/structure/capture_replay.py` | Rebuild PageGraph and DesignSpec from a saved bundle with no browser |
| `scripts/replay_dom_capture.py` | CLI entry point for offline replay |
| `src/app/services/structure/capture_asset_ledger.py` | Normalize existing asset records into `00_assets.json` |
| `src/app/services/evidence/dom_route_quality.py` | Evaluate redirect, empty-image, coverage, and geometry risks |
| `scripts/benchmark_dom_route.py` | Run frozen-page replay and aggregate quality metrics |
| `src/app/services/structure/capture.py` | Emit the bundle, layer tree, style snapshot, and asset ledger |
| `src/app/agents/precise_agent.py` | Invoke asset recovery and route-quality checks in the normal DOM flow |
| `tests/v2/test_capture_bundle.py` | Manifest/hash/schema tests |
| `tests/v2/test_dom_layer_tree.py` | Hierarchy reconstruction tests |
| `tests/v2/test_dom_capture_style_snapshot.py` | Browser style and pseudo-element extraction tests |
| `tests/v2/test_capture_replay.py` | Offline replay tests with capture disabled |
| `tests/v2/test_dom_route_quality.py` | Redirect and image-loss quality-gate tests |
| `tests/v2/test_dom_route_benchmark.py` | Four-page aggregation tests |

## Execution Order and Exit Criteria

- `P0`: Tasks 1-3 establish the immutable capture package and browser-free replay.
- `P1`: Tasks 4-5 make local assets and route failures visible before Figma rendering.
- `P2`: Task 6 freezes the four regression pages and records the adoption decision.
- A task is not complete unless its focused tests pass and old captures without the new artifacts still pass the existing regression tests.
- The plan is not complete unless replaying one bundle twice produces identical PageGraph and DesignSpec hashes with browser and network calls disabled.

---

### Task 1: Add a versioned capture bundle manifest

**Files:**
- Create: `src/app/services/structure/capture_bundle.py`
- Modify: `src/app/services/structure/capture.py:2055-2383`
- Create: `tests/v2/test_capture_bundle.py`

**Interfaces:**
- Consumes: existing paths for `00_screenshot.png`, `00_dom.json`, `00_page_state.json`, diagnostics, and M0 artifacts.
- Produces:
  - `CAPTURE_BUNDLE_SCHEMA_VERSION = "dom-capture-bundle/1.0"`
  - `write_capture_bundle(output_dir: Path, *, requested_url: str, page_state: Mapping[str, Any], artifact_paths: Mapping[str, str | Path | None]) -> dict[str, Any]`
  - `load_capture_bundle(output_dir: Path) -> dict[str, Any]`

- [ ] **Step 1: Write the failing manifest tests**

Create `tests/v2/test_capture_bundle.py` with tests that:

```python
def test_bundle_hashes_existing_artifacts_without_storage_state(tmp_path):
    manifest = write_capture_bundle(
        tmp_path,
        requested_url="https://example.test/start",
        page_state={
            "final_url": "https://example.test/final",
            "kind": "content",
            "screenshot_only": False,
        },
        artifact_paths={
            "screenshot": tmp_path / "00_screenshot.png",
            "dom": tmp_path / "00_dom.json",
            "page_state": tmp_path / "00_page_state.json",
        },
    )
    assert manifest["schema_version"] == CAPTURE_BUNDLE_SCHEMA_VERSION
    assert manifest["requested_url"] == "https://example.test/start"
    assert manifest["final_url"] == "https://example.test/final"
    assert manifest["artifacts"]["dom"]["sha256"] == sha256_file("00_dom.json")
    assert "storage_state" not in json.dumps(manifest).lower()


def test_load_bundle_rejects_missing_or_mutated_artifact(tmp_path):
    write_complete_fixture_bundle(tmp_path)
    (tmp_path / "00_dom.json").write_text("[]", encoding="utf-8")
    with pytest.raises(CaptureBundleError, match="sha256 mismatch"):
        load_capture_bundle(tmp_path)
```

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_capture_bundle.py -v
```

Expected: FAIL because `capture_bundle.py` does not exist.

- [ ] **Step 2: Implement the bundle schema and hashing**

`write_capture_bundle` writes `00_capture_bundle.json` and includes:

```json
{
  "schema_version": "dom-capture-bundle/1.0",
  "requested_url": "...",
  "final_url": "...",
  "page_state": {"kind": "content", "screenshot_only": false},
  "capture": {
    "viewport": {"width": 1440, "height": 900},
    "device_scale_factor": 1,
    "canvas_size": [1440, 900]
  },
  "artifacts": {
    "screenshot": {"path": "00_screenshot.png", "bytes": 0, "sha256": "..."},
    "dom": {"path": "00_dom.json", "bytes": 0, "sha256": "..."},
    "page_state": {"path": "00_page_state.json", "bytes": 0, "sha256": "..."}
  },
  "warnings": []
}
```

Artifact paths must be relative to the bundle directory. `load_capture_bundle`
must reject unsupported schema versions, missing required fields, traversal
paths, missing artifacts, and SHA-256 mismatches.

- [ ] **Step 3: Integrate manifest writing into both capture entry points**

After `_promote_attempt(...)` and final `page_state` construction, call
`write_capture_bundle(...)` in both `capture_page` and
`capture_page_with_fallback`. Add the returned manifest to the result under
`result["capture_bundle"]`.

- [ ] **Step 4: Run bundle and capture tests**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_capture_bundle.py `
  tests/v2/test_capture_browser_engine.py `
  tests/v2/test_p1_capture_state.py -v
```

Expected: all pass, and existing capture artifact names remain unchanged.

- [ ] **Step 5: Commit the bundle layer**

```powershell
git add src/app/services/structure/capture_bundle.py `
        src/app/services/structure/capture.py `
        tests/v2/test_capture_bundle.py
git commit -m "feat: add versioned DOM capture bundle"
```

---

### Task 2: Persist a canonical layer tree and richer style snapshot

**Files:**
- Create: `src/app/services/structure/layer_tree.py`
- Modify: `src/app/services/structure/capture.py:794-965`
- Create: `tests/v2/test_dom_layer_tree.py`
- Create: `tests/v2/test_dom_capture_style_snapshot.py`

**Interfaces:**
- Consumes: flat DOM records with `pIdx` and existing computed-style fields.
- Produces:
  - `build_layer_tree(nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]`
  - `00_layer_tree.json` with schema `dom-layer-tree/1.0`
  - optional DOM record field `styleSnapshot`
  - optional DOM record fields `pseudoBefore` and `pseudoAfter`

- [ ] **Step 1: Write the failing hierarchy tests**

Test that `build_layer_tree`:

- assigns stable IDs `n0`, `n1`, ... by source index;
- maps child `pIdx` values to parent node IDs;
- keeps roots separate;
- preserves source order;
- does not duplicate the full node payload.

```python
def test_build_layer_tree_preserves_parent_child_order():
    tree = build_layer_tree(
        [
            {"tag": "body", "x": 0, "y": 0, "w": 100, "h": 100},
            {"tag": "div", "pIdx": 0, "x": 0, "y": 0, "w": 100, "h": 40},
            {"tag": "span", "pIdx": 1, "x": 4, "y": 4, "w": 30, "h": 20},
        ]
    )
    assert tree["roots"] == ["n0"]
    assert tree["nodes"]["n0"]["children"] == ["n1"]
    assert tree["nodes"]["n1"]["children"] == ["n2"]
    assert tree["nodes"]["n2"]["sourceIndex"] == 2
```

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_dom_layer_tree.py -v
```

Expected: FAIL because `layer_tree.py` does not exist.

- [ ] **Step 2: Implement and persist the layer tree**

Write `00_layer_tree.json` immediately after `00_dom.json` is promoted. The
tree stores only hierarchy metadata and a compact node summary:

```json
{
  "schema_version": "dom-layer-tree/1.0",
  "roots": ["n0"],
  "nodes": {
    "n0": {
      "sourceIndex": 0,
      "parentId": null,
      "children": ["n1"],
      "tag": "body",
      "bbox": [0, 0, 1440, 900]
    }
  }
}
```

Add `layer_tree` to the capture-bundle artifact entries.

- [ ] **Step 3: Write the failing style-snapshot test**

Create `tests/v2/test_dom_capture_style_snapshot.py` with a Playwright fixture
containing flex, grid, transforms, CSS variables, `::before`, and `::after`.
Assert:

```python
flex = next(node for node in nodes if node.get("id") == "flex")
assert flex["styleSnapshot"]["display"] == "flex"
assert flex["styleSnapshot"]["justifyContent"] == "space-between"
assert grid["styleSnapshot"]["gridTemplateColumns"]
assert moved["styleSnapshot"]["transform"] != "none"
assert custom["styleSnapshot"]["customProperties"]["--brand"] == "#112233"
assert pseudo["pseudoBefore"]["content"] == '"•"'
assert pseudo["pseudoBefore"]["position"] == "absolute"
```

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_dom_capture_style_snapshot.py -v
```

Expected: FAIL because `styleSnapshot` and pseudo fields are absent.

- [ ] **Step 4: Extend `DOM_JS` with the stable style snapshot**

Add `styleSnapshot` to every visible captured node with this fixed subset:

```text
display, position, inset (top/right/bottom/left), visibility, direction,
flexDirection, flexWrap, justifyContent, alignItems, alignSelf,
rowGap, columnGap, gridTemplateColumns, gridTemplateRows,
transform, transformOrigin, textDecorationLine
```

Only include layout-only defaults when they are needed to interpret the node.
Always include non-default `transform`, non-`normal` flex/grid values, and
non-empty CSS custom properties.

Capture pseudo metadata when `content` is not `none` or `normal`:

```text
content, display, position, color, backgroundColor, font,
width, height, transform, zIndex
```

Do not claim pseudo-element pixel geometry unless it was measured.

- [ ] **Step 5: Run the focused capture tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_dom_layer_tree.py `
  tests/v2/test_dom_capture_style_snapshot.py `
  tests/v2/test_dom_rich_text_runs.py `
  tests/v2/test_capture_browser_engine.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit the capture-tree enhancements**

```powershell
git add src/app/services/structure/layer_tree.py `
        src/app/services/structure/capture.py `
        tests/v2/test_dom_layer_tree.py `
        tests/v2/test_dom_capture_style_snapshot.py
git commit -m "feat: capture canonical DOM layer trees and style snapshots"
```

---

### Task 3: Add browser-free capture replay

**Files:**
- Create: `src/app/services/structure/capture_replay.py`
- Create: `scripts/replay_dom_capture.py`
- Modify: `src/app/services/structure/capture_bundle.py`
- Create: `tests/v2/test_capture_replay.py`

**Interfaces:**
- Consumes: a validated `00_capture_bundle.json`, `00_dom.json`, and `00_screenshot.png`.
- Produces:
  - `replay_capture_bundle(bundle_dir: str | Path, output_dir: str | Path, *, build_design: bool = True) -> dict[str, Any]`
  - replay artifacts `10_pagegraph.json`, `11_som.json`, `replay_manifest.json`, and optional `12_design.json`.

- [ ] **Step 1: Write the failing no-browser replay test**

The test copies a fixture bundle, patches
`src.app.services.structure.capture.capture_page_with_fallback` to raise if
called, runs replay twice, and asserts:

```python
first = replay_capture_bundle(bundle_dir, first_out)
second = replay_capture_bundle(bundle_dir, second_out)
assert first["pagegraph_sha256"] == second["pagegraph_sha256"]
assert first["design_sha256"] == second["design_sha256"]
assert first["network_used"] is False
assert first["browser_used"] is False
```

Also assert that a mutated DOM artifact is rejected through
`load_capture_bundle`.

- [ ] **Step 2: Implement replay from existing components**

Reuse `DomProvider`, `assign_ids`, `assign_parent_depth`,
`annotate_som`, and `build_direct_design`; do not create a second renderer.

The replay output directory must use ASCII-safe artifact names and preserve
the same `schema_version`, source hashes, route, URL, viewport, and warnings in
replay metadata.

- [ ] **Step 3: Add the replay CLI**

`scripts/replay_dom_capture.py` accepts:

```text
--bundle <capture-directory>
--output-dir <replay-directory>
--no-design
```

It exits nonzero on missing artifacts, hash mismatch, unsupported schema,
provider failure, or nondeterministic replay.

- [ ] **Step 4: Run replay and regression tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_capture_replay.py `
  tests/v2/test_capture_bundle.py `
  tests/v2/test_dom_text_bounds.py `
  tests/v2/test_layout_hierarchy_frames.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit offline replay**

```powershell
git add src/app/services/structure/capture_replay.py `
        src/app/services/structure/capture_bundle.py `
        scripts/replay_dom_capture.py `
        tests/v2/test_capture_replay.py
git commit -m "feat: replay DOM captures without a browser"
```

---

### Task 4: Materialize image assets before Figma rendering

**Files:**
- Create: `src/app/services/structure/capture_asset_ledger.py`
- Modify: `src/app/services/structure/capture_bundle.py`
- Modify: `src/app/agents/precise_agent.py:825-883`
- Modify: `src/config/settings.py`
- Create: `tests/v2/test_capture_asset_ledger.py`
- Create: `tests/v2/test_dom_normal_asset_recovery.py`

**Interfaces:**
- Consumes: `design["elements"]` with `assetIdentity`, plus existing `recover_network_assets(...)`.
- Produces:
  - `build_asset_ledger(design: Mapping[str, Any]) -> dict[str, Any]`
  - `update_capture_bundle_assets(output_dir: Path, *, asset_manifest: str, asset_counts: Mapping[str, Any]) -> dict[str, Any]`
  - `00_assets.json`
  - `write_capture_bundle(..., asset_manifest=...)` updated with asset counts and hashes
  - setting `dom_network_asset_recovery`, env `DOM_NETWORK_ASSET_RECOVERY`, default `false`.

- [ ] **Step 1: Write failing asset-ledger tests**

Test that the ledger distinguishes:

- verified local bytes;
- reference-only remote URLs;
- missing or broken images;
- duplicate source URLs mapped to one retained hash;
- zero image references without falsely reporting success.

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_capture_asset_ledger.py -v
```

Expected: FAIL because the ledger module does not exist.

- [ ] **Step 2: Implement the asset ledger**

Write `00_assets.json` with:

```json
{
  "schema_version": "dom-capture-assets/1.0",
  "reference_count": 0,
  "verified_count": 0,
  "reference_only_count": 0,
  "missing_count": 0,
  "assets": []
}
```

Each asset row records source URL, source hash when available, MIME, natural
size, retained relative path, byte size, and status.

- [ ] **Step 3: Write the failing normal-flow recovery test**

Patch the DOM route design builder to return two image elements, patch
`recover_network_assets` to return one verified asset and one
`reference-only` asset, run the DOM branch in `PreciseAgent`, and assert:

- recovery is skipped when `dom_network_asset_recovery=false`;
- recovery runs once when true;
- `12_design.json` contains the upgraded asset identity;
- `00_assets.json` and `00_capture_bundle.json` record the same status counts.

- [ ] **Step 4: Integrate recovery before DesignSpec persistence**

In the DOM/URL path, after `backfill_design_image_crops(design, image)` and
before `12_design.json` is written:

```python
if cfg.dom_network_asset_recovery and route == "dom":
    recovery = recover_network_assets(
        design,
        page_url=page_state.get("final_url") or url,
        output_dir=out,
    )
    design = recovery.pop("design")
    asset_ledger = build_asset_ledger(design)
    (out / "00_assets.json").write_text(
        json.dumps(asset_ledger, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    update_capture_bundle_assets(
        out,
        asset_manifest="00_assets.json",
        asset_counts=asset_ledger,
    )
```

Even when recovery is disabled, write `00_assets.json` with
`reference_only` or `missing` statuses. Never rewrite a remote URL as a
verified original.

- [ ] **Step 5: Run asset and rendering tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_capture_asset_ledger.py `
  tests/v2/test_dom_normal_asset_recovery.py `
  tests/v2/test_network_asset_recovery.py `
  tests/v2/test_image_route_fallback.py `
  tests/v2/test_figma_adapter_edits.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit local asset materialization**

```powershell
git add src/app/services/structure/capture_asset_ledger.py `
        src/app/services/structure/capture_bundle.py `
        src/app/agents/precise_agent.py `
        src/config/settings.py `
        tests/v2/test_capture_asset_ledger.py `
        tests/v2/test_dom_normal_asset_recovery.py
git commit -m "feat: materialize DOM image assets before Figma rendering"
```

---

### Task 5: Add route-quality gates for redirect, image loss, and clipping

**Files:**
- Create: `src/app/services/evidence/dom_route_quality.py`
- Modify: `src/app/agents/precise_agent.py:825-896`
- Modify: `src/config/settings.py`
- Create: `tests/v2/test_dom_route_quality.py`

**Interfaces:**
- Consumes: capture bundle, flat DOM nodes, PageGraph, DesignSpec, and asset ledger.
- Produces:
  - `evaluate_dom_route_quality(bundle: Mapping[str, Any], dom_nodes: Sequence[Mapping[str, Any]], graph: Mapping[str, Any], design: Mapping[str, Any], asset_ledger: Mapping[str, Any]) -> dict[str, Any]`
  - `DOMRouteQualityError(RuntimeError)`
  - `00_route_quality.json`
  - statuses `pass`, `warn`, or `fail`.
  - setting `dom_route_quality_strict`, env `DOM_ROUTE_QUALITY_STRICT`, default `false`.

- [ ] **Step 1: Write the failing quality-gate tests**

Create tests with four exact cases:

```python
def test_requested_xiaomi_but_final_support_url_is_fail():
    result = evaluate_dom_route_quality(
        bundle={"requested_url": "https://www.mi.com/", "final_url": "https://www.mi.com/global/support/"},
        dom_nodes=[{"tag": "body", "x": 0, "y": 0, "w": 1440, "h": 1321}],
        graph={"containers": [], "elements": []},
        design={"canvas": {"width": 1440, "height": 1321}, "elements": []},
        asset_ledger={"reference_count": 0},
    )
    assert result["status"] == "fail"
    assert result["checks"]["redirect"]["status"] == "fail"


def test_dom_image_refs_without_design_images_is_fail():
    result = evaluate_dom_route_quality(
        bundle={"requested_url": "https://data.stats.gov.cn/", "final_url": "https://data.stats.gov.cn/"},
        dom_nodes=[{"tag": "img", "assetSrc": "https://img/hero.png", "x": 0, "y": 0, "w": 800, "h": 485}],
        graph={"containers": [], "elements": []},
        design={"canvas": {"width": 1440, "height": 800}, "elements": []},
        asset_ledger={"reference_count": 1, "verified_count": 0},
    )
    assert result["checks"]["image_coverage"]["status"] == "fail"
```

Add cases proving same-origin SPA navigation and a valid redirect do not fail
without a content mismatch.

- [ ] **Step 2: Implement the quality report**

The report must contain:

```json
{
  "schema_version": "dom-route-quality/1.0",
  "status": "pass",
  "checks": {
    "redirect": {"status": "pass", "reason": null},
    "content": {"status": "pass", "dom_node_count": 0},
    "image_coverage": {"status": "pass", "references": 0, "design_images": 0},
    "geometry": {"status": "pass", "canvas_size": [1440, 900]},
    "clipping": {"status": "pass", "clipped_node_count": 0}
  },
  "warnings": []
}
```

Rules:

- Normalize both URLs by removing fragments, trailing slashes, and query keys
  explicitly declared volatile. Same canonical URL: `pass`.
- Same host and same path after normalization: `pass`.
- Same host, requested path `/`, and final path `/`: `pass`.
- Same host, requested path `/`, and final path has one non-empty segment:
  `warn`.
- Same host, requested path `/`, and final path starts with a known
  region/locale prefix from
  `{"/global", "/us", "/en", "/en-us", "/cn", "/zh", "/zh-cn"}`: `fail`.
- A different host that differs only by a region or support subdomain prefix
  and has a different normalized path: `fail`.
- Any remaining cross-host or cross-path change: `warn`.
- DOM contains one or more image references but DesignSpec has zero image
  elements: `fail`.
- DOM contains two or more image references and fewer than half resolve to
  DesignSpec image elements: `warn`.
- canvas height differs from the screenshot by more than 5 percent:
  `warn`;
- DOM clipping exists and clipped descendants disappear from the graph:
  `warn`;
- empty shell remains governed by the existing `page_state`.

- [ ] **Step 3: Write and integrate the route-quality artifact**

Call the evaluator after DesignSpec generation and before rendering. Persist
`00_route_quality.json`. For `fail`, log the exact failing check and raise a
`DOMRouteQualityError` when `cfg.dom_route_quality_strict=true`; otherwise
continue with the warning for manual review.

- [ ] **Step 4: Run quality and route tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_dom_route_quality.py `
  tests/v2/test_image_route_fallback.py `
  tests/v2/test_capture_browser_engine.py `
  tests/v2/test_p1_navigation_only_probe.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit route-quality gates**

```powershell
git add src/app/services/evidence/dom_route_quality.py `
        src/app/agents/precise_agent.py `
        tests/v2/test_dom_route_quality.py
git commit -m "feat: gate DOM routes on redirect and image quality"
```

---

### Task 6: Freeze four-page replay and record the optimization decision

**Files:**
- Create: `scripts/benchmark_dom_route.py`
- Create: `tests/v2/test_dom_route_benchmark.py`
- Create: `docs/v2_mentor/DOM_ROUTE_OPTIMIZATION_RESULT_2026-10-29.md`

**Interfaces:**
- Consumes: four capture bundles for IT之家, 21ic, 国家数据, and 小米.
- Produces: `dom-route-benchmark.json` with per-page bundle hashes, replay hashes, quality statuses, image coverage, text-node counts, and Figma-readback results.

- [ ] **Step 1: Write the failing benchmark aggregation test**

Create two synthetic bundle-report rows and assert the benchmark JSON contains
per-page status, aggregate failure counts, and no network/browser claim.

- [ ] **Step 2: Implement the benchmark driver**

The CLI accepts repeated `--case name=bundle-dir` arguments and optional
`--figma-readback name=json`. It runs replay, evaluates route quality, and
writes one deterministic JSON report.

- [ ] **Step 3: Capture the four regression pages once**

Use the normal URL route for:

```text
IT之家: https://www.ithome.com/0/823/017.htm
21ic: https://bbs.21ic.com/
国家数据: https://data.stats.gov.cn/
小米: https://www.mi.com/
```

Record requested URL, final URL, viewport `1440x900`, DPR `1`, screenshot
hash, DOM hash, bundle hash, quality status, and image counts.

- [ ] **Step 4: Replay each bundle twice**

Assert each pair has identical PageGraph and DesignSpec hashes. Record Figma
image-fill counts separately; replay determinism and Figma runtime fidelity
are different claims.

- [ ] **Step 5: Write the result document**

The result document must end with:

```markdown
## Decision

- Versioned capture bundle: adopted / rejected
- Layer tree: adopted / rejected
- Offline replay: adopted / rejected
- Asset materialization: adopted / rejected
- Route-quality gate: adopted / rejected
- Default behavior changed: yes/no
- Remaining risks:
- Reproduction commands:
```

- [ ] **Step 6: Run the final regression suite**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_capture_bundle.py `
  tests/v2/test_dom_layer_tree.py `
  tests/v2/test_dom_capture_style_snapshot.py `
  tests/v2/test_capture_replay.py `
  tests/v2/test_capture_asset_ledger.py `
  tests/v2/test_dom_normal_asset_recovery.py `
  tests/v2/test_dom_route_quality.py `
  tests/v2/test_dom_route_benchmark.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit the benchmark and decision**

```powershell
git add scripts/benchmark_dom_route.py `
        tests/v2/test_dom_route_benchmark.py `
        docs/v2_mentor/DOM_ROUTE_OPTIMIZATION_RESULT_2026-10-29.md
git commit -m "docs: record DOM capture and replay optimization results"
```
