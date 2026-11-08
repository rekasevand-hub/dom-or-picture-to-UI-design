# Short-Unit Logical Label Merge

Date: 2026-11-08

Decision: **short OCR units such as `折` are merged into an adjacent numeric
owner before inventory/ScenePlan.**

This is an evidence-backed upstream fix, not a pass claim. The real Figma run
remains `blocked-fail` under `image-figma-mvp-product/2.0`.

## Defect

The ACCTOKEN Models OCR supplement observed:

```text
5.8  bbox=[1061, 660, 109, 74]
折   bbox=[1097, 725, 42, 40]
8.8  bbox=[2246, 660, 103, 74]
折   bbox=[2279, 725, 42, 40]
```

`折` was dropped with `reason=text-too-short` because the candidate normalizer
requires at least two characters. The visible logical labels were therefore
`5.8` and `8.8`, not `5.8折` and `8.8折`.

## Fix

`src/app/services/structure/image_contract.py` now attempts a conservative
logical-label merge before dropping a short OCR token:

- the token must be a known short unit suffix (`折`, `元`, `%`, `月`, `日`,
  `KB`, etc.);
- the owner must be a pure numeric text owner;
- the boxes must be adjacent on one line or vertically stacked;
- the unit box must be no larger than 60% of the owner box.

The merge rewrites the existing graph element text and bbox, writes
`logicalText` / `logicalTextParts`, and records `logical_merges` plus
`logical_merge_count` in `ocr_supplement.json`.

## Prepare-Only Evidence

Run:

`output/_calibration_shortunit_verify_20261108_acctoken`

```yaml
logical_merge_count: 2
merges:
  - before: 5.8
    unit: 折
    after: 5.8折
    bbox: [1061, 660, 109, 105]
  - before: 8.8
    unit: 折
    after: 8.8折
    bbox: [2246, 660, 103, 105]
```

`10_content_inventory.json` contains one `5.8折` item and one `8.8折` item.
No separate `折` item is emitted.

## Real Figma Evidence

Run:

`output/_calibration_shortunit_verify_20261108_acctoken`
(mode `residual`, emission `repair`, origin-x `40000`)

| Metric | Before short-unit fix | After |
|---|---:|---:|
| critical text | 24 / 27 | **25 / 27** |
| blockers | 32 | **31** |
| within30 | 94.121133% | **95.011687%** |
| native gate | 0 / 26 | 0 / 26 |
| chrome | fail | fail |
| overall | blocked-fail | blocked-fail |

Critical rows:

```text
5.8折  present=true
8.8折  present=true
本期好价  present=false
查看详情  present=false
```

`5.8折` and `8.8折` are present in the final DesignSpec as native text owners.
`查看详情` is a derived-truth typo: the screenshot reads `看详情 →`.
`本期好价` is a separate suppression/recall issue and is not addressed here.

## Boundary

- No underlay, asset identity, font identity, DPR, or adaptive-flow claim.
- Native gate remains `0/26`; the short-unit fix improves content coverage, not
  glyph fidelity.
- The real run remains `blocked-fail`.
