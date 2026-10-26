# Global Optimization Master Plan

> **For agentic workers:** This is the program-level handoff plan, not a
> single implementation plan. Before coding a phase, create a separate
> task-level plan from the relevant phase below. Use
> `superpowers:writing-plans` for that plan and
> `superpowers:executing-plans` or
> `superpowers:subagent-driven-development` for execution.

**Status:** active  
**Last updated:** 2026-10-25  
**Current phase:** A-011 Axure current scope closed  
**Completed phases:** DOM quality closure, image MVP, Axure shared IR boundary, controlled Axure paths, A-005 through A-010 holdout/remediation work and A-011 current-scope exit review  
**Next task:** await user priority decision between Axure capability expansion and production admission  
**Deferred product phase:** Axure routes  
**Deferred hardening phase:** additional deterministic fault-matrix and
production-environment work  
**Branch:** `feature/precise-agent-router`

**Goal:** Preserve the mentor-approved route hierarchy and priority order so
future work cannot accidentally return to the old `dom | grounding | cv`
three-route model, overstate current evidence, or spend effort on deferred
reliability work before the current product-route gates are closed.

**Architecture:** Treat input type and output target as product dimensions.
`DOM` and `image` are input families; Figma and Axure are output targets.
Grounding, CV and an explicitly proven hybrid are implementation strategies
under `image`, not peer product routes.

**Primary mentor source:** User-provided mentor reply dated 2026-10-25,
recorded at `C:/Users/lzq/Desktop/导师问题回答.txt`.

**Supporting specifications:**

- `docs/v2_mentor/V2_OPTIMIZATION_PLAN.md`
- `docs/v2_mentor/ROUND_01_ANSWERS_FORMATTED.md`
- `docs/v2_mentor/ROUND_02_ANSWERS_FORMATTED.md`
- `docs/v2_mentor/ROUND_03_ANSWERS_FORMATTED.md`
- `docs/v2_mentor/ROUND_05_ANSWERS_FORMATTED.md`
- `docs/v2_mentor/P1_CANONICAL_OUTPUT_FIDELITY.md`
- `docs/v2_mentor/P1_FIGMA_ACCEPTANCE.md`
- `docs/v2_mentor/P2_EXTENDED_CLOSURE.md`
- `docs/v2_mentor/P3_GRID_COMPLEX_HOLDOUT.md`
- `docs/v2_mentor/P5_DETERMINISTIC_FAULT_MATRIX.md`
- `docs/v2_mentor/R5_P5_PRODUCTION_ROADMAP_2026-10-22.md`

## How To Use This Document

1. Read the decision baseline before opening a new optimization task.
2. Check the current phase and task table before choosing work.
3. Do not advance a phase without its exit gate.
4. Update the status table, decision log and evidence references after every
   completed task.
5. Create a phase-specific implementation plan before touching code.
6. Run the mandatory regression suite in every phase.
7. Keep implementation evidence, test evidence and mentor decisions separate.

Status vocabulary:

| Status | Meaning |
|---|---|
| `complete-current-scope` | Implemented and evidenced only for the named controlled scope |
| `active` | The current priority |
| `planned` | Approved but not started |
| `deferred` | Intentionally postponed; do not start without a new priority decision |
| `blocked-environment` | Progress requires a missing real account, host or external service |
| `frozen` | A decision or task intentionally kept closed until a trigger is met |
| `not-admitted` | No production claim is allowed |

## 1. Decision Baseline

These decisions are the durable handoff baseline. A later change requires a
new dated decision entry with evidence and an impact statement.

| ID | Decision | Source | Status |
|---|---|---|---|
| G-001 | Product outputs are Figma and Axure. Figma comes first. | Mentor 2026-10-25 | frozen |
| G-002 | Product inputs are DOM and image (screenshot/image). | Mentor 2026-10-25 | frozen |
| G-003 | Grounding and CV are image parsing strategies, not product routes. | Mentor 2026-10-25 | frozen |
| G-004 | Grounding is the default image strategy. | Mentor 2026-10-25 | frozen |
| G-005 | CV is the fallback only when the Grounding VLM is unavailable. | Mentor 2026-10-25 | frozen |
| G-006 | A Grounding/CV hybrid may be evaluated as an experiment, but is not the default until evidence proves it better. The first frozen benchmark rejected the conservative hybrid. | Mentor 2026-10-25; benchmark 2026-10-26 | rejected-current-scope |
| G-007 | Close remaining DOM quality gaps and strategy fusion before starting the image product route. | Mentor 2026-10-25 | frozen |
| G-008 | The first image milestone is a single user-uploaded screenshot with basic editability and asset replacement. | Mentor 2026-10-25 | planned |
| G-009 | Image flow may be proposed as `candidate`, but cannot be claimed `verified` without evidence. | Mentor 2026-10-25 | frozen |
| G-010 | Fabricated or approximate output that is presented as verified/original is forbidden. | Mentor 2026-10-25 | frozen |
| G-011 | Partial visual, structure, asset and edit dimensions are allowed only when explicitly reported. | Mentor 2026-10-25 | frozen |
| G-012 | Axure routes follow after the Figma product route is sufficiently proven. | Mentor 2026-10-25 | complete-current-scope |
| G-013 | Additional deterministic fault-matrix expansion is deferred until the product-quality phases justify it. | User directive 2026-10-25 | deferred |
| G-014 | Task 10 Q8-Q10 mentor rulings are not part of the current plan. | User directive 2026-10-25 | frozen |
| G-015 | Layout, components and content target at least 90% current-scope usability rather than exact pixel identity. Generated icon approximations are allowed with explicit provenance; final glyph identity is non-required. | User directive 2026-10-25 | frozen |

Interpretation guard:

- "Basic editability" for the first image milestone means native text where
  trust conditions are met, replaceable assets where possible, and basic
  visibility/name operations. It does not mean all containers must pass
  adaptive Auto Layout L3.
- Any generated approximation is a visible fallback, not an original asset.
- A passing deterministic test proves only its named deterministic scope.

## 2. Canonical Route Model

```text
Product route
├── DOM -> Figma                  COMPLETE-CURRENT-SCOPE
├── image -> Figma                COMPLETE-CURRENT-SCOPE
├── DOM -> Axure                  COMPLETE-CURRENT-SCOPE / A-002
└── image -> Axure                COMPLETE-CURRENT-SCOPE / A-003/A-004

image parsing strategy
├── Grounding                     DEFAULT
├── CV                            FALLBACK WHEN VLM UNAVAILABLE
└── Grounding + CV hybrid         EXPERIMENT ONLY
```

The current implementation-level `dom | grounding | cv` router must not be
used as the product-planning vocabulary.

For URL input the desired high-level behavior is:

1. Capture the page and preserve reference-state evidence.
2. Use DOM when verified DOM evidence exists.
3. Use image parsing only when DOM is unavailable or explicitly requested.
4. Within image parsing, use Grounding by default.
5. Use CV only when the Grounding VLM is unavailable.
6. Use a hybrid only after a fixed benchmark shows a net improvement.
7. Do not silently switch from `faithful` to inferred `adaptive` behavior.

## 3. Current Baseline

### 3.1 DOM to Figma

Status: strongest implemented quality path, still not fully generalized.

Evidence already available:

| Evidence | Result | Limitation |
|---|---|---|
| Canonical Figma holdout | 5/5 pass under frozen policy | Controlled canonical samples only |
| P2 Figma holdout | 10 pass, 1 partial, 0 blocked | Not all fonts, layouts or real sites |
| Complex Grid holdout | Real Figma create, reload, document reopen and cleanup pass | Not all Grid permutations |
| Native text edit probe | Pass | Does not prove final glyph identity |
| Image fill replacement | Payload SHA-256 and replace/restore pass | Does not prove original SVG source identity |
| Auto Layout parent propagation | Vertical fixed-width probe pass | General adaptive layout remains incomplete |
| P5 output hard-gate matrix | 9/9 checks pass | Fixed authored profile |

Known DOM gaps:

- Text linebreak, baseline, mixed-font runs and final glyph identity remain
  incomplete.
- General Auto Layout L2/L3 behavior is not proven across Grid, wrap,
  component and complex nesting.
- Original asset identity and missing-asset strategy remain incomplete.
- Real-site canonical observation is limited and not continuous.
- Strategy fusion for assets that cannot be captured is not yet closed.

### 3.2 Image to Figma

Status: `pass-current-scope` for one owned screenshot and one real Figma
document.

Evidence:

- R3 defines image input state, grouping, text, assets, flow candidate and
  four-dimensional acceptance contracts.
- R3 and R4 contain controlled grouping, OCR, CV, asset, flow and acceptance
  experiments.
