# Axure Image Current-Scope Acceptance

**Tasks:** A-003 and A-004  
**Status:** `pass-current-scope`  
**Date:** 2026-10-25  
**Sample:** `IMG-MVP-01`  
**Evidence root:** `output/_axure_image_acceptance_2026-10-25_r2/`

## Decision

A-003 passes for the owned screenshot `IMG-MVP-01` under the Axure current
scope. The existing image MVP DesignSpec and shared `design-ir/2.0` were reused
without a second image-understanding pipeline. Axure RP 8 opened, reopened and
published a deterministic `.rp`, and independent published acceptance passed.

A-004 now has independent Axure acceptance evidence for both:

- `DOM -> Axure`: `DQ-R02` evidence in
  `output/_axure_dom_acceptance_2026-10-25_r2/`;
- `image -> Axure`: `IMG-MVP-01` evidence in this run.

This closes A-004 for the named controlled samples. It does not claim general
Axure product readiness.

## Input And Shared Boundary

| Item | Value |
|---|---|
| Source image | `tests/fixtures/image_mvp/simple_dashboard_v1.png` |
| Image SHA-256 | `7f39efc5e69b9ba16367aa19a1ccb1e3ea1681824419c93f0f9a3478e5153df4` |
| Image reference | `image-sha256:7f39ef...153df4` |
| Reference state | `faithful`, single frame, pixels observed |
| DPR / viewport / font identity | `unknown` |
| Shared IR | `design-ir/2.0`, document `63470f34...02ff` |
| Source strategy | existing Grounding candidate geometry with pixel-sampled styles |
| Flow | fixed-coordinate, candidate, not adaptive |

No Figma write/readback/export or edit evidence is used by this acceptance.

## Real Page And Artifact

| Item | Value |
|---|---|
| Axure page | `A003 IMG-MVP-01 Image Axure` |
| Page package GUID | `12bce8ac-d8f0-46c8-9da0-213fbf460010` |
| Canvas | `1200 x 800` |
| `.rp` | `output/_axure_image_acceptance_2026-10-25_r2/prototype.rp` |
| `.rp` size | `58296` bytes |
| `.rp` SHA-256 | `c48b3b076de70229af81cf26602e2b305b8375f9377fd7f1b6d82fb9f849a6b1` |
| Repeat `.rp` SHA-256 | `c48b3b076de70229af81cf26602e2b305b8375f9377fd7f1b6d82fb9f849a6b1` |

The Axure page has `22` top-level widgets:

| Widget class | Count |
|---|---:|
| `Text` | `14` |
| `Button` | `2` |
| `Image` | `1` |
| `Rect` | `5` |

The actual object graph matches all 22 primary widgets with zero comparison
mismatches and zero auxiliary widgets.

## Image Capability

The shared IR requires `runtime-image-replace`, but Axure RP 8 does not
support it. The route reports:

```text
runtime-image-replace -> creation-only-image-box
source_node_id: 14
```

The Axure `ImageBox` contains the selected display crop at creation time.
The crop payload SHA-256 is:

```text
17a9dd26f5efc4c91af75daf4c0309ef403b627d703b223a72277f1c27e89f91
```

The published image file matches that payload. It is explicitly
`reference_only=true`, `original=false`, `display_original=false` and
`generated=false`. There is no original asset or runtime replacement claim.

## Layout Defect Closed By TDD

The first real A-003 publish wrapped `Image import workspace` and split `24`
into `2` and `4`. This made the title overlap the subtitle even though the
aggregate visual score was above 90%.

The closed rule is limited to flat-image text candidates:

- no explicit line list;
- non-empty single-line text;
- box height no greater than `1.5 x font-size`;
- no change for multi-line descriptions.

The final publish keeps the title and two-digit statistics on one line while
the description remains wrap-capable. This behavior has a regression test in
`tests/v2/test_axure_evidence.py`.

## Axure Open, Reload And Publish

Environment:

```text
D:\Program File\Axure\Axure RP 8\AxureRP8.exe
version 8.0.0.3400
```

| Run | Result | Files |
|---|---|---:|
| First open/publish | `RESULT=OK` | `154` |
| Reopen/publish | `RESULT=OK` | `154` |

The page HTML is byte-identical between runs:

```text
E15E78D546B18372C46C520A85590A72430D4D7779DD20DAFF564179CD32FB00
```

All files except
`files/a003_img-mvp-01_image_axure/data.js` are byte-identical. That file
differs only in Axure's `generationDate`. See `reload_check.json`.

This proves reopen plus republish. It does not prove save-back rewriting or
runtime mutation.

## Independent Published Acceptance

| Check | Result |
|---|---|
| Page count | `1/1` |
| Page/package identity | `1/1` |
| Canvas | exact `1200 x 800` |
| Critical text | `14/14` |
| Native text widgets | `14` |
| Button widgets | `2` |
| Image widgets | `1` |
| Published unique image hashes | `1/1` |
| Unexpected image hashes | `0` |
| Failures | `0` |

