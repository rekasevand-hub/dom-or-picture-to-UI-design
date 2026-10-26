# Axure Holdout Acceptance

**Task:** A-005  
**Status:** `partial-post-holdout-tuning`  
**Date:** 2026-10-25  
**Holdout:** `axure-holdout/1.0`  
**Evidence root:** `output/_axure_holdout_2026-10-25/`

## Decision

The frozen holdout produced actionable failures:

- DQ-R01 exposed an IR/asset binding mismatch;
- DQ-R03 failed visual acceptance at `89.69745030511753%`;
- AX-IMG-H01 initially recovered only `1/3` assets and `1/3` critical text.

The failures were fixed by TDD and all three samples passed on re-run under the
same frozen thresholds. This is useful post-tuning evidence, but it is not a
clean generalization claim because the same holdout drove remediation.

The next validation step must use a new untouched holdout.

## Frozen Inputs

The holdout manifest was frozen before Axure measurement:

```text
tests/fixtures/axure_holdout/holdout_v1.json
sha256=0b5d26f5979b330f10174566bb7c5f8dc21a9e027d7ef1adc348c553fa692831
```

Tuning samples were explicitly excluded:

- `DQ-R02` from A-002;
- `IMG-MVP-01` from A-003.

| Sample | Input | SHA-256 |
|---|---|---|
| DQ-R01 | React frozen DOM + screenshot | DOM `ac99866e...f68`; PNG `7bbb30ad...e9c3` |
| DQ-R03 | Shoelace frozen DOM + screenshot | DOM `160351b5...98b5`; PNG `97ec38cf...73ae` |
| AX-IMG-H01 | asset-evidence screenshot | `a22150581a324550af68fa568eb8673ea9a2ce63ea874fca33590c899d1236e8` |

Frozen thresholds:

- critical text `100%`;
- page/package/object mapping `100%`;
- expected image hashes `100%`;
- deterministic `.rp` byte equality;
- exact size match;
- visual within-30 `>=90%`;
- no sample substitution;
- no composite score.

## Initial Failures

| Sample | Initial result | Root cause |
|---|---|---|
| DQ-R01 | route failed before Axure | 101 rendered image bindings vs 104 IR asset uses |
| DQ-R03 | Axure visual fail | `89.69745030511753%` within-30 |
| AX-IMG-H01 | Axure acceptance fail | critical text `1/3`, assets `1/3` |

The DQ-R01 mismatch came from three non-image CSS background asset uses and two
payload-only containers whose image bytes were not represented in the IR.

DQ-R03 lost layout quality because measured single-line text was reflowed by
Axure. A first fix expanded a wide captioned button and widened the body to
1709px; the final rule disables measured no-reflow for wide captioned buttons.

AX-IMG-H01 initially merged OCR fragments incorrectly. After horizontal-band
merging, the accepted frozen preparation contained four text candidates and
three ImageBoxes.

## TDD Fixes

1. Shared IR now synthesizes non-original `unverified-payload` assets for
   `imageBase64` without source metadata.
2. Axure routing retains non-image asset uses as `not-rendered` provenance
   instead of dropping them or failing the whole route.
3. Axure evidence maps payload-only containers to ImageBox records.
4. Browser-measured single-line text uses no-reflow unless it is a wide
   captioned button.
5. OCR fragments share horizontal bands, merge only across bounded gaps and
   suppress spatially overlapping near-duplicates.
6. Axure acceptance normalizes OCR punctuation and can enforce a frozen
   expected-asset count.

Regression tests:

```text
tests/v2/test_output_ir_boundary.py
tests/v2/test_axure_route.py
tests/v2/test_axure_evidence.py
tests/v2/test_axure_acceptance.py
tests/v2/test_image_contract.py
```

## Final Per-Sample Results

| Sample | Page | Package GUID | Widgets | Critical | Assets | Within-30 |
|---|---|---|---:|---|---:|---:|
| DQ-R01 | `A005 DQ-R01 React Axure` | `ee1c7b2f-2e81-4905-8f1b-2d1fadec18f2` | 794 | `3/3` | `80/80` | `93.7288067818298%` |
| DQ-R03 | `A005 DQ-R03 Shoelace Axure` | `8cda81f7-5820-45a0-9cd9-3d41edd4fa4d` | 265 | `3/3` | `29/29` | `90.2025368557791%` |
| AX-IMG-H01 | `A005 AX-IMG-H01 Image Axure` | `5473d2b9-4e40-470f-aebf-81e6f2d1abdf` | 10 | `3/3` | `3/3` | `97.24269841269842%` |

All final samples have:

- exact canvas size;
- deterministic `.rp` regeneration;
- Axure open/reopen publish success;
- identical published page HTML across reopen;
- no unexpected published image hash;
- explicit provenance and degradations.

| Sample | `.rp` SHA-256 | Size | Published page HTML |
|---|---|---:|---|
| DQ-R01 | `43ab92de5ccf2672d9df04a4ae352508d66089876a47296bb850e1fe43e99b7c` | 268646 | `5dff09fd577dfd142db4493d45cfad08520ef835711c06226ce515fafac03` |
| DQ-R03 | `e1459c55f54b1a507c410c8215d1c6f3b50ba8fd34e8bdb289bc963c0c29e5be` | 173668 | `783cfd6f9a7cee7ff7158310e746780fec0a378a1c63c01221711ecc3fb2e0d4` |
| AX-IMG-H01 | `b7709b8c204f8006c8852a1b7000dc38876fa3217f46ac72f9f4b3b0044fa8e3` | 49710 | `0635ad3b6a22387ad28ba8145a28a11e215bd687632aa6c83c3cbd8d33e4fbc8` |

## Evidence

- `summary.json`
- `prepared_manifest.json`
- `run/DQ-R01/`
- `run/DQ-R03/`
- `run/AX-IMG-H01_v2/`

Each run contains:

```text
prototype.rp
prototype.repeat.rp
design.ir.json
route.json
artifact_report.json
acceptance.json
reload_check.json
published/ or published_v3/
shots/ or shots_v3/
```

## Residual Risk

Fresh Grounding preparation of AX-IMG-H01 is not deterministic across repeated
live runs:

- first run: one image candidate plus one recovered crop;
- accepted v2 preparation: three image candidates;
- later v3 preparation: one image candidate.

The final image evidence is tied to the frozen accepted v2 prepared
DesignSpec. This variability prevents an arbitrary-image or deterministic-image
preparation claim.

## Verification

```text
A-005 focused regression set: 54 passed in 2.79s
tests/v2: 717 passed in 41.63s
A-005 touched-file Ruff check/format: pass
whole-repo Ruff baseline: 133 existing findings outside this task
node --check figma_bridge/code.js: pass
git diff --check: pass
Axure conformance: 3 files, c1 8/8, stores 7/7, pages 1/1 each
```

## Non-Claims

This task does not claim:

- clean unseen-sample generalization after remediation;
- arbitrary DOM or image fidelity;
- deterministic fresh Grounding output;
- original asset identity;
- Axure runtime image replacement;
- Auto Layout, clipping, native letter spacing or interaction reconstruction;
- save-back persistence;
- project-wide production readiness;
- transfer of Figma evidence.
