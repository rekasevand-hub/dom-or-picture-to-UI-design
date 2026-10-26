# Image To Figma MVP Ledger

**Date:** 2026-10-25  
**Status:** `pass-current-scope`  
**Sample:** `IMG-MVP-01`  
**Figma frame:** `77:4851`

## Task Status

| ID | Status | Evidence |
|---|---|---|
| I-001 | complete-current-scope | `docs/superpowers/specs/2026-10-25-image-to-figma-mvp-design.md`; truth manifest |
| I-002 | complete-current-scope | `src/app/services/structure/image_contract.py`; `pipeline/image_ir.json` |
| I-003 | complete-current-scope | `strategy.selected=grounding`; `fallback_used=false` |
| I-004 | partial-current-scope | full product path passes owned frame `2:62`; fresh holdout is `0/3` and CV quality is not generalized |
| I-005 | rejected-current-scope | frozen three-way benchmark; `reject-hybrid` because no independent improvement |
| I-006 | complete-current-scope | faithful reference state, grouping candidates and fixed-coordinate flow |
| I-007 | complete-current-scope | critical text `14/14`; OCR remains candidate-only |
| I-008 | complete-current-scope | one reference-only image; real display replacement pass |
| I-009 | complete-current-scope | flow `candidate`, fixed-coordinate, adaptive false |
| I-010 | complete-current-scope | real Figma write/readback/export/probes |
| I-011 | pass-current-scope | `acceptance.json`; `IMAGE_FIGMA_MVP_ACCEPTANCE_2026-10-25.md` |

## Final Evidence

| Item | Result |
|---|---|
| Critical text | `14/14` |
| Native text edit/restore | pass |
| Image display replace/restore | pass |
| Real export within-30 | `96.533125%` |
| Frozen product threshold | `90%` |
| Readback nodes | `24` |
| Native text nodes | `16` |
| Image nodes | `1` |
| Auto Layout nodes | `0` |
| Original asset claim | false |
| Generated asset claim | false |
| Adaptive flow claim | false |

## Implementation Additions

- `src/app/services/structure/image_contract.py`
  - faithful image reference;
  - deterministic pixel-sampled design;
  - OCR text candidate supplement;
  - local control-surface recovery;
  - embedded image-region recovery;
  - reference-only asset provenance;
  - field-level image IR.
- `src/app/services/structure/router.py`
  - Grounding remains default;
  - fallback only for missing config or Grounding-service availability.
- `src/app/agents/precise_agent.py`
  - image provenance and IR output;
  - no second VLM DesignSpec call for the image MVP;
  - OCR and image-region evidence artifacts;
  - deterministic image renderer integration.
- `src/app/services/evidence/image_figma_acceptance.py`
  - independent critical-text, native-text, asset, structure and visual gates;
  - real Figma evidence runner;
  - frozen 90% policy retention.
- `scripts/image_figma_mvp.py`
  - reproducible prepare and reuse-prepared real Figma commands.

## Defects Found And Closed By TDD

1. The generic second VLM assigned black backgrounds to text and altered
   candidate geometry. The image MVP now samples visible surfaces directly.
2. Grounding sometimes labels an entire white card panel as an image. Image
   candidate boxes are refined to the largest visible image-like component.
3. Grounding sometimes omits navigation/CTA text. A language-aware EasyOCR
   supplement adds only missing candidates and retains OCR provenance.
4. The first OCR line merge joined separate stat columns in right-to-left
   order. Line merging now requires bounded horizontal adjacency.
5. OCR substring duplicate suppression ignored location and hid `Orders`
   because of `Pending orders`. Substring duplicate checks now require spatial
   overlap.
6. White OCR text on a small blue CTA lost its surface. Local color-component
   recovery restores the button candidate.
7. Grounding can omit the embedded visual entirely. A large saturated
   component recovery supplies a reference-only image candidate.

## Verification

```text
focused image tests: 23 passed in 1.76s
tests/v2: 671 passed in 39.76s
ruff check: all checks passed
ruff format --check: 10 files already formatted
node --check figma_bridge/code.js: exit 0
bridge JS tests: pass
git diff --check: pass
```

## Claim Boundary

The pass covers one owned screenshot, one final prepared artifact set and one
real Figma document. It does not claim arbitrary image understanding, original
asset recovery, font/glyph truth, adaptive layout or production readiness.

No commit or push was performed.

## 2026-10-26 Fallback And Hybrid Follow-Up

- I-004 now has a real Figma CV-fallback run. The automatic route recorded
  `grounding-config-missing` before selecting CV and did not hide a route
  switch. The fallback wrote, read back and exported frame `1:26`, but failed
  product quality on critical text, structure and asset dimensions.
- I-005 ran the same frozen corpus under Grounding-only, CV fallback and a
  conservative Grounding + CV hybrid. Grounding-only and hybrid were identical
  in design, IR, export bytes and visual metrics; only Grounding-only passed
  with no added cost. Hybrid was rejected.
- Evidence:
  `docs/v2_mentor/IMAGE_CV_HYBRID_BENCHMARK_2026-10-26.md`;
  `output/_image_cv_hybrid_benchmark_2026-10-26/comparison.json`.
- Product default remains Grounding. CV remains an availability fallback only.

### I-004-R2 Product Path

- The full `PreciseAgent` path was exercised with `VISION_API_KEY` absent,
  including CV, OCR supplement and image-region recovery.
- Owned frame `2:62` passes critical text `14/14`, native text, reference-only
  asset replacement and visual `96.518229%`.
- Four visual/merge defects were closed by TDD during the run.
- A frozen three-sample follow-up holdout passes `0/3`; all three fail content
  or structure despite visual scores above `95%`.
- Evidence:
  `docs/v2_mentor/IMAGE_CV_FALLBACK_PRODUCT_ACCEPTANCE_2026-10-26.md`;
  `output/_image_fallback_holdout_2026-10-26/summary.json`.
- I-004 is `partial-current-scope`: routing is verified, fallback quality is
  not admitted beyond the owned sample.
- Verification after the follow-up:

```text
focused image tests: 44 passed
tests/v2: 755 passed
ruff check and format check: pass
node --check figma_bridge/code.js: pass
bridge JS tests: 20 passed
git diff --check: pass
```
