# DOM Asset Strategy Fusion Report

**Task:** D-007  
**Status:** `complete-current-scope / contract-report`  
**Date:** 2026-10-25  
**Corpus:** `dom-quality-real-sites/1.0`  
**Input:** `output/_dom_asset_quality_2026-10-25/summary.json`  
**Report:** `output/_dom_strategy_fusion_2026-10-25/summary.json`

## Result

The production fusion policy now evaluates every D-006 asset use with:

1. verified DOM source identity;
2. verified recovered network source identity;
3. screenshot crop marked `reference-only`;
4. generated approximation with complete provenance;
5. explicit missing display.

Identity and display remain independent decisions:

| Decision | Uses |
|---|---:|
| Verified source identity selected | 46 |
| Reference-only identity | 46 |
| Source identity unavailable | 132 |
| Source identity missing | 3 |
| Screenshot crop selected for display | 227 |
| Generated display selected | 0 |
| Missing display | 0 |
| Total decisions | 227 |

All 227 D-006 uses appear exactly once in the D-007 replay.

This is a strategy/contract report. It does not claim a real Figma runtime
replacement or visual pass.

## Frozen Inputs

```text
corpus_sha256:
edec396946c03755fabbdea70e6ab210d5a0516b3eef7034c218386f8e45f4ef

thresholds_sha256:
6dd4f29ed90041bb5fbd7912d8c772603279c27f114896dbc2c04f832251d8a2
```

No D-003 threshold, manifest baseline or D-006 source record was changed.

## Identity Selection

The verified-source count is measured in uses, not unique assets. D-006 has 42
unique byte-verified source assets; shared use expands those identities to 46
DOM uses.

| Fusion status | Uses |
|---|---:|
| Resolved source plus captured display | 46 |
| Partial unresolved identity plus captured display | 181 |

The 181 unresolved identities comprise:

- 46 reference-only network URL uses;
- 132 inline SVG uses without captured source bytes;
- 3 missing image uses.

Screenshot display survives all 181 unresolved-identity cases. That supports
visual partial delivery without promoting the crop to original identity.

## Display Selection

All 227 uses have a captured screenshot crop, so the generated tier is not
reached:

| Fallback chain | Uses |
|---|---:|
| `recovered-network > screenshot-crop` | 46 |
| `reference-only > screenshot-crop` | 46 |
| `unavailable > screenshot-crop` | 132 |
| `missing > screenshot-crop` | 3 |

Screenshot crop records retain:

- `original=false`;
- `reference_only=true`;
- generated status `false`;
- payload and screenshot hashes;
- display box, source rectangle and object-fit mapping where available.

No missing display was hidden by a generated placeholder.

## Generated Approximation Contract

The frozen corpus contains no generated asset candidates:

```text
requested_uses: 0
selected_uses: 0
original_uses: 0
replaceable_uses: 0
```

An explicit generated candidate is eligible for display only when the captured
display is missing and all required provenance is non-empty:

```text
generator
model
input_reference
prompt
prompt_version
review_status
payload_sha256
bytes_present=true
```

If any field is missing or the payload hash is invalid, the candidate is
`blocked`; it cannot be selected.

Generated output is always:

```text
original=false
replaceable=false
reference_only=false
generated=true
```

A generated candidate never replaces a verified source identity and never
outranks an available screenshot crop.

## Source Precedence

The implemented policy is:

1. verified DOM source (`dom-source`);
2. verified recovered network source (`recovered-network`);
3. screenshot capture (`screenshot-crop`);
4. complete generated approximation;
5. missing.

The decision record exposes every candidate, its selected/rejected/blocked
state, a reason and a deterministic fallback chain.

## Implementation

- Pure fusion policy:
  `src/app/services/structure/asset_fusion.py`;
- DesignSpec integration:
  `src/app/services/som/direct_design.py`;
- generated-aware acceptance:
  `src/app/services/rendering/figma_acceptance.py`;
- frozen corpus replay:
  `src/app/services/evidence/dom_strategy_fusion.py`;
- report CLI:
  `scripts/dom_strategy_fusion.py`;
- tests:
  `tests/v2/test_asset_fusion.py`,
  `tests/v2/test_dom_strategy_fusion.py`,
  `tests/v2/test_p1_asset_metadata.py`,
  `tests/v2/test_p1_figma_acceptance.py`.

## Reproduce

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_strategy_fusion.py `
  --asset-report output\_dom_asset_quality_2026-10-25\summary.json `
  --out output\_dom_strategy_fusion_2026-10-25
```

Report hash:

```text
summary.json SHA-256:
a2eaf3b3bb1fed100cbd91dfe73356385b377315fa3d9c2f9de1a2a773b58118
```

## Verification

Focused tests:

```text
python -m pytest tests/v2/test_asset_fusion.py
tests/v2/test_dom_strategy_fusion.py tests/v2/test_p1_asset_metadata.py
tests/v2/test_p1_figma_acceptance.py -q
```

Final mandatory regression:

```text
python -m pytest tests/v2 -q
606 passed in 34.31s

node --check figma_bridge/code.js
exit 0
```

## Remaining Boundaries

- The corpus has no generated candidates, so the generated branch is verified
  only by controlled contract tests.
- D007 does not invoke an image generator or create approximation bytes.
- Screenshot crops remain the current display payload even when a verified
  source identity exists.
- Real Figma write, fill replacement, readback and export remain D-008 work.
- Unknown text is not synthesized by this policy.
- Inline SVG source markup and effect semantics remain outside this task.

## Non-Claims

This report does not claim:

- generated output is original or replaceable;
- a screenshot crop is an original asset;
- the frozen corpus exercised a real generated fallback;
- real Figma replacement passed;
- arbitrary real-site asset coverage;
- project-wide `verified=true`;
- production admission.
