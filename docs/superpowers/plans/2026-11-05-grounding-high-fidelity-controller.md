# Grounding High-Fidelity Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in Grounding high-fidelity controller that inventories visible content and geometry, builds one canonical scene plan, and performs bounded local structure repairs.

**Architecture:** Grounding remains the only semantic pipeline. A new fidelity package converts the existing PageGraph, OCR/CV data, tables, controls, and slice candidates into an evidence bundle, content inventory, geometry manifest, and scene plan. A bounded repair loop consumes verifier blockers, applies validated local patches, recompiles the scene, and rolls back regressions.

**Tech Stack:** Python 3.11, existing Grounding VLM/OCR/CV services, Pillow/OpenCV, pytest, existing SVG/Figma adapters and acceptance evidence.

**Spec:** `docs/superpowers/specs/2026-11-05-grounding-high-fidelity-controller-design.md`

## Global Constraints

- `GROUNDING_FIDELITY_MODE` defaults to `off`.
- High-fidelity mode uses at most 3 repair rounds.
- High-fidelity mode uses at most 6 additional local model calls.
- High-fidelity mode requires `IMAGE_ENRICHMENT_MODE=apply`.
- All geometry uses source-pixel top-left `xywh`.
- Full-screenshot underlay is always a hard failure.
- `sliceAnalysis` is evidence only; it must not create a second scene tree.
- Final text and controls remain native editable nodes.
- Reference-only images must remain explicitly non-original.
- Legacy output must remain unchanged when high-fidelity mode is off.

## File Structure

- Create: `src/app/services/structure/fidelity/__init__.py`
  - Export the public fidelity contracts.
- Create: `src/app/services/structure/fidelity/contracts.py`
  - Evidence bundle schema, normalization, validation, and provenance helpers.
- Create: `src/app/services/structure/fidelity/inventory.py`
  - Deterministic ContentInventory and GeometryManifest builders.
- Create: `src/app/services/structure/fidelity/scene_plan.py`
  - ScenePlan construction and application to a canonical graph.
- Create: `src/app/services/structure/fidelity/repair.py`
  - Blocker-to-request planning, bounded repair loop, patch validation, rollback.
- Create: `src/app/services/structure/fidelity/local_repair.py`
  - Crop-based VLM repair adapter and coordinate translation.
- Create: `src/app/services/evidence/region_quality.py`
  - Region-level same-size visual metrics.
- Modify: `src/config/settings.py`
  - Add high-fidelity mode and budget settings.
- Modify: `src/app/agents/precise_agent.py`
  - Orchestrate high-fidelity mode and write artifacts.
- Modify: `src/app/services/evidence/image_figma_acceptance.py`
  - Require region quality and repair-budget evidence.

---

### Task 1: Build Evidence, Content Inventory, and Geometry Manifest

**Files:**
- Create: `src/app/services/structure/fidelity/__init__.py`
- Create: `src/app/services/structure/fidelity/contracts.py`
- Create: `src/app/services/structure/fidelity/inventory.py`
- Test: `tests/v2/test_grounding_fidelity_contracts.py`

**Interfaces:**
- Consumes: existing `graph` with `containers`, `elements`, `tables`, `imageEnrichment`, `sliceAnalysis`, and `provenance`.
- Produces: `build_evidence_bundle(graph: Mapping[str, Any], reference: Mapping[str, Any]) -> dict[str, Any]`
- Produces: `build_content_inventory(bundle: Mapping[str, Any]) -> dict[str, Any]`
- Produces: `build_geometry_manifest(bundle: Mapping[str, Any]) -> dict[str, Any]`

- [ ] **Step 1: Write failing contract tests**

