# D-011 Browser-Context Asset Recovery

**Task:** D-011  
**Status:** `complete-current-scope / asset-source-partial`  
**Date:** 2026-10-25  
**Sample:** `DQ-R02` Dushu  
**Frame:** `75:3819`  
**Run root:** `output/_dom_figma_asset_recovery_2026-10-25_r1/`

## Result

Browser-context recovery resolved every listed Dushu image URL that direct
HTTP probing had blocked:

| Asset group | Count |
|---|---:|
| Unique referenced image URLs | 24 |
| URLs recovered with verified bytes | 24 |
| Verified-original image uses | 44 |
| Replaceable original image uses | 44 |
| Remaining unavailable uses | 10 |
| Screenshot-crop displays | 54 |
| Missing displays | 0 |

The 10 remaining uses are not missing image URLs. They are iconfont glyphs
rendered through `::before`, including `icon-search`, `icon-user` and
`icon-arrow-right`. Their current screenshot crops remain valid display
payloads, but they do not have replaceable image source bytes.

## Recovery Method

1. Collect only HTTPS URLs already present in the frozen DesignSpec.
2. Deduplicate by URL.
3. Open the original page in Chromium and request each URL through the same
   browser context with its page Referer and cookies.
4. Reject non-image responses, oversized payloads, decode failures and
   natural-size mismatches.
5. Write bytes under their SHA-256 filename.
6. Recompute fusion with source identity above screenshot display.

The recovery consumed `254,162` bytes across 24 content-addressed files.
No arbitrary URL, private host or generated fallback was admitted.

## Identity Separation

Verified source recovery does not change visual display semantics:

- source identity: `verified-original` for 44 uses;
- display payload: `screenshot-crop` for all 54 uses;
- source replacement: allowed for 44;
- screenshot crop remains `original=false`;
- 10 iconfont glyph crops remain `unavailable` as image sources;
- no display is missing.

## Real Figma Evidence

```text
origin: [20000, 0]
canvas: 1440x2544
readback nodes: 516
mean: 1.708378
ink mean: 9.291356
over-30: 2.463149%
bad pixels: 2.463149%
size match: pass
```

Visual, structure, edit, content, linebreak, text box and projected baseline
remain pass. Text glyph identity remains explicitly not evaluated.

Artifact hashes:

```text
export.png:
add58115d9336bd450ba45483bbb53efa6b7538377a0287d65dbff847f3d7e8a

readback.json:
2adab796635c3db355c99ef53e1c67b3782c0d7d7e180c6916fa019ecc5d78cd

design.json:
a5af206c521678573b97f58a151dd9eb879c36f1a61243ee8ddaea91df85c36a

acceptance.json:
34c14604c4e7b5c0909a2b3f379f15904c52de184930c58054b6314437b7129d

source_probes.json:
189f3f7da96f6d56e403ac27cab0f883cfa36bef9141ba09f48a74c457f5824f
```

## Implementation

- source identity upgrade:
  `src/app/services/structure/asset_metadata.py`;
- browser-context recovery:
  `src/app/services/structure/network_asset_recovery.py`;
- opt-in acceptance preparation:
  `scripts/dom_figma_acceptance.py`,
  `src/app/services/evidence/dom_figma_acceptance.py`;
- tests:
  `tests/v2/test_network_asset_recovery.py`,
  `tests/v2/test_p1_asset_metadata.py`,
  `tests/v2/test_dom_figma_acceptance.py`.

## Verification

```text
python -m pytest tests/v2 -q
643 passed in 38.87s

ruff format/check: pass
node --check figma_bridge/code.js: exit 0
git diff --check: pass
```

## Policy Resolution

D-012 resolved this policy: the 10 iconfont uses remain unavailable as image
sources, but now display LLM-authored generated similar icons with complete
provenance. They are excluded from the required-original image denominator
only because they are classified as `icon-crop`, not because their screenshot
crops were promoted to originals.

## Non-Claims

This report does not claim:

- the 10 iconfont glyphs are replaceable original image assets;
- screenshot crops are originals;
- final glyph identity;
- complete asset identity under the current denominator;
- Stage 1 exit;
- image-phase admission.
