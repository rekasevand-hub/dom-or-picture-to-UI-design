# Axure Current-Scope Exit Review Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decide whether the Axure current scope can close after A-010, while
keeping all unsupported and production claims explicit.

**Architecture:** Review the existing frozen holdouts, controlled image route,
independent acceptance, reopen-publish and capability declarations. Produce a
pass-current-scope decision for named controlled routes or a fail/blocked
decision if a required gate is missing.

**Tech Stack:** Python 3.11, pytest, Axure RP 8 evidence, DesignSpec,
`design-ir/2.0`.

**Specs:**
- `docs/v2_mentor/AXURE_FRESH_HOLDOUT_A010_2026-10-25.md`
- `docs/v2_mentor/AXURE_IMAGE_ACCEPTANCE_2026-10-25.md`
- `docs/v2_mentor/AXURE_HOLDOUT_V2_ACCEPTANCE_2026-10-25.md`

**Execution status:** `pass-current-scope` on 2026-10-25.

## Global Constraints

- A-010 supports only its frozen three-sample pass.
- A-006/A-008 remain historical failures and cannot be silently removed.
- Image evidence remains limited to named controlled samples.
- No Figma acceptance is transferable to Axure.
- Runtime replacement, Auto Layout, clipping, letter spacing, interactions,
  shadows/gradients and save-back remain explicit non-claims.
- No product code change is expected in this review.
- Do not commit or push.

## Review Focus

- Is DOM -> Axure covered by an untuned fresh holdout after remediation?
- Is image -> Axure supported by a distinct controlled real-publish result?
- Are object mapping, critical text, assets, visible regions and visual gates
  all represented?
- Are deterministic generation and reopen publish proven separately?
- Does any residual gap invalidate current scope or only limit future claims?

### Task 1: Audit Evidence

**Files:**
- Read: A-001 through A-010 evidence.
- Read: `src/app/services/contracts/output_ir.py`.
- Read: route ledger and acceptance reports.

- [x] **Step 1: Build the route and gate matrix**

- [x] **Step 2: Distinguish closed failures from open limitations**

### Task 2: Decide Current Scope

**Files:**
- Create:
  `docs/v2_mentor/AXURE_CURRENT_SCOPE_EXIT_REVIEW_2026-10-25.md`
- Create:
  `output/_axure_current_scope_exit_2026-10-25/summary.json`

- [x] **Step 1: Record `pass-current-scope` or the blocking reason**

- [x] **Step 2: List every retained non-claim and future trigger**

### Task 3: Update Program State

**Files:**
- Modify:
  `docs/v2_mentor/AXURE_ROUTE_LEDGER_2026-10-25.md`
- Modify:
  `docs/v2_mentor/GLOBAL_OPTIMIZATION_MASTER_PLAN_2026-10-25.md`
- Modify: `README.md`
- Modify: `docs/v2_mentor/README.md`

- [x] **Step 1: Mark A-011 and define the next-priority trigger**

- [x] **Step 2: Run focused regression and evidence checks**

**Final result:** `pass-current-scope`. The named controlled routes close for
the documented scope. A future capability or production phase requires an
explicit user priority decision and new gates. Focused tests pass `28/28`;
`tests/v2` passes `732 passed in 41.51s`; `git diff --check` passes. No product
code changed in this review.
