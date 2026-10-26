# DOM Quality Gap Register

**Status:** D-002 and D-006 through D-012 have current-scope evidence;
DOM quality exit is `pass-current-scope`  
**Date:** 2026-10-25  
**Product route:** `DOM -> Figma`  
**Spec:** [Global Optimization Master Plan](GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md)  
**Product vocabulary:** [README.md](../../README.md)  
**Next task:** image phase admitted but not started

## Purpose

This register deduplicates the remaining DOM quality gaps raised by R1, R2,
R3-D, P1, P2 and P3. It records what exists, what the evidence proves and what
still needs implementation or a wider corpus. It does not turn bounded fixture
passes into real-site quality claims.

One gap may cite several source rounds. Repeated observations are merged under
one stable ID so later work can close the quality issue once, rather than
closing each mentor answer independently.

## Status Vocabulary

| Status | Meaning |
|---|---|
| `not-implemented` | The required production behavior or contract is absent. |
| `implemented-not-verified` | Code or a probe exists, but the required scope is not accepted. |
| `verified-bounded-fixture` | Verified only on the named controlled fixture or probe. |
| `blocked-environment` | Progress requires an unavailable browser, machine, account or service. |
| `out-of-current-scope` | Known work is intentionally postponed by the current priority decision. |

These statuses do not replace the master plan's `complete-current-scope` or
`verified` vocabulary. They describe the gap state only.

## Source Coverage

| Source | Primary DOM demands | Mapped gaps |
|---|---|---|
| R1 | Four-dimensional acceptance, traceable geometry, true-flow boundaries, source assets, hierarchy and failure reporting | DOM-GAP-001, 003, 004, 007, 008, 010, 011, 014, 015 |
| R2 | Authored flow perturbation, single-child layout decisions, asset/use-instance model, stable identity, reference state and Chinese text metrics | DOM-GAP-001, 002, 004, 006, 009, 010, 011, 012, 013 |
| R3-D | Source order, Grid/wrap equivalence, complex SVG/effects, duplicate disambiguation, full-page/sticky state and baseline calibration | DOM-GAP-002, 006, 007, 009, 012, 013, 014 |
| P1 | Canonical Chromium/Figma output fidelity, independent dimensions, native edit, asset payload and Auto Layout propagation | DOM-GAP-001, 003, 004, 005, 007, 008, 010, 015, 016, 017 |
| P2 | Italic/variable fonts, ambiguous platform fallback, mobile matrix and bounded real-site observation | DOM-GAP-002, 005, 006, 015, 016, 017 |
| P3 | Nested Grid, track/span behavior, row auto-flow, long text/image combinations and persistent readback | DOM-GAP-007, 008, 010, 015, 017, 020 |

## Evidence Index

| Evidence | Repository path |
|---|---|
| Product vocabulary and implementation boundary | `README.md` |
| R1 mentor answers | `docs/v2_mentor/ROUND_01_ANSWERS_FORMATTED.md` |
| R2 mentor answers | `docs/v2_mentor/ROUND_02_ANSWERS_FORMATTED.md` |
| R2 authored flow perturbation | `docs/v2_mentor/R2_EXP_01_DOM_FLOW_PERTURBATION.md` |
| R3-D mentor answers | `docs/v2_mentor/ROUND_03_DOM_ANSWERS_FORMATTED.md` |
| P1 canonical output | `docs/v2_mentor/P1_CANONICAL_OUTPUT_FIDELITY.md` |
| P1 Figma acceptance | `docs/v2_mentor/P1_FIGMA_ACCEPTANCE.md` |
| P2 extended closure | `docs/v2_mentor/P2_EXTENDED_CLOSURE.md` |
| P3 complex Grid holdout | `docs/v2_mentor/P3_GRID_COMPLEX_HOLDOUT.md` |
| Frozen real-site DOM corpus | `docs/v2_mentor/DOM_QUALITY_CORPUS_2026-10-25.md` |
| Corpus manifest | `tests/fixtures/dom_quality/real_site_corpus_v1.json` |
| Auto Layout quality report | `docs/v2_mentor/DOM_LAYOUT_QUALITY_2026-10-25.md` |
| Asset quality report | `docs/v2_mentor/DOM_ASSET_QUALITY_2026-10-25.md` |
| Strategy fusion report | `docs/v2_mentor/DOM_STRATEGY_FUSION_2026-10-25.md` |
| Real Figma acceptance report | `docs/v2_mentor/DOM_FIGMA_ACCEPTANCE_2026-10-25.md` |
| Figma text metrics report | `docs/v2_mentor/DOM_TEXT_METRICS_FIGMA_2026-10-25.md` |
| Browser-context asset recovery report | `docs/v2_mentor/DOM_ASSET_RECOVERY_2026-10-25.md` |
| Generated icon and product-scope report | `docs/v2_mentor/DOM_GENERATED_ICONS_2026-10-25.md` |
| DOM quality exit review | `docs/v2_mentor/DOM_QUALITY_EXIT_REVIEW_2026-10-25.md` |