```python
def test_inventory_preserves_all_table_rows_and_full_timestamps():
    graph = _graph_with_five_table_rows()
    bundle = build_evidence_bundle(graph, _reference(1920, 826))
    inventory = build_content_inventory(bundle)
    table = inventory["tables"][0]
    assert len(table["rows"]) == 5
    assert table["rows"][0][1] == "2026-11-01 03:30:00"


def test_checkbox_label_and_control_have_distinct_inventory_items():
    bundle = build_evidence_bundle(_graph_with_checkbox_label(), _reference(400, 200))
    inventory = build_content_inventory(bundle)
    assert [item["kind"] for item in inventory["items"]].count("control") == 1
    assert any(
        item["kind"] == "text" and item["text"] == "以auto用户身份执行"
        for item in inventory["items"]
    )


def test_geometry_manifest_keeps_source_pixel_boxes():
    geometry = build_geometry_manifest(
        build_evidence_bundle(_graph_with_layout(), _reference(1920, 826))
    )
    assert geometry["image_size"] == [1920, 826]
    assert all(
        item["bbox"][2] > 0 and item["bbox"][3] > 0
        for item in geometry["items"]
    )
```

- [ ] **Step 2: Run tests and verify the module is missing**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_grounding_fidelity_contracts.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the evidence and inventory contracts**

`build_evidence_bundle` copies source records without losing provenance. Each record has `id`, `kind`, `status`, `authority`, `confidence`, `bbox`, `payload_ref`, and `reason`.

`build_content_inventory` emits one item per visible label, control value/state, table cell, visible asset, and explicit unknown. Normalize text only for matching; preserve display text exactly.

`build_geometry_manifest` emits page/header/sidebar/main/form/table/control/column/row geometry in source pixels.

- [ ] **Step 4: Run the contract tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_grounding_fidelity_contracts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/services/structure/fidelity tests/v2/test_grounding_fidelity_contracts.py
git commit -m "feat: add grounding fidelity evidence contracts"
```

---

### Task 2: Build One Canonical ScenePlan

**Files:**
- Create: `src/app/services/structure/fidelity/scene_plan.py`
- Test: `tests/v2/test_grounding_scene_plan.py`

**Interfaces:**
- Consumes: `graph`, `content_inventory`, and `geometry_manifest` from Task 1.
- Produces: `build_scene_plan(graph: Mapping[str, Any], inventory: Mapping[str, Any], geometry: Mapping[str, Any]) -> dict[str, Any]`
- Produces: `apply_scene_plan(graph: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]`
- ScenePlan node contract: `id`, `parent_id`, `type`, `role`, `bbox`, `content_ref`, `geometry_ref`, `children`.

- [ ] **Step 1: Write failing ownership tests**

```python
def test_checkbox_label_has_one_text_owner():
    plan = build_scene_plan(
        _graph_with_checked_checkbox(),
        _inventory_with_checkbox_label(),
        _geometry_with_checkbox_and_label(),
    )
    labels = [
        node for node in plan["nodes"]
        if node["content_ref"] == "text:checkbox-label"
    ]
    assert len(labels) == 1
    assert labels[0]["parent_id"] == "form:status"


def test_table_cell_has_exactly_one_owner():
    plan = build_scene_plan(
        _graph_with_duplicate_table_text(),
        _inventory_with_table_rows(),
        _geometry_with_table_grid(),
    )
    owners = [
        node for node in plan["nodes"]
        if node["content_ref"] == "table:0:1"
    ]
    assert len(owners) == 1


def test_slice_asset_cannot_create_a_second_layout_tree():
    plan = build_scene_plan(
        _graph_with_slice_assets(),
        _inventory_with_reference_assets(),
        _geometry_with_asset_boxes(),
    )
    assert all(
        node["type"] != "container"
        for node in plan["nodes"]
        if str(node.get("content_ref") or "").startswith("asset:")
    )
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_grounding_scene_plan.py -q`

Expected: FAIL because `scene_plan` does not exist.

- [ ] **Step 3: Implement scene ownership and graph projection**

ScenePlan resolves control labels, table cells, text duplicates, and asset payloads before `build_image_design`. `apply_scene_plan` must not introduce a new coordinate system.

- [ ] **Step 4: Run scene-plan tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_grounding_scene_plan.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/services/structure/fidelity/scene_plan.py tests/v2/test_grounding_scene_plan.py
git commit -m "feat: build canonical grounding scene plan"
```

---

### Task 3: Add High-Fidelity Configuration and Artifacts

**Files:**
- Modify: `src/config/settings.py`
- Test: `tests/v2/test_grounding_fidelity_config.py`

