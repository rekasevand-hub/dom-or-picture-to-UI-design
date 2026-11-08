# BuilderIO DOM to Figma Source Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the useful DOM-to-Figma algorithms from BuilderIO/figma-html and port only evidence-backed Python helpers into the existing DOM route, without adding a JavaScript runtime dependency.

**Architecture:** Keep `playwright capture -> PageGraph -> layout inference -> DesignSpec -> Figma bridge` as the product pipeline. Use BuilderIO as a source reference for inline geometry, DOM-derived frame nesting, shape extraction, and Figma property mapping. Any port stays route-scoped, feature-flagged, and must beat or match the current implementation on frozen DOM samples.

**Tech Stack:** Python 3.11, Playwright, pytest, existing PageGraph/rendering modules, Figma bridge.

**Spec:** `README.md`, `HANDOFF_2026-10-27_dom_figma_crosssite_holdout.md`

**Prerequisite:** Complete
`docs/superpowers/plans/2026-10-28-cross-project-figma-effect-benchmark.md`
with a `source-study-approved` decision before starting Task 1 of this plan.

## Global Constraints

- Do not add `@builder.io/html-to-figma`, npm, Node, or a JavaScript subprocess to the production path.
- Use BuilderIO master `2b244343ba3fcc1a2de50fa652e13833e78e36f9` for repository facts and source parent `7fece2560e6ac67814e25c2e6abfadb00211c0e9` for the removed implementation.
- Preserve the MIT notice and record the exact upstream commit in every source-derived file.
- Do not change the default DOM route until a frozen comparison demonstrates no regression.
- Do not reuse LeetCode, 掘金, CSDN, or dushu as new holdout samples.
- Preserve the dirty worktree and stage only files named by the task being executed.
- Keep `requested_route=dom`, `effective_route=dom`, and `fallbacks=[]` for DOM holdout runs.
- Treat BuilderIO behavior as a reference, not as truth; current PageGraph provenance and geometry evidence remain authoritative.

---

### Task 1: Freeze the upstream source and license facts

**Files:**
- Create: `docs/v2_mentor/BUILDERIO_SOURCE_INVENTORY_2026-10-28.md`

**Interfaces:**
- Consumes: BuilderIO GitHub repository and git history.
- Produces: exact commits, license, source-file inventory, removed-file inventory, and non-runtime policy for later tasks.

- [ ] **Step 1: Create a read-only upstream checkout**

Run:

```powershell
$root = Join-Path $env:TEMP 'codex-builderio-adoption'
git clone https://github.com/BuilderIO/figma-html.git $root
git -C $root worktree add --detach "$root-pre-cleanup" 7fece2560e6ac67814e25c2e6abfadb00211c0e9
git -C "$root-pre-cleanup" rev-parse HEAD
```

Expected: the final command prints `7fece2560e6ac67814e25c2e6abfadb00211c0e9`.

- [ ] **Step 2: Capture repository and license facts**

Run:

```powershell
$root = Join-Path $env:TEMP 'codex-builderio-adoption'
git -C $root log -1 --format='%H %ad %s' --date=iso
Get-Content -LiteralPath (Join-Path $root 'LICENSE.md')
git -C $root show --stat --oneline 0f2659c7
```

Expected: commit `2b244343ba3fcc1a2de50fa652e13833e78e36f9`, MIT text, and deleted `lib/html-to-figma` plus `plugin` files.

- [ ] **Step 3: Write the inventory**

Create `docs/v2_mentor/BUILDERIO_SOURCE_INVENTORY_2026-10-28.md` with:

```markdown
# BuilderIO Source Inventory

- Repository: https://github.com/BuilderIO/figma-html
- Current commit: 2b244343ba3fcc1a2de50fa652e13833e78e36f9
- Source-bearing parent: 7fece2560e6ac67814e25c2e6abfadb00211c0e9
- License: MIT
- Runtime policy: source study only; no JavaScript runtime dependency

## Browser source

- `lib/html-to-figma/index.ts`
- `lib/html-to-figma/helpers/dimensions.ts`
- `lib/html-to-figma/helpers/frames.ts`
- `lib/html-to-figma/helpers/image.ts`
- `lib/html-to-figma/helpers/nodes.ts`
- `lib/html-to-figma/helpers/parsers.ts`
- `lib/html-to-figma/helpers/styles.ts`
- `lib/html-to-figma/helpers/svg.ts`
- `lib/html-to-figma/helpers/text.ts`
- `lib/html-to-figma/helpers/url.ts`
- `lib/html-to-figma/types/nodes.ts`

## Figma plugin source

- `plugin/code.ts`
- `plugin/functions/traverse-layers.ts`
- `plugin/functions/encode-images.ts`

## Current repository counterpart

- DOM capture: `src/app/services/structure/capture.py`
- DOM structure: `src/app/services/structure/providers/dom.py`
- PageGraph: `src/app/services/structure/graph.py`
- Layout: `src/app/services/rendering/layout_infer.py`
- Layout plan: `src/app/services/rendering/layout_plan.py`
- Figma adapter: `src/app/services/rendering/figma_adapter.py`
- Figma bridge: `figma_bridge/code.js`
```

