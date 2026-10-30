# DOM Route Optimization Result - 2026-10-29

## Verdict

The P0 capture/replay infrastructure and P1 visual-fidelity mechanisms are implemented and
covered by focused tests. The four regression captures replay deterministically and now have
real Figma export/readback evidence. All four regression pages now pass the visual gate.

Two valid unseen holdouts, Rust and PostgreSQL, pass the real Figma visual gate. The frozen
Wikipedia holdout still fails capture with `net::ERR_CONNECTION_TIMED_OUT`; it remains a
preserved failure rather than being replaced.

Therefore:

- mechanism-level implementation: verified;
- four-page Figma image-fill/readback gate: evaluated, 4 pass / 0 fail;
- default-enable decision: not passed;
- P1 flags remain disabled by default.

## Implemented

| Capability | Status | Default |
|---|---|---|
| Versioned capture bundle and hashes | adopted | enabled with new captures |
| Canonical layer tree | adopted | enabled with new captures |
| Browser-free deterministic replay | adopted | explicit CLI |
| Canonical text model | implemented | `DOM_TEXT_MODEL_V2=false` |
| Browser-measurement-first text layout | implemented | consumed only with canonical measured lines |
| Font manifest and Figma `resolve_font` | implemented | resolution data captured; default behavior unchanged |
| Background/pseudo visual assets | implemented | `DOM_VISUAL_ASSETS_V2=false` |
| Safe SVG sanitization/rasterization | implemented | `DOM_SVG_MATERIALIZATION_V2=false` |
| Image-fill/blank-area visual quality report | implemented | report-only, no default gate |

## Focused Tests

| Command group | Result |
|---|---|
| P0 bundle, browser capture, capture state | 33 passed |
| P0 layer tree, style snapshot, rich text, browser capture | 17 passed |
| P0 replay, bundle, text bounds, hierarchy frames | 21 passed |
| P1 text model, rich text, bounds, control anchors | 15 passed |
| P1 text layout, DOM geometry, control anchor, border, Figma acceptance | 69 passed |
| P1 font bundle, platform provenance, bridge metrics, Figma acceptance | 67 passed |
| P1 visual assets, asset quality, Figma acceptance, generated icons | 21 passed |
| P1 SVG policy, asset metadata, capture, Figma acceptance | 51 passed |
| P1 visual quality, benchmark, canonical fidelity, adapter edits | 50 passed |
| Relative capture-path regression | 9 passed |
| CSP style-injection accessibility and capture regression | 13 passed |

