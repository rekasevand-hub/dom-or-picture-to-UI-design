# Cross-Project Figma Effect Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compare the actual output of the current project, BuilderIO/figma-html, and 50kg/image-to-slice on frozen inputs before spending time on source adoption.

**Architecture:** Run a small, representative benchmark that separates the two product inputs. Use three DOM samples for current-vs-BuilderIO and three image samples for current-vs-Image-To-Slice. Capture browser output, Figma layers/readback, editability, visual difference, manual correction effort, and failure modes. Source-adoption work starts only after the report identifies a measurable gap.

**Tech Stack:** Existing Python pipeline, Figma Desktop, BuilderIO browser extension plus published Figma plugin, Image To Slice local/manual mode, Playwright screenshots, PIL image diff, existing Figma bridge/readback.

**Spec:** `README.md`, `HANDOFF_2026-10-27_dom_figma_crosssite_holdout.md`

## Global Constraints

- Freeze all six inputs and hashes before running any tool.
- Use one common viewport for DOM: `1440x900`, DPR `1`.
- Use the original image dimensions for image samples; do not upscale.
- Do not replace failed samples.
- Do not use BuilderIO or Image To Slice as production dependencies in this phase.
- Do not port source code until the benchmark report is complete.
- Run every external plugin on public or owned test inputs only.
- Request explicit confirmation immediately before installing or running either
  third-party browser extension or Figma plugin.
- Keep Figma outputs in unique files or uniquely named frames.
- Record every plugin version and upstream commit.
- Do not count partial output after a timeout as success.
- Preserve the dirty worktree and stage only benchmark files.

---

### Task 1: Freeze the benchmark manifest and input hashes

**Files:**
- Create: `tests/fixtures/cross-project-figma-benchmark/manifest.json`
- Create: `tests/fixtures/cross-project-figma-benchmark/README.md`
- Create: `scripts/cross_project_figma_freeze.py`
- Create: `tests/v2/test_cross_project_figma_freeze.py`

**Interfaces:**
- Produces: `freeze_manifest(manifest_path: Path, root: Path) -> dict`
- Manifest IDs: `DOM-ARTICLE`, `DOM-ECOMMERCE`, `DOM-DASHBOARD`, `IMG-FORM`, `IMG-PHOTO-BG`, `IMG-DENSE-NAV`

- [ ] **Step 1: Select the six frozen samples**

Use:

| ID | Input | Purpose |
|---|---|---|
| `DOM-ARTICLE` | public article page | long text, inline formatting, images |
| `DOM-ECOMMERCE` | public product-grid page | grids, cards, repeated assets |
| `DOM-DASHBOARD` | public data page | tables, charts, dense nesting |
| `IMG-FORM` | authored screenshot | simple form and native text |
| `IMG-PHOTO-BG` | authored screenshot | text over photographic background |
| `IMG-DENSE-NAV` | authored screenshot | icons, assets, overlays, nested navigation |

DOM pages must not be LeetCode, Juejin, CSDN, or dushu.

- [ ] **Step 2: Write the manifest**

Create `manifest.json` with:

```json
{
  "schema_version": "cross-project-figma-benchmark/1.0",
  "frozen_at": "2026-10-28T00:00:00+08:00",
  "viewport": [1440, 900],
  "device_scale_factor": 1,
  "samples": [
    {
      "id": "DOM-ARTICLE",
      "kind": "dom",
      "url": "https://www.ithome.com/0/823/017.htm",
      "path": null,
      "title": null,
      "sha256": null
    },
    {
      "id": "DOM-ECOMMERCE",
      "kind": "dom",
      "url": "https://www.mi.com/",
      "path": null,
      "title": null,
      "sha256": null
    },
    {
      "id": "DOM-DASHBOARD",
      "kind": "dom",
      "url": "https://data.stats.gov.cn/",
      "path": null,
      "title": null,
      "sha256": null
    },
    {
      "id": "IMG-FORM",
      "kind": "image",
      "url": null,
      "path": "tests/fixtures/image_mvp/simple_dashboard_v1.png",
      "title": "simple dashboard",
      "sha256": "7f39efc5e69b9ba16367aa19a1ccb1e3ea1681824419c93f0f9a3478e5153df4"
    },
    {
      "id": "IMG-PHOTO-BG",
      "kind": "image",
      "url": null,
      "path": "tests/fixtures/axure_holdout_v2/overlay.png",
      "title": "overlay screenshot",
      "sha256": "ac8fd6ee2af97f1cd8eb42c43f332d4b52793e349feaa78aaa70e463f3bdc2a7"
    },
    {
      "id": "IMG-DENSE-NAV",
      "kind": "image",
      "url": null,
      "path": "tests/fixtures/image_fallback_holdout_2026-10-26/ax10-dom-assets.png",
      "title": "dense asset screenshot",
      "sha256": "a22150581a324550af68fa568eb8673ea9a2ce63ea874fca33590c899d1236e8"
    }
  ]
}
```

