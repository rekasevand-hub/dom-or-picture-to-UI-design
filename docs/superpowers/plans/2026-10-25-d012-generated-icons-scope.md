# D-012 Generated Icons And Product Scope

**Goal:** Apply the approved 2026-10-25 product policy to the remaining
iconfont crops and final glyph identity.

## Constraints

- Generated icons are `original=false`, `replaceable=false`.
- Every generated candidate requires complete provenance and payload SHA-256.
- Screenshot crops remain recorded as reference evidence.
- Generated icons can be selected ahead of screenshot crops only for
  `icon-crop` uses.
- Final glyph identity remains reported as `not-evaluated`, while the text
  gate maps the approved policy to `not-required`.
- Existing visual thresholds remain unchanged.

## Task 1: Generated Icon Candidates

- [x] Add failing tests for deterministic icon generation and provenance.
- [x] Generate transparent PNGs for search, user, bookshelf and chevron.
- [x] Attach one complete generated candidate to each icon-crop element.

## Task 2: Fusion Policy

- [x] Add a failing test for generated-icon preference over capture.
- [x] Extend fusion with an explicit icon-crop preference.
- [x] Preserve rejected screenshot and identity candidates in the report.

## Task 3: Acceptance Scope

- [x] Add a failing text test for `glyph=not-required`.
- [x] Map frozen `explicit-not-evaluated` to the approved non-blocking scope.
- [x] Treat proof-complete generated icon crops as
  `not-required-original`, not original images.
- [x] Keep generated/reference/original counts separate.

## Task 4: Real Reproof

- [x] Prepare a new DQ-R02 design with recovered images and generated icons.
- [x] Run a new owned Figma frame.
- [x] Confirm visual quality remains above the approved 90% product bar and
  frozen visual thresholds.
- [x] Re-evaluate D-009 with the approved policy.
- [x] Run focused and full regression checks.

## Execution Evidence

```text
generated icon uses: 10
unique generated PNGs: 6
generated asset flags:
  original=false
  reference_only=false
  generated=true
  replaceable=false

frame: 76:4335
overall acceptance: pass
export_allowed: true
within-30 pixel similarity: 97.5138%

full regression: 648 passed in 39.01s
```
