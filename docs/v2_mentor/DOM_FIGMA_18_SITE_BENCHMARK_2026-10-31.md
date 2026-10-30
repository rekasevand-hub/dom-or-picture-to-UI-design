# DOM to Figma 18-Site Benchmark - 2026-10-31

## Result

The six-category, 18-URL benchmark was executed against the Figma `Untitled`
file with the current DOM pipeline and semantic component-instance default.

| Stage | Result |
|---|---:|
| Designated pages | 18 |
| Capture and DesignSpec success | 15 |
| Figma render/readback success | 15 |
| Strict visual pass | 9 |
| Visual warning | 5 |
| Visual failure | 1 |
| Capture failure | 3 |
| Figma render failure | 0 |

All 15 successfully captured pages rendered in Figma. Every rendered page has
`height_drift_px=0`. The benchmark does not replace the three capture failures
or count their missing results as visual passes.

Across the 15 rendered pages:

- mean bad-pixel ratio: `9.95%`
- median bad-pixel ratio: `6.07%`
- maximum bad-pixel ratio: `68.16%`
- DesignSpec text nodes: `1,666`

The ecommerce mean is dominated by the JD failure. The median is the more useful
central metric for this run.

## Environment

- viewport: `1440x900`
- device scale factor: `1`
- browser engine: Chromium headless
- route: `dom`
- target Figma file: `Untitled`
- frame prefix: `B18-`
- Figma export scale: `1.0`
- semantic metadata: enabled
- semantic component instances: enabled

The 18 URLs and category definitions are frozen in:

`tests/fixtures/dom_figma_18_20261031/manifest.json`

## Category Summary

| Category | Rendered | Pass | Warn | Fail | Capture failure | Mean bad pixels | Mean image fill |
|---|---:|---:|---:|---:|---:|---:|---:|
| Documentation and developer | 3/3 | 2 | 1 | 0 | 0 | 6.14% | 92.7% |
| News and content | 2/3 | 1 | 1 | 0 | 1 | 6.99% | 90.7% |
| Community and forum | 1/3 | 1 | 0 | 0 | 2 | 6.85% | 100.0% |
| Ecommerce and products | 3/3 | 2 | 0 | 1 | 0 | 23.21% | 100.0% |
| Government and data | 3/3 | 2 | 1 | 0 | 0 | 5.18% | 99.2% |
| SaaS and product sites | 3/3 | 1 | 2 | 0 | 0 | 8.27% | 91.3% |

## Page Results

| ID | Category | Status | Bad pixels | Image fill | Blank area | Text nodes | Height drift |
|---|---|---|---:|---:|---:|---:|---:|
| DOC-01 | Documentation | warn | 6.45% | 83.7% | 89.2% | 229 | 0 |
| DOC-02 | Documentation | pass | 5.90% | 100.0% | 33.8% | 40 | 0 |
| DOC-03 | Documentation | pass | 6.07% | 94.4% | 70.7% | 72 | 0 |
| NEWS-01 | News | pass | 3.78% | 100.0% | 79.6% | 85 | 0 |
| NEWS-02 | News | capture fail | - | - | - | - | - |
| NEWS-03 | News | warn | 10.21% | 81.3% | 81.0% | 175 | 0 |
| COMM-01 | Community | pass | 6.85% | 100.0% | 73.5% | 163 | 0 |
| COMM-02 | Community | capture fail | - | - | - | - | - |
| COMM-03 | Community | capture fail | - | - | - | - | - |
| SHOP-01 | Ecommerce | pass | 0.47% | 100.0% | 35.4% | 32 | 0 |
| SHOP-02 | Ecommerce | fail | 68.16% | 100.0% | 2.3% | 12 | 0 |
| SHOP-03 | Ecommerce | pass | 1.01% | 100.0% | 50.8% | 109 | 0 |
| DATA-01 | Government/data | pass | 4.26% | 100.0% | 38.0% | 14 | 0 |
| DATA-02 | Government/data | pass | 4.36% | 97.5% | 52.5% | 122 | 0 |
| DATA-03 | Government/data | warn | 6.92% | 100.0% | 63.3% | 29 | 0 |
| SAAS-01 | SaaS/product | pass | 4.29% | 89.5% | 80.1% | 314 | 0 |
| SAAS-02 | SaaS/product | warn | 10.24% | 89.0% | 65.1% | 175 | 0 |
| SAAS-03 | SaaS/product | warn | 10.29% | 95.5% | 70.3% | 95 | 0 |

