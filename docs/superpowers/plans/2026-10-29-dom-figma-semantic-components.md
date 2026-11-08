# DOM to Figma Semantic Components Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recognize and represent navigation, cards, lists, and buttons from captured DOM evidence without changing visual geometry or allowing screenshot/VLM guesses to outrank DOM semantics.

**Architecture:** Add a deterministic semantic layer after P0 replay and before/alongside DesignSpec layout planning. Classify components from tags, ARIA roles, direct-child patterns, repeated geometry, and text/asset structure; attach `semanticRole`, confidence, evidence, and stable group IDs; optionally convert repeated groups into Figma components behind a strict feature flag.

**Tech Stack:** Python 3.11, captured `00_dom.json`/`00_layer_tree.json`, PageGraph/DesignSpec, existing `layout_infer`/`layout_plan`, existing component detector as secondary evidence, pytest, Figma bridge.

**Spec:** `docs/superpowers/plans/2026-10-29-dom-figma-capture-replay-hardening.md`, `docs/superpowers/plans/2026-10-29-dom-figma-visual-fidelity.md`, and the existing detection modules under `src/app/services/detection/`.

**Prerequisite:** Complete P0 Tasks 1-3. Semantic integration should run on a reproducible capture bundle, not on a fresh ad hoc browser session.

## Global Constraints

- DOM tags, ARIA roles, explicit class/role hints, parent-child structure, and repeated browser-measured geometry are authoritative.
- Screenshot detection and VLM output may add candidates but must not override high-confidence DOM evidence.
- Semantic recognition must not move, resize, restyle, or repaint any element.
- A component classification without evidence must remain `unknown`.
- Repeated-pattern inference requires at least three list items or two repeated controls; two arbitrary sibling boxes are not a list.
- Component instance generation is off by default and must preserve a one-to-one mapping between source DOM nodes and rendered nodes.
- Figma component-master creation must never be required for a basic successful render.
- All semantic artifacts are versioned and deterministically ordered.
- Keep the dirty worktree intact and stage only files named by the current task.

## Review Focus

- A navigation bar made from `<div>` and links: it must be recognized by role, direct-link count, and horizontal geometry, not tag alone.
- A three-card content grid: cards and the parent list/grid must be separate semantic nodes without duplicating the same bounds.
- A table row mistaken for a card: repeated cells and table semantics must block card inference.
- A link styled as text mistaken for a button: interactive role alone is insufficient; geometry, background, border, and label structure must be recorded.
- Semantic grouping changes paint order or text geometry: the visual hash must remain unchanged.
- Repeated cards differ in text or image count: they may group as a list but must not become one component signature unless shared structure is proven.

---

## File Map

| File | Responsibility |
|---|---|
| `src/app/services/structure/semantic_components.py` | Schema and deterministic role classifier |
| `src/app/services/structure/component_patterns.py` | Repeated list/card/button/nav pattern inference |
| `src/app/services/structure/semantic_merge.py` | Merge DOM, existing detector, and optional VLM candidates |
| `src/app/services/rendering/semantic_groups.py` | Attach roles and group IDs to DesignSpec |
| `src/app/services/rendering/adapter_base.py` | Preserve semantic metadata during rendering |
| `src/app/services/rendering/figma_adapter.py` | Optional componentization commands |
| `figma_bridge/code.js` | Create/read component and instance groups |
| `scripts/dom_semantic_benchmark.py` | Four-page semantic benchmark and false-positive report |
| `tests/v2/test_semantic_components.py` | Role classifier tests |
| `tests/v2/test_component_patterns.py` | Repeated pattern tests |
| `tests/v2/test_semantic_merge.py` | Authority and merge tests |
| `tests/v2/test_semantic_design_integration.py` | Grouping and geometry invariance tests |
| `tests/v2/test_semantic_figma_components.py` | Optional componentization tests |
| `tests/v2/test_dom_semantic_benchmark.py` | Benchmark aggregation tests |

---

### Task 1: Define semantic roles and evidence fields

**Files:**
- Create: `src/app/services/structure/semantic_components.py`
- Create: `tests/v2/test_semantic_components.py`
- Create: `tests/fixtures/dom_semantics/semantic_fixture.html`