## Gap Index

| ID | Theme | Status | Owning task |
|---|---|---|---|
| DOM-GAP-001 | Frozen real-site canonical corpus and thresholds | `implemented-not-verified` | D-004..D-008 |
| DOM-GAP-002 | Reference state and dynamic page stability | `implemented-not-verified` | D-003, D-008 |
| DOM-GAP-003 | Critical text content, measured linebreak and text box | `implemented-not-verified` | D-008 |
| DOM-GAP-004 | Baseline and per-run vertical metrics | `implemented-not-verified` | D-008 |
| DOM-GAP-005 | Platform font resolution and ambiguous fallback reporting | `verified-bounded-fixture` | D-004 |
| DOM-GAP-006 | Per-glyph mixed-run identity and arbitrary variable axes | `not-implemented` | D-004 |
| DOM-GAP-007 | General Auto Layout inference for Grid, wrap, component and nesting | `implemented-not-verified` | D-005 |
| DOM-GAP-008 | Flow perturbation and parent propagation on real-site DOM | `implemented-not-verified` | D-005, D-008 |
| DOM-GAP-009 | Source order, Grid clustering and slot semantics | `implemented-not-verified` | D-005 |
| DOM-GAP-010 | Asset source identity, crop mapping and local payload identity | `verified-bounded-fixture` | D-006 |
| DOM-GAP-011 | Asset use instances, missing assets and replacement semantics | `verified-bounded-fixture` | D-006, D-007 |
| DOM-GAP-012 | Stable identity and duplicate ambiguity | `implemented-not-verified` | D-005, D-006 |
| DOM-GAP-013 | Full-page stitching, sticky/fixed state and seams | `implemented-not-verified` | D-003, D-005 |
| DOM-GAP-014 | Pseudo-elements, complex SVG and effect chains | `not-implemented` | D-006, D-007 |
| DOM-GAP-015 | Real Figma write/readback/export acceptance | `verified-bounded-fixture` | D-008 |
| DOM-GAP-016 | Continuous real-site observation cadence | `not-implemented` | D-008 |
| DOM-GAP-017 | Cross-browser, cross-document and cross-machine coverage | `blocked-environment` | D-003, D-008 |
| DOM-GAP-018 | Explicit strategy fusion and generated-approximation provenance | `verified-bounded-fixture` | D-007 |
| DOM-GAP-019 | Image Grounding/CV routing and fallback provenance | `out-of-current-scope` | I-003, I-004 |
| DOM-GAP-020 | Production concurrency, storage and long-soak admission | `out-of-current-scope` | S-003, S-005, S-006 |

## Gap Details

### DOM-GAP-001

**Status:** `implemented-not-verified`

**Evidence:** R1 requires independent visual/structure/edit/asset acceptance
and reproducible comparison. R2 records authored fixtures only. P1 and P2 use
fixed canonical fixtures and bounded real-site observations. D-003 now freezes
React, Dushu and Shoelace under one Chromium/viewport/font/threshold profile
and verifies the saved states twice. See
[ROUND_01_ANSWERS_FORMATTED.md](ROUND_01_ANSWERS_FORMATTED.md),
[ROUND_02_ANSWERS_FORMATTED.md](ROUND_02_ANSWERS_FORMATTED.md),
[P1_CANONICAL_OUTPUT_FIDELITY.md](P1_CANONICAL_OUTPUT_FIDELITY.md), and
[P2_EXTENDED_CLOSURE.md](P2_EXTENDED_CLOSURE.md). The frozen corpus details
are in [DOM_QUALITY_CORPUS_2026-10-25.md](DOM_QUALITY_CORPUS_2026-10-25.md).

