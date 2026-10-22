# P3 Real Figma Runtime Fault Recovery

> Date: 2026-10-21  
> Status: `real-runtime-fault-rollback-pass`  
> Scope: a real Figma API error after an earlier edit in the same transaction.

## 1. Fault Design

The probe creates a 2x2 Grid with four occupied children, then submits one
`apply_edit_batch` transaction:

1. replace the first child text;
2. expand that child across two columns while the adjacent column remains
   occupied.

Both actions pass bridge preflight. Figma rejects step 2 at runtime:

```text
Cannot set child to specified column span due to existing children
in adjacent columns
```

This is a real Figma constraint failure, not a synthetic plugin exception.

## 2. Defects Found

The first real run returned `rollback-incomplete`. Two production defects were
found:

1. A failed action captured a snapshot but did not add that snapshot to the
   rollback stack. Partial mutations made before the exception could survive.
2. Grid anchor rollback attempted to assign `gridRowAnchorIndex` and
   `gridColumnAnchorIndex` directly. Figma exposes these as readback properties;
   restoring them requires `setGridChildPosition(row, column)`.

The plugin now:

- pushes each edit snapshot before applying the action;
- rolls back the failed action together with earlier successful actions;
- restores Grid spans before positions;
- restores anchors through `setGridChildPosition`;
- reports `rollback-incomplete` with per-node failure details if restoration
  still cannot complete.

## 3. Result

Real Figma result:

```text
status: rolled-back
rollback attempted: 2
rollback restored: 2
rollback failures: 0
text restored: true
layout snapshot restored: true
content_hash: 93846c2f5efeab6afbc1d326b0908e773e2a5423017685dea0d5d906c1f8f86d
```

Evidence:

`output/_p3_runtime_fault_round1/figma_runtime_fault_probe.json`

The persistent bridge journal also recorded the transition:

- first attempt: `rollback-incomplete`;
- after the fixes: `rolled-back`.

## 4. Reproduction

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe `
  scripts\figma_runtime_fault_probe.py `
  --out output\_p3_runtime_fault_round1
```

The probe owns and removes `P3 Runtime Fault Probe`.

## 5. Boundary

This proves rollback after a real Figma constraint error inside one edit
transaction. It does not prove recovery from:

- simultaneous multiplayer conflict;
- upload/network interruption;
- Figma process termination or API-version incompatibility;
- unknown outcome reconciliation after bridge restart.

RR-006 remains open for those failure classes.