- Grounding and CV provider prototypes already exist.
- The MVP now has a faithful image reference, deterministic pixel-sampled
  design, candidate-safe OCR supplement, reference-only image provenance and
  real Figma write/readback/export evidence.

Current evidence:

- `docs/v2_mentor/IMAGE_FIGMA_MVP_ACCEPTANCE_2026-10-25.md`;
- `docs/v2_mentor/IMAGE_FIGMA_MVP_LEDGER_2026-10-25.md`;
- `output/_image_figma_mvp_2026-10-25_r4/acceptance.json`.

Current-scope result:

- Grounding selected; no fallback used;
- critical text `14/14`;
- native text edit/restore pass;
- one reference-only image display replace/restore pass;
- real Figma frame `77:4851`;
- export within-30 `96.533125%`, above the frozen 90% gate;
- original asset, font, DPR/viewport and adaptive-flow claims remain false.

Known gaps:

- no arbitrary-screenshot benchmark;
- CV fallback has a real Figma run, but the fallback result is
  `blocked-fail` on critical text, structure and assets;
- OCR supplement is not a general end-to-end text detector;
- original asset identity and font/glyph truth remain unavailable;
- adaptive flow is not implemented;
- the conservative Grounding/CV hybrid was rejected for the current sample
  because it produced no independent improvement.

### 3.3 Axure

Status: the named controlled Axure current scope is `pass-current-scope`
through A-011. A-001 through A-004, A-007, A-009 and A-011 are
`complete-current-scope`/`pass-current-scope` for their declared scopes.
A-005 is `partial-post-holdout-tuning`; A-006 and A-008 are historic failures.
A-010 is `pass-unseen-holdout` for three frozen samples. Arbitrary capability
and production readiness remain unclaimed.

The same canonical IR and source provenance should eventually drive Axure.
Do not build a separate image understanding stack for Axure.

Current boundary evidence:

- `docs/v2_mentor/AXURE_SHARED_IR_BOUNDARY_2026-10-25.md`;
- `docs/v2_mentor/AXURE_ROUTE_LEDGER_2026-10-25.md`;
- `output/_axure_shared_ir_2026-10-25_r1/summary.json`.

A-002 current evidence:

- `docs/v2_mentor/AXURE_DOM_ACCEPTANCE_2026-10-25.md`;
- `output/_axure_dom_acceptance_2026-10-25_r2/artifact_report.json`;
- `output/_axure_dom_acceptance_2026-10-25_r2/acceptance.json`;
- `output/_axure_dom_acceptance_2026-10-25_r2/reload_check.json`.

The boundary projects both `IMG-MVP-01` and `DQ-R02` designs with zero
validation issues. A-002 now generates a deterministic `.rp`, Axure RP 8
opens/reopens and publishes it, and independent Axure HTML acceptance passes
for DQ-R02. The DOM output has 469 widgets, 54 creation-time image payloads,
3/3 critical text, 30/30 published unique asset hashes and 99.3772%
within-30 similarity against the original DOM screenshot.

This is still one controlled sample. Native letter spacing remains
unsupported and uses a hard-line workaround. Runtime image replacement,
Auto Layout, clipping and interaction reconstruction remain unavailable.

A-003/A-004 current evidence:

- `docs/v2_mentor/AXURE_IMAGE_ACCEPTANCE_2026-10-25.md`;
- `output/_axure_image_acceptance_2026-10-25_r2/artifact_report.json`;
- `output/_axure_image_acceptance_2026-10-25_r2/acceptance.json`;
- `output/_axure_image_acceptance_2026-10-25_r2/reload_check.json`.

The image output reuses the existing image MVP design and shared IR. It has
22 widgets, one creation-time reference-only image payload, 14/14 critical
text, 1/1 published image hash and 96.5720% within-30 similarity against the
original screenshot. Axure reopens and republishes the same deterministic
`.rp` with identical page HTML. Runtime replacement is explicitly degraded to
`creation-only-image-box`.

A-005 holdout evidence:

- `docs/v2_mentor/AXURE_HOLDOUT_ACCEPTANCE_2026-10-25.md`;
- `output/_axure_holdout_2026-10-25/summary.json`;
- `tests/fixtures/axure_holdout/holdout_v1.json`.

The frozen inputs exposed real DQ-R01 asset-binding, DQ-R03 layout and
AX-IMG-H01 OCR/asset failures. TDD fixes made all samples pass under the
unchanged thresholds, but the same holdout drove remediation. This is
post-tuning evidence, not a clean generalization claim. A new untouched
holdout is required next.

A-006 untouched holdout evidence:

- `docs/v2_mentor/AXURE_HOLDOUT_V2_ACCEPTANCE_2026-10-25.md`;
- `output/_axure_holdout_v2_2026-10-25/summary.json`;
- `tests/fixtures/axure_holdout_v2/holdout_v2.json`.

Frozen `AX6-DOM-FONTFALLBACK` and `AX6-IMG-OVERLAY` pass.
`AX6-DOM-TEXTFLOW` fails the object-mapping gate because the `.rp` contains
an unexpected empty 360x96 Rect at `(24,178)`. No remediation was performed
after the result.

A-007 attribution evidence:

- `docs/v2_mentor/AXURE_EXTRA_RECT_ATTRIBUTION_2026-10-25.md`;
- `output/_axure_holdout_v2_2026-10-25/a007_retriage/AX6-DOM-TEXTFLOW/artifact_report.json`;
- `tests/v2/test_axure_evidence.py`.

A-007 identifies the Rect as a derived auxiliary background for a styled
native Text, not a ghost object. The comparator now allows one unlabeled Rect
only when it exactly explains an already matched Text's source outer geometry.
The regenerated `.rp` is byte-identical to A-006, so this remediation changes
attribution, not visual output. A-006 remains failed; A-008 requires a fresh
untouched holdout.

A-008 fresh holdout evidence:

- `docs/v2_mentor/AXURE_FRESH_HOLDOUT_A008_2026-10-25.md`;
- `output/_axure_holdout_v3_2026-10-25/summary.json`;
- `tests/fixtures/axure_holdout_v3/holdout_v3.json`.

`AX8-DOM-MOBILE320` passes. `AX8-DOM-IFRAME` passes deterministic artifact,
object and label-only text gates but fails reference review because iframe
content is absent and the content Text overlaps the title. The source
DesignSpec already contains the wrong child coordinate. `AX8-DOM-PARTIAL-ASSET`
matches the reference and all two image hashes, but the frozen manifest expects
one asset while the truth declares two; it is an evaluation-contract
inconclusive, not evidence of an output mismatch. Aggregate remains
`fail-unseen-holdout`.

A-009 remediation evidence:

- `docs/v2_mentor/AXURE_A009_RENDERED_REGION_REPAIR_2026-10-25.md`;
- `output/_axure_a009_2026-10-25/summary.json`;
- `tests/v2/test_axure_acceptance.py`.

The current frame collector already places accessible iframe text at
`(18,133)`; A-008 used a stale DesignSpec at `(16,37)`. A-009 regenerated the
input, added screenshot-region ink verification to Axure acceptance and
corrected the partial-asset count contract. Replaying the old A-008 render
now fails at the iframe content region, while the repaired render preserves
the reference ink ratio. This closes only the repaired sample scope.

A-010 fresh holdout evidence:

- `docs/v2_mentor/AXURE_FRESH_HOLDOUT_A010_2026-10-25.md`;
- `output/_axure_holdout_v4_2026-10-25/summary.json`;
- `tests/fixtures/axure_holdout_v4/holdout_v4.json`.

`AX10-DOM-ASSETS`, `AX10-DOM-TRANSPARENT-CROP` and
`AX10-DOM-NESTED-IFRAME` all pass object, critical text, asset, visible-region,
visual, deterministic and reopen gates. This is a clean frozen-holdout pass.
It does not establish arbitrary DOM fidelity or production readiness.

A-011 exit review evidence:

- `docs/v2_mentor/AXURE_CURRENT_SCOPE_EXIT_REVIEW_2026-10-25.md`;
- `output/_axure_current_scope_exit_2026-10-25/summary.json`.

The named `DOM -> Axure` and controlled image-sample routes close as
`pass-current-scope`. Historical A-006/A-008 failures and A-007/A-009
remediations remain separately recorded. The image route was not rerun with
the A-009 visible-region gate, so that coverage limitation is retained.
Production admission and arbitrary generalization remain false.

### 3.4 Deterministic Fault Matrix And Stability

Status: sufficient for the current controlled scope; expansion deferred.

Current evidence:

- Permission, rate-limit, plugin reconnect, expected-state, region
  compensation, unknown/no-resend and cleanup safety have deterministic
  coverage.
- Round-2 matrix evidence is recorded in
  `docs/v2_mentor/P5_DETERMINISTIC_FAULT_MATRIX.md`.