**Interfaces:**
- Consumes: flat DOM nodes, layer tree, boxes, tags, roles, class/ARIA hints, links, buttons, text, and image children.
- Produces:
  - `classify_semantic_components(dom_nodes: Sequence[Mapping[str, Any]], *, layer_tree: Mapping[str, Any] | None = None) -> dict[str, Any]`
  - schema `dom-semantic-components/1.0`
  - roles `navigation`, `list`, `card`, `button`, `link`, `unknown`

- [ ] **Step 1: Add the semantic fixture**

The fixture contains:

- a `nav` element with four links;
- a `<div role="navigation">` with three links;
- a `ul` with three `li` cards;
- a card grid built from three sibling `article` elements;
- two native buttons;
- one bordered link acting as a button;
- a semantic table with rows containing cells;
- an ordinary paragraph link.

- [ ] **Step 2: Write failing role tests**

Assert:

```python
result = classify_semantic_components(nodes)
roles = Counter(item["role"] for item in result["components"])
assert roles["navigation"] == 2
assert roles["list"] == 2
assert roles["card"] == 6
assert roles["button"] == 3
assert roles["link"] == 1
assert result["unknownCount"] == 0

for item in result["components"]:
    assert item["evidence"]
    assert 0.0 <= item["confidence"] <= 1.0
    assert item["sourceDomIndices"]
    assert item["bbox"][2] > 0 and item["bbox"][3] > 0
```

Add a malformed fixture case where a `tr` with three `td` children never
classifies as `card`.

- [ ] **Step 3: Implement deterministic classification**

Rules:

- `navigation`: tag `nav`, role `navigation`, or a container with at least
  three direct link descendants, horizontal centers within 24px, and no
  vertical card-like repetition.
- `button`: tag `button`, role `button`, or interactive element with visible
  text and at least two of border/background/minimum 28px height.
- `list`: tag `ul/ol`, role `list`, or at least three sibling nodes sharing
  tag/class signature and equal-axis spacing within 2px.
- `card`: tag `article`, role `article`, or a child of a recognized list with
  at least one image/visual asset and at least one text block.
- `link`: interactive `a` not satisfying button evidence.
- `unknown`: all remaining candidates.

Each output includes:

```json
{
  "id": "semantic-n4",
  "role": "navigation",
  "confidence": 0.95,
  "sourceDomIndices": [4],
  "bbox": [0, 0, 1440, 64],
  "evidence": [
    {"kind": "tag", "value": "nav", "weight": 1.0},
    {"kind": "direct-link-count", "value": 4, "weight": 1.0},
    {"kind": "horizontal-line", "value": true, "weight": 0.5}
  ]
}
```

- [ ] **Step 4: Add capture hints only where explicit**

Extend `DOM_JS` with `semanticHints` for explicit HTML:

```text
landmark: nav/main/aside/footer/header
ariaRole
ariaLabel
listType
```

Do not add CSS-class-based labels directly to the final semantic result; classes
are supporting hints only.

- [ ] **Step 5: Run semantic classifier tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_semantic_components.py `
  tests/v2/test_layout_hierarchy_frames.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit semantic roles**

```powershell
git add src/app/services/structure/semantic_components.py `
        tests/v2/test_semantic_components.py `
        tests/fixtures/dom_semantics/semantic_fixture.html