- [ ] **Step 4: Verify every listed path**

Run:

```powershell
$root = Join-Path $env:TEMP 'codex-builderio-adoption-pre-cleanup'
$paths = @(
  'lib/html-to-figma/index.ts',
  'lib/html-to-figma/helpers/dimensions.ts',
  'lib/html-to-figma/helpers/frames.ts',
  'lib/html-to-figma/helpers/styles.ts',
  'plugin/code.ts'
)
$paths | ForEach-Object { if (-not (Test-Path (Join-Path $root $_))) { throw $_ } }
```

Expected: no exception.

- [ ] **Step 5: Commit the inventory only**

```powershell
git add docs/v2_mentor/BUILDERIO_SOURCE_INVENTORY_2026-10-28.md
git commit -m "docs: record BuilderIO source inventory"
```

---

### Task 2: Build the feature-gap matrix against the current Python implementation

**Files:**
- Create: `docs/v2_mentor/BUILDERIO_DOM_GAP_MATRIX_2026-10-28.md`

**Interfaces:**
- Consumes: inventory from Task 1 and current Python source.
- Produces: a `port`, `adapt`, or `reject` decision for every candidate feature.

- [ ] **Step 1: Record the matrix rows**

Create the document with these exact rows:

```markdown
# BuilderIO DOM Gap Matrix

| Feature | BuilderIO source | Current Python source | Current tests | Gap decision |
|---|---|---|---|---|
| Inline element aggregate bounds | `helpers/dimensions.ts:3-81` | `providers/dom.py`, `capture.py` | `test_dom_text_bounds.py`, `test_dom_control_text_anchor.py` | adapt |
| DOM-derived frame tree | `helpers/frames.ts:36-260` | `layout_infer.py`, `layout_plan.py` | `test_layout_hierarchy_frames.py` | reject |
| Four-sided borders and radii | `helpers/styles.ts:226-352` | `capture.py`, `providers/dom.py`, `adapter_base.py` | `test_dom_rich_text_runs.py`, Figma adapter tests | reject |
| Background images | `helpers/image.ts:5-70` | `capture.py`, `direct_design.py` | capture and layout tests | reject |
| Shadow effects | `helpers/styles.ts:353-390` | `capture.py`, `figma_bridge/code.js` | Figma adapter tests | reject |
| SVG `<use>` handling | `helpers/svg.ts:3-38` | `capture.py`, generated icon recovery | generated icon tests | reject |
| Text/font matching | `helpers/text.ts`, `plugin/code.ts:576-617` | `text_wrap.py`, `figma_adapter.py`, bridge | rich text and bridge tests | reject |
| Figma property assignment | `plugin/code.ts:517-637` | `figma_adapter.py`, `figma_bridge/code.js` | adapter and bridge tests | reject |
| URL-hosted conversion API | `plugin/ui.tsx` | local-only pipeline | none | reject |

## Decision rules

- `port`: current code lacks the behavior and the upstream implementation is small and evidence-preserving.
- `adapt`: concept is useful but upstream implementation depends on browser globals or Figma APIs.
- `reject`: behavior is already stronger locally, depends on hosted services, or weakens provenance.
```

- [ ] **Step 2: Fill every decision with source evidence**

For each row, inspect both sides and add:

```markdown
**Evidence:** ...

**Decision:** `port` | `adapt` | `reject`

**Reason:** ...

**Planned tests:** exact test file or `none`
```

The table above is the initial decision baseline. Replace each decision only
when source inspection and the parity fixture directly contradict it.

- [ ] **Step 3: Verify the expected outcome**

Run:

```powershell
rg -n "TBD|TODO" docs/v2_mentor/BUILDERIO_DOM_GAP_MATRIX_2026-10-28.md
```

Expected: no matches.

