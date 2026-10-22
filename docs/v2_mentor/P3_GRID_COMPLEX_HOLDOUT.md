# P3 Grid Complex Holdout

> Date: 2026-10-21  
> Status: `create-pass / plugin-reload-readback-pass / document-close-reopen-readback-pass / cleanup-pass`  
> Scope: nested Grid, fixed/Flex/Hug tracks, manual spans, row auto-flow,
> long text, image fills, and resumable readback.

## 1. Result

The first complex Grid holdout passed in real Figma:

- manual 2x3 root Grid;
- nested 2x2 Grid;
- `FIXED`, `FLEX`, and `HUG` track types;
- column and row spans;
- row auto-flow with `gridAutoTracks=ROWS`;
- wrapped long text in nested and outer tracks;
- image fills in nested and outer tracks;
- explicit child alignment and sizing.

Evidence:

- `output/_p3_grid_complex_holdout_round1/figma_grid_complex_create.json`
- `output/_p3_grid_complex_holdout_round1/figma_grid_complex_verify.json`
- `output/_p3_grid_complex_holdout_round1/figma_grid_complex_cleanup.json`
- `output/_p3_grid_complex_holdout_round1/complex_grid_manifest.json`

Create result:

```text
status: pass
manual_root_id: 39:363
auto_root_id: 39:370
content_hash: aaa7d6cba30d8b0c985f9c9f7d5b5ceca015688659904f17151c79bbd45ad2e7
```

Document close/reopen and plugin readback result:

```text
status: pass
reopen_status: verified
readback_context: document-reopen
manual_nested_mixed_grid: pass, 0 differences
row_auto_flow_grid: pass, 0 differences
content_hash: f312b48305bdad0ff9d5a43f9b5324d13886aeb8edddb064e3f3e88b632afe7a
```

The readback compares persistent layout semantics, not viewport-dependent
absolute coordinates. Geometry uses a 0.5 px tolerance; names, hierarchy,
track types, spans, alignment, text, and image hashes remain exact.

The real persistence check closed the `Untitled` Figma tab, reopened it from
`Recently closed`, started the development plugin again, and then ran the
verify phase. Both owned roots and all compared fields survived the cycle.
The cleanup phase then removed exactly the two owned probe roots.

## 2. Figma Constraint Found

Real Figma rejects a Grid dimension update when occupied rows or columns would
be deleted. Reapplying an identical full Grid configuration can therefore fail
after Figma has adjusted the track count.

The bridge now:

- writes Grid columns before rows;
- skips unchanged dimension setters;
- provides `set_grid_child_overrides` for span/alignment updates without
  rewriting frame dimensions.

The resulting transaction order is:

1. create the Grid and place children in non-overlapping cells;
2. finish one layout pass and read the actual Grid dimensions;
3. apply spans through child-only overrides.

## 3. Reproduction

Create and retain the owned probe roots:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe `
  scripts\figma_grid_complex_holdout_probe.py `
  --out output\_p3_grid_complex_holdout_round1 `
  --phase create
```

After reloading the plugin, or after manually saving and reopening the Figma
document, verify the retained roots:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe `
  scripts\figma_grid_complex_holdout_probe.py `
  --out output\_p3_grid_complex_holdout_round1 `
  --phase verify `
  --readback-context document-reopen
```

Remove only nodes owned by the probe:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe `
  scripts\figma_grid_complex_holdout_probe.py `
  --out output\_p3_grid_complex_holdout_round1 `
  --phase cleanup
```

## 4. Boundary

The current evidence proves:

- real Figma creation of the complex combination;
- deterministic child-only span updates;
- zero-difference readback after plugin reload;
- zero-difference readback after closing and reopening the Figma document;
- snapshot comparison catches hierarchy, geometry, track, text, and image
  changes by path.

The current evidence does not yet prove:

- cross-version readback;
- automatic Grid track extension beyond the explicit row count;
- collaborative edits or undo/redo;
- long text and image combinations across every Grid track/span permutation.

RR-005 therefore remains open. Do not describe this holdout as complete Grid
combination coverage or unconditional production admission.