**Interfaces:**
- Produces config fields: `grounding_fidelity_mode`, `grounding_repair_max_rounds`, `grounding_repair_max_extra_calls`, `grounding_repair_min_region_gain`, and `grounding_region_regression_tolerance`.
- Produces artifacts: `09_evidence_bundle.json`, `10_content_inventory.json`, `10_geometry_manifest.json`, and `11_scene_plan.json`.

- [ ] **Step 1: Write failing config tests**

```python
def test_high_fidelity_defaults(monkeypatch):
    monkeypatch.setenv("GROUNDING_FIDELITY_MODE", "high")
    cfg = Config()
    assert cfg.grounding_repair_max_rounds == 3
    assert cfg.grounding_repair_max_extra_calls == 6


def test_high_fidelity_requires_image_enrichment_apply():
    with pytest.raises(ValueError, match="IMAGE_ENRICHMENT_MODE=apply"):
        Config(
            grounding_fidelity_mode="high",
            image_enrichment_mode="analyze",
        )
```

- [ ] **Step 2: Run config tests and verify failure**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_grounding_fidelity_config.py -q`

Expected: FAIL on missing fields or validation.

- [ ] **Step 3: Implement settings and validation**

Use environment validation matching existing settings style. Reject non-positive round/call budgets and incompatible enrichment mode.

- [ ] **Step 4: Run config tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_grounding_fidelity_config.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/config/settings.py tests/v2/test_grounding_fidelity_config.py
git commit -m "feat: add high fidelity grounding controls"
```

---

### Task 4: Add Region-Level Visual Quality

**Files:**
- Create: `src/app/services/evidence/region_quality.py`
- Test: `tests/v2/test_region_quality.py`

**Interfaces:**
- Produces: `evaluate_region_quality(reference_path: str | Path, render_path: str | Path, regions: Sequence[Mapping[str, Any]]) -> dict[str, Any]`
- Each region: `id`, `bbox`, optional `role`.

- [ ] **Step 1: Write failing region tests**

```python
def test_region_metrics_expose_local_regression(tmp_path):
    reference, render = _images_with_changed_table_only(tmp_path)
    result = evaluate_region_quality(
        reference,
        render,
        [
            {"id": "form", "bbox": [0, 0, 100, 100]},
            {"id": "table", "bbox": [0, 100, 100, 100]},
        ],
    )
    assert result["regions"]["form"]["bad_pixel_ratio"] == 0.0
    assert result["regions"]["table"]["bad_pixel_ratio"] > 0.0


def test_region_metrics_fail_on_size_mismatch(tmp_path):
    result = evaluate_region_quality(*_different_size_images(tmp_path), [])
    assert result["status"] == "blocked"
    assert result["size_match"] is False
```

- [ ] **Step 2: Run tests and verify failure**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_region_quality.py -q`

Expected: FAIL because `region_quality` does not exist.

- [ ] **Step 3: Implement region metrics**

Reuse the product metric's max-channel threshold. Clamp supplied regions to the canvas and reject empty/invalid boxes.

- [ ] **Step 4: Run region tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_region_quality.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/services/evidence/region_quality.py tests/v2/test_region_quality.py
git commit -m "feat: evaluate regional reconstruction quality"
```

---

### Task 5: Implement Bounded Repair Planning and Patch Validation

**Files:**
- Create: `src/app/services/structure/fidelity/repair.py`
- Test: `tests/v2/test_grounding_fidelity_repair.py`

**Interfaces:**
- Produces: `plan_repair_requests(report: Mapping[str, Any], plan: Mapping[str, Any], *, max_requests: int) -> list[dict[str, Any]]`
- Produces: `apply_repair_patch(plan: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]`
- Produces: `run_bounded_repair_loop(plan: Mapping[str, Any], verify: Callable[[Mapping[str, Any]], Mapping[str, Any]], repair: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any] | None], *, max_rounds: int = 3, max_extra_calls: int = 6) -> dict[str, Any]`
- `verify(plan)` returns a fidelity report with `status` and `blockers`.
- `repair(request, plan)` returns a patch or `None`.

- [ ] **Step 1: Write failing repair tests**

