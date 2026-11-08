# Calibration Mode A/B: legacy vs residual

Date: 2026-11-08

Decision: **adopt `residual` as the default calibration mode; keep `legacy` as an
explicit fallback.**

This is a non-regression decision, not a pass claim. Both modes remain
`blocked-fail` on both samples under frozen `image-figma-mvp-product/2.0`.

## Scope

The A/B reuses the frozen prepared pipelines and runs real Figma
write/readback/export. No VLM call was made during calibration.

- FlexWeaver source:
  `output/_grounding_manual_20261108_search_control_post/pipeline/`
- ACCTOKEN Models source:
  `output/_image_figma_acctoken_models_20261108_rerun_full_high/pipeline/`
- acceptance policy: `image-figma-mvp-product/2.0`
- emission contract: `repair` (new default)
- calibration modes: `legacy`, `residual`
- Figma bridge: `ws://localhost:8765`
- origins: FlexWeaver `30000/32000/34000`, ACCTOKEN `36000/38000`

## Results

### FlexWeaver Admin

| Mode | Run | Critical | Native gate | Chrome | Within30 | Blockers | Adjusted | Rendered groups |
|---|---|---|---:|---|---:|---:|---:|---:|
| legacy | `_calibration_ab_20261108_flexweaver_legacy` | 24/24 | 14/33 | pass | 96.766167% | 19 | 176 | 12 |
| residual r1 | `_calibration_ab_20261108_flexweaver_residual` | 24/24 | 13/33 | pass | 96.762258% | 20 | 170 | 11 |
| residual r2 | `_calibration_ab_20261108_flexweaver_residual_r2` | 24/24 | 14/33 | pass | 96.766167% | 19 | 176 | 12 |

Residual r1 exposed a mapping defect: the profile had no `toolbar` region, so
the three toolbar groups were skipped and the native gate dropped by one owner.
Toolbar strategies now accept `toolbar | table | form | page` regions. Residual
r2 restores exact parity with legacy on every reported metric.

### ACCTOKEN Models

| Mode | Run | Critical | Native gate | Chrome | Within30 | Blockers | Adjusted | Selected / rendered groups |
|---|---|---|---:|---|---:|---:|---:|---:|
| legacy | `_calibration_ab_20261108_acctoken_legacy` | 24/27 | 0/26 | fail | 94.121133% | 32 | 9 | 13 / 1 |
| residual | `_calibration_ab_20261108_acctoken_residual` | 24/27 | 0/26 | fail | 94.121133% | 32 | 9 | 6 / 1 |

Residual mode produced byte-equivalent acceptance metrics while evaluating
seven fewer strategy groups. Only `font-initial` actually rendered in both
modes; the skipped table/form groups had no adjustments.

## Decision

- `--calibration-mode residual` is now the default.
- `--calibration-mode legacy` remains available for historical replay and A/B.
- The residual profile is recomputed after each actual render, so later groups
  are selected from current evidence rather than the initial frame only.
- No frozen truth, threshold, acceptance policy, or pass/fail status changed.

## Reproduction

FlexWeaver residual:

```powershell
python scripts/image_figma_mvp.py `
  --image tests/fixtures/image_to_slice_benchmark_2026-11-02/IMG-FLEXWEAVER-ADMIN.png `
  --truth tests/fixtures/image_to_slice_benchmark_2026-11-02/truth/IMG-FLEXWEAVER-ADMIN.truth.json `
  --out output/_calibration_ab_20261108_flexweaver_residual_r2 `
  --route grounding --acceptance-policy 2.0 --reuse-prepared `
  --calibration-mode residual --origin-x 34000 --origin-y 0
```

ACCTOKEN residual:

```powershell
python scripts/image_figma_mvp.py `
  --image output/_image_figma_acctoken_models_20261108_rerun_full_high/input.png `
  --truth output/_image_figma_acctoken_models_20261108_rerun_full_high/derived.truth.json `
  --out output/_calibration_ab_20261108_acctoken_residual `
  --route grounding --acceptance-policy 2.0 --reuse-prepared `
  --calibration-mode residual --origin-x 38000 --origin-y 0
```

All runs remain `blocked-fail`. This A/B supports only the calibration-mode
default change, not arbitrary-image generalization or production admission.