git commit -m "feat: classify DOM semantic roles"
```

---

### Task 2: Infer repeated list, card, and control patterns

**Files:**
- Create: `src/app/services/structure/component_patterns.py`
- Modify: `src/app/services/structure/semantic_components.py`
- Create: `tests/v2/test_component_patterns.py`

**Interfaces:**
- Consumes: classified semantic components, sibling structure, and boxes.
- Produces:
  - `infer_component_patterns(dom_nodes: Sequence[Mapping[str, Any]], semantic: Mapping[str, Any]) -> dict[str, Any]`
  - `componentSignatures` and `groups`
  - schema `dom-component-patterns/1.0`

- [ ] **Step 1: Write failing repeated-pattern tests**

Assert:

```python
patterns = infer_component_patterns(nodes, semantic)
assert patterns["groups"]["list-0"]["role"] == "list"
assert len(patterns["groups"]["list-0"]["members"]) == 3
assert patterns["groups"]["list-0"]["axis"] == "x"
assert patterns["groups"]["list-0"]["gap"] == 24
assert patterns["groups"]["card-set-0"]["structuralSignature"] == (
    "visual:1|text:2|interactive:1"
)
assert len(patterns["groups"]["button-set-0"]["members"]) == 2
```

Add negative tests:

- spacing differs by more than 2px;
- one candidate is absolutely positioned while siblings are in flow;
- same width/height but different semantic roles;
- only two repeated generic boxes.

- [ ] **Step 2: Implement repeated sibling signatures**

A repeat signature includes:

```text
tag
stable class token set
semantic role
child-role counts
visual-asset count bucket
text-block count bucket
interactive-child count
position mode
```

Do not include text content, URL paths, or image hashes in the structural
signature; those are instance overrides.

- [ ] **Step 3: Implement axis and gap checks**

For two or more adjacent members:

- sort by `x` or `y`;
- require consistent reading order;
- require gaps within 2px;
- require overlap on the cross axis of at least 60%;
- mark horizontal, vertical, or grid.

Grid detection may use row and column bands, but must fail closed to a list of
rows when the grid cannot be proven.

- [ ] **Step 4: Merge classifier and pattern results**

Enrich semantic items with:

- `groupId`;
- `groupRole`;
- `memberIndex`;
- `memberCount`;
- `structuralSignature`.

Resolve duplicate bounds by preferring the strongest explicit role evidence,
then the higher confidence, then the smaller deterministic source index.

- [ ] **Step 5: Run pattern tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_component_patterns.py `
  tests/v2/test_semantic_components.py `
  tests/v2/test_dom_layout_quality.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit repeated patterns**

```powershell
git add src/app/services/structure/component_patterns.py `
        src/app/services/structure/semantic_components.py `
        tests/v2/test_component_patterns.py
git commit -m "feat: infer repeated DOM component patterns"
```

---

### Task 3: Merge detector evidence without overriding DOM semantics

**Files:**
- Create: `src/app/services/structure/semantic_merge.py`
- Modify: `src/app/services/detection/component_detector.py`
- Create: `tests/v2/test_semantic_merge.py`

**Interfaces:**
- Consumes: DOM semantic result and optional image-detector or VLM candidates.
- Produces:
  - `merge_semantic_candidates(dom_semantics: Mapping[str, Any], external_candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]`
  - authority states `dom-explicit`, `dom-inferred`, `detector-match`, `review-required`

- [ ] **Step 1: Write failing authority tests**

Assert:

- a detector `button` cannot override an explicit DOM `link` with no button evidence;
- a detector `card` can fill an `unknown` DOM node but remains low confidence;
- exact IoU >= 0.94 plus matching role produces `detector-match`;
- a 0.5 IoU candidate is `review-required`, not auto-merged;
- a VLM title is stored as evidence but cannot change the role when explicit DOM evidence exists.

- [ ] **Step 2: Implement deterministic merge**

Matching uses 3D/2D box IoU plus role and source priorities. Exact thresholds:

```text
auto-merge IoU >= 0.94 and same role
overlap review IoU >= 0.70 and < 0.94
no merge below 0.70
```

DOM explicit and DOM inferred authorities always outrank detector evidence.

- [ ] **Step 3: Persist the merge result**

Write `20_semantic_components.json` in the run output. It includes:

- DOM-only components;
- detector-only candidates;
- merged components;
- review-required candidates;
- counts by role and authority.

- [ ] **Step 4: Run authority regressions**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_semantic_merge.py `
  tests/v2/test_image_route_fallback.py `
  tests/v2/test_image_strategy.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit semantic merging**

```powershell
git add src/app/services/structure/semantic_merge.py `
        src/app/services/detection/component_detector.py `
        tests/v2/test_semantic_merge.py