```python
def test_missing_table_emits_one_local_repair_request():
    requests = plan_repair_requests(
        _report_with_missing_table(),
        _scene_plan(),
        max_requests=3,
    )
    assert len(requests) == 1
    assert requests[0]["kind"] == "table"
    assert requests[0]["bbox"] == [300, 550, 1600, 276]


def test_invalid_patch_rolls_back():
    result = apply_repair_patch(_scene_plan(), _patch_that_removes_native_text())
    assert result["accepted"] is False
    assert result["plan"] == _scene_plan()


def test_repair_loop_stops_at_call_budget():
    result = run_bounded_repair_loop(
        _scene_plan(),
        verify=_always_failing_verify,
        repair=_always_returning_patch,
        max_rounds=3,
        max_extra_calls=2,
    )
    assert result["extra_calls"] == 2
    assert result["status"] == "budget-exhausted"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_grounding_fidelity_repair.py -q`

Expected: FAIL because `repair` does not exist.

- [ ] **Step 3: Implement repair requests, transactional patches, and budgets**

Each request carries `id`, `kind`, `bbox`, `target_ids`, `reason`, and `acceptance`. Reject patches that remove covered inventory, worsen protected regions, introduce underlay, or fail schema validation.

- [ ] **Step 4: Run repair tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_grounding_fidelity_repair.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/services/structure/fidelity/repair.py tests/v2/test_grounding_fidelity_repair.py
git commit -m "feat: add bounded grounding repair controller"
```

---

### Task 6: Add Crop-Based Local Structure Repair

**Files:**
- Create: `src/app/services/structure/fidelity/local_repair.py`
- Test: `tests/v2/test_grounding_local_repair.py`

**Interfaces:**
- Produces: `class GroundingLocalRepairer`
- Produces: `repair(request: Mapping[str, Any], image_path: str | Path, plan: Mapping[str, Any]) -> dict[str, Any] | None`
- Consumes backend protocol: `ground(image_path: str | Path, image_w: int, image_h: int) -> dict[str, Any]`
- Repair calls return ScenePlan patch operations only.

- [ ] **Step 1: Write failing local-repair tests**

```python
def test_table_repair_crops_only_requested_region(tmp_path):
    backend = _RecordingGroundingBackend()
    repairer = GroundingLocalRepairer(backend)
    patch = repairer.repair(
        _table_request(bbox=[300, 550, 1600, 276]),
        _fixture_image(tmp_path),
        _scene_plan(),
    )
    assert backend.calls[0]["size"] == [1600, 276]
    assert patch["region_id"] == "table"


def test_repair_patch_boxes_are_translated_to_page_coordinates(tmp_path):
    patch = _repairer_with_crop_box([10, 20, 80, 30]).repair(
        _table_request(bbox=[300, 550, 1600, 276]),
        _fixture_image(tmp_path),
        _scene_plan(),
    )
    assert patch["operations"][0]["bbox"] == [310, 570, 80, 30]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_grounding_local_repair.py -q`

Expected: FAIL because `local_repair` does not exist.

- [ ] **Step 3: Implement crop repair with existing Grounding backend**

Crop with page-bbox expansion, call the configured backend on the crop, translate bboxes back, cache by crop digest + request signature, and return patch operations.

- [ ] **Step 4: Run local repair tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_grounding_local_repair.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/services/structure/fidelity/local_repair.py tests/v2/test_grounding_local_repair.py
git commit -m "feat: add crop based grounding repair"
```

---

### Task 7: Wire High-Fidelity Mode into PreciseAgent

**Files:**
- Modify: `src/app/agents/precise_agent.py`
- Test: `tests/v2/test_grounding_fidelity_integration.py`

**Interfaces:**
- Consumes: Tasks 1-6.
- Produces artifacts: `09_evidence_bundle.json`, `10_content_inventory.json`, `10_geometry_manifest.json`, `11_scene_plan.json`, `13_fidelity_report.json`, and `14_repair_history.json`.

- [ ] **Step 1: Write failing integration tests**