**Missing evidence / implementation:** The frozen corpus has not yet produced
text, layout, asset, edit and real Figma acceptance results. Quality thresholds
exist but remain unmeasured.

**Current claim boundary:** State reproducibility is proven only for the two
recorded corpus runs. It does not prove rendering quality or continuous
availability.

**Owning task:** D-004..D-008.

**D-003 resolution:** Three required sites, one explicit W3Schools exclusion,
frozen environment, immutable threshold hash and initial fingerprints are
recorded in `tests/fixtures/dom_quality/real_site_corpus_v1.json`.

### DOM-GAP-002

**Status:** `implemented-not-verified`

**Evidence:** Captured-state and gate code exists in
`src/app/services/structure/capture_state.py` and `capture_outcome.py`; tests
cover stable, alternating and incomplete states. P2 records React and Dushu
observations but also records W3Schools as `state-unstable` and Shoelace as
different. R2 and R3-D require multi-signal M0 -> S -> M1 verification.

**Missing evidence / implementation:** The pipeline does not yet prove stable
real-site states across fonts, lazy images, carousels, sticky headers,
login/anti-bot challenges and repeated captures.

**Current claim boundary:** A deterministic state test or one ready capture
does not prove continuous real-site stability.

**Owning task:** D-003 defines the state contract; D-008 verifies it.

**D-003 corpus input:** Freeze saved state, transition witnesses and rejection
conditions for every selected site.

### DOM-GAP-003

**Status:** `implemented-not-verified`

**Evidence:** P1 records browser-measured `textLines`, container paint
ownership and a `holdout-text` pass. Tests in
`tests/v2/test_p1_dom_text_geometry.py` verify line propagation and measured
wrap reuse. P1 Figma acceptance checks critical text content independently.
D-004 measures the frozen React/Dushu/Shoelace corpus: critical text `3/3`,
content `914/914`, text box `914/914`, and measured linebreak rows `885/885`.
See `docs/v2_mentor/DOM_TEXT_FONT_QUALITY_2026-10-25.md`.

**Missing evidence / implementation:** 29 mixed-content nodes have multi-line
browser measurements but no retained per-line strings. Figma text acceptance
and broader punctuation/ellipsis/zoom coverage remain open.

**Current claim boundary:** Content and horizontal text-box checks pass on the
frozen corpus. Measured linebreak rows pass, but total linebreak coverage is
`96.83%`, not a project-wide text fidelity claim.

**Owning task:** D-008 verifies Figma output on the frozen corpus.

**D-004 evidence:** Capture and report paths are recorded in
`DOM_TEXT_FONT_QUALITY_2026-10-25.md`.

### DOM-GAP-004

**Status:** `implemented-not-verified`

**Evidence:** D-004 adds `textBaseline` from browser Canvas
`fontBoundingBoxAscent/Descent`, with actual-box fallback. All 914 frozen
corpus text nodes have a derived baseline. Figma acceptance keeps baseline
independent from content, linebreak, box and glyph.

**Missing evidence / implementation:** The browser-derived baseline is not a
source-glyph baseline and has not been compared with real Figma readback.
Per-run vertical alignment remains incomplete for mixed font runs.

**Current claim boundary:** The report records `914/914` derived baselines,
not baseline correctness. It must not be called measured glyph truth.

**Owning task:** D-008.

**D-004 evidence:** `textBaseline.method=canvas-font-metrics` and the frozen
`1.0 px` tolerance are recorded in the D-004 report.

### DOM-GAP-005

**Status:** `verified-bounded-fixture`

**Evidence:** Chromium platform-font provenance is implemented in
`src/app/services/structure/font_provenance.py`; P1 and P2 record resolved
faces, explicit missing-font results and ambiguous multi-font fail-closed
behavior. D-004 probes one representative node per unique font style on the
frozen corpus: 33 direct face results, 805 representative inheritances, 21
ambiguous mixed-face nodes and 55 missing React results.

**Missing evidence / implementation:** Results remain limited to the recorded
Windows/Chromium environment and do not prove final glyph outlines or Figma
face identity.

**Current claim boundary:** A resolved family/style/size is not final glyph
identity, and ambiguous fallback must not be replaced by a guessed face.

**Owning task:** D-004.

