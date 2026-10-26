# Fixed Real-Site DOM Quality Corpus

**Task:** D-003  
**Status:** `frozen-current-scope`  
**Corpus ID:** `dom-quality-real-sites/1.0`  
**Frozen at:** `2026-10-25T02:42:07.442021+00:00`  
**Manifest:** `tests/fixtures/dom_quality/real_site_corpus_v1.json`  
**Thresholds SHA-256:** `6dd4f29ed90041bb5fbd7912d8c772603279c27f114896dbc2c04f832251d8a2`  
**Corpus SHA-256:** `edec396946c03755fabbdea70e6ab210d5a0516b3eef7034c218386f8e45f4ef`

## Result

The corpus is frozen with three required real sites:

- React: hydrated documentation;
- Dushu: dense Grid, text and image content;
- Shoelace: open-shadow web components.

W3Schools iframe remains an explicit exclusion because its prior observation was
`state-unstable / inconclusive`; it is not part of the quality denominator.

Both the initial freeze and an independent verification run passed the
state/content/drift checks. This proves that the frozen current-scope
observations are reproducible under the recorded environment. It does not
prove DOM-to-Figma quality; that remains D-004..D-008.

## Frozen Environment

| Field | Frozen value |
|---|---|
| Engine | Chromium |
| Browser version | `151.0.7922.34` |
| Executable SHA-256 | `409805a16d6416087e6b2f778df1cf8f7bbb267d6b99f6b5bb0a618eace234f2` |
| Viewport | `1440x900` |
| DPR | `1` |
| Locale | `zh-CN` |
| Timezone | `Asia/Shanghai` |
| Headless | `true` |
| OS | `Windows-11-10.0.26300-SP0` |
| Capture contract | `capture_page_with_fallback+dom-quality-corpus/1.0` |

Frozen font files:

| Font file | Bytes | SHA-256 |
|---|---:|---|
| `segoeui.ttf` | 960,076 | `704eada12961a27fd271f7d3b09e2066520e758390c1776744eff430fee30f6e` |
| `msyh.ttc` | 19,704,352 | `d79c55e68b1131eea0cc1c47be4f572d964f28c682e143db2ad09c1e4cb07a3f` |
| `arial.ttf` | 1,045,720 | `b3658eadae55e682b5f69eb64c439c1ecc8f196c0bb8d4756d145d13bc86476a` |
| `simhei.ttf` | 9,745,792 | `9b1959db3b3abeb7efdaec26edf7dfe871a6039de8d614af7248575207be629e` |

## Saved States

Every required sample starts at scroll `(0, 0)`, waits for `networkidle`,
waits for document fonts, requires a stable capture window of at least
`900 ms`, and permits two capture attempts. Real-session fallback and
cross-origin frame blocking are disabled.

Allowed network behavior is public network access under the frozen Chromium
profile. Remote assets remain `reference-only` during corpus capture; this task
does not claim original asset bytes.

| ID | Site | Saved state | Required markers |
|---|---|---|---|
| `DQ-R01` | React | `homepage-top` | DOM >= 500, text >= 200, img >= 5, SVG >= 20 |
| `DQ-R02` | Dushu | `homepage-top` | DOM >= 300, text >= 100, img >= 20 |
| `DQ-R03` | Shoelace | `homepage-top` | DOM >= 300, text >= 100, shadow >= 10 |

Critical text is checked independently:

- React: `React`, `The library for web and native user interfaces`,
  `Learn React`;
- Dushu: `读书好，好读书，读好书！`, `在线读书`, `出版图书`;
- Shoelace: `Shoelace`, `web components`, `Web Awesome`.

Challenge/login markers are forbidden from content states:
`Access Denied`, `403 Forbidden`, `Just a moment...`.

## Frozen Thresholds

The corpus does not use a composite score. Each required dimension remains
independent:

| Dimension | Frozen threshold |
|---|---|
| Critical text | `100%` required, `0%` forbidden |
| Required objects | `100%` of declared minima |
| Structure geometry | `2.0 px` |
| Global node/text drift | `20%` default |
| React node/text drift | `20%` |
| Dushu node/text drift | `15%` |
| Shoelace node/text drift | `15%` |
| Text linebreak match | `98%` |
| Text box tolerance | `2.0 px` |
| Baseline tolerance | `1.0 px` |
| Per-glyph identity | Must be reported as `explicit-not-evaluated` until D-004 |
| Auto Layout L1 | Required to pass |
| Auto Layout L2 mutation rate | `100%` |
| Auto Layout L3 mutation rate | `90%` |
| Original asset identity | `100%` of claimed original assets |
| Asset replacement probe | `100%` of claimed replaceable assets |
| Missing asset outcome | `partial-not-pass` |
| Native text edit | `100%` of claimed native text |
| Visual mean max | `3.0` |
| Visual ink mean max | `100.0` |
| Visual over-30 max | `2.5%` |
| Visual bad-pixel ratio max | `3%` |
| Size match | Required |