Critical text includes the title, navigation, statistics, card copy and
`View details`.

Visual comparison uses the original screenshot, not the Figma export:

| Metric | Result |
|---|---:|
| Reference SHA-256 | `7f39efc5e69b9ba16367aa19a1ccb1e3ea1681824419c93f0f9a3478e5153df4` |
| Axure screenshot SHA-256 | `ca29adf7ab399f6bf38dc00d2da102905c66b3b43adb5370d6c8092887cec39d` |
| Size match | `1200 x 800` |
| Within-30 pixels | `96.57197916666667%` |
| Over-30 pixels | `3.428020833333333%` |
| Mean difference | `4.040980555555556` |
| Ink mean difference | `9.574870591987667` |
| Axure product minimum | `90%` |

## Evidence Hashes

| Artifact | SHA-256 |
|---|---|
| `axure_design.json` | `064ac0d5c568f6d9138cdba64a66da3036f1e22e1b939c2dcf86591764617d52` |
| `design.ir.json` | `977dbcfa258965b0f824c5b157993b0c0598d1055f66c4212bab534644197b81` |
| `route.json` | `244890ac916126eb3971805ede025c627105e9efe174ec30038d3ea78e8cba1b` |
| `artifact_report.json` | `0a7429937b29e3a68d8303a4fccf110969afd852af1a55368b9328c59df8384a` |
| `acceptance.json` | `12669e0fd95712cc2df208bab7bd748c94b0f3fee59bd5a87773be360653f319` |

Implemented code:

- `scripts/image_axure_mvp.py`;
- `src/app/services/rendering/axure_route.py`;
- `src/app/services/rendering/axure/evidence.py`;
- `src/app/services/evidence/axure_acceptance.py`.

## Reproduce

Generate the image-to-Axure artifact:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/image_axure_mvp.py `
  --design output/_image_figma_mvp_2026-10-25_r4/figma_design.json `
  --ir output/_axure_shared_ir_2026-10-25_r1/IMG-MVP-01-figma.ir.json `
  --out output/_axure_image_acceptance_2026-10-25_r2 `
  --page-name "A003 IMG-MVP-01 Image Axure" `
  --generate-twice
```

Publish with Axure RP 8:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/axure_publish_html.ps1 `
  -Path output/_axure_image_acceptance_2026-10-25_r2/prototype.rp `
  -Tag axure_image_a003_r2
```

Screenshot:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/axure_shoot_html.py `
  --dir "$env:USERPROFILE/Documents/Axure/HTML/axure_image_a003_r2" `
  --out output/_axure_image_acceptance_2026-10-25_r2/shots `
  --page a003_img-mvp-01_image_axure.html `
  --prefix axure_img_mvp_01 --width 1200 --height 800
```

Evaluate with the 14 truth-manifest strings:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/axure_acceptance.py `
  --publish-dir "$env:USERPROFILE/Documents/Axure/HTML/axure_image_a003_r2" `
  --design output/_axure_image_acceptance_2026-10-25_r2/axure_design.json `
  --rp output/_axure_image_acceptance_2026-10-25_r2/prototype.rp `
  --out output/_axure_image_acceptance_2026-10-25_r2 `
  --critical-text "Northstar Admin" `
  --critical-text "Image import workspace" `
  --critical-text "Start import" `
  --critical-text "128" `
  --critical-text "Pending orders" `
  --critical-text "24" `
  --critical-text "New customers today" `
  --critical-text "96%" `
  --critical-text "Fulfillment completion" `
  --critical-text "Latest imported layout" `
  --critical-text "Editable text" `
  --critical-text "sampled surfaces" `
  --critical-text "review report" `
  --critical-text "View details" `
  --reference-screenshot tests/fixtures/image_mvp/simple_dashboard_v1.png `
  --render-screenshot output/_axure_image_acceptance_2026-10-25_r2/shots/axure_img_mvp_01_p1.png
```

## Verification

```text
Axure-focused regression set: 32 passed in 2.63s
tests/v2: 703 passed in 40.81s
A-003/A-004 touched-file Ruff check/format: pass
whole-repo Ruff baseline: 133 existing findings outside this task
node --check figma_bridge/code.js: pass
git diff --check: pass
Axure conformance: c1 8/8, stores 7/7, pages 1/1, ok
```

The final `.rp` was regenerated after formatting with the same SHA-256
`c48b3b076de70229af81cf26602e2b305b8375f9377fd7f1b6d82fb9f849a6b1`.

## Non-Claims

This task does not claim:

- arbitrary screenshot-to-Axure reconstruction;
- original asset identity;
- original DPR, viewport or font identity;
- runtime image replacement in Axure;
- adaptive Auto Layout;
- hidden-region recovery;
- save-back editing or persistence;
- transfer of Figma acceptance or Figma runtime replacement evidence;
- general Axure product readiness.