**D-003 corpus input:** Required font files, hashes, fallback stack and
expected ambiguity policy.

### DOM-GAP-006

**Status:** `not-implemented`

**Evidence:** R2 and R3-D call for per-run font evidence and baseline
separation. P2 proves named variable-font instances but records arbitrary
variable axes and ambiguous per-glyph face splits as unverified or blocked.
D-004 reports browser faces and glyph counts but keeps final outline identity
`not-evaluated`.

**Missing evidence / implementation:** No production contract maps each glyph
run to its source face, exact variable-axis value and verification threshold.

**Current claim boundary:** Named-instance support must not be described as
arbitrary variable-axis or per-glyph identity support.

**Owning task:** D-004.

**D-003 corpus input:** Mixed-font runs, fallback runs and variable-axis cases
that must remain fail-closed when unprovable.

### DOM-GAP-007

**Status:** `implemented-not-verified`

**Evidence:** `layout_infer.py`, bridge Grid/wrap commands and fail-closed
rollback tests exist. P1 verifies one vertical fixed-width parent propagation.
P3 verifies a complex authored Grid, nested Grid, fixed/Flex/Hug tracks,
spans, row auto-flow, long text and images in real Figma. See
[P3_GRID_COMPLEX_HOLDOUT.md](P3_GRID_COMPLEX_HOLDOUT.md). D-005 classifies the
frozen corpus into L1 `308/448`, L2 `225/448` and bounded L3 local contract
`115/448`.

**Missing evidence / implementation:** General inference across real-site
Grid permutations, wrap, components, nested Auto Layout and content growth is
not accepted. Real Figma runtime and parent propagation remain unproven. P3
explicitly excludes every track/span permutation, cross-version readback,
collaboration and undo/redo.

**Current claim boundary:** L1/L2/L3-local evidence is current-scope only.
Grid/wrap now fall back to fixed coordinates instead of a guessed linear
stack; this is not complete adaptive Auto Layout.

**Owning task:** D-008.

**D-005 evidence:** Counts, fallback reasons and non-claims are recorded in
`DOM_LAYOUT_QUALITY_2026-10-25.md`.

### DOM-GAP-008

**Status:** `implemented-not-verified`

**Evidence:** R1 defines geometry plus perturbation as the flow gate. R2
records authored DOM perturbations with 42/42 checks in
[R2_EXP_01_DOM_FLOW_PERTURBATION.md](R2_EXP_01_DOM_FLOW_PERTURBATION.md).
P1 verifies one real Figma vertical parent propagation probe. D-005 adds 115
bounded local output-contract L3 simulations on the frozen corpus.

**Missing evidence / implementation:** No frozen real-site DOM has passed
content growth, deletion, reorder, width change and rollback checks with real
Figma readback.

**Current claim boundary:** Local sibling reflow is simulated; source-browser
and parent propagation remain not evaluated.

**Owning task:** D-008 verifies real Figma behavior.

**D-003 corpus input:** Exact containers, mutations, failure criteria and
fallback-to-fixed-coordinate policy.

### DOM-GAP-009

**Status:** `implemented-not-verified`

**Evidence:** DOM capture preserves document order and capture fields such as
`order`; the evidence IR exposes `OrderMapping`. R3 records
`visual_order=derived`, `figma_child_order=observed` and `dom_order=unknown`
for the online Grid experiment. R2 requires slot, row and column semantics to
remain distinguishable.

**Missing evidence / implementation:** Source-order proof, Grid clustering
confidence and slot identity are not established for the future real-site
corpus.

**Current claim boundary:** Figma child order or visual clustering cannot be
presented as source DOM order.

**Owning task:** D-005.

**D-003 corpus input:** Expected source order, visual order, slot mappings and
known reverse/order overrides.

### DOM-GAP-010

**Status:** `verified-bounded-fixture`

**Evidence:** P1 records natural size, MIME, SHA-256, object-fit,
`sourceCrop`, local display bytes and real Figma payload/replacement probes.
The canonical asset sample and P2 DPR2 sample pass within their recorded
scopes. See [P1_FIGMA_ACCEPTANCE.md](P1_FIGMA_ACCEPTANCE.md).

**Missing evidence / implementation:** Original SVG source bytes are not
proven to be the bytes held by Figma. Complex shared images, source-version
changes and real-site crop identity remain open.

