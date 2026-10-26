# Axure Shared IR Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define one output-neutral design IR and explicit Figma/Axure
capability boundary for `A-001`.

**Architecture:** The existing DesignSpec remains the runtime renderer input.
A new deterministic projection wraps its frames, nodes, styles, assets and
provenance without replacing or mutating DesignSpec. A separate capability
matrix states what each output can preserve and what must be reported as
degraded.

**Tech Stack:** Python 3.12, existing DesignSpec dictionaries, existing
contracts layer, stdlib dataclasses/hashlib/json.

**Spec:** `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`;
`docs/v2_mentor/R4_EXP_04_PROVENANCE_IR.md`

**Execution status:** `complete-current-scope` on 2026-10-25.

## Global Constraints

- Preserve current Figma and image MVP behavior.
- Do not create a second image-understanding stack for Axure.
- Do not convert a Figma pass into an Axure acceptance claim.
- Screenshot crops remain reference-only and non-original.
- Candidate/fixed-coordinate flow must not become verified adaptive layout.
- Do not commit or push.
- A-001 defines the boundary only; A-002/A-003 still require separate adapter
  and acceptance work.

## Review Focus

- Two outputs must share node identity, content and asset provenance.
- Unsupported features must be visible rather than silently dropped.
- Reference-only assets must remain non-original after projection.
- Verification status must not be upgraded by changing target.
- Multi-page and Auto Layout capability differences must stay target-specific.

---

### Task 1: Build Output-Neutral Design IR

**Files:**
- Create: `src/app/services/contracts/output_ir.py`
- Create: `tests/v2/test_output_ir_boundary.py`

**Interfaces:**
- Produces: `build_output_ir(design, *, source_kind, reference=None) -> dict`
- Produces: `OUTPUT_IR_SCHEMA_VERSION`

- [x] Write failing tests for single-page and multi-page projection.
- [x] Write a failing test proving stable document and node identity.
- [x] Write a failing test proving reference-only asset provenance survives.
- [x] Run tests and confirm the module/function is missing.
- [x] Implement deterministic frame/node/style/layout/asset projection.
- [x] Run focused tests to green.

### Task 2: Validate Claims And Project Capabilities

**Files:**
- Modify: `src/app/services/contracts/output_ir.py`
- Modify: `tests/v2/test_output_ir_boundary.py`

**Interfaces:**
- Produces: `validate_output_ir(ir) -> list[dict]`
- Produces: `output_capabilities(target) -> dict`
- Produces: `project_for_output(ir, target) -> dict`

- [x] Write failing tests for duplicate nodes, geometry errors and a
  reference-only asset marked original.
- [x] Write a failing test for verified flow without evidence.
- [x] Write failing capability tests proving Figma supports clip but not
  multi-page, while Axure supports multi-page but not clip or Auto Layout.
- [x] Run tests and confirm failure.
- [x] Implement fail-closed validation, capability reporting and degraded
  feature projection.
- [x] Run focused tests to green.

### Task 3: Record Boundary And Regression

**Files:**
- Create: `docs/v2_mentor/AXURE_SHARED_IR_BOUNDARY_2026-10-25.md`
- Create: `docs/v2_mentor/AXURE_ROUTE_LEDGER_2026-10-25.md`
- Modify: `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`
- Modify: `README.md`

- [x] Document shared fields, target-owned fields and unsupported/degraded
  capabilities.
- [x] Run focused tests.
- [x] Run `pytest tests/v2 -q`.
- [x] Run Ruff check/format and `git diff --check`.
- [x] Update A-001 to `complete-current-scope` and point to A-002.
- [x] Confirm no commit or push.
