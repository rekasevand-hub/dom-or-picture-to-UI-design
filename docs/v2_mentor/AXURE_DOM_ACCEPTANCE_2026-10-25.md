# Axure DOM Current-Scope Acceptance

**Task:** A-002  
**Status:** `pass-current-scope`  
**Date:** 2026-10-25  
**Sample:** `DQ-R02`  
**Evidence root:** `output/_axure_dom_acceptance_2026-10-25_r2/`

## Decision

A-002 passes for the named controlled sample `DQ-R02` under the Axure-specific
current scope. The command path generated two byte-identical `.rp` files from
the shared `design-ir/2.0` input, Axure RP 8 opened and published the artifact,
the same `.rp` was reopened and published again, and independent published
HTML acceptance passed.

This decision does not upgrade the general Axure capability boundary.
`letter-spacing` remains unsupported and is represented by the captured
linebreak workaround. `can_claim_complete=false` remains correct for a full
Axure capability claim.

## Real Page And Artifact

| Item | Value |
|---|---|
| Axure page | `A002 DQ-R02 DOM Axure` |
| Page package GUID | `8f1cd483-2b3b-47f2-afd1-4d4b937b6e3e` |
| Canvas | `1440 x 2544` |
| Shared IR document | `fbc635a4362b1e85d7d4b469c4085f417f388e4410387e0e0c794eac476fa8ed` |
| `.rp` path | `output/_axure_dom_acceptance_2026-10-25_r2/prototype.rp` |
| `.rp` size | `647034` bytes |
| `.rp` SHA-256 | `4a18721adb6d6a709b2050b9f14f0a3624f7b9c75ffa845a7bbf65296a011944` |
| Repeat `.rp` SHA-256 | `4a18721adb6d6a709b2050b9f14f0a3624f7b9c75ffa845a7bbf65296a011944` |
| Second page | none; DQ-R02 is one page |

The Axure file does not expose a Figma-style frame ID. The real output
identity is page name plus page package GUID. Figma frame `76:4335` is source
provenance only and is not Axure evidence.

## Object Graph

`scripts/axure_rp8_conform.py` parsed the generated document directly:

| Check | Result |
|---|---:|
| ZIP members | `8` |
| Page packages | `1` |
| Registered pages | `1` |
| c1 stream round trip | `8/8` |
| Store layout round trip | `7/7` |
| Result | `ok` |

The page contains `469` top-level widgets:

| Widget class | Count |
|---|---:|
| `Rect` | `204` |
| `Button` | `119` |
| `Text` | `91` |
| `Image` | `54` |
| `TextField` | `1` |

The source/IR comparison accounts for `441` primary widgets plus `28`
auxiliary border rectangles created for bordered text. It reports:

```text
comparison_ok=true
content_mismatches=0
geometry/object mismatches=[]
```

The `.rp` graph retains `54` `ImageBox` payloads. Their bytes were compared
with the selected display payloads from the source DesignSpec.

## Asset Provenance

| Asset state | Uses |
|---|---:|
| Verified source identity | `44` |
| Source unavailable | `10` |
| Screenshot display crop | `44` |
| Generated approximation | `10` |
| `display_original=true` | `0` |

All 44 verified-source uses have `reference_only=true` display crops and are
not represented as original display assets. The 10 generated icon
approximations remain generated and non-original. Axure receives the selected
display bytes at creation time; it does not provide runtime image replacement
through this adapter.

## Axure Open, Reload And Publish

Environment:

```text
D:\Program File\Axure\Axure RP 8\AxureRP8.exe
version 8.0.0.3400
```

Axure published the same `.rp` twice:

| Run | Result | Files |
|---|---|---:|
| First open/publish | `RESULT=OK` | `183` |
| Reopen/publish | `RESULT=OK` | `183` |

Both runs contain the same file set. The published page HTML is byte-identical:

```text
EC593337CD4E34188D0ED99D754A576DA6B1B908ADD7A0AFFDB5F548C83AAB5A
```

All files except
`files/a002_dq-r02_dom_axure/data.js` are byte-identical between the two runs.
That file differs only in Axure's `generationDate`. The comparison is retained
in `reload_check.json`.

This proves reopen plus republish of the same `.rp`. It does not prove
save-back rewriting, dynamic widget mutation or post-publish runtime editing.

## Independent Published Acceptance

Evidence:

- `acceptance.json`;
- `published/`;
- `published_reload/`;
- `shots/axure_dq_r02_p1.png`.

| Check | Result |
|---|---|
| Published page count | `1` |
| `data-label` widget count | `469` |
| Source labels present | pass |
| Critical text | `3/3` |
| Native text/button/input widgets | present |
| Page/package registry | `1/1` |
| Canvas match | `1440 x 2544` |
| Unique image bytes | `30/30` |
| Unexpected image hashes | `0` |
| Failures | `0` |

Critical text checked:

```text
读书好，好读书，读好书！
搜索海量图书
国学入门
```

