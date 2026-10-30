# DOM Semantic Component Result - 2026-10-29

## Summary

The DOM semantic layer is implemented end to end:

- deterministic navigation/list/card/button/link classification with evidence;
- repeated list/card/control pattern inference;
- detector/VLM merge with DOM authority preserved;
- optional semantic metadata and Figma plugin data;
- rollback-safe optional componentization;
- a six-page semantic benchmark covering the four P1 regression pages and two valid
  holdouts.

The semantic metadata layer does not change visual geometry. Across all six pages,
geometry, style, element count, and paint order were identical before and after applying
semantic groups.

The tightened semantic metadata layer is enabled by default after all six benchmark pages
passed. Component instance generation remains opt-in because only two real repeated button
groups met the strict geometry and structural-signature requirements.

## Four Regression Pages

All four P1 Figma visual readbacks pass. Semantic classification was evaluated from the
same frozen DOM captures.

| Page | Navigation | List | Card | Button | Link | Review candidates | Geometry | Visual |
|---|---:|---:|---:|---:|---:|---:|---|---|
| IT之家 | 6 | 5 | 0 | 7 | 27 | 0 | invariant | pass |
| 21ic | 2 | 37 | 4 | 33 | 261 | 0 | invariant | pass |
| 国家数据 | 1 | 2 | 0 | 18 | 16 | 0 | invariant | pass |
| 小米 | 3 | 0 | 0 | 2 | 51 | 0 | invariant | pass |

The tightened rules remove the previously observed share/ranking/title navigation groups
and the small-avatar card rows. No deterministic false-positive candidates remain on the
four regression pages.

## Holdouts

The two valid unseen holdouts were frozen before capture and use the existing P1
visual-passing Figma readbacks.

| Page | Navigation | List | Card | Button | Link | Review candidates | Geometry | Visual |
|---|---:|---:|---:|---:|---:|---:|---|---|
| Rust | 2 | 3 | 0 | 10 | 1 | 0 | invariant | pass |
| PostgreSQL | 1 | 20 | 0 | 20 | 26 | 0 | invariant | pass |

Neither holdout has a deterministic semantic false-positive signal. Wikipedia remains
excluded because its frozen network capture still times out; semantic success is not
claimed for a page that did not pass capture.

## False-Positive Review

The following checks are deterministic and retained per page:

- table/list/card confusion;
- duplicate semantic bounds;
- unstyled links classified as buttons;
- large inferred navigation regions;
- navigation containers whose identity indicates share, ranking, title, footer, or
  information groups;
- cards whose only visual asset is a small icon or avatar.

After tightening the classifier:

- table-derived navigation/card candidates: `0`;
- unstyled-link button candidates: `0`;
- duplicate semantic bounds: `0`;
- small visual card review candidates: `0`;
- navigation-specificity/large-region review candidates: `0`.

The same fixture negative cases cover inconsistent spacing, mixed positioning modes,
two generic siblings, table cells, navigation-list items, CTA rows, and wrappers around
explicit navigation.

## Componentization

`DOM_SEMANTIC_COMPONENTS=true` and `DOM_SEMANTIC_COMPONENT_INSTANCES=false`.

Fixture tests verify:

- two identical controls become one master plus one instance;
- three identical cards become one master plus two instances;
- mismatched structural signatures are rejected;
- missing nodes return a typed rejection;
- an instance/member failure rolls back the group and leaves all source nodes visible.

The six real-page captures produced one button group on 国家数据 and one on PostgreSQL
that met the strict repeated geometry and structural-signature requirements. Two groups
across two pages are not enough breadth to enable instance generation by default, so it
remains blocked until more real pages and component roles produce proven groups.

## Reproduction

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_semantic_components.py `
  tests/v2/test_component_patterns.py `
  tests/v2/test_semantic_merge.py `
  tests/v2/test_semantic_design_integration.py `
  tests/v2/test_semantic_figma_components.py `
  tests/v2/test_dom_semantic_benchmark.py -v

C:\Users\lzq\.conda\envs\omni\python.exe scripts/dom_semantic_benchmark.py `
  --case "IT之家=output/_dom_visual_benchmark_20261029/it-home-r2=output/_dom_visual_ab_it_scale1_20261030/dom-visual-ab.json" `
  --case "21ic=output/_dom_visual_benchmark_20261029/bbs21=output/_dom_visual_ab_bbs21_scale1_20261030/dom-visual-ab.json" `
  --case "国家数据=output/_dom_visual_benchmark_20261029/stats=output/_dom_visual_ab_stats_scale1_20261030/dom-visual-ab.json" `
  --case "小米=output/_dom_visual_benchmark_20261029/xiaomi=output/_dom_visual_ab_xiaomi_scale1_20261030/dom-visual-ab.json" `
  --case "Rust=output/_dom_visual_benchmark_20261029/holdout-rust=output/_dom_visual_benchmark_20261029/holdout-results.json" `
  --case "PostgreSQL=output/_dom_visual_benchmark_20261029/holdout-postgres-r2=output/_dom_visual_benchmark_20261029/holdout-results.json" `
  --out output/_dom_semantic_benchmark_20261031/dom-semantic-benchmark.json
```

## Decision

- DOM-only semantic classifier: adopted; `DOM_SEMANTIC_COMPONENTS=true`
- Repeated list/card patterns: rejected for default use; retained experimental
- Detector merge: adopted; DOM authority tests pass
- Figma component instances: rejected for now; only two real button groups are proven
- Default behavior changed: yes for semantic names and plugin metadata; visual geometry
  is unchanged
- False-positive risks: repeated-pattern support is thin outside PostgreSQL; navigation
  inference still requires continued regression as new page layouts appear
- Reproduction commands: listed above
