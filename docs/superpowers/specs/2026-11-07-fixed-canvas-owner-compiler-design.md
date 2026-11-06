# Fixed-Canvas Owner Compiler Design

Date: 2026-11-07

## Intent

Replace the current image high-fidelity path's competing post-hoc element
appenders with one fixed-canvas owner compiler. The mentor-agent FlexWeaver
sample establishes the target mechanism: one occurrence-level owner per
visible item, exact source pixels, native fixed-size text, isolated image
assets, and deterministic Figma authoring groups.

## Decisions

### Fixed canvas

The canvas is the source screenshot size. Layout is absolute and
non-responsive. Auto Layout and component reuse are not required.

### Two geometry domains

Every container may carry:

- `source_bbox`: the visible source region;
- `authoring_bbox`: the Figma group/frame bounds used to organize children.

An authoring frame may equal the root canvas when children remain absolutely
positioned. This is valid only when `layout_mode` is
`fixed-canvas-absolute`.

### Text editability

Fixed-size native text is valid. Editability requires:

- the node remains TEXT;
- characters can be changed;
- font family, style, size, color, and alignment survive the edit;
- the original characters can be restored;
- the original text fits its intended box or an explicit source clipping rule.

Automatic geometry growth after editing is not required.

### Dynamic style resolution

Mentor-output values are priors, not global constants. For every text owner,
resolve:

- foreground color;
- font size;
- font weight;
- font family candidate;
- horizontal alignment;
- line height policy.

Unavailable or ambiguous fonts remain explicit evidence gaps and use a
verified fallback.

### Single ownership

Every visible occurrence gets a stable owner ID containing:

```text
sample / region_instance / semantic_role / occurrence_key / subpart
```

OCR and generic text passes may attach evidence to a claim but may not append a
second rendering.

### Tables

Cell identity is structural:

```text
table_instance / section / row_key / column_key
```

Repeated values never determine identity.

## Non-Goals

- responsive reflow;
- Auto Layout reconstruction;
- component/instance reuse;
- original font identity from pixels without evidence;
- rasterizing required text.

## Acceptance

- complete occurrence inventory coverage;
- no unauthorized duplicate rendered owner;
- exact displayed strings, including spaces and punctuation;
- table row/column ownership complete;
- source geometry coverage;
- native editable text;
- no full-screenshot underlay;
- region visual gates.