- The latest full regression recorded at the time of that work was 525 tests
  plus 20 bridge JS tests and `node --check`.

Deferred work:

- Additional combinatorial fault expansion beyond a newly identified real
  product risk.
- Real permission/rate-limit/two-collaborator/takeover evidence.
- Task 10 Q8-Q10 rulings.
- Production storage scaffolding.
- 1h/24h/7d cloud soak and production admission.

Mandatory maintenance:

- Run existing focused and full regression tests in every phase.
- Any new bug fix still requires a failing regression test.
- Existing fault-matrix tests are not deleted or weakened because expansion is
  deferred.

## 4. Priority Ladder

### Stage 1: DOM Quality Closure

Priority: highest  
Status: `pass-current-scope`  
Product route: `DOM -> Figma`

Exit gate:

- A fixed real-site canonical corpus is frozen before measurement.
- Critical text, structure, native edit and required asset checks are reported
  independently.
- Known typography and layout gaps are either closed or explicitly scoped out.
- The missing-asset and generated-approximation fusion policy is implemented
  without masquerading.
- At least one representative real-site sample passes the agreed DOM quality
  gate with real Figma write/readback/export evidence.
- No project-wide Figma fidelity claim is made from controlled samples alone.

**D-009 decision:** `pass-current-scope`. The DQ-R02 Figma run passes visual,
structure, edit, asset, text and export gates. Generated icons fill the 10
iconfont gaps with complete provenance. Final glyph identity is
`not-required`. Within-30 pixel similarity is `97.5138%`, above the approved
90% product bar. Stage 2 was admitted by this decision and has since completed
its own current-scope gate.

### Stage 2: Image To Figma MVP

Priority: next  
Status: `pass-current-scope`  
Product route: `image -> Figma`

Exit gate:

- One user-uploaded screenshot can traverse the complete route.
- Grounding is the default; CV fallback occurs only when the Grounding VLM is
  unavailable.
- Critical text is correct.
- Native text exists where claimed; image assets can be replaced where claimed.
- At least one owned Figma sample completes write, readback and export.
- Unsupported structure, fixed-coordinate limits and `candidate` flow are
  visible in the report.
- No OCR candidate, screenshot crop or generated approximation is presented as
  a verified original.

**I-MVP-01 decision:** `pass-current-scope`. One owned screenshot traversed
Grounding, deterministic pixel-sampled presentation, reference-only asset
handling, real Figma write/readback/export and independent four-dimension
acceptance. Critical text is `14/14`; runtime image display replacement passes;
real export within-30 is `96.533125%`. Adaptive flow and original asset identity
remain explicit non-claims.

### Stage 3: Axure Route

Priority: after Stage 2  
Status: pass-current-scope for one controlled DOM sample and one controlled image sample  
Product routes: `DOM -> Axure`, `image -> Axure`

Exit gate:

- Reuse the canonical IR and strategy layer rather than duplicating image
  understanding.
- State explicitly which editability and asset guarantees Axure can preserve.
- Produce a separate Axure acceptance report; Figma pass cannot substitute.

### Stage 4: Deferred Stability And Production Hardening

Priority: after product-route milestones unless a current blocker demands it  
Status: deferred

Exit gate:

- Reopen only from a named unresolved risk or an admission requirement.
- Do not treat deterministic `current-scope` evidence as real-environment
  proof.
- Keep Task 10 Q8-Q10, production storage and long soak as separate decisions.

## 5. Task Register

The tables below are the handoff memory. Update them after each task. A task
may not be marked complete without an evidence path and verification command.

### 5.1 Stage 1: DOM Quality

| ID | Task | Status | Depends on | Required output |
|---|---|---|---|---|
| D-001 | Freeze the route taxonomy and update architecture language | complete-current-scope | G-003 | A route model without `dom/grounding/cv` product-peer wording |
| D-002 | Audit remaining DOM quality gaps against R1/R2/R3-D/P1/P2/P3 | complete-current-scope | D-001 | Deduplicated gap register with current evidence links |
| D-003 | Build a fixed real-site canonical DOM corpus | complete-current-scope | D-002 | Frozen URLs/states/viewports/fonts/DPR and thresholds |
| D-004 | Close text and font quality gaps | complete-current-scope | D-003 | Content, linebreak, box, baseline and glyph results separated |
| D-005 | Close general Auto Layout behavior gaps | complete-current-scope | D-003 | L1/L2/L3 evidence and fixed-coordinate fallback rules |
| D-006 | Close asset identity and replacement gaps | complete-current-scope | D-003 | Source identity, crop, replacement mode and missing-state behavior |
| D-007 | Implement strategy fusion with explicit provenance | complete-current-scope | D-004..D-006 | Ordered source/fallback policy and generated-approximation status |
| D-008 | Run real Figma DOM acceptance on the frozen corpus | complete-current-scope | D-003..D-007 | Real write/readback/export and four-dimensional report |
| D-009 | Hold the DOM quality exit review | complete-current-scope | D-008 | `current-scope`, `partial` or blocked decision with evidence |

#### D-001 Deliverable

- Replace product documentation that describes Grounding/CV as peer routes.
- Record `input family x output target` as the stable vocabulary.
- Keep implementation-level strategy names only where needed.

Current evidence (2026-10-25):

- Product vocabulary: `README.md`.
- Interactive input choices and CV-fallback wording:
  `src/app/agents/route_select.py`.
- CLI implementation-layer wording: `src/main.py`.
- Regression:
  `tests/v2/test_route_taxonomy.py` -> `3 passed`.
- Product-level forbidden wording scan:
  `rg -n -i -e 三条路线 -e 三源路由 -e 可直接作为主处理方向 README.md src tests`
  -> no matches.

#### D-002 Deliverable

The gap register must distinguish:

- not implemented;
- implemented but not verified for the current controlled scope;
- verified only for a bounded fixture;
- blocked by real environment;
- intentionally out of current scope.

Current evidence (2026-10-25):

- Register: `docs/v2_mentor/DOM_QUALITY_GAP_REGISTER_2026-10-25.md`.
- 20 deduplicated gaps across R1, R2, R3-D, P1, P2 and P3.
- Contract tests: `tests/v2/test_dom_quality_gap_register.py` and
  `tests/v2/test_route_taxonomy.py` -> `7 passed`.
- Mandatory regression:
  `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q`
  -> `532 passed in 31.38s` (final rerun).
- Bridge syntax: `node --check figma_bridge\code.js` -> exit 0.
- Claim impact: no quality dimension was upgraded to `verified`; D-003 was
  activated at this checkpoint and completed separately below.

#### D-003 Corpus Gate

Freeze before measurement:

- page URLs and saved states;
- Chromium build;
- viewport and DPR;
- locale and timezone;
- font environment;
- allowed network behavior;
- critical text and objects;
- acceptance thresholds;
- known exclusions.

Do not modify thresholds after observing results.

Current evidence (2026-10-25):

- Corpus document: `docs/v2_mentor/DOM_QUALITY_CORPUS_2026-10-25.md`.
- Frozen manifest: `tests/fixtures/dom_quality/real_site_corpus_v1.json`.
- Required samples: React, Dushu and Shoelace; W3Schools iframe is excluded
  as `excluded-state-unstable`.
- Frozen environment: Chromium `151.0.7922.34`, `1440x900`, DPR 1,
  `zh-CN`, `Asia/Shanghai`, headless.
- Freeze summary: `output/_dom_quality_corpus_2026-10-25/summary.json`;
  required samples `3/3` pass.
- Independent verify summary:
  `output/_dom_quality_corpus_verify_2026-10-25/summary.json`; required
  samples `3/3` pass and all frozen environment checks pass.
- Frozen hashes:
  thresholds `6dd4f29ed90041bb5fbd7912d8c772603279c27f114896dbc2c04f832251d8a2`,
  corpus `edec396946c03755fabbdea70e6ab210d5a0516b3eef7034c218386f8e45f4ef`.
- Claim impact: corpus state reproducibility is `current-scope`; no text,
  layout, asset, edit or Figma quality dimension is upgraded.
- Mandatory regression:
  `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q`
  -> `544 passed in 31.84s`.
- Static checks: Ruff check and format check pass for the corpus module,
  script and tests; `node --check figma_bridge\code.js` -> exit 0.

#### D-004 Deliverable

Current evidence (2026-10-25):

- Report: `docs/v2_mentor/DOM_TEXT_FONT_QUALITY_2026-10-25.md`.
- Enhanced capture:
  `output/_dom_text_quality_capture_2026-10-25/summary.json`; required
  samples `3/3` pass.
- Independent text report:
  `output/_dom_text_quality_2026-10-25/summary.json`; hard gate pass,
  overall `partial`.
