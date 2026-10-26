# D-011 Browser-Context Network Asset Recovery

**Goal:** Recover original bytes for frozen DOM assets whose direct URL probe
was blocked but whose source loaded successfully in the page browser context.

## Constraints

- Only fetch URLs already present in the frozen DesignSpec.
- HTTPS only; no private or arbitrary hosts.
- Deduplicate by URL and enforce per-asset and total byte limits.
- Require successful image decoding, SHA-256, MIME and natural-size checks.
- Keep screenshot crops as the visual display payload.
- Do not promote unavailable inline/pseudo icons to original assets.
- Keep a URL alone as `reference-only`; only retained verified bytes become
  `verified-original`.
- Do not change visual, text or frozen quality thresholds.

## Task 1: Verified Source Upgrade

- [x] Add a failing asset-record test.
- [x] Implement an explicit source-identity upgrade helper.
- [x] Preserve display, missing-state and use fields.

## Task 2: Bounded Recovery Service

- [x] Add failing tests for deduplication, size limits, invalid MIME and
  successful bytes.
- [x] Implement browser-context requests with injectable request transport.
- [x] Write content-addressed source bytes and a probe report.
- [x] Re-run asset fusion after each source upgrade.

## Task 3: Acceptance Preparation Integration

- [x] Add an opt-in `prepare --recover-network-assets` path.
- [x] Ensure the recovered design hash is written to metadata.
- [x] Keep the default offline prepare path unchanged.

## Task 4: Real DQ-R02 Reproof

- [x] Run recovery against the same Dushu page state.
- [x] Verify the screenshot, structure and text fingerprints remain unchanged.
- [x] Run a new Figma frame at a new origin.
- [x] Report verified/reference/unavailable counts honestly.
- [x] Run focused and full regression checks.

## Execution Evidence

```text
unique URLs: 24
verified URLs: 24
verified image uses: 44
replaceable image uses: 44
unavailable icon-font crops: 10
missing displays: 0
retained source bytes: 254,162
frame: 75:3819
origin: [20000, 0]
```

The remaining 10 uses were inspected in the live page and are iconfont
`::before` glyphs, not unresolved image URLs. They remain unavailable in the
image-source denominator until a product policy scopes icon crops separately.

Verification: full regression `643 passed in 38.87s`; Ruff, `node --check` and
`git diff --check` pass.