**Current claim boundary:** Local PNG/fill payload identity is not original
asset identity, and a visible crop is not automatically independently
replaceable.

**Owning task:** D-006.

**D-003 corpus input:** Original URLs, source hashes, crop/display boxes,
`object-fit/position`, repeated use instances and missing-asset probes.

**D-006 evidence:** The asset ledger now keeps source identity, actual display
payload, screenshot crop, missing state and replacement eligibility in
separate fields. On the frozen corpus, 42 unique remote sources were retained
and revalidated from bytes, 26 remained reference-only, all 227 display uses
have screenshot-crop hashes, and no crop was promoted to original. See
[DOM_ASSET_QUALITY_2026-10-25.md](DOM_ASSET_QUALITY_2026-10-25.md).

### DOM-GAP-011

**Status:** `verified-bounded-fixture`

**Evidence:** R1 and R2 require separate source asset, use instance and
capture state. R2 also requires explicit
`faithful-as-captured`/`stable-loaded` behavior and separate visible,
replaceable and traceable results. P1 preserves declared missing assets as
`partial`, but the full production model is absent.

**Missing evidence / implementation:** No complete asset/use-instance model,
replacement-mode contract, missing-state policy or generated-approximation
status reaches the product route.

**Current claim boundary:** A missing asset report or screenshot crop cannot
be counted as a complete original asset.

**Owning task:** D-006 implements collection; D-007 implements fallback.

**D-003 corpus input:** Assets with multiple uses, transparent overlays,
backgrounds, gradients, absent bytes and permitted substitutions.

**D-006 evidence:** Asset IDs and use IDs are separate. The corpus contains 203
identities and 227 unique uses, including three shared identities with 4, 21
and 2 uses. Three unloaded image uses remain `partial-not-pass`. Replacement is
allowed only through retained source bytes; 161 identities remain
non-replaceable. Real Figma replacement remains not evaluated.

### DOM-GAP-012

**Status:** `implemented-not-verified`

**Evidence:** R2 recommends `verified-id / scoped-slot / weak-match /
ambiguous / unknown`; R3-D requires `ambiguous`/`not-seen` rather than forced
matching. The controlled identity experiment exists, but no production DOM
route exposes the required identity status.

**Missing evidence / implementation:** Stable semantic keys and explicit
ambiguity handling are absent for duplicate cards, missing IDs, virtual lists,
cross-section moves and node reuse.

**Current claim boundary:** Position or Figma node ID cannot be used as a
global stable identity; an unseen item is not proof of deletion.

**Owning task:** D-005 and D-006 for asset-use identity; D-008 for cross-state
acceptance.

**D-003 corpus input:** Stable-ID, missing-ID, duplicate-swap and node-reuse
cases with expected ambiguity.

**D-006 evidence:** Asset-use identity now has deterministic
`sample:node:source-kind` keys, content-derived source IDs and explicit shared
uses. All 227 corpus use IDs are unique. This closes asset-use duplication only;
semantic DOM node identity across swaps, moves and unseen states remains open.

### DOM-GAP-013

**Status:** `implemented-not-verified`

**Evidence:** State gates and full-page capture exist. R2 and R3-D require
local M0/S/M1 comparison for sticky/fixed elements and full-page seams. P2
records real-site state instability but does not establish seam or sticky
equivalence.

**Missing evidence / implementation:** No accepted report jointly records
viewport/document boxes, stitching seams and local state witnesses for the
future corpus.

**Current claim boundary:** A stitched full-page image is not one simultaneous
browser state, and unchanged viewport position can hide a document-coordinate
shift.

**Owning task:** D-003 defines the state contract; D-005 handles layout.

**D-003 corpus input:** Full-page height, scroll positions, sticky/fixed
observations, seam probes and state-equivalence failures.

### DOM-GAP-014

**Status:** `not-implemented`

**Evidence:** Diagnostics report visible pseudo-elements, gradients and
unsupported structure, but `diagnostics.py` states that pseudo-elements only
participate in icon detection. R2 and R3-D require explicit support matrices.
Controlled effect experiments are not production coverage.

**Missing evidence / implementation:** Pseudo-layers, complex SVG,
`filter` chains, mask/effect ordering and explicit raster fallback are not
closed in the DOM product route.