- Critical text: `3/3` required samples.
- Content: `914/914` text nodes pass.
- Text box: `914/914` pass with horizontal `2.0 px` tolerance and separate
  vertical font-paint overflow.
- Linebreak: measured rows `885/885` pass; coverage `885/914 = 96.83%`;
  29 mixed-content nodes remain `not-evaluated`.
- Baseline: `914/914` browser-derived baselines; status is `derived`, not
  glyph-baseline truth.
- Glyph: direct faces `33`, representative inheritances `805`, ambiguous
  mixed faces `21`, missing React evidence `55`; face coverage `93.98%`.
  Final glyph-outline identity remains `not-evaluated`.
- Implementation: `src/app/services/evidence/dom_text_quality.py`,
  `scripts/dom_text_quality.py` and DOM capture evidence fields.
- Claim impact: content, linebreak/box reporting and representative font
  evidence are current-scope; no Figma or final-glyph claim is upgraded.
- Mandatory regression:
  `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q`
  -> `558 passed in 32.57s`.
- Static checks: Ruff check and format check pass; `node --check
  figma_bridge\code.js` -> exit 0.

#### D-005 Deliverable

Current evidence (2026-10-25):

- Report: `docs/v2_mentor/DOM_LAYOUT_QUALITY_2026-10-25.md`.
- Report JSON:
  `output/_dom_layout_quality_2026-10-25/summary.json`.
- Frozen corpus: `448` containers with at least two direct children.
- L1 inferred candidates: `308/448`, split into CSS `214` and geometry `94`.
- L2 static replay: `225/448`.
- L3 bounded local output contracts: `115/448`.
- Fixed fallback reasons include inline-flow `75`, geometry mismatch `39`,
  non-uniform gap `10`, float `10`, wrap `2`, Grid `1`, order `1`,
  content overflow `1` and unsupported display `1`.
- Policy change: Grid/wrap/reverse no longer continue into one-dimensional
  geometry fallback; they remain fixed-coordinate.
- Claim impact: L1/L2/L3-local evidence is current-scope. Real Figma runtime,
  parent propagation and source-browser perturbation remain not evaluated.
- Mandatory regression:
  `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q`
  -> `569 passed in 32.71s`.
- Static checks: Ruff check and format check pass; `node --check
  figma_bridge\code.js` -> exit 0.

#### D-006 Deliverable

Current evidence (2026-10-25):

- Report: `docs/v2_mentor/DOM_ASSET_QUALITY_2026-10-25.md`.
- Report JSON:
  `output/_dom_asset_quality_2026-10-25/summary.json`.
- Source probes:
  `output/_dom_asset_quality_2026-10-25/source_probes.json`.
- Frozen corpus: `203` asset identities and `227` display uses across React,
  Dushu and Shoelace.
- Source identity: `42` unique remote sources were retained and re-read from
  bytes; MIME, SHA-256 and natural dimensions were revalidated. `26` remote
  references remain `reference-only`, `132` inline SVG identities remain
  source-unavailable and `3` loaded-image uses remain missing.
- Display payload: all `227` uses have a screenshot-crop hash and are marked
  `original=false` / `reference-only=true`; `181` unique crop hashes and `83`
  source-rectangle mappings were recorded.
- Missing behavior: three uses remain `partial-not-pass`.
- Replacement: `42` assets are eligible only through retained source bytes;
  `161` identities remain non-replaceable. No crop is promoted to original.
- Use identity: three shared assets expand to 4, 21 and 2 separate uses; all
  `227` use IDs are unique.
- Known limitations: Dushu returned HTTP 403 for 24 unique image URLs; two
  Shoelace badge sources timed out. Inline SVG markup and effects remain open.
- Claim impact: source identity, display-crop separation, missing-state
  retention and replacement-mode contracts are `complete-current-scope`.
  Real Figma replacement/readback and arbitrary asset coverage remain
  `not-evaluated`.
- Mandatory regression:
  `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q`
  -> `588 passed in 33.66s`.
- Static checks: Ruff check and format check pass; `node --check
  figma_bridge\code.js` -> exit 0.

#### D-007 Strategy Fusion Policy

Current evidence (2026-10-25):

- Report: `docs/v2_mentor/DOM_STRATEGY_FUSION_2026-10-25.md`.
- Report JSON:
  `output/_dom_strategy_fusion_2026-10-25/summary.json`.
- Frozen replay: `227/227` D-006 uses accounted for exactly once.
- Verified source identity selected for `46` uses; `46` uses remain
  reference-only, `132` source-unavailable and `3` missing at the identity
  layer.
- Screenshot crop selected for all `227` display uses. Generated fallback uses
  `0`; missing display uses `0`.
- Fusion status: `46` resolved-source-and-capture and `181`
  partial-unresolved-identity.
- Generated candidates require generator/model, input reference, prompt,
  prompt version, review status, payload hash and retained bytes. Generated
  output remains non-original and non-replaceable and cannot outrank a captured
  screenshot.
- Claim impact: ordered fusion and generated provenance gates are
  `complete-current-scope`; the generated branch is controlled-fixture evidence
  only because the frozen corpus requested no generated candidate. Real Figma
  replacement/readback remains D-008.
- Mandatory regression:
  `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q`
  -> `606 passed in 34.31s`.
- Static checks: Ruff check and format check pass; `node --check
  figma_bridge\code.js` -> exit 0.

Default source preference:

1. verified DOM source fact or captured original asset;
2. recoverable browser/network asset whose identity can be verified;
3. screenshot crop marked `reference-only`;
4. generated approximation marked `generated-approximation`.

Rules:

- Generated output never satisfies the original-asset requirement.
- The fallback reason, generator/model, input reference, prompt/version and
  review status must be retained where applicable.
- A generated or approximated asset may support visual partial delivery.
- It cannot be represented as a replaceable original asset without explicit
  user acceptance and a new claim.
- Filling unknown text from context is forbidden unless marked
  `user-supplied` or otherwise separately verified.

#### D-008 Deliverable

Current evidence (2026-10-25):

- Report: `docs/v2_mentor/DOM_FIGMA_ACCEPTANCE_2026-10-25.md`.
- Final sample: `DQ-R02` Dushu.
- Final Figma frame: `76:4335`, origin `[22000, 0]`, `1440×2544`, 516
  readback nodes.
- Real export: `714936` bytes, SHA-256
  `05974f4ce4b6696883c5ce8c84f45d8a3402ac57b3eaf2ef8c1d959aa97d0e55`.
- Critical text: `3/3` present.
- Native text edit/restore: pass.
- Image fill replace/restore: pass.
- Layout readback: 102 Auto Layout nodes; parent propagation not evaluated.
- Quality result: `pass-current-scope`; visual, structure, edit, asset, text
  and export pass.
- Visual: mean `1.7279`, ink mean `9.3781`, over-30 `2.4862%`, bad-pixel
  ratio `2.4862%`. Within-30 pixel similarity is `97.5138%`.
- Figma linebreak and projected baseline pass `91/91`. Final glyph identity is
  evidence `not-evaluated` and product-scope `not-required`.
- Asset source recovery verifies 44 uses from 24 browser-context responses.
  The 10 remaining iconfont uses display generated similar icons with complete
  provenance and remain non-original.
- Real-run defects fixed by TDD: missing image payloads now create transparent
  placeholders; frozen full-page screenshots now define canvas height instead
  of the 900 px viewport; single-line text now uses the browser-measured line
  box without applying a duplicate CSS line-height offset.
- Mandatory regression:
  `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q`
  -> `648 passed in 39.01s`.
- Static checks: Ruff check and format check pass; `node --check
  figma_bridge\code.js` -> exit 0.

#### D-009 Deliverable

Current evidence (2026-10-25):

- Review: `docs/v2_mentor/DOM_QUALITY_EXIT_REVIEW_2026-10-25.md`.
- Decision: `pass-current-scope`.
- Corpus, text, layout, asset, fusion and real-Figma execution tasks have
  current-scope evidence.
- The representative real-site Figma sample passes visual, structure, edit,
  asset, text and export dimensions.
- Final glyph identity is non-required; generated icon provenance is explicit.
- Stage 1 is complete for the frozen DQ-R02 current scope.
- Stage 2 image-to-Figma is admitted but not started under G-007.

### 5.2 Stage 2: Image To Figma

