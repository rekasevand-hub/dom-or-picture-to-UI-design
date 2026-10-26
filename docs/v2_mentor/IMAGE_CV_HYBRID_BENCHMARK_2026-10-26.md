# Image CV Fallback And Hybrid Benchmark

**Task:** I-004 / I-005  
**Date:** 2026-10-26  
**Decision:** `reject-hybrid`  
**Product default:** Grounding, with CV only as an availability fallback  
**Scope:** one owned screenshot, one scratch Figma document, three real frames

## Decision

Do not adopt the Grounding + CV hybrid.

The hybrid preserved critical text, native text, reference-only asset
replacement, visual quality, provenance, latency bounds and route safety. It
did not improve one independent structure or editability dimension on the
frozen sample. It had the same design elements, IR counts, Figma export bytes
and measured quality as Grounding-only. It encountered 33 CV duplicate
candidates that were all suppressed by the conservative merge.

This is not a general rejection of all future hybrids. It rejects this
conservative merge for the current owned sample and keeps the product default
unchanged.

## Frozen Setup

| Item | Value |
|---|---|
| Corpus | `IMAGE-STRATEGY-CORPUS-2026-10-26-R1` |
| Sample | `IMG-MVP-01` |
| Image | `tests/fixtures/image_mvp/simple_dashboard_v1.png` |
| Image SHA-256 | `7f39efc5e69b9ba16367aa19a1ccb1e3ea1681824419c93f0f9a3478e5153df4` |
| Truth SHA-256 | `942852b2c07d40b1da3bdaa93c7d9b015ede09655fd83a1c6de4785ad03c7c53` |
| Size | `1200x800` |
| Visual threshold | `90%` within-30, frozen before the run |
| Critical text | `14` required strings |
| Python | `3.12.0` |
| OpenCV | `4.10.0` |
| EasyOCR | `1.7.2` |
| Grounding model | `qwen3-vl-plus` |
| Figma file | `https://www.figma.com/design/k1r1zK3DDREcvTcimasd7P/Untitled` |
| Readback depth | `8` |

Two pre-existing Figma tabs exposed only `View only`. The benchmark therefore
used a newly created scratch design file owned by the signed-in user. All three
frames were written into that one document, with unchanged source image, truth,
policy, font environment and export scale.

## Strategy Isolation

The benchmark froze one Grounding candidate graph and one CV candidate graph
for the sample:

- Grounding-only and hybrid reuse the same Grounding graph.
- CV fallback and hybrid reuse the same CV graph.
- Provider replay is explicit in runtime provenance.
- Hybrid executes only the merge and deterministic presentation increment.

This prevents VLM sampling variance from being mistaken for a strategy
difference.

The logical latency includes the shared source run plus presentation and real
Figma work. Exact token usage was not exposed by the provider, so cost is
bounded by the configured request count rather than claimed as measured
tokens.

## Routing Evidence

CV fallback was reached through image `auto`, not explicit `--route cv`.

```text
requested=auto
attempt 1: grounding unavailable, grounding-config-missing
attempt 2: cv selected
hidden_route_switch=false
```

Existing tests additionally prove that Grounding JSON/schema errors and
ordinary downstream errors do not switch to CV. Explicit Grounding remains a
single route and fails closed.

Hybrid routing:

```text
requested=auto
attempt 1: grounding selected
attempt 2: cv supplemented
selected=hybrid
hidden_route_switch=false
```

## Real Figma Results

| Strategy | Frame | Critical text | Native text | Asset | Structure | Visual | Quality status |
|---|---|---:|---|---|---|---:|---|
| Grounding-only | `1:2` | `14/14` | pass, 16 nodes | pass, 1 reference-only image | pass | `96.541979%` | pass |
| CV fallback | `1:26` | `13/14` | pass, 33 nodes | fail, 0 image nodes | fail | `93.057500%` | `blocked-fail` |
| Grounding + CV hybrid | `1:84` | `14/14` | pass, 16 nodes | pass, 1 reference-only image | pass | `96.541979%` | pass |

No aggregate score is used.

### Critical Text

- Grounding-only: all 14 required strings present.
- CV fallback: missing `New customers today`.
- Hybrid: all 14 required strings present.

### Native Text

- All three strategies wrote native Figma text.
- Text edit and restore passed on all three frames.
- CV fallback wrote 33 native text nodes but still missed critical content.
- Node count alone is not treated as a quality improvement.

### Assets

- Grounding-only and hybrid each contain one reference-only image node.
- Both image replacement and restore probes pass.
- CV fallback contains no image candidate.
- CV asset probe is `not-evaluated`, which fails the claimed-asset gate.
- No strategy claims original asset identity.

### Visual Metrics