**Current claim boundary:** SVG import success does not prove effect
semantics; a name, raster crop or single-effect probe is insufficient.

**Owning task:** D-006 preserves assets; D-007 records fallback provenance.

**D-003 corpus input:** Representative pseudo-element, inline SVG, mask,
filter-chain and unsupported-effect cases.

**D-006 contribution:** Inline SVG nodes retain screenshot-crop display
evidence but no source bytes, so they remain `unavailable`. This prevents a
crop from masquerading as SVG source identity but does not close source markup,
masks, filters or effect ordering.

### DOM-GAP-015

**Status:** `verified-bounded-fixture`

**Evidence:** P1 records real Figma write, readback, PNG export and independent
structure/visual/edit/asset acceptance. Five canonical holdouts pass in the
current scope, including native text edit and image replacement probes. See
[P1_CANONICAL_OUTPUT_FIDELITY.md](P1_CANONICAL_OUTPUT_FIDELITY.md) and
[P1_FIGMA_ACCEPTANCE.md](P1_FIGMA_ACCEPTANCE.md).

**Missing evidence / implementation:** No representative real-site corpus
sample has completed the agreed DOM quality gate with real Figma evidence.

**Current claim boundary:** Five canonical fixtures do not prove arbitrary DOM
page fidelity or project-wide `verified=true`.

**Owning task:** D-008.

**D-003 corpus input:** Choose the representative acceptance sample and its
owned Figma destination before measurement.

### DOM-GAP-016

**Status:** `not-implemented`

**Evidence:** P2 makes two real-site observations and explicitly limits their
scope. D-003 now provides a frozen corpus and replayable `capture/verify`
commands, but no recurring observation schedule or history exists.

**Missing evidence / implementation:** There is no recurring rerun schedule,
versioned time series or policy for handling site revisions over time.

**Current claim boundary:** Two current-scope runs cannot be described as
continuous stability.

**Owning task:** D-008.

**D-003 corpus input:** The frozen manifest and capture dates are ready; future
observation cadence is not.

### DOM-GAP-017

**Status:** `blocked-environment`

**Evidence:** P2 records Firefox launch as `spawn UNKNOWN`. P1 limits evidence
to one Figma document and one Windows/client environment. P3 excludes
cross-version readback and collaboration.

**Missing evidence / implementation:** Firefox execution, additional Figma
documents/versions/machines and collaborative edit/undo behavior are not
available or not proven.

**Current claim boundary:** Chromium/Windows/current-Figma evidence cannot be
silently applied to other engines or hosts.

**Owning task:** D-003 records exclusions; D-008 may run only when the required
environment exists.

**D-003 corpus input:** Declare the canonical browser/host and explicitly list
cross-browser/cross-machine exclusions.

### DOM-GAP-018

**Status:** `verified-bounded-fixture`

**Evidence:** R1, R2 and R3-D require unknown values and fallbacks to remain
explicit. P1 preserves partial assets but does not implement the full ordered
fusion policy. The master plan's D-007 fixes source precedence and generated
approximation rules.

**Missing evidence / implementation:** No product-level fusion ledger orders
verified DOM/original bytes, recoverable network bytes, reference-only crops
and generated approximations with reason, model, prompt/version and review
status.

**Current claim boundary:** Generated or approximated output never satisfies
the original-asset requirement without a separately verified claim.

**Owning task:** D-007.

**D-003 corpus input:** Asset cases requiring each precedence level and at
least one visible partial fallback.

**D-007 evidence:** The production fusion policy now orders verified source,
recovered network source, screenshot crop, generated approximation and missing
display. Frozen replay accounts for all `227/227` D-006 uses: `46` verified
source uses, `46` reference-only identities, `132` source-unavailable inline
SVG uses, `3` missing source identities, `227` screenshot display uses, no
missing display and no generated candidates. Generated candidates are covered
by controlled tests only and remain non-original/non-replaceable. See
[DOM_STRATEGY_FUSION_2026-10-25.md](DOM_STRATEGY_FUSION_2026-10-25.md).

### DOM-GAP-019

**Status:** `out-of-current-scope`

**Evidence:** The master plan makes image -> Figma the next phase after DOM
closure. Grounding is the planned default and CV is fallback only when the VLM
is unavailable or unconfigured; current implementation names are not accepted
as the product taxonomy.