| ID | Task | Status | Depends on | Required output |
|---|---|---|---|---|
| I-001 | Freeze the single-upload-screenshot MVP contract | complete-current-scope | Stage 1 exit | Input, supported actions, exclusions and report schema |
| I-002 | Define the shared image pipeline | complete-current-scope | I-001 | One contract covering state, grouping, text, assets, flow and Figma |
| I-003 | Make Grounding the default strategy | complete-current-scope | I-002 | Grounding-only baseline with deterministic provenance |
| I-004 | Restrict CV fallback to VLM unavailability | partial-current-scope | I-002, I-003 | Full product path passes the owned sample; fresh holdout is `0/3`, so fallback quality is not generalized |
| I-005 | Benchmark an optional Grounding/CV hybrid | rejected-current-scope | I-003, I-004 | Same-corpus comparison and explicit `reject-hybrid` decision |
| I-006 | Implement image reference-state and grouping lineage | complete-current-scope | I-002 | `faithful` state, grouping candidates and ambiguity reporting |
| I-007 | Implement text and OCR promotion boundaries | complete-current-scope | I-006 | Critical text gate, candidate-only OCR and manual review |
| I-008 | Implement image asset and replacement contract | complete-current-scope | I-006 | Independent/reference/derived/missing states |
| I-009 | Implement flow candidates and fixed-coordinate fallback | complete-current-scope | I-006 | Candidate-only flow and deterministic fallback |
| I-010 | Connect image output to Figma write/readback/export | complete-current-scope | I-007..I-009 | Real owned-sample existence proof |
| I-011 | Run the image MVP acceptance review | pass-current-scope | I-010 | Hard-gate result and honest partial report |

#### I-001 First Image MVP Scope

Input:

- one user-uploaded image;
- no claim of original DPR, viewport or font unless supplied;
- source-pixel coordinates and explicit uncertainty.

Required:

- critical text correctness;
- basic editability where claimed;
- replaceable assets where claimed;
- Figma write/readback/export existence proof;
- visible partial limitations.

Allowed as partial:

- visual score;
- structure score;
- asset coverage;
- editability;
- candidate-only flow.

Forbidden:

- presenting screenshot crops as original assets;
- promoting OCR text without the required evidence or review;
- claiming original font identity without evidence;
- claiming general adaptive behavior from a static screenshot;
- hiding unsupported regions or failed dimensions.

#### I-004 CV Fallback Rule

CV must not be selected for every Grounding exception. The implementation must
distinguish:

- Grounding model/service unavailable;
- missing VLM configuration;
- Grounding returned an invalid or empty result;
- ordinary downstream failure unrelated to VLM availability.

Only the first two are default fallback triggers unless a new mentor decision
changes the rule.

#### I-005 Hybrid Decision Gate

The hybrid experiment is accepted only if the same frozen corpus shows:

- no regression in critical text;
- improved structure or asset editing without reducing visual quality;
- preserved provenance and ambiguity reporting;
- bounded latency and cost;
- no hidden route switch that changes the claimed deliverable.

If those conditions are not met, keep Grounding as default and CV as fallback.

The 2026-10-26 frozen benchmark ran Grounding-only, CV fallback and the
conservative hybrid in one Figma document. The hybrid had no independent
structure or editability improvement and therefore I-005 is
`rejected-current-scope`. Evidence is
`docs/v2_mentor/IMAGE_CV_HYBRID_BENCHMARK_2026-10-26.md`.

#### I-011 Current-Scope Evidence

- Accepted sample: `IMG-MVP-01`, `1200x800`.
- Final Figma frame: `77:4851`, origin `[24000, 0]`.
- Critical text: `14/14`.
- Native text edit/restore: pass.
- Reference-only image display replace/restore: pass.
- Real export within-30: `96.533125%`.
- Frozen product threshold: `90%`.
- Readback nodes: `24`; native text `16`; image fills `1`; Auto Layout `0`.
- IR: `21` nodes, `16` text candidates, `1` image candidate.
- Asset identity remains unavailable; display crop is `original=false` /
  `reference_only=true`.
- Fixed-coordinate flow remains `candidate`; adaptive flow is not claimed.

### 5.3 Stage 3: Axure

| ID | Task | Status | Depends on | Required output |
|---|---|---|---|---|
| A-001 | Define shared Figma/Axure IR boundary | complete-current-scope | Stage 2 exit | Input/output responsibilities and unsupported features |
| A-002 | Implement `DOM -> Axure` current-scope path | complete-current-scope | A-001 | Deterministic artifacts and tests |
| A-003 | Implement `image -> Axure` current-scope path | complete-current-scope | A-001, I-002 | Deterministic image route artifact and tests |
| A-004 | Add independent Axure acceptance | complete-current-scope | A-002, A-003 | Independent DOM and image reports |
| A-005 | Validate frozen Axure holdout | partial-post-holdout-tuning | A-002..A-004 | Initial failures, TDD fixes and post-tuning rerun |
| A-006 | Validate a new untouched Axure holdout | fail-unseen-holdout | A-005 | Two samples pass; textflow emits an extra Rect |
| A-007 | Triage the AX6-DOM-TEXTFLOW extra Rect | complete-current-scope | A-006 | Root cause, narrow comparator fix, identical-artifact evidence and claim boundary |
| A-008 | Run a fresh untouched Axure holdout | fail-unseen-holdout | A-007 | Mobile pass; iframe rendered-content failure; asset-contract conflict |
| A-009 | Repair iframe placement and rendered-content/asset verification | complete-current-scope | A-008 | Refreshed input, rendered-region gate and corrected asset contract |
| A-010 | Run a new untouched Axure holdout | pass-unseen-holdout | A-009 | Three-sample frozen generalization pass |
| A-011 | Review Axure current-scope exit and non-claims | pass-current-scope | A-010 | Controlled route closure, retained non-claims and next-priority decision |

#### A-002 Deliverable

Current evidence (2026-10-25):

- Report: `AXURE_DOM_ACCEPTANCE_2026-10-25.md`.
- Evidence root: `output/_axure_dom_acceptance_2026-10-25_r2/`.
- Real page: `A002 DQ-R02 DOM Axure`, package
  `8f1cd483-2b3b-47f2-afd1-4d4b937b6e3e`, canvas `1440 x 2544`.
- Deterministic `.rp`: `647034` bytes, SHA-256
  `4a18721adb6d6a709b2050b9f14f0a3624f7b9c75ffa845a7bbf65296a011944`;
  a second generation is byte-identical.
- Object graph: 1 page, 469 top-level widgets; Button 119, Image 54,
  Rect 204, Text 91, TextField 1; 441 primary and 28 auxiliary border
  widgets; zero comparison/content mismatches.
- Assets: 44 reference-only screenshot display crops and 10 generated
  approximations. `display_original=true` remains 0.
- Axure 8.0.0.3400 opened and published the same `.rp` twice; each run
  produced 183 files and identical page HTML. Only Axure's `generationDate`
  in `data.js` changes between publish runs.
- Independent acceptance: `3/3` critical text, `30/30` unique published
  image hashes, `1/1` page package mapping, `469` labels, exact
  `1440 x 2544` size.
- Axure visual: `99.37718378756114%` within-30 against the original DOM
  screenshot, `0.6228162124388539%` over-30, policy minimum `90%`.
- Focused A-002 tests: `15 passed`.
- `tests/v2`: `698 passed in 40.47s`.
- Ruff check/format pass for A-002 touched files; the pre-existing whole-repo
  baseline reports 133 findings outside this task.
- `node --check figma_bridge/code.js`, `git diff --check` and the Axure
  conformance probe pass.
- Claim impact: A-002 closes for DQ-R02. A-004 was completed after A-003
  added the independent image acceptance slice. No Figma evidence is
  transferred.

#### A-003 And A-004 Deliverable

Current evidence (2026-10-25):

- Report: `AXURE_IMAGE_ACCEPTANCE_2026-10-25.md`.
- Evidence root: `output/_axure_image_acceptance_2026-10-25_r2/`.
- Image input: `IMG-MVP-01`, screenshot SHA-256
  `7f39efc5e69b9ba16367aa19a1ccb1e3ea1681824419c93f0f9a3478e5153df4`.
- Shared IR: `design-ir/2.0`, document
  `63470f34aab242fad73f4e7456de8af2e0983ff1d363c62cd5400eb9042502ff`.
- Real page: `A003 IMG-MVP-01 Image Axure`, package
  `12bce8ac-d8f0-46c8-9da0-213fbf460010`, canvas `1200 x 800`.
- Deterministic `.rp`: `58296` bytes, SHA-256
  `c48b3b076de70229af81cf26602e2b305b8375f9377fd7f1b6d82fb9f849a6b1`;
  second generation is byte-identical.
- Object graph: 22 widgets; Text 14, Button 2, Image 1, Rect 5; zero
  comparison mismatches and zero auxiliary widgets.
- Critical text: `14/14`.
- Published image: `1/1`; reference-only crop, `original=false`,
  `display_original=false`, `generated=false`.
- Runtime replacement is unsupported and reported as
  `creation-only-image-box`.
- Axure open/reopen publish: two `RESULT=OK` runs with 154 files each and
  identical page HTML; only `generationDate` changes.