Thresholds are hashed into the frozen manifest. Changing any threshold makes
`validate_corpus()` fail until an explicit new corpus version is established.

## Baseline Fingerprints

| ID | Nodes | Text | DOM SHA-256 | Screenshot SHA-256 |
|---|---:|---:|---|---|
| `DQ-R01` | 1415 | 529 | `ac99866e8f97f964a91e977ac988d7cf1cabbb4229d48642139e0943e5e91f68` | `7bbb30ad375c533c3f50f2253a7d1ce2c9f5900b8bd369eb6c7ea3ec6957e9c3` |
| `DQ-R02` | 487 | 165 | `724aeb93771dc173d4cd8134879fd46fe1cf3a53d2b9b14541f4b35372451bbd` | `2f51949d84d0e88e13c5d7817703771afcaad83c559e7a03bebce401128b2f8c` |
| `DQ-R03` | 457 | 220 | `73ed52d84f1342246645b27946afbf4d8800b8a37855f719cf56c999cb63b4e4` | `df8787f89e3a3551a5de3a94d785c049bd1ebf4647d9a11321de7deae13086f5` |

The manifest also stores text, structure, frame, page-state and screenshot
hashes for every sample.

## Independent Verification

Verification timestamp: `2026-10-25T02:42:51.081771+00:00`

| ID | State | Stable | Nodes | Text | Result |
|---|---|---|---:|---:|---|
| `DQ-R01` | `content` | yes | 1415 | 529 | pass |
| `DQ-R02` | `content` | yes | 487 | 165 | pass |
| `DQ-R03` | `content` | yes | 463 | 220 | pass |

Shoelace changed from 457 to 463 nodes between freeze and verification. The
drift is `1.31%`, inside the frozen 15% threshold. The baseline was not
rewritten to match the verification run.

Evidence:

- freeze summary:
  `output/_dom_quality_corpus_2026-10-25/summary.json`;
- frozen manifest copy:
  `output/_dom_quality_corpus_2026-10-25/frozen_manifest.json`;
- freeze captures:
  `output/_dom_quality_corpus_2026-10-25/DQ-R01`,
  `DQ-R02`, `DQ-R03`;
- verify summary:
  `output/_dom_quality_corpus_verify_2026-10-25/summary.json`;
- verify captures:
  `output/_dom_quality_corpus_verify_2026-10-25/DQ-R01`,
  `DQ-R02`, `DQ-R03`.

## Reproduce

Capture without changing the manifest:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_quality_corpus.py capture `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --out output\_dom_quality_capture_replay
```

Verify against the frozen baseline:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\dom_quality_corpus.py verify `
  --manifest tests\fixtures\dom_quality\real_site_corpus_v1.json `
  --out output\_dom_quality_verify_replay
```

Frozen manifests refuse implicit mutation. Creating a new baseline requires an
explicit `freeze --refreeze` command and should normally create a new corpus
version rather than changing this one.

## Known Exclusions

- W3Schools iframe remains `excluded-state-unstable`.
- Firefox remains `blocked-environment` and is not substituted by Chromium.
- Closed shadow roots remain unobservable.
- Font baseline, mixed-run glyph identity and arbitrary variable axes remain
  open for D-004.
- General Grid/wrap/component Auto Layout remains open for D-005.
- Original asset identity and replacement remain open for D-006.
- Strategy fusion and generated-approximation provenance remain open for D-007.
- Real Figma acceptance remains open for D-008.
- Production concurrency, storage and long soak remain deferred.

## Non-Claims

This corpus is not a Figma quality pass. It does not claim:

- arbitrary real-site fidelity;
- correct linebreak, baseline or glyph identity;
- general Auto Layout behavior;
- original asset identity or replaceability;
- cross-browser equivalence;
- continuous observation stability beyond the two recorded runs;
- production admission or project-wide `verified=true`.