**Missing evidence / implementation:** Default Grounding selection,
availability-vs-ordinary-error classification, CV fallback and hybrid
benchmarking belong to I-003..I-005.

**Current claim boundary:** Provider prototypes do not prove image product
readiness or authorize a CV-first route.

**Owning task:** I-003 and I-004 after the Stage 1 exit gate.

**D-003 corpus input:** None; defer to the Stage 2 image contract.

### DOM-GAP-020

**Status:** `out-of-current-scope`

**Evidence:** P5 provides deterministic current-scope fault coverage, but the
master plan explicitly defers production storage, real collaborator/takeover
tests and 1h/24h/7d soak. P3 excludes collaborative edits and undo/redo.

**Missing evidence / implementation:** Real permission/rate-limit/takeover
evidence, production storage scaffolding, long soak and production admission
are not complete.

**Current claim boundary:** Deterministic fault tests do not substitute for
real-environment evidence or production admission.

**Owning task:** S-003, S-005 and S-006 only after their resume triggers.

**D-003 corpus input:** None; keep outside the quality corpus.

## Deduplicated Findings

The source rounds converge on six root causes:

1. Evidence exists, but no frozen real-site corpus binds state, environment,
   critical objects and thresholds.
2. Text content and linebreak improved materially, while baseline and
   per-glyph identity remain separate unresolved dimensions.
3. Auto Layout primitives exist, while general inference and perturbation on
   real DOM remain unproven.
4. Asset source identity, screenshot display payload, use instance, missing
   state and replacement mode are now separate for the frozen corpus; Dushu
   source bytes and inline SVG source markup remain partial.
5. Ordered asset fusion and generated provenance gates are now production
   contract behavior; the frozen corpus contains no generated candidate, so
   that branch is controlled-fixture evidence only.
6. Bounded canonical Figma evidence is real, but real-site, cross-browser,
   cross-document and production claims remain outside it.

## D-003 Completion

D-003 froze:

- React, Dushu and Shoelace URLs and saved states;
- Chromium version and executable SHA-256;
- `1440x900`, DPR 1, `zh-CN`, `Asia/Shanghai` and headless mode;
- four font files with SHA-256 values;
- allowed network behavior and the real-session prohibition;
- critical text, required object markers and W3Schools exclusion;
- independent content, structure, text, layout, asset, edit and visual
  thresholds;
- immutable threshold and corpus hashes;
- initial DOM, page-state, screenshot, text and structure fingerprints.

An independent replay passed all three required samples. Shoelace changed from
457 to 463 nodes and remained inside the frozen drift threshold; its baseline
was not rewritten. D-003 does not claim quality; measurement and Figma
acceptance remain D-004..D-008 work.

## D-006 Completion

D-006 completes the current controlled-scope asset contract:

- 42 unique remote sources have retained, byte-verified original identities;
- 26 remote references remain `reference-only`;
- 132 inline SVG uses remain source-unavailable and screenshot-crop-only;
- 3 missing image uses remain `partial-not-pass`;
- all 227 display uses have reference-only screenshot-crop hashes;
- 42 assets are replaceable by retained source bytes in contract only;
- real Figma replacement/readback remains D-008 work;
- no generated asset was used.

The Dushu host returned HTTP 403 for all 24 unique image URLs during the bounded
probe. Those pixels remain display crops, not originals. Two Shoelace badge
sources timed out and remain reference-only.

Report:
`docs/v2_mentor/DOM_ASSET_QUALITY_2026-10-25.md`.

Mandatory regression:

```text
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
588 passed in 33.66s

node --check figma_bridge\code.js
exit 0
```

## D-007 Completion

D-007 implements the controlled-scope fusion policy:

- source identity and display payload are decided separately;
- source precedence is verified DOM source, verified recovered network source,
  screenshot crop, complete generated approximation, then missing;
- generated candidates require generator/model, input reference, prompt,
  prompt version, review status, payload hash and retained bytes;
- generated output is never original or replaceable and cannot outrank a
  captured screenshot;
- every fusion decision carries candidate status, reasons and a deterministic
  fallback chain.

Frozen replay:

- `227/227` uses accounted for;
- `46` verified-source uses;
- `46` reference-only identity uses;
- `132` source-unavailable inline SVG uses;
- `3` missing-source identity uses;
- `227` screenshot display uses;
- `0` generated fallback uses;
- `0` missing display uses.