## Capture Failures

| ID | URL | Recorded cause |
|---|---|---|
| NEWS-02 | `https://news.sina.com.cn/` | Homepage login widgets triggered a `hard_login` page-state false positive despite meaningful content |
| COMM-02 | `https://news.ycombinator.com/` | `net::ERR_CONNECTION_TIMED_OUT` |
| COMM-03 | `https://www.v2ex.com/` | `net::ERR_CONNECTION_TIMED_OUT` |

These are P0 capture/state-classification failures. They are not DOM-to-Figma
fidelity failures because no DesignSpec/Figma frame was produced.

## Representative Failures

### SHOP-02 JD

- source screenshot is the JD login/benefit modal;
- page state was incorrectly treated as usable content;
- Figma output diverges into a red “page exception” block and loses the modal;
- bad-pixel ratio is `68.16%`.

This is the highest-priority correctable failure. The page-state/state-signal
gate should reject a visible login modal before the DOM route continues.

Evidence:

`output/_dom_figma_18_20261031/SHOP-02/figma_compare.png`

### DOC-01 React

- text hierarchy and native text are present;
- animated/code-preview surfaces are not fully materialized;
- several headings wrap differently and collide with following content;
- image fill rate is `83.7%`.

Evidence:

`output/_dom_figma_18_20261031/DOC-01/figma_compare.png`

### SAAS-03 Notion

- headline text overflows and overlaps;
- large video/animated media regions render as black blocks;
- footer text density and wrapping differ significantly;
- image fill rate is `95.5%`, but fill coverage does not prove media content
  correctness.

Evidence:

`output/_dom_figma_18_20261031/SAAS-03/figma_compare.png`

## Findings

1. Stable documentation and government/data pages are the strongest segment.
   Four of six strict passes have bad-pixel ratios between `3.78%` and `6.07%`.
2. Ecommerce home pages without login/challenge interstitials are strong:
   Mi and IKEA are `0.47%` and `1.01%`.
3. Login modals and challenge states are a P0 correctness risk. JD passes image
   fill and blank-area checks while rendering entirely wrong content.
4. Dynamic media remains a P1 gap. Video/canvas/animated code previews can be
   absent even when ordinary image fills are high.
5. Display headings still need browser-measured line breaks and overflow guards
   on marketing pages.
6. Network access failures affect the community category most severely in this
   run: only one of three community pages was captured.
7. Automatic semantic component instances did not introduce render failures.
   `Untitled` contains the generated `B18-*` page frames.

## Recommended Next Work

1. Reject visible login/QR/challenge modals and “page exception” states before
   DOM replay.
2. Add a video/canvas/animated-background representative-frame fallback and
   count it separately from ordinary image fills.
3. Use browser-measured display-heading line boxes for hero text and validate
   that text bounds do not overlap adjacent elements.
4. Keep failed URLs in the corpus and retry them as separate runs rather than
   replacing them.
5. Add these 18 pages as the regression corpus for the next P0/P1 iteration.

## Artifacts

- summary: `output/_dom_figma_18_20261031/summary.json`
- visual benchmark: `output/_dom_figma_18_20261031/visual-benchmark.json`
- capture status: `output/_dom_figma_18_20261031/capture-status.json`
- Figma status: `output/_dom_figma_18_20261031/figma-status.json`
- raw page outputs: `output/_dom_figma_18_20261031/<ID>/`