- [ ] **Step 4: Verify all referenced local paths exist**

Run:

```powershell
$paths = @(
  'src/app/services/structure/capture.py',
  'src/app/services/structure/providers/dom.py',
  'src/app/services/rendering/layout_infer.py',
  'src/app/services/rendering/layout_plan.py',
  'src/app/services/rendering/figma_adapter.py',
  'figma_bridge/code.js'
)
$paths | ForEach-Object { if (-not (Test-Path $_)) { throw $_ } }
```

Expected: no exception.

- [ ] **Step 5: Commit the matrix only**

```powershell
git add docs/v2_mentor/BUILDERIO_DOM_GAP_MATRIX_2026-10-28.md
git commit -m "docs: map BuilderIO gaps to current DOM pipeline"
```

---

### Task 3: Create a frozen DOM parity fixture and probe

**Files:**
- Create: `tests/fixtures/dom_builderio_parity/reference.html`
- Create: `tests/fixtures/dom_builderio_parity/expected_features.json`
- Create: `scripts/builderio_dom_parity_probe.py`
- Create: `tests/v2/test_builderio_dom_parity_probe.py`

**Interfaces:**
- Consumes: a DOM capture output directory containing `00_dom.json`.
- Produces: `builderio_parity.json` with counts and booleans for inline text, borders, shadows, background images, SVG `<use>`, clipping, and pseudo gaps.

- [ ] **Step 1: Add the fixture HTML**

Create `tests/fixtures/dom_builderio_parity/reference.html` with:

- one paragraph containing normal text, `<strong>`, `<em>`, and `<code>`;
- one inline span containing two visible child spans;
- four border widths `1px`, `2px`, `3px`, `4px` with four colors;
- a card with `box-shadow` and `border-radius`;
- a div with an inline data-URI background image;
- an SVG `<symbol>` plus `<use>`;
- a button with `::before` and `::after` visual decorations;
- a nested overflow-hidden card.

- [ ] **Step 2: Add expected feature assertions**

Create `tests/fixtures/dom_builderio_parity/expected_features.json`:

```json
{
  "schema_version": "builderio-dom-parity/1.0",
  "text": {
    "must_contain": ["Alpha", "Beta", "Gamma"]
  },
  "border": {
    "must_have_asymmetric_widths": true
  },
  "shadow": {
    "minimum_count": 1
  },
  "background_image": {
    "minimum_count": 1
  },
  "svg_use": {
    "minimum_count": 1
  },
  "clip": {
    "minimum_count": 1
  },
  "pseudo_visual": {
    "must_report_unsupported_or_materialized": true
  }
}
```

- [ ] **Step 3: Write the failing probe test**

Create `tests/v2/test_builderio_dom_parity_probe.py`:

```python
import json
from pathlib import Path

from scripts.builderio_dom_parity_probe import probe_capture


FIXTURE = Path("tests/fixtures/dom_builderio_parity")


def test_probe_reports_required_features():
    result = probe_capture(
        FIXTURE,
        json.loads((FIXTURE / "expected_features.json").read_text("utf-8")),
    )
    assert result["text"]["found"] == ["Alpha", "Beta", "Gamma"]
    assert result["border"]["asymmetric_widths"] is True
    assert result["shadow"]["count"] >= 1
    assert result["background_image"]["count"] >= 1
    assert result["clip"]["count"] >= 1
    assert result["pseudo_visual"]["reported"] is True
```

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_builderio_dom_parity_probe.py -v
```

Expected: FAIL because `probe_capture` does not exist.

- [ ] **Step 4: Implement the probe**

Create `scripts/builderio_dom_parity_probe.py` with:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def _walk(node: Mapping[str, Any]):
    yield node
    for key in ("children", "containers", "elements"):
        value = node.get(key)
        if isinstance(value, list):
            for child in value:
                if isinstance(child, Mapping):
                    yield from _walk(child)


def probe_capture(fixture: Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    dom_path = fixture / "00_dom.json"
    if not dom_path.exists():
        # Fixture mode uses the fixture HTML as the source text until a capture is supplied.
        text = (fixture / "reference.html").read_text("utf-8")
        data: Mapping[str, Any] = {"html": text}
    else:
        data = json.loads(dom_path.read_text("utf-8"))
    nodes = list(_walk(data))
    serialized = json.dumps(data, ensure_ascii=False)
    required_text = expected["text"]["must_contain"]
    return {
        "schema_version": "builderio-dom-parity/1.0",
        "text": {
            "found": [value for value in required_text if value in serialized]
        },
        "border": {
            "asymmetric_widths": all(token in serialized for token in
                                     ["borderTopWidth", "borderRightWidth",
                                      "borderBottomWidth", "borderLeftWidth"])
        },
        "shadow": {
            "count": sum(bool(node.get("boxShadow")) for node in nodes)
        },
        "background_image": {
            "count": serialized.lower().count("background-image")
        },
        "clip": {
            "count": serialized.lower().count("overflow") + serialized.lower().count("clip")
        },
        "pseudo_visual": {
            "reported": "pseudo" in serialized.lower()
            or "::before" in serialized.lower()
            or "::after" in serialized.lower()
        },
        "svg_use": {
            "count": serialized.lower().count("<use")
        },
    }
```