Do not change URLs/images after this step. DOM screenshot and DOM hashes are
filled by the freeze command after capture.

- [ ] **Step 3: Write the failing freeze test**

```python
from pathlib import Path

from scripts.cross_project_figma_freeze import freeze_manifest


def test_manifest_requires_six_unique_hashed_samples():
    result = freeze_manifest(
        Path("tests/fixtures/cross-project-figma-benchmark/manifest.json"),
        Path("tests/fixtures/cross-project-figma-benchmark"),
    )
    assert result["sample_count"] == 6
    assert result["unique_ids"] == 6
    assert result["unique_inputs"] == 6
    assert result["missing_hashes"] == 0
```

- [ ] **Step 4: Implement the freeze validator**

`freeze_manifest` must:

- load JSON;
- require exactly six samples;
- reject duplicate IDs and duplicate input URLs/paths;
- require DOM viewport and DPR exactly;
- compute or verify SHA-256 for local image inputs;
- record screenshot and DOM hashes after capture;
- fail if a DOM sample is on a forbidden host;
- write a sibling `frozen_manifest.lock.json`.

- [ ] **Step 5: Run the test**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_cross_project_figma_freeze.py -v
```

Expected: PASS after inputs and hashes are frozen.

- [ ] **Step 6: Commit only benchmark freeze files**

```powershell
git add tests/fixtures/cross-project-figma-benchmark `
        scripts/cross_project_figma_freeze.py `
        tests/v2/test_cross_project_figma_freeze.py
git commit -m "test: freeze cross-project Figma benchmark"
```

---

### Task 2: Capture the current project baseline

**Files:**
- Create: `scripts/cross_project_figma_baseline.py`
- Create: `tests/v2/test_cross_project_figma_baseline.py`
- Output: `output/_cross_project_figma_benchmark/baseline/<sample>/`

**Interfaces:**
- Produces one observation record per sample:

```python
{
    "sample_id": str,
    "tool": "current",
    "variant": "dom" | "image",
    "status": "success" | "fail" | "timeout",
    "design_path": str | None,
    "screenshot_path": str | None,
    "figma_frame_name": str | None,
    "metrics": dict,
    "errors": list[str],
}
```

- [ ] **Step 1: Write the baseline-runner test**

Use a fake manifest with one DOM sample and assert:

- unique output directory;
- `--route dom`;
- no fallback flags;
- artifact paths are recorded;
- partial failure is marked `fail`.

- [ ] **Step 2: Implement the runner**

For DOM samples run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m src.main `
  --url "<url>" --route dom --tool svg --no-headed-fallback `
  --output-dir "output/_cross_project_figma_benchmark/baseline/<sample>"
```

For image samples run the existing image MVP path with the same source image.

- [ ] **Step 3: Validate page state and route**

Fail the observation if:

- `effective_route != requested_route`;
- fallbacks are non-empty;
- the screenshot is missing or blank;
- the DesignSpec is missing;
- a soft block or hard login state is recorded.

- [ ] **Step 4: Run**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_cross_project_figma_baseline.py -v
C:\Users\lzq\.conda\envs\omni\python.exe scripts\cross_project_figma_baseline.py `
  --manifest tests/fixtures/cross-project-figma-benchmark/manifest.json `
  --out output/_cross_project_figma_benchmark/baseline
```

Expected: six observation records, each with explicit status.

- [ ] **Step 5: Commit the runner**

```powershell
git add scripts/cross_project_figma_baseline.py `
        tests/v2/test_cross_project_figma_baseline.py
git commit -m "test: add current Figma route baseline runner"
```

---

### Task 3: Run BuilderIO on the three DOM samples

**Files:**
- Create: `tests/fixtures/cross-project-figma-benchmark/builderio.md`
- Output: `output/_cross_project_figma_benchmark/builderio/<sample>/`

**Interfaces:**
- Produces: manual observation record using the same six status and metric fields as Task 2.

- [ ] **Step 1: Record the external versions**

Record:

- BuilderIO repository current commit `2b244343ba3fcc1a2de50fa652e13833e78e36f9`;
- published Figma plugin version shown in Figma Community;
- Chrome extension version shown in the browser;
- exact input URL and capture date.

- [ ] **Step 2: Run the published extension workflow**

For each DOM sample:

1. Open the frozen URL in a fresh browser profile.
2. Use the BuilderIO Chrome extension to generate `page.figma.json`.
3. Open the published HTML To Figma plugin in a unique Figma file.
4. Upload the JSON.
5. Wait for completion and export a PNG of the generated root.
6. Save the Figma file URL and readback JSON.

Do not reuse a partial output after a plugin timeout.

- [ ] **Step 3: Record editability**

For each builder output count:

- FRAME nodes;
- TEXT nodes;
- IMAGE/RECTANGLE nodes;
- native text character count;
- text nodes containing unintended line breaks;
- nodes outside their direct parent.

- [ ] **Step 4: Record visual difference**

Normalize source and output to the same pixel dimensions and compute:

- mean absolute grayscale difference;
- percentage of pixels above 30;
- per-region difference for header/main/sidebar/footer.

- [ ] **Step 5: Record manual correction categories**

Use fixed categories:

```text
missing-text
wrong-text-wrap
wrong-asset
wrong-background
wrong-hierarchy
wrong-spacing
wrong-clip
unsupported-visual
```

- [ ] **Step 6: Write the observations**

Write `builderio.md` with a table containing all three samples and explicit pass/fail/timeout status.

---

### Task 4: Run Image To Slice on the three image samples

**Files:**
- Create: `tests/fixtures/cross-project-figma-benchmark/image_to_slice.md`
- Output: `output/_cross_project_figma_benchmark/image-to-slice/<sample>/`

**Interfaces:**
- Produces: manual observation record using the same fields as Task 2.

- [ ] **Step 1: Install and run only in an isolated local environment**

Record:

- upstream commit `ecc184c982a000c815796864ecce034fc0030c31`;
- Node version;
- model provider and model IDs used;
- whether manual JSON mode or AI mode was used.

Do not expose API keys in logs or benchmark files.

- [ ] **Step 2: Run the manual/zero-API mode first**

Use the plugin manual JSON mode with the same image inputs.
For the first pass, do not use AI-generated HTML; evaluate:

- slice imports;
- background candidates;
- frame and text creation from a supplied manual JSON;
- asset provenance presentation.

- [ ] **Step 3: Run the AI decomposition pass second**

For each image:

1. Run AI slice/background analysis.
2. Save the proposed assets, backgrounds, overlays, and JSON.
3. Inspect and correct only obvious invalid boxes.
4. Generate editable layers.
5. Export a PNG of the resulting root.

Record every manual correction.

- [ ] **Step 4: Record the same metrics**

Use the same text/editability, visual-difference, hierarchy, and manual-correction fields as Task 3. Additionally record:

- source crop count;
- inpainted background count;
- generated asset count;
- unmapped asset count;
- provenance mismatches.

- [ ] **Step 5: Write the observations**

Write `image_to_slice.md` with all three samples and explicit status.

---

### Task 5: Produce the effect comparison and source-study gate

**Files:**
- Create: `docs/v2_mentor/CROSS_PROJECT_FIGMA_EFFECT_BENCHMARK_2026-10-28.md`
- Create: `output/_cross_project_figma_benchmark/summary.json`

**Interfaces:**
- Consumes: baseline, BuilderIO, and Image To Slice observations.
- Produces: a source-study decision for each upstream project.

- [ ] **Step 1: Build the summary**

The report must contain:

```markdown
# Cross-Project Figma Effect Benchmark

## Frozen inputs

## Current baseline

## BuilderIO DOM route

## Image To Slice image route

## Metric comparison

## Failure taxonomy

## Manual correction effort

## What current project does better

## What upstream projects do better

## Source-study gate
```

- [ ] **Step 2: Apply the decision gates**

BuilderIO source study proceeds only if at least one is true:

- current DOM route loses a major hierarchy metric;
- BuilderIO produces materially more editable text;
- BuilderIO handles a repeated unsupported visual with lower manual effort;
- BuilderIO source reveals a concrete 20%+ improvement opportunity.

Image To Slice source study proceeds only if at least one is true:

- current image route has a major asset or background-recovery gap;
- Image To Slice materially improves text/layout recovery on two of three images;
- its slice classification lowers manual strategy selection;
- its manual JSON/provenance model is demonstrably useful.

- [ ] **Step 3: Record a stop decision when the gate fails**

Use one of:

```text
source-study-approved
source-study-reference-only
source-study-rejected
```

No source porting starts on `reference-only` or `rejected`.

- [ ] **Step 4: Commit the report**

```powershell
git add docs/v2_mentor/CROSS_PROJECT_FIGMA_EFFECT_BENCHMARK_2026-10-28.md
git commit -m "docs: compare cross-project Figma effects"
```
