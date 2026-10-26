# Axure Shared IR Boundary

**Task:** A-001  
**Status:** `pass-current-scope`  
**Date:** 2026-10-25  
**Evidence root:** `output/_axure_shared_ir_2026-10-25_r1/`

## Decision

A-001 adopts one output-neutral projection over the existing DesignSpec. It
does not replace DesignSpec, mutate either adapter, or create a second image
understanding stack.

```text
input capture / image understanding
  -> existing DesignSpec
  -> output-neutral design-ir/2.0
  -> target capability projection
       -> Figma adapter
       -> Axure adapter
```

The neutral IR owns shared design facts and provenance. Each adapter still
owns its output format, runtime behavior and acceptance.

This is a boundary decision, not Axure product acceptance. A-002/A-003 must
write real Axure output from the shared design input, and A-004 must evaluate
that output independently.

## Shared Ownership

The canonical projection retains:

- deterministic `document_id`;
- frame order, frame names and canvas geometry;
- stable projected node IDs plus source node IDs;
- node kind and source-pixel/CSS geometry;
- text content and structured style tokens;
- layout mode/status and required capabilities;
- asset use, identity status, display mode and provenance;
- generated/reference-only/original flags;
- source input kind and optional image reference;
- explicit limitations and non-claims.

The current schema is:

```text
design-ir/2.0
```

Top-level fields:

```text
schema_version / document_id / output_neutral / source /
frames / assets / required_features / limitations
```

## Target-Owned

### Figma

- frame and clip-container construction;
- Auto Layout APIs and Figma layer behavior;
- native text/font resolution;
- image fill and runtime replacement probes;
- readback, export and Figma-specific acceptance.

### Axure

- `.rp` page/package generation;
- mapping to `Text`, `Button`, `TextField`, `ImageBox`, `Rect` and `Ellipse`;
- Axure font/color/line-height serialization;
- published HTML behavior;
- Axure-specific reload, visual and editability acceptance.

Neither target may transfer its evidence to the other.

## Capability Matrix

| Capability | Figma | Axure RP 8 boundary |
|---|---:|---|
| Native text | true | true |
| Image fill at creation | true | true |
| Fixed-coordinate output | true | true |
| Multi-page/design pages | false | true |
| Clip container | true | false |
| Auto Layout | true | false |
| Runtime image replacement | true | false |
| Visibility mutation | true | false |
| Letter spacing | true | false |
| Shadow/gradient | true | false |
| Component instance creation | false | false |
| Interaction behavior from DesignSpec | false | false |

The matrix is checked against adapter class boundaries in
`tests/v2/test_output_ir_boundary.py`.

## Explicit Degradation

`project_for_output()` reports instead of silently dropping unsupported
features:

| Target feature gap | Reported fallback/status |
|---|---|
| Axure clip | `flatten-or-reference-crop` |
| Axure Auto Layout | `fixed-coordinate` |
| Axure runtime image replacement | `creation-only-image-box` |
| Axure visibility | `omit-or-flatten` |
| Axure letter spacing | `linebreak-workaround` |
| Axure shadow/gradient | `reference-crop-or-explicit-loss` |
| Figma multi-page | `single-frame-per-write` |

An unsupported required feature means `can_claim_complete=false` for that
target until a later task implements and validates a fallback.

## Asset Semantics

The IR separates two different `original` questions:

- `original`: source identity is verified original bytes;
- `display_original`: the selected display payload is original.

A DOM asset may have verified original identity while its display payload is a
reference-only screenshot crop. That combination is valid.

These states fail validation:

- reference-only display marked as original;
- generated display marked as original.

## Policy Gates

Validation fails closed on:

- unsupported IR schema;
- missing/non-positive frames or geometry;
- duplicate frame/node IDs;
- unsupported node kinds;
- verified flow without explicit evidence;
- reference-only or generated display promoted to original.

## Evidence

The probe projected two already-validated designs through the same boundary:

| Case | Source | Frames | Nodes | Assets | Axure unsupported |
|---|---|---:|---:|---:|---|
| `IMG-MVP-01-figma` | image MVP DesignSpec | 1 | 21 | 1 | `runtime-image-replace` |
| `DQ-R02-figma` | DOM Figma DesignSpec | 1 | 440 | 54 | `letter-spacing` |

Both cases have:

- IR validation issue count `0`;
- Figma capability projections;
- Axure capability projections;
- explicit degradation lists;
- `figma_evidence_transferable=false` and
  `image_figma_evidence_transferable=false` for Axure.

Document IDs:

```text
IMG-MVP-01: 63470f34aab242fad73f4e7456de8af2e0983ff1d363c62cd5400eb9042502ff
DQ-R02:     fbc635a4362b1e85d7d4b469c4085f417f388e4410387e0e0c794eac476fa8ed
summary:    5784de5527dc3fe214bb2c8b63bcd40b060f031e4626201bda5525a75d41b04c
```

## Reproduce

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/axure_shared_ir_probe.py `
  --image-design output/_image_figma_mvp_2026-10-25_r4/figma_design.json `
  --dom-design output/_dom_figma_generated_icons_2026-10-25_r1/design.json `
  --out output/_axure_shared_ir_2026-10-25_next
```

## Verification

```text
focused boundary tests: 12 passed in 0.71s
tests/v2: 683 passed in 39.05s
ruff check/format: pass
node --check figma_bridge/code.js: exit 0
git diff --check: pass
```

## Next Task

A-002 can now implement `DOM -> Axure` using the neutral design projection and
the reported Axure gaps. It must:

1. produce a deterministic `.rp`;
2. verify page count, node/widget mapping and asset bytes;
3. open/reload the output in Axure RP 8;
4. publish and visually verify the result;
5. produce a separate Axure acceptance report.

A Figma pass does not satisfy any of those A-002/A-004 steps.

## Non-Claims

This task does not claim:

- Axure product readiness;
- an Axure `.rp` write for the projected samples;
- Axure reload or visual fidelity;
- Axure editability beyond model capability declarations;
- Auto Layout, clip, visibility or runtime image replacement in Axure;
- original font, glyph, DPR or viewport identity;
- transfer of Figma acceptance evidence.