- [ ] **Step 5: Run the unit test**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_builderio_dom_parity_probe.py -v
```

Expected: PASS.

- [ ] **Step 6: Capture the fixture with the real DOM route**

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m src.main `
  --url "file:///D:/LLM-Data/Figma_auto_agent/tests/fixtures/dom_builderio_parity/reference.html" `
  --route dom --tool svg --no-headed-fallback `
  --output-dir "output/_builderio_dom_parity_20261028"
```

Expected: `00_dom.json` and `00_screenshot.png` exist and the page is not `soft_block`.

- [ ] **Step 7: Run the probe against the real capture**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\builderio_dom_parity_probe.py `
  --capture "output/_builderio_dom_parity_20261028" `
  --expected "tests/fixtures/dom_builderio_parity/expected_features.json" `
  --out "output/_builderio_dom_parity_20261028/builderio_parity.json"
```

Expected: JSON is written and any missing feature is named explicitly.

- [ ] **Step 8: Commit the parity fixture and probe**

```powershell
git add tests/fixtures/dom_builderio_parity `
        scripts/builderio_dom_parity_probe.py `
        tests/v2/test_builderio_dom_parity_probe.py
git commit -m "test: add BuilderIO DOM parity fixture"
```

---

### Task 4: Port only approved upstream helpers

**Files:**
- Create: `src/app/services/structure/geometry.py`
- Modify: `src/app/services/structure/providers/dom.py`
- Modify: `src/app/services/structure/providers/base.py`
- Modify: `src/app/agents/precise_agent.py`
- Modify: `src/config/settings.py`
- Create: `tests/v2/test_dom_inline_aggregate_bounds.py`

**Interfaces:**
- Consumes: `aggregate_inline_box(element_box, child_boxes, display) -> list[int] | None`.
- Produces: optional inline aggregate bounds controlled by `DOM_INLINE_AGGREGATE_BOUNDS=false`.

- [ ] **Step 1: Write the failing pure helper test**

Create `tests/v2/test_dom_inline_aggregate_bounds.py`:

```python
from src.app.services.structure.geometry import aggregate_inline_box


def test_inline_parent_uses_child_visual_bounds():
    result = aggregate_inline_box(
        [10, 20, 300, 40],
        [[10, 18, 40, 10], [60, 30, 50, 10]],
        "inline",
    )
    assert result == [10, 18, 300, 22]


def test_inline_parent_does_not_expand_beyond_line_box():
    result = aggregate_inline_box(
        [10, 20, 100, 40],
        [[10, 18, 40, 10], [60, 30, 50, 10]],
        "inline",
    )
    assert result == [10, 18, 100, 22]


def test_block_parent_is_unchanged():
    assert aggregate_inline_box([10, 20, 100, 40], [[0, 0, 10, 10]], "block") == [
        10,
        20,
        100,
        40,
    ]
```

Run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_dom_inline_aggregate_bounds.py -v
```

Expected: FAIL because `geometry.py` does not exist.

- [ ] **Step 2: Implement the helper**

Create `src/app/services/structure/geometry.py`:

```python
from __future__ import annotations

from collections.abc import Sequence


def aggregate_inline_box(
    element_box: Sequence[int],
    child_boxes: Sequence[Sequence[int]],
    display: str,
) -> list[int]:
    """Port BuilderIO's aggregate-inline visual bounds rule."""
    x, _y, width, _height = (int(value) for value in element_box)
    if "inline" not in str(display).lower() or not child_boxes:
        return [int(value) for value in element_box]
    boxes = [tuple(int(value) for value in box) for box in child_boxes if len(box) == 4]
    if not boxes:
        return [int(value) for value in element_box]
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    aggregate_width = right - left
    if width > aggregate_width:
        return [x, top, width, bottom - top]
    return [left, top, aggregate_width, bottom - top]
```

