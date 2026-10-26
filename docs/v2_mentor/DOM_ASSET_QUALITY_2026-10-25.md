# DOM Asset Identity And Replacement Report

**Task:** D-006  
**Status:** `complete-current-scope / partial-report`  
**Date:** 2026-10-25  
**Corpus:** `dom-quality-real-sites/1.0`  
**Manifest:** `tests/fixtures/dom_quality/real_site_corpus_v1.json`  
**Capture:** `output/_dom_text_quality_capture_2026-10-25/`  
**Source probes:** `output/_dom_asset_quality_2026-10-25/source_probes.json`  
**Report:** `output/_dom_asset_quality_2026-10-25/summary.json`

## Result

The asset path now keeps six independent facts:

1. original source identity;
2. actual display payload;
3. screenshot crop mapping;
4. missing-asset state;
5. replacement eligibility and mode;
6. asset-use identity and sharing.

The frozen corpus resolves to:

| Result | Count |
|---|---:|
| Asset identities | 203 |
| Display uses | 227 |
| Unique screenshot-crop hashes | 181 |
| Verified original source identities | 42 |
| Reference-only source identities | 26 |
| Inline SVG with unavailable source bytes | 132 |
| Missing source uses | 3 |
| Replaceable assets by retained source bytes | 42 |
| Shared asset identities | 3 |
| Duplicate use IDs | 0 |

The source probe acquired and revalidated `201,318` bytes for 42 unique
remote assets. It did not acquire bytes for 26 references; those remain
`reference-only`.

This is a partial asset report. No screenshot crop is counted as an original,
and replacement eligibility is not a real Figma runtime pass.

## Frozen Inputs

The D-003 inputs were read without changing a threshold:

```text
corpus_sha256:
edec396946c03755fabbdea70e6ab210d5a0516b3eef7034c218386f8e45f4ef

thresholds_sha256:
6dd4f29ed90041bb5fbd7912d8c772603279c27f114896dbc2c04f832251d8a2
```

Source probe policy:

| Limit | Value |
|---|---:|
| Maximum unique assets | 80 |
| Maximum bytes per asset | 2 MiB |
| Maximum retained source bytes | 40 MiB |
| Network timeout | 10 s |
| Private or local hosts | prohibited |
| Supported types | PNG, JPEG, GIF, WebP, SVG |

Each verified row is accepted only after the report re-reads retained bytes,
recomputes SHA-256, detects the actual image type, and checks dimensions against
both the probe and DOM observation.

## Per-Site Evidence

| Site | Assets | Uses | Verified source | Reference-only | Unavailable source | Missing |
|---|---:|---:|---:|---:|---:|---:|
| React | 150 | 153 | 30 | 0 | 118 | 2 |
| Dushu | 25 | 45 | 0 | 24 | 0 | 1 |
| Shoelace | 28 | 29 | 12 | 2 | 14 | 0 |

React contributed 30 verified photograph and SVG source identities. Shoelace
contributed 12 verified image and SVG sources. Dushu returned HTTP 403 for its
24 unique image URLs, so none of its displayed pixels are promoted to original
source bytes.

The 26 failed source probes split as:

| Host | Failed probes | Observed reason |
|---|---:|---|
| Dushu image hosts | 24 | HTTP 403 |
| `img.shields.io` | 2 | timeout / TLS handshake timeout |

These failures are visible and do not reduce the display-use denominator.

## Source Identity

Verified original identity requires:

- retained source bytes;
- recomputed SHA-256;
- detected image MIME;
- positive dimensions;
- MIME and dimension consistency with the source probe;
- dimensions consistent with the DOM for raster images, or aspect-ratio
  consistency for SVG `viewBox` sources.

The 42 verified sources are content-addressed as:

```text
asset:sha256:<source-payload-sha256>
```

An unverified URL is content-free as an original claim. It is recorded as:

```text
asset:ref:<sha256-normalized-url>
```

Inline SVG nodes without captured source markup remain `unavailable`. They
have screenshot crops for visual evidence, not source identity.

## Display Payload And Crop

All 227 display uses have an actual PNG screenshot-crop payload hash.

```text
display_payload.kind = screenshot-crop
display_payload.original = false
display_payload.reference_only = true
```

