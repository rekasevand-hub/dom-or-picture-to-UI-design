# Open-source DOM to Figma Notes

**Date:** 2026-10-28  
**Scope:** Research notes only; no code was installed or integrated in this round.

## BuilderIO/figma-html

- Repository: https://github.com/BuilderIO/figma-html
- NPM package: `@builder.io/html-to-figma`
- License: MIT
- GitHub stars: 3,709
- GitHub forks: 362
- Open issues: 60
- Latest push observed: 2025-08-19
- Figma plugin: https://www.figma.com/community/plugin/747985167520967365
- Chrome extension: https://chromewebstore.google.com/detail/builderio/cfldfgibklhmjhnkfighkbafbkbfcmij

### Current repository state

The README says the project has moved to the Builder.io Chrome
extension. The current GitHub tree is no longer a complete self-contained
repository:

- The browser extension remains under `chrome-extension/`.
- The HTML serializer is distributed through the NPM package.
- The Figma plugin is distributed through Figma Community.
- The old local `lib/html-to-figma` and `plugin/` source directories are no
  longer present on the current master branch.

The published NPM package still contains `dist/browser.js`, `dist/main.js`,
`dist/ui.html`, `dist/code.js`, and `dist/plugin/*`, so the implementation is
available in packaged form even though the repository is split.

### Two supported workflows

1. **URL import**
   - Enter a URL in the Figma plugin.
   - The import path uses Builder.io's hosted conversion service.
   - This path is convenient but is not fully offline or self-contained.

2. **Chrome capture**
   - The Chrome extension runs `htmlToFigma(document.body)` on the current
     page.
   - It downloads `page.figma.json`.
   - Upload that JSON to the published Figma plugin.
   - This path can capture authenticated pages and interactive page states.

The NPM package exports:

```ts
htmlToFigma(
  selector?: HTMLElement | string,
  useFrames?: boolean,
  time?: boolean
)
```

It returns editable Frame, Rectangle, Text, and SVG layer descriptions rather
than a screenshot-only payload.

### Strengths

- Official Builder.io project with a published end-user workflow.
- Supports both URL import and browser-state capture.
- Produces editable Figma layers.
- Handles computed styles, text, images, SVG, and a broad subset of layout
  patterns.
- MIT-licensed browser serializer can be vendored if the hosted services are
  avoided.

### Risks and limitations

- The GitHub repository is split across the extension, NPM package, Figma
  Community plugin, and hosted Builder.io API.
- URL import is not a fully local or auditable conversion path.
- The NPM stable package was `0.0.3` while the repository package was
  `0.0.5-3`, so packaged and repository versions may differ.
- The project uses older frontend infrastructure such as React 16 and
  Webpack 4.
- Open issues still cover fetch failures, authenticated images, imported JSON
  structure, and Auto Layout behavior.
- The project describes conversion as best effort. Iframes, pseudo-elements,
  video, animated GIFs, and some CSS properties remain unsupported or
  incomplete.

### Comparison with sergcen/html-to-figma

Builder.io has the stronger product and broader implementation. It is the
better benchmark for a production-grade DOM -> Figma workflow.

The previously tested `sergcen/html-to-figma` is fully local and directly
buildable, but it is older and much simpler. It is useful for a local
prototype, not as a production-quality reference.

### Assessment for this repository

BuilderIO/figma-html should be treated as:

- a feature and quality benchmark;
- a reference for browser-side style extraction and serialization;
- a possible source for a local browser serializer;
- a source of design ideas for a JSON handoff between a browser and a Figma
  importer.

It should not be treated as a drop-in replacement for the current pipeline
without resolving:

- local-only execution;
- Figma plugin source ownership;
- deterministic layer schema;
- version pinning between repository and NPM;
- image/font handling;
- timeout and partial-import behavior.

For a quick effect comparison, the most controlled path is:

```text
Chrome extension
  -> page.figma.json
  -> published Figma plugin upload
```

This path is more self-contained than URL import, while still using the
published plugin for the final Figma write.