git commit -m "feat: merge semantic candidates with DOM authority"
```

---

### Task 4: Attach semantic roles to DesignSpec without changing pixels

**Files:**
- Create: `src/app/services/rendering/semantic_groups.py`
- Modify: `src/app/services/som/direct_design.py`
- Modify: `src/app/services/rendering/layout_plan.py`
- Modify: `src/app/services/rendering/adapter_base.py`
- Modify: `src/config/settings.py`
- Create: `tests/v2/test_semantic_design_integration.py`

**Interfaces:**
- Consumes: `20_semantic_components.json`, PageGraph, and DesignSpec.
- Produces:
  - `apply_semantic_groups(design: dict[str, Any], semantics: Mapping[str, Any]) -> dict[str, Any]`
  - element fields `semanticRole`, `semanticGroupId`, `semanticConfidence`, `semanticEvidence`
  - stable frame names `Nav / Card / List / Button`

- [ ] **Step 1: Write geometry-invariance tests**

Render the same fixture twice:

```python
baseline = build_direct_design(som, profile, dom)
semantic = apply_semantic_groups(copy.deepcopy(baseline), semantics)
assert geometry_hash(baseline) == geometry_hash(semantic)
assert style_hash(baseline) == style_hash(semantic)
assert paint_order(baseline) == paint_order(semantic)
```

Assert semantic fields exist only when the feature flag is enabled.

- [ ] **Step 2: Apply groups to DesignSpec**

Map `domIndex` to semantic results and attach metadata to:

- the representative container;
- synthesized Auto Layout frame names;
- button/link text elements;
- card/list group shells.

Naming examples:

```text
Nav / Primary
List / Article grid
Card / Article 1
Button / Search
```

Do not create additional visible containers. Group shells remain transparent
and are created only when the existing layout plan already needs a Frame.

- [ ] **Step 3: Propagate metadata through rendering**

`adapter_base` carries semantic metadata into the render action but does not
change geometry. The Figma bridge stores it in plugin data:

```text
figma_auto_agent.semantic_role
figma_auto_agent.semantic_group_id
figma_auto_agent.semantic_confidence
```

- [ ] **Step 4: Add a disabled-by-default flag**

Add `dom_semantic_components`, env `DOM_SEMANTIC_COMPONENTS`, default `false`.
When false, do not read `20_semantic_components.json` and preserve existing
DesignSpec bytes.

- [ ] **Step 5: Run DesignSpec and renderer tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_semantic_design_integration.py `
  tests/v2/test_direct_design_canvas.py `
  tests/v2/test_layout_hierarchy_frames.py `
  tests/v2/test_dom_control_text_anchor.py -v
```

Expected: all pass and geometry hashes are unchanged.

- [ ] **Step 6: Commit DesignSpec semantic groups**

```powershell
git add src/app/services/rendering/semantic_groups.py `
        src/app/services/som/direct_design.py `
        src/app/services/rendering/layout_plan.py `
        src/app/services/rendering/adapter_base.py `
        src/config/settings.py `
        tests/v2/test_semantic_design_integration.py
git commit -m "feat: attach semantic groups to DOM DesignSpec"
```

---

### Task 5: Add optional Figma component instances for proven repeated groups

**Files:**
- Modify: `src/app/services/rendering/figma_adapter.py`
- Modify: `figma_bridge/code.js`
- Modify: `src/config/settings.py`
- Create: `tests/v2/test_semantic_figma_components.py`

**Interfaces:**
- Consumes: rendered node IDs plus semantic group IDs/signatures.
- Produces:
  - bridge action `componentize_semantic_groups`
  - adapter method `componentize_semantic_groups(groups: Sequence[Mapping[str, Any]]) -> dict[str, Any]`
  - setting `dom_semantic_component_instances`, env `DOM_SEMANTIC_COMPONENT_INSTANCES`, default `false`

- [ ] **Step 1: Write failing componentization tests**

Test groups:

- two identical buttons produce one master plus one instance;
- three cards with identical structural signatures produce one master plus two
  instances;
- cards with different structural signatures are grouped but not componentized;
- missing node ID returns a typed rejection without deleting any rendered node;
- a partial failure leaves the original rendered nodes intact.