All listed commands used:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest ...
```

## Four-Page Regression

Capture environment: viewport `1440x900`, DPR `1`, `requested_route=dom`,
`effective_route=dom`, P1 flags enabled only for this benchmark.

| Page | Capture | Replay twice | Figma bad-pixel ratio | Text nodes | Figma fills | Visual |
|---|---|---|---|---|---|---|
| IT之家 | content, 428 DOM nodes | identical hashes | 0.0374 | 54 | 15 | pass |
| 21ic | content, 2757 DOM nodes | identical hashes | 0.0672 | 160 | 204 | pass |
| 国家数据 | content, SPA hash route, 941 DOM nodes | identical hashes | 0.0515 | 14 | 10 | pass |
| 小米 | content, 1056 DOM nodes | identical hashes | 0.0047 | 32 | 25 | pass |

The aggregate visual report has `pass_case_count=4`, `fail_case_count=0`, and
`warning_counts={}`. Every page reached a nonzero Figma image-fill rate.

Replay hashes:

| Page | PageGraph SHA-256 | DesignSpec SHA-256 |
|---|---|---|
| IT之家 | `f83aa657a0690cd4edb057078927509ec33b92336fc59cd181f7fad358fd536f` | `1abb89150bcd484e51380e8235be9c3d12e802c6db0ed2675a549fc97af0f04d` |
| 21ic | `cf89999bfec96465d560a58752d8efd92063f3ccd6bcf67297293a9a480d73bd` | `b71e5b657d35d33aa1952b9fa14ee452baee854afd194c3980b88c529219d939` |
| 国家数据 | `3178f9c29c003ba858e5e7713d4039788cf4a1452dcc2999f02fef7698413141` | `2724d73d88e659d6acf3c8c8c2ff3efb4e022b96f09466fdca40d8598fa51e07` |
| 小米 | `a18d0f288ac0debc2ef39d4dbbc6c81ae7020c0f9bb21e5e74d8c868c57040ea` | `04a31025d8a01f6f21fec0a349ecb71ac38a77733125f80ab708afe6546404b5` |

## P0 Route Benchmark

The dedicated P0 driver replayed each frozen bundle twice and evaluated redirect,
content, image coverage, geometry, and clipping independently:

| Page | Bundle SHA-256 | Route quality | DOM images | Design images | Figma fills | Text nodes |
|---|---|---|---|---|---|---|
| 21ic | `2164924de2d95fc202203e77e6b987209c93b3a4ffb46792bd644fd2812c3a70` | warn | 67 | 61 | 204 | 160 |
| IT之家 | `0b5ce3abac9d5df4b158e5cfb894b6e53e5022626bf6f2557459b2e9028c62e1` | warn | 19 | 8 | 15 | 54 |
| 国家数据 | `2d5c4bbc03ea04f9e8795d58b38ecfbc76e0ff3bd6a126c0d1b7c7f79b667490` | warn | 33 | 5 | 10 | 14 |
| 小米 | `3bdc8ce6f5f4d4233ff659f538a573710c8d02ea973ad9938aaee35cd16dd055` | warn | 36 | 23 | 25 | 32 |

Aggregate result:

- cases: 4
- deterministic replay pairs: 4/4
- route-quality failures: 0
- route-quality warnings: 4
- Figma fills: 254

IT之家 has an image-coverage warning. 国家数据 has SPA path and image-coverage
warnings. No route-quality failure was hidden by the aggregate report.

## Legacy vs P1 A/B

The national-data page was rendered from the same capture in two distinct Figma frames:
legacy P1 flags off and current P1 flags on.

| Metric | Legacy | P1 | P1 - Legacy |
|---|---:|---:|---:|
| bad-pixel ratio | 0.2354 | 0.0515 | -0.1839 |
| mean pixel delta | 30.062 | 4.871 | -25.190 |
| blank-area ratio | 0.6216 | 0.3900 | -0.2316 |
| Figma image fills | 8 | 10 | +2 |
| text nodes | 14 | 14 | 0 |

Only legacy fails the absolute visual gate; P1 passes. Every evaluable region improves:

- query-region score improved by `98.324`;
- header score improved by `13.610`;
- table score improved by `32.895`;
- content coverage increased substantially.

The root cause was a screenshot crop whose DesignSpec box was `1440×2890` while the retained
PNG was `1440×900`. Figma `FILL` scaling enlarged and cropped that image. Visual source-crop
boxes are now clamped to the screenshot canvas before DesignSpec emission.

Structured gradients are mapped to native Figma `GRADIENT_LINEAR`/`GRADIENT_RADIAL` paints.
A minimal real-Figma probe read back `GRADIENT_LINEAR`. The crop clamp then removed the
remaining large header/query-area mismatch.

## Unseen Holdouts

The URLs were frozen before execution in
`output/_dom_visual_benchmark_20261029/holdout_manifest.json`.

| Holdout | Result |
|---|---|
| `https://www.wikipedia.org/` | retry failed with `net::ERR_CONNECTION_TIMED_OUT`; preserved failure |
| `https://www.rust-lang.org/` | 242 nodes, deterministic replay, Figma visual pass |
| `https://www.postgresql.org/` | 365 nodes, deterministic replay, Figma visual pass |

Rust visual report:

- `blank_area=pass`, `image_fill=pass`, `visual_diff=pass`
- image-fill rate `1.0`, fills `9`
- bad-pixel ratio `0.0590`
- `height=pass`, drift `0`
- PageGraph `46ad0305...`
- DesignSpec `2d979038...`

PostgreSQL visual report:

- `blank_area=pass`, `image_fill=pass`, `visual_diff=pass`
- image-fill rate `1.0`, fills `17`
- bad-pixel ratio `0.0607`
- height drift `0`
- 67 text nodes

The two valid unseen holdouts pass. The Wikipedia network failure remains recorded and was
not replaced.

## Figma Execution

After the plugin was restarted, IT之家 initially exceeded the 30-second bridge response
window and returned `PLUGIN_TIMEOUT`; that partial write was cleaned and not counted. The
bridge was restarted with a 180-second runtime timeout, and the replay CLI now accepts an
explicit `--timeout` argument.

Final replay actions succeeded for all four regression pages, Rust, and PostgreSQL with
`get_node_tree`, `image_fill_report`, and PNG export. The final route benchmark records
254 Figma image fills.

The 国家数据 Figma header/query area still differs visually from the source screenshot. This
is the reason the default-enable decision remains rejected.

## Reproduction

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_capture_bundle.py `
  tests/v2/test_dom_layer_tree.py `
  tests/v2/test_capture_replay.py `
  tests/v2/test_dom_text_model.py `
  tests/v2/test_dom_text_layout.py `
  tests/v2/test_dom_font_bundle.py `
  tests/v2/test_dom_visual_assets.py `
  tests/v2/test_dom_svg_materialization.py `
  tests/v2/test_dom_visual_quality.py `
  tests/v2/test_dom_visual_benchmark.py -v

C:\Users\lzq\.conda\envs\omni\python.exe -m pytest `
  tests/v2/test_capture_csp_accessibility.py `
  tests/v2/test_capture_browser_engine.py -v

C:\Users\lzq\.conda\envs\omni\python.exe scripts/replay_dom_capture.py `
  --bundle output/_dom_visual_benchmark_20261029/it-home-r2 `
  --output-dir output/_dom_visual_benchmark_20261029/replays/it-home

C:\Users\lzq\.conda\envs\omni\python.exe scripts/dom_visual_benchmark.py `
  --case "IT之家=output/_dom_visual_benchmark_20261029/it-home-r2=output/_dom_visual_benchmark_20261029/it-home-r2" `
  --out output/_dom_visual_benchmark_20261029/result.json

C:\Users\lzq\.conda\envs\omni\python.exe scripts/benchmark_dom_route.py `
  --case "IT之家=D:/LLM-Data/Figma_auto_agent/output/_dom_visual_benchmark_20261029/it-home-r2" `
  --case "21ic=D:/LLM-Data/Figma_auto_agent/output/_dom_visual_benchmark_20261029/bbs21" `
  --case "国家数据=D:/LLM-Data/Figma_auto_agent/output/_dom_visual_benchmark_20261029/stats" `
  --case "小米=D:/LLM-Data/Figma_auto_agent/output/_dom_visual_benchmark_20261029/xiaomi" `
  --out output/_dom_visual_benchmark_20261029/dom-route-benchmark.json

C:\Users\lzq\.conda\envs\omni\python.exe scripts/figma_replay.py `
  --out output/_dom_visual_benchmark_20261029/it-home-r2 `
  --design 12_design.json `
  --screen-name P1-IT-HOME `
  --readback-depth 4 `
  --timeout 180

C:\Users\lzq\.conda\envs\omni\python.exe scripts/dom_visual_ab.py `
  --case "stats=D:/LLM-Data/Figma_auto_agent/output/_dom_visual_benchmark_20261029/stats" `
  --out-dir output/_dom_visual_ab_gradient_20261030 `
  --timeout 180
```

## Decision

- Versioned capture bundle: adopted
- Layer tree: adopted
- Offline replay: adopted
- Asset materialization: adopted behind `DOM_NETWORK_ASSET_RECOVERY=false` and
  `DOM_VISUAL_ASSETS_V2=false`
- Route-quality gate: adopted in report-only mode; strict gate remains false
- Default behavior changed: no
- Remaining risks: default adoption still needs per-page legacy/P1 A/B evidence outside 国家数据, Wikipedia network failure, large pages need a 180-second bridge timeout, PingFang SC and MiSans Medium fallbacks remain visible in font reports
- Reproduction commands: listed above