- [ ] **Step 3: Run the helper tests**

Expected: PASS.

- [ ] **Step 4: Add the disabled-by-default config switch**

Add a boolean setting `dom_inline_aggregate_bounds` backed by `DOM_INLINE_AGGREGATE_BOUNDS`, default `false`.

Add the same boolean as `ProviderContext.inline_aggregate_bounds` and pass it
when `PreciseAgent` constructs the DOM provider context.

When enabled, build a parent-to-child index from each captured node's `pIdx`
and replace only the working rectangle used by `_canvas_bbox`:

```python
children_by_parent: dict[int, list[list[int]]] = {}
for child_index, node in enumerate(nodes):
    parent_index = int(node.get("pIdx", -1))
    if parent_index >= 0:
        children_by_parent.setdefault(parent_index, []).append(rects[child_index])

for node_index, node in enumerate(nodes):
    demo_box = [int(node["x"]), int(node["y"]), int(node["w"]), int(node["h"])]
    if ctx.inline_aggregate_bounds:
        demo_box = aggregate_inline_box(
            demo_box,
            children_by_parent.get(node_index, []),
            str(node.get("display") or ""),
        )
```

Use the original node box for clipping, paint, and provenance. Use `demo_box`
only for the text/container geometry candidate.

- [ ] **Step 5: Add an integration test for the flag**

Run the same fixture capture twice:

```text
DOM_INLINE_AGGREGATE_BOUNDS=false
DOM_INLINE_AGGREGATE_BOUNDS=true
```

Write `tests/v2/test_dom_inline_aggregate_integration.py` to assert:

- false: no existing DesignSpec fields change;
- true: only the inline fixture node changes and the saved DOM screenshot remains unchanged.

- [ ] **Step 6: Run the DOM regression suite**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_dom_rich_text_runs.py `
  tests/v2/test_dom_text_bounds.py `
  tests/v2/test_layout_hierarchy_frames.py `
  tests/v2/test_dom_inline_aggregate_bounds.py `
  tests/v2/test_dom_inline_aggregate_integration.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit only if the gate passes**

```powershell
git add src/app/services/structure/geometry.py `
        src/app/services/structure/providers/dom.py `
        src/app/services/structure/providers/base.py `
        src/app/agents/precise_agent.py `
        src/config/settings.py `
        tests/v2/test_dom_inline_aggregate_bounds.py `
        tests/v2/test_dom_inline_aggregate_integration.py
git commit -m "feat: add optional inline aggregate DOM bounds"
```

If the integration comparison does not improve the fixture without regressions, do not commit production integration; keep only the probe and record `reject` in the gap matrix.

---

### Task 5: Run a fresh DOM holdout and write the adoption decision

**Files:**
- Create: `docs/v2_mentor/BUILDERIO_SOURCE_ADOPTION_RESULT_2026-10-28.md`

**Interfaces:**
- Consumes: gap matrix, parity fixture, frozen DOM holdout results.
- Produces: final `adopted`, `reference-only`, or `rejected` list.

- [ ] **Step 1: Freeze a new DOM holdout**

Use 6 unseen URLs not used in prior DOM repairs. Record URL, viewport `1440x900`, DPR `1`, source screenshot SHA-256, DOM SHA-256, DesignSpec SHA-256, and `requested_route=dom`.

- [ ] **Step 2: Run baseline and candidate**

For each sample run:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m src.main `
  --url "<frozen-url>" --route dom --tool svg --no-headed-fallback `
  --output-dir "output/_builderio_adoption/<sample>-<variant>"
```

Variants are `baseline` and `inline-aggregate`.

- [ ] **Step 3: Compare metrics**

Record:

- text bbox error;
- container and child retention;
- wrong text wrapping;
- hierarchy preservation;
- visual difference;
- any changed DOM-to-Figma fields.

- [ ] **Step 4: Write the result**

The document must end with:

```markdown
## Final decision

- Ported source files:
- Adapted concepts:
- Rejected source areas:
- Current default changed: yes/no
- Remaining risks:
- Reproduction commands:
```

- [ ] **Step 5: Commit the result**

```powershell
git add docs/v2_mentor/BUILDERIO_SOURCE_ADOPTION_RESULT_2026-10-28.md
git commit -m "docs: record BuilderIO source adoption decision"
```