The generated branch is verified by controlled tests only because the corpus
contains no generated candidate. Real Figma runtime remains D-008 work.

Report:
`docs/v2_mentor/DOM_STRATEGY_FUSION_2026-10-25.md`.

Mandatory regression:

```text
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
606 passed in 34.31s

node --check figma_bridge\code.js
exit 0
```

## D-008 Completion

D-008 completed a real Figma run for frozen `DQ-R02`:

- final frame `76:4335`, full-page `1440×2544`, origin `[22000, 0]`;
- 516 readback nodes;
- real PNG export, `714936` bytes, SHA-256
  `05974f4ce4b6696883c5ce8c84f45d8a3402ac57b3eaf2ef8c1d959aa97d0e55`;
- critical text `3/3` present;
- native text edit/restore pass;
- image fill replace/restore pass;
- 102 Auto Layout nodes observed, parent propagation not evaluated.

The visual gate now passes:

- visual bad-pixel ratio `2.4862%` against `3%`: pass;
- mean `1.7279` against `3.0`: pass;
- ink mean `9.3781` against `100`: pass;
- over-30 `2.4862%` against `2.5%`: pass;
- within-30 similarity `97.5138%` against the approved 90% product bar: pass;
- structure, edit, content and text-box pass;
- linebreak and projected baseline pass `91/91`, including the measured input
  placeholder line and baseline;
- all 24 unique remote image URLs were recovered through the page browser
  context, upgrading 44 uses to verified-original and replaceable;
- 10 iconfont glyph uses display generated similar icons with complete
  provenance; generated assets remain non-original and non-replaceable;
- final glyph identity and baseline remain not evaluated.

The complete Figma acceptance is `pass-current-scope`; export is allowed.

Implementation fixes discovered by the real run:

- missing image payloads now create transparent placeholders instead of
  aborting `create_image`;
- frozen full-page screenshots now define canvas height rather than using the
  `900 px` viewport height;
- single-line text now uses the browser-measured line box without applying a
  duplicate CSS line-height offset. The change was introduced by a failing
  regression test and rechecked in a new real Figma frame;
- D-010 preserves browser baseline evidence and evaluates Figma linebreak and
  projected baseline without promoting either to glyph-outline identity;
- input placeholders now retain a measured content line box, one-line count
  and Canvas-font baseline;
- D-011 recovers blocked remote assets through the page browser context,
  validates dimensions and retained SHA-256, and preserves screenshot display
  semantics;
- D-012 generates similar icons for unresolved iconfont crops and applies the
  approved non-required glyph policy.

Report:
`docs/v2_mentor/DOM_FIGMA_ACCEPTANCE_2026-10-25.md`.

Mandatory regression:

```text
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2 -q
648 passed in 39.01s

node --check figma_bridge\code.js
exit 0
```

## D-009 Completion

D-009 reviewed all current-scope DOM evidence and returns:

```text
DOM quality exit: pass-current-scope
Stage 1: pass-current-scope
Image phase: admitted, not started
```

The corpus, text measurement, local layout, asset provenance, fusion and real
Figma execution are evidenced. The representative DQ-R02 frame now passes the
visual, structure, edit, asset, content, text-box, linebreak and
projected-baseline gates. The Stage 1 representative real-site condition is
met.

Required remediation:

- none blocking for the frozen DQ-R02 current scope;
- retain generated/original/non-required classifications in future runs.

Review:
`docs/v2_mentor/DOM_QUALITY_EXIT_REVIEW_2026-10-25.md`.

## Verification

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_dom_quality_gap_register.py tests/v2/test_route_taxonomy.py -q
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests/v2/test_dom_asset_quality.py tests/v2/test_p1_asset_metadata.py -q
rg -n "DOM-GAP-[0-9]{3}" docs/v2_mentor/DOM_QUALITY_GAP_REGISTER_2026-10-25.md
```

## Non-Claims

This register does not claim:

- arbitrary DOM page fidelity;
- all fonts, text runs or baselines are correct;
- general Auto Layout or complete Grid coverage;
- original asset identity for every captured image;
- continuous real-site stability;
- cross-browser, cross-document or cross-machine equivalence;
- Figma or Axure product readiness;
- project-wide `verified=true`;
- production admission.