| Strategy | Size match | Within-30 | Over-30 | Mean channel delta | Ink mean delta |
|---|---|---|---:|---:|---:|
| Grounding-only | true | `96.541979%` | `3.458021%` | `4.195659` | `9.872519` |
| CV fallback | true | `93.057500%` | `6.942500%` | `6.586613` | `24.775485` |
| Hybrid | true | `96.541979%` | `3.458021%` | `4.195659` | `9.872519` |

CV fallback remains above the numeric visual threshold, but its missing text,
missing asset, overlapping text and visibly wrong embedded region prevent a
product pass.

## Hybrid Decision Gates

| Gate | Result |
|---|---|
| Real Figma runtime | pass |
| Critical text no regression | pass |
| Native text editability | pass |
| Reference-only asset replacement | pass |
| Independent structure/editability improvement | fail |
| Visual non-regression and threshold | pass |
| Provenance retained | pass |
| No hidden route switch | pass |
| Latency bound | pass |
| Cost bounded by request count | pass |
| Original asset / adaptive flow non-claims | pass |

Hybrid structure had 21 nodes, 16 text candidates and 1 image candidate, exactly
equal to Grounding-only. Merge output was `no-change`:

```text
text_added=0
visual_added=0
container_added=0
duplicate_suppressed=33
unresolved_ambiguity=0
```

The only failing reason is `independent-improvement`, so the evaluator emits
`reject-hybrid`.

## Runtime And Cost

| Strategy | Logical wall time | Logical Grounding calls | Logical CV executions |
|---|---:|---:|---:|
| Grounding-only | `29.403s` | 1 | 0 |
| CV fallback | `17.480s` | 0 | 1 |
| Hybrid | `41.812s` | 1 | 1 |

Hybrid is `1.42x` the Grounding-only time, inside the frozen `2x` and `180s`
bounds. It has no quality or editability payoff on this sample.

## Artifact Hashes

| Artifact | SHA-256 |
|---|---|
| `comparison.json` | `409c99ee96fd1a930775d8de9ead0a515f599887e33808bf6efc782566df4456` |
| Grounding design | `2e81d9ed27486f1bd50a865b0b3667017f0fdf40e26c020d1bc3e076d49a4614` |
| Grounding image IR | `4889029c3e0bc6faf8d3f2e006c5a0422ec0242451e71b635de7bc73c0397587` |
| Grounding readback | `5bbbbc5f37a328009d28559562bdd495e8fc860d057977c03370a0bb3a8d646a` |
| Grounding export | `8c7a901b18071bb23ac631a625b26999f42ffb362fd12c917fcbef930cd0afda` |
| CV design | `6d1a29981f76e0bbd5f8da746ec6c91d17e3e1e3e5a355950df7ce9a9f9334cc` |
| CV image IR | `2de78c3dd66182e3db302a5b29a1e61dc35ac62223775d765bd11ebad9052142` |
| CV readback | `144074c90be19463c133321fe6228c1d81ab10c4e3b8acd6c4755cb3c431a62e` |
| CV export | `35a2226f5ce4d7b7516c0c11d2856e9865a2af574e09c560011b24cc6637c6d0` |
| Hybrid design | `d91ec49d7260f7da756756da27b1274408ced71cc3ac5e7c3b1b8c5db4db62e5` |
| Hybrid image IR | `e71a3d7aabd8dda0f4d87fd371b1be2530257b67d8ed58d48bd349e41ad6bb86` |
| Hybrid readback | `7ee6bdf0f9f39aa4ed3524217888b2afca0882657a98b0f77bb657d5935ab1f7` |
| Hybrid export | `8c7a901b18071bb23ac631a625b26999f42ffb362fd12c917fcbef930cd0afda` |

Grounding-only and hybrid exports are byte-identical. This independently
confirms that the hybrid did not improve the rendered result on this sample.

## Reproduce

Prepare the shared candidate graphs and all three designs:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/image_strategy_benchmark.py `
  --prepare-only
```

With the Figma bridge plugin connected to `ws://localhost:8765`:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/image_strategy_benchmark.py `
  --reuse-prepared --run-figma
```

Rebuild the comparison from retained Figma artifacts:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/image_strategy_benchmark.py `
  --compare-only
```

## Claim Boundary

This result supports:

- the current automatic CV fallback route classification;
- one real Figma CV fallback write/readback/export/probe run;
- rejection of the current conservative hybrid on one owned sample;
- preservation of Grounding as the default.

It does not support:

- CV fallback as a product-quality replacement for Grounding;
- arbitrary screenshot acceptance;
- a general hybrid rejection across other screenshots or a different merge;
- original asset, font, DPR, viewport or hidden-state recovery;
- adaptive layout;
- production readiness;
- Axure evidence substitution;
- a composite quality score.

No commit or push was performed.

## Verification

```text
focused image tests: 44 passed
tests/v2: 751 passed
ruff check: pass
ruff format --check: pass
node --check figma_bridge/code.js: pass
bridge JS tests: 20 passed
git diff --check: pass
```
