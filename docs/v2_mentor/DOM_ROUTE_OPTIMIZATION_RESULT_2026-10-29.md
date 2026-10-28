# DOM Route Optimization Result - 2026-10-29

## Verdict

The P0 capture/replay infrastructure and P1 visual-fidelity mechanisms are implemented and
covered by focused tests. They are not adopted as default behavior. The four regression
captures replay deterministically, but all four real Figma attempts were blocked by
`PLUGIN_DISCONNECTED: Figma plugin is not connected`.

The Rust holdout produced a valid capture and deterministic replay. The Wikipedia holdout
failed capture with `chrome-error://chromewebdata/` and remained a frozen failure rather than
being replaced.

Therefore:

- mechanism-level implementation: verified;
- four-page Figma image-fill/readback gate: not evaluated;
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

All listed commands used:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest ...
```

## Four-Page Regression

Capture environment: viewport `1440x900`, DPR `1`, `requested_route=dom`,
`effective_route=dom`, P1 flags enabled only for this benchmark.

| Page | Capture | Replay twice | SVG bad-pixel ratio | Text nodes | Figma |
|---|---|---|---|---|---|
| IT之家 | content, 428 DOM nodes | identical hashes | 0.0231 | 54 | `PLUGIN_DISCONNECTED` |
| 21ic | content, 2757 DOM nodes | identical hashes | 0.0668 | 160 | `PLUGIN_DISCONNECTED` |
| 国家数据 | content, SPA hash route, 941 DOM nodes | identical hashes | 0.1939 | 14 | `PLUGIN_DISCONNECTED` |
| 小米 | content, 1056 DOM nodes | identical hashes | 0.0037 | 32 | `PLUGIN_DISCONNECTED` |

The aggregate report has `fail_case_count=4`. Every page fails the `image_fill` dimension
because no Figma readback exists. The SVG `visual_diff` warning on 国家数据 is retained and
does not offset that failure.

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
| 21ic | `2164924de2d95fc202203e77e6b987209c93b3a4ffb46792bd644fd2812c3a70` | warn | 67 | 61 | 0 | 160 |
| IT之家 | `0b5ce3abac9d5df4b158e5cfb894b6e53e5022626bf6f2557459b2e9028c62e1` | warn | 19 | 8 | 0 | 54 |
| 国家数据 | `2d5c4bbc03ea04f9e8795d58b38ecfbc76e0ff3bd6a126c0d1b7c7f79b667490` | warn | 33 | 5 | 0 | 14 |
| 小米 | `3bdc8ce6f5f4d4233ff659f538a573710c8d02ea973ad9938aaee35cd16dd055` | warn | 36 | 23 | 0 | 32 |

Aggregate result:

- cases: 4
- deterministic replay pairs: 4/4
- route-quality failures: 0
- route-quality warnings: 4
- Figma fills: 0, because no plugin readback was available

IT之家 has an image-coverage warning. 国家数据 has SPA path and image-coverage
warnings. No route-quality failure was hidden by the aggregate report.

## Unseen Holdouts

The URLs were frozen before execution in
`output/_dom_visual_benchmark_20261029/holdout_manifest.json`.

| Holdout | Result |
|---|---|
| `https://www.wikipedia.org/` | capture failed, `soft_block`, final URL `chrome-error://chromewebdata/` |
| `https://www.rust-lang.org/` | captured 242 nodes, final URL `https://rust-lang.org/`, replay deterministic |

Rust visual report:

- `blank_area=pass`
- `image_fill=fail`, rate `0.0`, because Figma readback is absent
- `visual_diff=warn`, bad-pixel ratio `0.0737`
- `height=pass`, drift `0`
- PageGraph `46ad0305...`
- DesignSpec `2d979038...`

The holdout requirement is therefore not passed: one page failed capture and real Figma
readback was unavailable for the valid page.

## Figma Blocker

The local bridge server was listening on `ws://localhost:8765`, but every Figma replay
returned:

```text
FigmaBridgeError: Figma 插件返回错误:
PLUGIN_DISCONNECTED: Figma plugin is not connected
```

No partial frame from these failed attempts is counted as visual evidence.

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
```

## Decision

- Versioned capture bundle: adopted
- Layer tree: adopted
- Offline replay: adopted
- Asset materialization: adopted behind `DOM_NETWORK_ASSET_RECOVERY=false` and
  `DOM_VISUAL_ASSETS_V2=false`
- Route-quality gate: adopted in report-only mode; strict gate remains false
- Default behavior changed: no
- Remaining risks: Figma plugin disconnect, one failed unseen capture, no real image-fill readback, P1 visual metrics only partially evaluated
- Reproduction commands: listed above