- Axure visual: `96.57197916666667%` within-30 against the original
  screenshot; policy minimum `90%`.
- TDD closed a real layout defect: flat-image single-line title and two-digit
  statistics no longer reflow in Axure.
- A-004 closes for both controlled samples because DOM and image routes each
  have independently parsed page/widget/asset evidence and published HTML
  acceptance.
- Final `tests/v2`: `703 passed in 40.81s`; touched-file Ruff/format, Node,
  diff-check and Axure conformance pass. The pre-existing whole-repo Ruff
  baseline remains 133 findings outside this task.

#### A-005 Deliverable

Current evidence (2026-10-25):

- Report: `AXURE_HOLDOUT_ACCEPTANCE_2026-10-25.md`.
- Evidence root: `output/_axure_holdout_2026-10-25/`.
- Frozen samples: DQ-R01 React, DQ-R03 Shoelace and AX-IMG-H01.
- Initial failures: DQ-R01 IR/asset binding, DQ-R03 visual
  `89.69745030511753%`, AX-IMG-H01 critical text `1/3` and assets `1/3`.
- TDD fixes: payload-only IR assets, non-rendered background provenance,
  payload-container ImageBox mapping, measured-single-line reflow,
  wide-caption button expansion, OCR band merge and duplicate suppression.
- Final post-tuning results:
  DQ-R01 `93.7288067818298%`, DQ-R03 `90.2025368557791%`,
  AX-IMG-H01 `97.24269841269842%`; all have exact size, deterministic
  `.rp`, `100%` critical/asset matches and identical page HTML after reopen.
- Decision: `partial-post-holdout-tuning`. A-006 must use a new untouched
  holdout before any broad generalization claim.
- Verification: A-005 focused `54 passed in 2.79s`; `tests/v2`
  `717 passed in 41.63s`; touched-file Ruff/format, Node, diff-check and
  three-file Axure conformance pass. Whole-repo Ruff baseline remains 133
  pre-existing findings.

#### A-006 Deliverable

Current evidence (2026-10-25):

- Report: `AXURE_HOLDOUT_V2_ACCEPTANCE_2026-10-25.md`.
- Evidence root: `output/_axure_holdout_v2_2026-10-25/`.
- Frozen samples: AX6-DOM-TEXTFLOW, AX6-DOM-FONTFALLBACK and
  AX6-IMG-OVERLAY.
- `AX6-DOM-FONTFALLBACK`: object graph pass, `3/3` critical, visual
  `96.15206349206349%`.
- `AX6-IMG-OVERLAY`: object graph pass, `3/3` critical, `1/1` asset,
  visual `97.60984126984127%`.
- `AX6-DOM-TEXTFLOW`: published acceptance passes with `3/3` critical and
  `99.34079365079364%` visual, but the `.rp` has 7 widgets versus 6 projected
  primary widgets. The extra empty Rect is `360x96` at `(24,178)`, so the
  object-mapping gate fails.
- Result: `fail-unseen-holdout`; no thresholds, samples or code were changed
  in response. A-007 must triage the extra Rect.
- Verification: `tests/v2` `720 passed in 40.09s`; manifest tests `3 passed`;
  touched-file Ruff/format, Node, diff-check and three-file Axure conformance
  pass.

#### A-007 Deliverable

Current evidence (2026-10-25):

- Report: `AXURE_EXTRA_RECT_ATTRIBUTION_2026-10-25.md`.
- Plan:
  `docs/superpowers/plans/2026-10-25-axure-extra-rect-attribution.md`.
- Evidence root:
  `output/_axure_holdout_v2_2026-10-25/a007_retriage/AX6-DOM-TEXTFLOW/`.
- Root cause: styled Text with non-neutral fill/border emits an unlabeled
  Rect background; Axure emits the editable Text one pixel inside that box.
- Fix: comparator accepts one unlabeled Rect only when it matches an already
  matched Text's source outer geometry within `0.5 px`, and records the
  source-label mapping in `auxiliary_widgets`.
- A-007 `.rp` SHA-256 is
  `acc356d7a5d30dcdc2b5d47294d1007e34e9bffc23d3c26ee6cbf15cc946913c`,
  identical to A-006. Deterministic repeat, unchanged published acceptance
  and one-file Axure conformance pass.
- A-006 remains `fail-unseen-holdout`; A-007 changes comparison evidence only
  and does not retroactively pass the old holdout.
- Verification: A-007 evidence tests `10 passed in 1.58s`; `tests/v2`
  `722 passed in 41.23s`; touched-file Ruff/format, Node, diff-check and
  Axure conformance pass.

#### A-008 Deliverable

Current evidence (2026-10-25):

- Report: `AXURE_FRESH_HOLDOUT_A008_2026-10-25.md`.
- Plan: `docs/superpowers/plans/2026-10-25-axure-fresh-holdout-a008.md`.
- Manifest: `tests/fixtures/axure_holdout_v3/holdout_v3.json`.
- Evidence root: `output/_axure_holdout_v3_2026-10-25/`.
- Frozen samples: `AX8-DOM-IFRAME`, `AX8-DOM-PARTIAL-ASSET` and
  `AX8-DOM-MOBILE320`.
- All three artifacts are deterministic and Axure-conformant; all six publish
  runs returned `RESULT=OK`; page HTML is identical across reopen.
- Mobile passes all automated gates and reference review.
- Iframe passes automated object/text/pixel thresholds but fails reference
  review: the source DesignSpec puts accessible iframe content over the title
  and the rendered iframe interior is blank.
- Partial-asset matches the reference at `100%` and all two image hashes, but
  the frozen manifest expected one renderable asset while the truth declares
  two. This is an evaluation-contract conflict, not changed after observation.
- Result: `fail-unseen-holdout`; no product code changed after the initial
  result. A-009 must repair placement and rendered critical-region verification
  through TDD, clarify asset-count semantics and run a new untouched holdout.
- Verification: manifest tests `4 passed`; `tests/v2`
  `726 passed in 40.70s`; touched-file Ruff/format, Node, JSON parsing,
  Axure conformance and diff-check pass.

#### A-009 Deliverable

Current evidence (2026-10-25):

- Report: `AXURE_A009_RENDERED_REGION_REPAIR_2026-10-25.md`.
- Plan:
  `docs/superpowers/plans/2026-10-25-axure-a009-rendered-region-repair.md`.
- Evidence root: `output/_axure_a009_2026-10-25/`.
- Root cause: A-008 used a stale iframe DesignSpec. Current capture already
  places accessible child text at `(18,133)`.
- Fix: regenerate iframe input, add critical rendered-region ink acceptance,
  expose repeated CLI regions, and correct the partial-asset contract to two
  displayed assets with one missing-original provenance row.
- Repaired iframe and partial-asset artifacts pass deterministic generation,
  conformance, publish/reopen and independent acceptance.
- The new gate fails the old A-008 iframe render with
  `critical-region-missing`; the repaired render reports region ink
  `7.01923076923077%` in both reference and render.
- A-008 remains failed. A-009 is not a new untouched holdout; A-010 is required
  for a generalization claim.
- Verification: Axure acceptance tests `11 passed`; `tests/v2`
  `728 passed in 41.66s`; Ruff/format, Node, JSON, conformance and diff-check
  pass.

#### A-010 Deliverable

Current evidence (2026-10-25):

- Report: `AXURE_FRESH_HOLDOUT_A010_2026-10-25.md`.
- Plan: `docs/superpowers/plans/2026-10-25-axure-fresh-holdout-a010.md`.
- Manifest: `tests/fixtures/axure_holdout_v4/holdout_v4.json`.
- Evidence root: `output/_axure_holdout_v4_2026-10-25/`.
- Frozen samples: `AX10-DOM-ASSETS`, `AX10-DOM-TRANSPARENT-CROP` and
  `AX10-DOM-NESTED-IFRAME`.
- All three pass object mapping, critical text, assets, visible regions,
  visual acceptance and manual reference review.
- All three artifacts are deterministic and Axure-conformant; six publish
  runs returned `RESULT=OK`; page HTML is identical across reopen.
- Result: `pass-unseen-holdout` for the frozen three samples only.
- A-011 must perform the current-scope exit review and retain all unsupported
  capability and production non-claims.
- Verification: manifest tests `4 passed`; `tests/v2`
  `732 passed in 40.43s`; Ruff/format, Node, JSON, conformance and diff-check
  pass.

#### A-011 Deliverable

Current evidence (2026-10-25):

- Report: `AXURE_CURRENT_SCOPE_EXIT_REVIEW_2026-10-25.md`.
- Plan:
  `docs/superpowers/plans/2026-10-25-axure-current-scope-exit-review.md`.
- Summary:
  `output/_axure_current_scope_exit_2026-10-25/summary.json`.
