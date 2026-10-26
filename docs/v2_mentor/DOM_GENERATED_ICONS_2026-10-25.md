# D-012 Generated Icons And Product Scope

**Task:** D-012  
**Status:** `complete-current-scope / pass`  
**Date:** 2026-10-25  
**Sample:** `DQ-R02` Dushu  
**Frame:** `76:4335`  
**Run root:** `output/_dom_figma_generated_icons_2026-10-25_r1/`

## Result

The approved product policy is now applied end to end:

- 10 unresolved iconfont uses received generated similar icons;
- 6 unique transparent PNGs cover the 10 uses;
- every generated icon has complete provenance and payload SHA-256;
- generated icons are `original=false`, `reference_only=false`,
  `generated=true` and `replaceable=false`;
- screenshot crops remain retained as source comparison evidence;
- final glyph identity is `not-evaluated` in evidence and `not-required` in
  the product gate.

The complete DQ-R02 Figma acceptance is:

```text
overall_status: pass
export_allowed: true
visual: pass
structure: pass
edit: pass
asset: pass
text: pass
```

## Generated Icons

The icon generators are code-native LLM-authored PNG drawings, not original
image bytes:

| Semantic | Uses | Generated candidates |
|---|---:|---:|
| search | 1 | 1 |
| user | 1 | 1 |
| bookshelf | 1 | 1 |
| chevron-right | 7 | 3 size/color variants |
| Total | 10 | 6 unique PNG files |

Provenance:

```text
generator: codex-pillow-icon-v1
model: gpt-5-codex
prompt_version: d012.1
review_status: accepted-product-policy
```

The generated candidate is selected ahead of the screenshot crop only for
`source_kind=icon-crop`. Original and generated accounting remain separate.

## Product Quality

The approved 90% product bar is satisfied:

```text
pixels within max-channel delta 30: 97.5138%
content: pass
structure: pass
text box: pass
linebreak: pass
projected baseline: pass
```

Frozen visual thresholds remain unchanged:

```text
mean: 1.727879 <= 3.0
ink mean: 9.378094 <= 100
over-30: 2.486242% <= 2.5%
bad pixels: 2.486242% <= 3%
size: exact match
```

Final glyph outline identity is not required for this scope. The evidence still
states `not-evaluated`; it is not claimed as verified.

## Real Figma Evidence

```text
origin: [22000, 0]
canvas: 1440x2544
readback nodes: 516
Auto Layout nodes observed: 102
```

Artifact hashes:

```text
export.png:
05974f4ce4b6696883c5ce8c84f45d8a3402ac57b3eaf2ef8c1d959aa97d0e55

readback.json:
16b61b380439dd46b101ffb23b5c5c5daee81ea11cedf9d45a73aec2f5ff3a16

design.json:
75e6673d3b6a6c433016a91d291c5eed2382fbbaf01cd9243cd9422f45b15b53

acceptance.json:
4068aa213175bdecb7ac7eb2eab83532a379b5fcd684d110d435ed8a32714fb0

generated_icons.json:
5488d6391ad7e7ccd2da779d7976ea5bf9518647c546797b6cd80a45925e94d3
```

## Implementation

- generated icon assets:
  `src/app/services/structure/generated_icon_recovery.py`;
- explicit icon-crop fusion preference:
  `src/app/services/structure/asset_fusion.py`;
- glyph policy mapping:
  `src/app/services/rendering/text_wrap.py`,
  `src/app/services/rendering/figma_acceptance.py`,
  `src/app/services/evidence/dom_figma_text_metrics.py`;
- preparation integration:
  `scripts/dom_figma_acceptance.py`,
  `src/app/services/evidence/dom_figma_acceptance.py`;
- tests:
  `tests/v2/test_generated_icon_recovery.py`,
  `tests/v2/test_asset_fusion.py`,
  `tests/v2/test_p1_figma_acceptance.py`,
  `tests/v2/test_dom_figma_acceptance.py`.

## Verification

```text
python -m pytest tests/v2 -q
648 passed in 39.01s

ruff format/check: pass
node --check figma_bridge/code.js: exit 0
git diff --check: pass
```

## Claim Boundary

This is a current-scope pass for the frozen DQ-R02 sample and one real Figma
document. It does not claim:

- generated icons are original assets;
- final glyph outline identity;
- arbitrary real-site coverage;
- adaptive Auto Layout propagation;
- project-wide `verified=true`;
- production admission.
