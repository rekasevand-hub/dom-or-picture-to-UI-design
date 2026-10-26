# Image CV Fallback And Hybrid Benchmark Design

**Date:** 2026-10-26  
**Task:** I-004 / I-005 final current-scope verification  
**Product route:** `image -> Figma`  
**Decision under test:** keep Grounding-only default with CV fallback, or adopt a
Grounding + CV hybrid.

## Intent

Resolve the deferred hybrid question with one honest, reproducible comparison
on a frozen image corpus. The result must show whether CV fallback is a safe
availability fallback and whether a hybrid improves editable structure or
asset usefulness without regressing critical text, visual quality, provenance,
or bounded runtime.

This is a current-scope image-to-Figma experiment. It does not establish
arbitrary-screenshot quality, production readiness, or an Axure result.

## Known Baseline

The existing `IMG-MVP-01` Grounding run wrote a real Figma frame, read it back,
exported it, and passed 14/14 critical texts, native-text edit/restore,
reference-only image replacement, and the frozen 90% within-30 visual gate.
That run used the standard image post-processing chain; OCR and image-region
recovery were both `no-change` / `not-needed`.

I-004 has routing and failure-classification tests. It does not yet have a
real Figma CV-fallback run. I-005 has never run a same-corpus three-way
benchmark.

## Strategy Definitions

The benchmark fixes these meanings before any result is observed:

- **Grounding-only:** Grounding candidate structure and text, deterministic
  pixel-sampled presentation, no OCR supplement and no image-region recovery.
- **CV fallback:** automatic image routing reaches CV only because the
  Grounding VLM is unavailable; CV OCR/OmniParser candidates use the same
  deterministic presentation and acceptance gates.
- **Grounding + CV hybrid:** Grounding remains primary. CV contributes only
  missing text and non-duplicate visual-box candidates. Every added candidate
  keeps CV provenance; ambiguity is reported rather than promoted.

An explicit `--route cv` invocation is diagnostic, not proof of automatic CV
fallback. The fallback evidence must show `requested=auto`, a Grounding
unavailability attempt, and `selected=cv`.

## Routing Safety

- Missing Grounding configuration and Grounding service unavailability may
  select CV in image `auto`.
- Grounding JSON/schema errors, empty results, SoM failures, deterministic
  presentation failures, and renderer failures must not silently select CV.
- Explicit Grounding requests remain single-route and fail close.
- The final provenance retains requested route, ordered attempts, fallback
  reasons, selected strategy, and all CV/OCR/hybrid additions.

## Frozen Corpus

The corpus is `tests/fixtures/image_strategy_benchmark/manifest.json`.

Initial scope is one owned screenshot, `IMG-MVP-01`:

- image: `tests/fixtures/image_mvp/simple_dashboard_v1.png`;
- image SHA-256:
  `7f39efc5e69b9ba16367aa19a1ccb1e3ea1681824419c93f0f9a3478e5153df4`;
- size: `1200x800`;
- truth: `tests/fixtures/image_mvp/simple_dashboard_v1.truth.json`;
- source state: faithful single visible frame;
- original viewport/DPR/font/hidden-region identity remains unknown.

One sample is sufficient to test the local implementation and reject a hybrid
that regresses this sample. It is not sufficient to claim general adoption
benefit; the decision report must retain that limitation.

## Frozen Environment

- Python `3.12.0` from `C:\Users\lzq\.conda\envs\omni\python.exe`;
- OpenCV `4.10.0`;
- EasyOCR `1.7.2`, local GPU;
- Grounding model from `VISION_MODEL`, default `qwen3-vl-plus`;
- source viewport `1200x800`, device scale factor `1`;
- locale `en-US`, timezone `Asia/Shanghai`;
- one Figma document, one bridge configuration, distinct frames per strategy;
- export scale `1`, readback depth `8`;
- same source image and truth across all strategies.

The manifest records observed versions and SHA-256 values. A changed sample,
truth, model, or Figma document requires a new benchmark run.

## Independent Metrics

No composite score is allowed. Each strategy reports:

1. critical text matched/required;
2. native text node count and text edit/restore probe;
3. image/asset node count and display replace/restore probe;
4. structure counts, candidate ambiguity, and reference-only/original claims;
5. rendered size and within-30 visual similarity;
6. mean channel delta, ink mean delta, and over-30 ratio;
7. wall-clock duration, Grounding VLM request count, and local CV execution;
8. ordered route and provenance events;
9. export/readback hashes and real Figma frame identity.

## Decision Gates

Hybrid adoption requires all of the following on the same frozen run:

- critical text does not regress and remains 14/14;
- native text and reference-only asset replacement remain passing;
- at least one independent structure, text-coverage, or editable-asset metric
  improves over Grounding-only;
- visual within-30 does not decrease and remains at least the frozen 90%;
- no original asset, original font, adaptive flow, or hidden-state claim is
  introduced;
- all hybrid contributions retain source and ambiguity provenance;
- no hidden route switch occurs;
- wall time stays within 180 seconds per image and no more than 2x the
  Grounding-only wall time;
- external Grounding request count stays at one or less per image, with no
  unbounded retries;
- exact cost telemetry is either available or bounded by request count.

Failure of any gate produces `reject-hybrid`. The default remains Grounding,
with CV eligible only as an availability fallback. A successful sample does
not silently promote hybrid.

## Approaches Considered

### A. Keep Grounding-only default and CV availability fallback

Lowest routing and cost risk. Preserves the existing current-scope pass.

### B. Merge Grounding primary with conservative CV supplements

Can add missing OCR text or visual boxes, but adds duplicate/conflict risk and
requires a full Figma comparison. It is experimental until every gate passes.

### C. Run full CV on every image

Not a hybrid and not justified as default: it adds local model cost while
losing Grounding's semantic candidates.

The benchmark compares A, the CV fallback variant, and B. C is only the
fallback implementation and is not proposed as the default.

## Non-Claims

- no arbitrary screenshot or real-site acceptance;
- no multi-sample generalization from `n=1`;
- no original asset/font/DPR/viewport/hidden-state recovery;
- no adaptive layout claim;
- no Axure evidence substitution;
- no production admission;
- no commit or push as part of this task.