- Decision: `pass-current-scope` for controlled `DOM -> Axure` and named
  image-sample routes.
- Controlling evidence: A-010 fresh holdout, A-003 image acceptance,
  A-006 overlay sample, independent acceptance and deterministic reopen
  publish.
- Historical A-006/A-008 failures remain; A-007/A-009 remediations remain
  separately documented.
- No product code changed in this review.
- Next work requires a user priority choice between Axure capability expansion
  and production admission.

### 5.4 Deferred Stability

| ID | Task | Status | Resume trigger |
|---|---|---|---|
| S-001 | Maintain existing regression suites | active | Every phase |
| S-002 | Expand deterministic matrix only for newly discovered product risks | deferred | DOM or image milestone exposes a concrete gap |
| S-003 | Real permission/rate-limit/collaborator/takeover matrix | blocked-environment | Required accounts and fixed pilot window exist |
| S-004 | Task 10 Q8-Q10 rulings and one-hour rerun | frozen | User explicitly reopens this work |
| S-005 | Production storage scaffolding | frozen | User explicitly starts production-storage phase |
| S-006 | Cloud 1h/24h/7d soak and admission review | deferred | Product routes stable and cloud host scheduled |

Do not interpret `deferred` as cancelled. It means no work starts until the
resume trigger is recorded in the decision log.

## 6. Phase Exit Gates

### Global Hard Gates

These apply to every Figma product milestone:

1. **No masquerade**
   OCR candidates, generated images, screenshot crops, fixed-coordinate
   structure and candidate flow must keep their true status.
2. **Existence proof**
   At least one controlled sample must complete real Figma write, readback and
   export for the claimed route.
3. **Critical text**
   Critical text must be correct. A large visual area cannot compensate for a
   wrong price, title, identifier or other critical string.
4. **Evidence linkage**
   Record code revision, plugin build, environment, test command, evidence path
   and content hash.

### DOM Quality Gate

Required:

- frozen real-site corpus;
- independent visual/structure/edit/asset reporting;
- no composite score;
- critical object/field checks at 100% of the frozen required set;
- known font and Auto Layout limits disclosed;
- real Figma proof for the representative sample.

### Image MVP Gate

Required:

- single user-uploaded screenshot;
- one end-to-end run;
- correct critical text;
- basic editability and asset replacement for the claimed subset;
- candidate flow clearly separated from verified flow;
- the frozen current-scope product metric is at least `90%` within-30 pixels;
- partial dimensions retained in the original denominator;
- no generated/reference-only output presented as original.

### Axure Gate

Required:

- shared IR consumes verified decisions;
- Axure-specific limitations separately tested;
- no claim inherited from Figma.

## 7. Mandatory Verification

