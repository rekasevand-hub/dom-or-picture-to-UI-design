# Product Quality Policy

**Status:** approved by user on 2026-10-25  
**Scope:** DOM-to-Figma Stage 1 and later UI replication work

## Priorities

The product prioritizes, in order:

1. layout and component usability;
2. content and text correctness;
3. editable assets and replaceability;
4. pixel similarity.

Exact pixel, glyph-outline or source-asset identity is not required when the
component remains usable and the current-scope evidence reaches at least 90%
coverage or pass rate.

## Text

- Content, linebreak, text box and projected baseline remain independent
  quality dimensions.
- Final glyph outline identity is explicitly `not-required` for the current
  product scope.
- The underlying evidence must still report final glyph identity as
  `not-evaluated`; it must never be described as verified.

## Icons And Generated Assets

- Iconfont glyph crops may use LLM-generated similar icons when no reusable
  image source is available.
- Generated icons require complete provenance and must remain non-original and
  non-reference-only.
- A generated icon may be selected for an icon-crop display even when a
  screenshot crop exists, because component editability is a product priority.
- Generated icons do not satisfy original-image identity and are reported in
  a separate generated-icon count.

## Quality Gate

- Existing frozen visual thresholds remain in force until separately changed.
- The current-scope 90% rule applies to coverage/pass rates, not to hiding
  failed pixels, missing evidence or denominator changes.
- Parent layout propagation and final glyph identity may be scoped as
  non-blocking when their evidence remains explicit in the report.