The crop hash is computed from the encoded PNG that the DOM direct-design path
would send to an image fill. It is not the source image hash.

Crop mapping is partial:

| Mapping result | Uses |
|---|---:|
| Source rectangle available | 83 |
| Source rectangle unavailable | 144 |

The unavailable group consists mainly of inline SVG without captured source
bytes and missing images. No guessed source rectangle is inserted.

## Missing Assets

Three `<img>` uses have no loaded source dimensions. They remain in the report:

| Use | Display box |
|---|---|
| `DQ-R01:468:img` | `[746, 3328, 558, 40]` |
| `DQ-R01:713:img` | `[746, 4581, 558, 40]` |
| `DQ-R02:16:img` | `[525, 54, 415, 46]` |

Their outcome is `partial-not-pass`, matching the frozen asset threshold. They
are not silently excluded and their screenshot regions are still reference-only
display evidence.

## Replacement Semantics

Replacement is allowed only when verified original source bytes are retained.

| Mode | Assets |
|---|---:|
| `source-bytes` | 42 |
| `none` | 161 |

The contract records:

```text
replacement.figma_runtime = not-evaluated
```

No screenshot crop is replaceable as an original. A source can be eligible for
replacement while the current visual payload is a screenshot crop; those two
facts remain separate in the record.

Real Figma fill replacement, readback, restore and export remain D-008 work.

## Use Identity

Asset and use identities are independent:

```text
asset:sha256:<source-hash>       one verified source identity
<sample>:<dom-node>:<kind>       one display use
```

The corpus contains three shared assets:

- one React background source used 4 times;
- one Dushu reference URL used 21 times;
- one Shoelace reference URL used 2 times.

All 227 use IDs are unique, and no shared source collapses multiple display
boxes into one use.

## Implementation

- Asset record contract:
  `src/app/services/structure/asset_metadata.py`;
- DOM source/crop metadata:
  `src/app/services/structure/providers/dom.py`;
- direct-design screenshot-crop provenance:
  `src/app/services/som/direct_design.py`;
- explicit asset acceptance:
  `src/app/services/rendering/figma_acceptance.py`;
- independent report:
  `src/app/services/evidence/dom_asset_quality.py`;
- probe/report CLI:
  `scripts/dom_asset_quality.py`;
- contract and report tests:
  `tests/v2/test_p1_asset_metadata.py`,
  `tests/v2/test_dom_asset_quality.py`,
  `tests/v2/test_p1_figma_acceptance.py`.

## Reproduce

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_asset_quality.py probe `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --capture-root output\_dom_text_quality_capture_2026-10-25 `
  --out output\_dom_asset_quality_2026-10-25

C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_asset_quality.py report `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --capture-root output\_dom_text_quality_capture_2026-10-25 `
  --source-probes output\_dom_asset_quality_2026-10-25\source_probes.json `
  --out output\_dom_asset_quality_2026-10-25
```

Evidence file hashes from this run:

```text
source_probes.json SHA-256:
af3a5826664e822b87eed135661c079546aec710d91c795632e0d833e573037d

summary.json SHA-256:
ddded5a66b485389d971bde2c9b9d4263a9f398b074640bc98dc9f101cdc1f17
```

## Verification

TDD and regression result:

```text
python -m pytest tests/v2 -q
588 passed in 33.66s

node --check figma_bridge/code.js
exit 0
```

The focused asset, acceptance and evidence slices also pass, along with Ruff
check and format check for all D-006 Python files.

## Remaining Boundaries

- Dushu source images remain reference-only because the origin returned HTTP
  403 during the bounded probe.
- Two Shoelace badge sources timed out and remain reference-only.
- Inline SVG markup, masks, filters and effect chains are not recovered by this
  report.
- The display payload is a screenshot crop even when source replacement bytes
  are available.
- Real Figma replacement/readback/export has not been run in D-006.
- The 42 replacement-eligible assets are a contract result, not runtime proof.
- No generated approximation was used.

## Non-Claims

This report does not claim:

- all remote assets were acquired;
- screenshot crops are original assets;
- reference-only URLs are replaceable originals;
- inline SVG source bytes or effects are preserved;
- real Figma replacement passed;
- arbitrary real-site asset coverage;
- project-wide `verified=true`;
- production admission.