- [ ] **Step 2: Implement a safe componentization strategy**

The bridge must:

1. validate every node ID exists and is a FRAME or GROUP;
2. create component masters under a dedicated page named `DOM Components`;
3. keep the rendered source node in place;
4. expose instance overrides for text and image content;
5. only switch a rendered repeated node to an instance after the instance has
   been created and geometry-verified;
6. roll back the entire group on failure.

Do not move or consume the original rendered node until replacement succeeds.

- [ ] **Step 3: Preserve editability and provenance**

Instance plugin data records:

```text
master_id
group_id
source_dom_indices
structural_signature
override_fields
```

Text overrides and image payloads map back to captured DOM node IDs.

- [ ] **Step 4: Expose component results**

Write `21_semantic_components_figma.json` with:

```json
{
  "status": "committed",
  "masters": [],
  "instances": [],
  "rejected": [],
  "geometry_checks": []
}
```

- [ ] **Step 5: Run bridge/component tests**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_semantic_figma_components.py `
  tests/v2/test_figma_bridge_text_metrics.py `
  tests/v2/test_figma_adapter_edits.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit optional componentization**

```powershell
git add src/app/services/rendering/figma_adapter.py `
        figma_bridge/code.js `
        src/config/settings.py `
        tests/v2/test_semantic_figma_components.py
git commit -m "feat: componentize proven repeated semantic groups"
```

---

### Task 6: Benchmark semantic quality and false positives

**Files:**
- Create: `scripts/dom_semantic_benchmark.py`
- Create: `tests/v2/test_dom_semantic_benchmark.py`
- Create: `docs/v2_mentor/DOM_SEMANTIC_COMPONENT_RESULT_2026-10-29.md`

**Interfaces:**
- Consumes: four P0 capture bundles, P1 visual results, semantic artifacts, and Figma readback.
- Produces: `dom-semantic-benchmark.json` and a human-readable adoption decision.

- [ ] **Step 1: Write the failing aggregation test**

Use synthetic page rows and assert the report preserves:

- per-role counts;
- false-positive candidates;
- unknown count;
- groups that were not componentized;
- geometry-invariance result;
- feature-flag state.

Do not calculate a single aggregate score that can hide false cards/buttons.

- [ ] **Step 2: Implement the benchmark driver**

The CLI accepts repeated:

```text
--case name=<page>=<bundle-dir>=<figma-readback-json>
```

It writes deterministic per-page and aggregate JSON.

- [ ] **Step 3: Run the four regression pages**

Report:

```text
IT之家 navigation/cards/lists/buttons
21ic navigation/lists/buttons
国家数据 navigation/lists/buttons and table false positives
小米 navigation/cards/lists/buttons and region-redirect failure separation
```

Do not count semantic success on a page rejected by P0 redirect quality.

- [ ] **Step 4: Run at least two unseen pages**

Each semantic result must include manual or deterministic evidence review for:

- false cards;
- missed navigation;
- table/list confusion;
- duplicate semantic bounds;
- unstyled links classified as buttons.

- [ ] **Step 5: Write the result document**

The document must end with:

```markdown
## Decision

- DOM-only semantic classifier: adopted / rejected
- Repeated list/card patterns: adopted / rejected
- Detector merge: adopted / rejected
- Figma component instances: adopted / rejected
- Default behavior changed: yes/no
- False-positive risks:
- Reproduction commands:
```

- [ ] **Step 6: Run final semantic regressions**

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_semantic_components.py `
  tests/v2/test_component_patterns.py `
  tests/v2/test_semantic_merge.py `
  tests/v2/test_semantic_design_integration.py `
  tests/v2/test_semantic_figma_components.py `
  tests/v2/test_dom_semantic_benchmark.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit benchmark and decision**

```powershell
git add scripts/dom_semantic_benchmark.py `
        tests/v2/test_dom_semantic_benchmark.py `
        docs/v2_mentor/DOM_SEMANTIC_COMPONENT_RESULT_2026-10-29.md
git commit -m "docs: record DOM semantic component results"
```