Visual acceptance used the original DQ-R02 screenshot, not a Figma export:

| Metric | Result |
|---|---:|
| Reference SHA-256 | `2f51949d84d0e88e13c5d7817703771afcaad83c559e7a03bebce401128b2f8c` |
| Axure screenshot SHA-256 | `6958ce862642116f67f4f80237e2f2d5827ff26f19be93eb811ed8dea7cec411` |
| Size match | `1440 x 2544` |
| Within-30 pixels | `99.37718378756114%` |
| Over-30 pixels | `0.6228162124388539%` |
| Mean difference | `0.41638705086769157` |
| Ink mean difference | `1.8691833545549252` |
| Axure product minimum | `90%` |

This visual result is Axure-specific. Figma acceptance fields are explicitly
false/not transferable in the route report.

## Code And Data Evidence

| Artifact | SHA-256 |
|---|---|
| `axure_design.json` | `769541fd14fedc99185f759a604aaedc5b1522ac903469b3d9743f56aea0c8b7` |
| `design.ir.json` | `4cf86945550cba6a4079079f4501d4ab028946cc50dba08f7169b6c1e2e798d0` |
| `route.json` | `ec7b2a43ef9ad621d9c71a73338c2e9f72388b1a198bc4f812000812e6b3694f` |
| `artifact_report.json` | `77053fc813c5812fb33caeb74cb0df01cafef427e6677f2d3d26d72499e7f1e6` |
| `acceptance.json` | `bea6574857fb2b31c7228e3c54c8e316a2929b13f6b95c1f488a4a8711f6352d` |
| `reload_check.json` | `c816f89d8099c99b4acb5c80c8a49847378d8dd4799b69c4d8a145bbb427dce0` |

Implemented code:

- `src/app/services/rendering/axure_route.py`;
- `src/app/services/rendering/axure/evidence.py`;
- `src/app/services/evidence/axure_acceptance.py`;
- `scripts/axure_dom_output.py`;
- `scripts/axure_acceptance.py`.

## Reproduce

Generate and verify deterministic `.rp`:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/axure_dom_output.py `
  --design output/_dom_figma_generated_icons_2026-10-25_r1/design.json `
  --ir output/_axure_shared_ir_2026-10-25_r1/DQ-R02-figma.ir.json `
  --out output/_axure_dom_acceptance_2026-10-25_r2_next `
  --source-kind dom `
  --page-name "A002 DQ-R02 DOM Axure" `
  --generate-twice
```

Publish with Axure RP 8:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/axure_publish_html.ps1 `
  -Path output/_axure_dom_acceptance_2026-10-25_r2_next/prototype.rp `
  -Tag axure_dom_a002_r2_next
```

Screenshot the published page:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/axure_shoot_html.py `
  --dir "$env:USERPROFILE/Documents/Axure/HTML/axure_dom_a002_r2_next" `
  --out output/_axure_dom_acceptance_2026-10-25_r2_next/shots `
  --page a002_dq-r02_dom_axure.html `
  --prefix axure_dq_r02 --width 1440 --height 2544
```

Evaluate published artifacts:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts/axure_acceptance.py `
  --publish-dir "$env:USERPROFILE/Documents/Axure/HTML/axure_dom_a002_r2_next" `
  --design output/_axure_dom_acceptance_2026-10-25_r2_next/axure_design.json `
  --rp output/_axure_dom_acceptance_2026-10-25_r2_next/prototype.rp `
  --out output/_axure_dom_acceptance_2026-10-25_r2_next `
  --critical-text "读书好，好读书，读好书！" `
  --critical-text "搜索海量图书" `
  --critical-text "国学入门" `
  --reference-screenshot output/_dom_text_quality_capture_placeholder_2026-10-25/DQ-R02/00_screenshot.png `
  --render-screenshot output/_axure_dom_acceptance_2026-10-25_r2_next/shots/axure_dq_r02_p1.png
```

## Verification

```text
A-002 focused tests: 15 passed
tests/v2: 698 passed in 40.47s
Ruff check/format on A-002 touched files: pass
Whole-repo Ruff baseline: 133 existing findings outside this task
node --check figma_bridge/code.js: pass
git diff --check: pass
Axure conform: 1 file, 8 c1 streams, 7 stores, all pass
```

The focused test count includes route planning, `.rp` inspection,
determinism/output probing, published acceptance, and HTML-escaped labels.
The whole-repo Ruff finding count is recorded rather than hidden; this task
does not modify unrelated legacy scripts or source files.

## Non-Claims

This task does not claim:

- arbitrary DOM-to-Axure fidelity;
- Axure runtime image replacement;
- native Axure letter spacing;
- Auto Layout, clipping containers or component instances;
- interactions reconstructed from DesignSpec;
- save-back/reload mutation durability;
- general Axure product readiness;
- transfer of any Figma acceptance result;
- that screenshot crop or generated icon pixels are original display assets.