```python
def test_high_fidelity_mode_writes_plan_and_reports(tmp_path, monkeypatch):
    _prepare_fake_grounding(monkeypatch)
    cfg = replace(
        Config(),
        output_dir=tmp_path,
        grounding_fidelity_mode="high",
        image_enrichment_mode="apply",
    )
    PreciseAgent(cfg).run(image=str(_fixture_image(tmp_path)), route="grounding", tool="svg")
    for name in (
        "09_evidence_bundle.json",
        "10_content_inventory.json",
        "10_geometry_manifest.json",
        "11_scene_plan.json",
        "13_fidelity_report.json",
        "14_repair_history.json",
    ):
        assert (tmp_path / name).is_file()


def test_high_fidelity_off_preserves_legacy_artifacts(tmp_path):
    names = _run_once_with_mode(tmp_path, "off")
    assert "09_evidence_bundle.json" not in names
    assert "11_scene_plan.json" not in names
```

- [ ] **Step 2: Run integration tests and verify failure**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_grounding_fidelity_integration.py -q`

Expected: FAIL because high-fidelity orchestration is not wired.

- [ ] **Step 3: Wire the bounded controller into image Grounding**

Build the plan before DesignSpec when mode is `high`. Keep the existing PageGraph path when mode is `off`. Persist every retry, accepted patch, rejected patch, and rollback.

- [ ] **Step 4: Run integration tests**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_grounding_fidelity_integration.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/agents/precise_agent.py tests/v2/test_grounding_fidelity_integration.py
git commit -m "feat: run grounding high fidelity controller"
```

---

### Task 8: Extend Acceptance and Run Multi-Image Benchmark

**Files:**
- Modify: `src/app/services/evidence/image_figma_acceptance.py`
- Modify: `tests/v2/test_image_figma_acceptance.py`
- Create: `docs/v2_mentor/GROUNDING_HIGH_FIDELITY_ACCEPTANCE_2026-11-05.md`

**Interfaces:**
- Consumes: fidelity artifacts from Task 7.
- Produces acceptance dimensions: `fidelity`, `region_visual`, and `repair_budget`.

- [ ] **Step 1: Write failing acceptance tests**

```python
def test_visual_pass_cannot_mask_region_regression():
    report = build_image_acceptance_report(
        **_acceptance_bundle(region_regression={"table": 0.08}),
    )
    assert report["status"] == "blocked-fail"
    assert "region-visual:table" in report["blockers"]


def test_repair_budget_exhaustion_blocks_acceptance():
    report = build_image_acceptance_report(
        **_acceptance_bundle(repair_status="budget-exhausted"),
    )
    assert "repair-budget" in report["blockers"]
```

- [ ] **Step 2: Run acceptance tests and verify failure**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_image_figma_acceptance.py -q`

Expected: FAIL because new blockers are absent.

- [ ] **Step 3: Add acceptance blockers and benchmark evidence**

Acceptance must fail when content, geometry, native structure, region quality, or repair budgets fail. Document:

- high-fidelity status;
- call and round counts;
- rejected and rolled-back patches;
- frozen-sample metrics;
- remaining differences.

- [ ] **Step 4: Run the full verification suite**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest -q
python -m ruff check src tests
python -m ruff format --check src tests
node --check figma_bridge/code.js
```

Expected: all pass.

- [ ] **Step 5: Run the three-image E2E benchmark**

Run the existing image-to-Figma evidence path for:

- `IMG-FLEXWEAVER-ADMIN`
- `IMG-ACCTOKEN-API`
- `IMG-ARTICLE`

Expected:

- All content and structure gates pass.
- Each sample remains within the configured call budget.
- No sample uses a full-screenshot underlay.
- High-fidelity metrics are no worse than the single-pass baseline.

- [ ] **Step 6: Commit**

```bash
git add src/app/services/evidence/image_figma_acceptance.py tests/v2/test_image_figma_acceptance.py docs/v2_mentor/GROUNDING_HIGH_FIDELITY_ACCEPTANCE_2026-11-05.md
git commit -m "test: gate grounding high fidelity reconstruction"
```

## Review Focus

- A long checkbox label next to a small control must remain one independent text node and one native control.
- A table must keep all visible rows and complete timestamp values without adding a row to fill the panel.
- A cropped logo, avatar, or badge must include all visible content and preserve its display/identity bbox separation.
- A repaired region must not introduce a black-filled Vector frame or a second overlapping text owner.
- A repair loop must stop cleanly at the call/round budget and leave the last verified plan intact.