Every implementation phase must keep these commands green, adjusting the exact
suite names only when a narrower focused suite is run first:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
node --check figma_bridge\code.js
```

For bridge changes, also run:

```powershell
Get-ChildItem 'tests/bridge/*.js' | Sort-Object Name | ForEach-Object {
  node $_.FullName
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

For image or DOM quality changes, add the phase-specific frozen-corpus probe.
A unit test pass alone is not a quality acceptance result.

## 8. Review Focus

These are the highest-risk misunderstandings to check in every review:

1. **Route-level confusion:** Does the change still describe Grounding/CV as
   peer product routes?
2. **Fallback leakage:** Does CV run after ordinary Grounding errors instead of
   VLM unavailability?
3. **False original asset:** Is a screenshot crop or generated image being
   counted as the original/replaceable asset?
4. **Flow overclaim:** Is `layoutMode` or visual appearance being called
   verified true flow without perturbation?
5. **Critical-text masking:** Can a high visual score hide a wrong critical
   string?
6. **Evidence overreach:** Is canonical or deterministic evidence being
   generalized to all real sites or production?
7. **Priority drift:** Is deferred fault-matrix or storage work displacing a
   DOM or image quality milestone?
8. **OCR scope creep:** Is OCR text being promoted to editability, role or
   original asset?
9. **Axure duplication:** Is an independent image stack being created instead
   of reusing the shared IR?
10. **Post-hoc threshold change:** Was a frozen policy changed after seeing the
    result?

## 9. Decision Log

Append new decisions; do not rewrite history.

| Date | ID | Decision | Evidence / source | Impact | Status |
|---|---|---|---|---|---|
| 2026-10-25 | G-001..G-014 | Adopt mentor route model, DOM-first priority, image MVP scope, hard/partial gate and deferred stability work | Mentor reply supplied by user | Freezes the global route and priority order | active |
| 2026-10-25 | D-006 | Separate verified source identity, screenshot display payload, missing state, use identity and replacement eligibility; close only the frozen controlled scope | `docs/v2_mentor/DOM_ASSET_QUALITY_2026-10-25.md`; `output/_dom_asset_quality_2026-10-25/summary.json` | D-006 becomes `complete-current-scope`; D-007 becomes active; real Figma replacement stays with D-008 | complete-current-scope |
| 2026-10-25 | D-007 | Adopt deterministic source/display fusion with explicit generated provenance and no generated original claim | `docs/v2_mentor/DOM_STRATEGY_FUSION_2026-10-25.md`; `output/_dom_strategy_fusion_2026-10-25/summary.json` | D-007 becomes `complete-current-scope`; D-008 becomes active | complete-current-scope |
| 2026-10-25 | D-008 | Real DQ-R02 Figma write/readback/export/probes completed, but the frozen quality gate failed | `docs/v2_mentor/DOM_FIGMA_ACCEPTANCE_2026-10-25.md`; `output/_dom_figma_acceptance_2026-10-25/acceptance.json` | D-008 is `complete-current-scope` as execution evidence only; no quality pass or image-phase admission | complete-current-scope |
| 2026-10-25 | D-008-R1 | Attribute over-30 pixels, reject per-node fitting and repair single-line measured-line-box placement | `output/_dom_figma_over30_attribution/summary.json`; `tests/v2/test_figma_adapter_edits.py`; `output/_dom_figma_acceptance_over30fix_2026-10-25_r1/acceptance.json` | DQ-R02 visual gate moves to pass at `2.4616%`; thresholds are unchanged | complete-current-scope |
| 2026-10-25 | D-010 | Preserve browser baseline evidence and add independent Figma linebreak/projected-baseline evaluation, including input placeholders | `docs/v2_mentor/DOM_TEXT_METRICS_FIGMA_2026-10-25.md`; `output/_dom_figma_text_metrics_placeholder_2026-10-25_r2/acceptance.json` | Linebreak and projected baseline pass `91/91`; glyph identity remains separate | complete-current-scope |
| 2026-10-25 | D-011 | Recover blocked remote assets through the page browser context and retain verified source bytes | `docs/v2_mentor/DOM_ASSET_RECOVERY_2026-10-25.md`; `output/_dom_figma_asset_recovery_2026-10-25_r1/acceptance.json` | 24/24 URLs and 44/54 uses verified; 10 iconfont crops remain explicit | complete-current-scope |
| 2026-10-25 | D-012 | Apply the 90% product policy, generated icon fallback and non-required glyph identity scope | `docs/v2_mentor/DOM_GENERATED_ICONS_2026-10-25.md`; `output/_dom_figma_generated_icons_2026-10-25_r1/acceptance.json` | D-009 becomes `pass-current-scope`; image phase is admitted | complete-current-scope |
| 2026-10-25 | D-009 | DOM quality exit review returns `partial-not-pass` | `docs/v2_mentor/DOM_QUALITY_EXIT_REVIEW_2026-10-25.md` | Stage 1 remains active; image phase is not admitted | complete-current-scope |
| 2026-10-25 | D-009-R2 | Re-review after generated icon policy and non-required glyph scope | `docs/v2_mentor/DOM_QUALITY_EXIT_REVIEW_2026-10-25.md`; `output/_dom_figma_generated_icons_2026-10-25_r1/acceptance.json` | D-009 becomes `pass-current-scope`; Stage 1 completes and Stage 2 is admitted | complete-current-scope |
| 2026-10-25 | I-MVP-01 | Admit the deterministic image presentation layer, candidate-safe OCR supplement and reference-only image contract; accept one owned screenshot after real Figma evidence | `docs/v2_mentor/IMAGE_FIGMA_MVP_ACCEPTANCE_2026-10-25.md`; `output/_image_figma_mvp_2026-10-25_r4/acceptance.json` | I-001..I-004 and I-006..I-011 close for current scope; hybrid I-005 remains under benchmark | pass-current-scope |
| 2026-10-26 | I-004/I-005 | Run the frozen Grounding-only, CV-fallback and conservative hybrid comparison in one real Figma document | `docs/v2_mentor/IMAGE_CV_HYBRID_BENCHMARK_2026-10-26.md`; `output/_image_cv_hybrid_benchmark_2026-10-26/comparison.json` | Grounding-only and hybrid pass product gates; hybrid has no independent improvement and adds cost; CV fallback is route-safe but quality-blocked; decision is `reject-hybrid` | rejected-current-scope |
| 2026-10-26 | I-004-R2 | Exercise the full CV fallback product path, close four merge/rendering defects by TDD, and run a frozen three-sample holdout | `docs/v2_mentor/IMAGE_CV_FALLBACK_PRODUCT_ACCEPTANCE_2026-10-26.md`; `output/_image_fallback_holdout_2026-10-26/summary.json` | Owned frame `2:62` passes; holdout passes `0/3`; CV routing is verified, but fallback quality is not generalized and remains availability-only | partial-current-scope |
| 2026-10-25 | A-001 | Adopt `design-ir/2.0` as an output-neutral projection over existing DesignSpec and define target-owned capability/degradation reporting | `docs/v2_mentor/AXURE_SHARED_IR_BOUNDARY_2026-10-25.md`; `output/_axure_shared_ir_2026-10-25_r1/summary.json` | A-001 closes; A-002 is next; Figma evidence cannot transfer to Axure | complete-current-scope |
| 2026-10-25 | A-002 | Generate deterministic DOM -> Axure RP 8 output, verify the actual page/widget/asset graph, republish after reopen and accept the published Axure page independently | `docs/v2_mentor/AXURE_DOM_ACCEPTANCE_2026-10-25.md`; `output/_axure_dom_acceptance_2026-10-25_r2/` | A-002 closes for DQ-R02; A-003 image -> Axure is next; full A-004 remains blocked on A-003; unsupported Axure capability claims remain false | pass-current-scope |
| 2026-10-25 | A-003/A-004 | Reuse the image MVP DesignSpec and shared IR to generate a deterministic image -> Axure artifact, reopen/republish it and accept the Axure HTML independently | `docs/v2_mentor/AXURE_IMAGE_ACCEPTANCE_2026-10-25.md`; `output/_axure_image_acceptance_2026-10-25_r2/` | A-003 closes for IMG-MVP-01; A-004 closes for the controlled DOM and image samples; runtime replacement and general Axure readiness remain non-claims | pass-current-scope |
| 2026-10-25 | A-005 | Run a frozen three-sample Axure holdout, apply TDD fixes to observed defects and re-run under unchanged thresholds | `docs/v2_mentor/AXURE_HOLDOUT_ACCEPTANCE_2026-10-25.md`; `output/_axure_holdout_2026-10-25/summary.json` | Initial holdout failed on DQ-R03 and AX-IMG-H01; all post-tuning reruns pass, but the same holdout was used for remediation, so the result remains partial and A-006 needs a new untouched holdout | partial-post-holdout-tuning |
| 2026-10-25 | A-006 | Run a new untouched three-sample Axure holdout and record the result before remediation | `docs/v2_mentor/AXURE_HOLDOUT_V2_ACCEPTANCE_2026-10-25.md`; `output/_axure_holdout_v2_2026-10-25/summary.json` | Font fallback and overlay pass; textflow published acceptance passes but an unexpected extra Rect fails the object-mapping gate; A-007 must triage it | fail-unseen-holdout |
| 2026-10-25 | A-007 | Attribute the extra AX6-DOM-TEXTFLOW Rect to styled-text background rendering and add one-to-one auxiliary matching in the read-only comparator | `docs/v2_mentor/AXURE_EXTRA_RECT_ATTRIBUTION_2026-10-25.md`; `output/_axure_holdout_v2_2026-10-25/a007_retriage/AX6-DOM-TEXTFLOW/artifact_report.json` | A-007 closes; `.rp` remains byte-identical; A-006 remains failed; A-008 must run a new untouched holdout before a generalization claim | complete-current-scope |
| 2026-10-25 | A-008 | Run a fresh three-sample Axure holdout and record generation, publish, reload, automated acceptance and reference review before remediation | `docs/v2_mentor/AXURE_FRESH_HOLDOUT_A008_2026-10-25.md`; `output/_axure_holdout_v3_2026-10-25/summary.json` | Mobile passes; iframe reveals an upstream child-coordinate/visible-content failure hidden by label-only acceptance; partial asset produces an evaluation-contract conflict; A-009 is required before another generalization claim | fail-unseen-holdout |
| 2026-10-25 | A-009 | Refresh the stale iframe input, add rendered critical-region ink verification and correct the displayed asset-count contract | `docs/v2_mentor/AXURE_A009_RENDERED_REGION_REPAIR_2026-10-25.md`; `output/_axure_a009_2026-10-25/summary.json` | Repaired iframe and partial-asset scopes close; old A-008 render now fails the new gate; A-008 stays failed and A-010 needs a new untouched holdout | complete-current-scope |
| 2026-10-25 | A-010 | Run a fresh three-sample Axure holdout with visible-region acceptance and record all results before remediation | `docs/v2_mentor/AXURE_FRESH_HOLDOUT_A010_2026-10-25.md`; `output/_axure_holdout_v4_2026-10-25/summary.json` | Assets, transparent-crop and nested-iframe all pass under frozen thresholds; holdout-scoped generalization is supported, while arbitrary/product claims remain false | pass-unseen-holdout |
| 2026-10-25 | A-011 | Review all Axure route evidence and close the named controlled current scope while retaining capability and production non-claims | `docs/v2_mentor/AXURE_CURRENT_SCOPE_EXIT_REVIEW_2026-10-25.md`; `output/_axure_current_scope_exit_2026-10-25/summary.json` | Controls close as `pass-current-scope`; next work requires user choice between capability expansion and production admission | pass-current-scope |

Template:

```text
Date:
Decision ID:
Decision:
Source/evidence:
Affected tasks:
Scope or claim changed:
Cost if wrong:
Review/expiry:
```

## 10. Handoff Update Protocol

After completing any task:

1. Update its status and actual evidence path in the task register.
2. Record the exact verification command and result.
3. Record failures instead of deleting them.
4. State whether any claim changed.
5. Add a decision-log entry if scope, priority or thresholds changed.
6. Point to the next task and any blocker.
7. Do not commit unless the user explicitly asks.

Do not mark a whole phase complete merely because its code exists. The phase
exit gate must be evidenced.

## 11. Immediate Next Queue

1. Stage 1 remains `pass-current-scope` for DQ-R02 and frame `76:4335`.
2. Stage 2 is `pass-current-scope` for `IMG-MVP-01` and frame `77:4851`.
3. A-001 is `complete-current-scope`; shared IR probe root is
   `output/_axure_shared_ir_2026-10-25_r1/`.
4. A-002 is `complete-current-scope` for DQ-R02:
   `output/_axure_dom_acceptance_2026-10-25_r2/`.
5. A-003 is `complete-current-scope` for IMG-MVP-01:
   `output/_axure_image_acceptance_2026-10-25_r2/`.
6. A-004 is `complete-current-scope` for the controlled DOM and image Axure
   samples.
7. A-005 is `partial-post-holdout-tuning`; its evidence is
   `output/_axure_holdout_2026-10-25/`.
8. A-006 is `fail-unseen-holdout`; evidence is
   `output/_axure_holdout_v2_2026-10-25/`.
9. A-007 is `complete-current-scope`; evidence is
   `output/_axure_holdout_v2_2026-10-25/a007_retriage/AX6-DOM-TEXTFLOW/`.
10. A-008 is `fail-unseen-holdout`; evidence is
   `output/_axure_holdout_v3_2026-10-25/`.
11. A-009 is `complete-current-scope`; evidence is
   `output/_axure_a009_2026-10-25/`.
12. A-010 is `pass-unseen-holdout`; evidence is
   `output/_axure_holdout_v4_2026-10-25/`.
13. A-011 is `pass-current-scope`; evidence is
   `output/_axure_current_scope_exit_2026-10-25/`.
14. No Axure implementation starts automatically; the next priority must be
   chosen between capability expansion and production admission.
15. The Axure ledger is `docs/v2_mentor/AXURE_ROUTE_LEDGER_2026-10-25.md`.
16. I-005 conservative hybrid is rejected for the current frozen sample;
   Grounding remains default and CV remains an availability fallback only.
17. S-002..S-006 and Task 10 Q8-Q10 remain deferred or frozen by their
   existing triggers.

## 12. Non-Claims

This plan does not claim:

- arbitrary DOM page fidelity;
- arbitrary screenshot-to-design reconstruction;
- Grounding or CV product readiness;
- Axure readiness;
- project-wide `verified=true`;
- production admission;
- real multi-collaborator reliability;
- that deterministic fault-matrix coverage substitutes for missing real
  environment evidence.
