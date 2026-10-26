# P5 Deterministic Fault Matrix

> Date: 2026-10-23  
> Status: `current-scope` only  
> This matrix records deterministic and local JS-harness evidence. It does not
> claim real Figma permission behavior, real collaboration timing, production
> admission or project-wide verification.

## Covered Scenarios

| Area | Scenario | Primary coverage | Deterministic result |
|---|---|---|---|
| Permission | View-only, denied write, revoked token, user modification and unknown failure remain manual/no-resend. | `test_p5_permission_takeover_probe.py` | Covered |
| Permission | Figma rate limit is distinct, retryable and preserves `retryAfterMs`. | `test_p5_permission_takeover_probe.py` | Covered |
| Plugin reconnect | Plugin token revocation, connection takeover and unknown writes are classified before any automatic resend. | `test_bridge_fencing.py`, `test_plugin_error_classification.js` | Covered |
| Collaboration | Same target with matching state still requires operator no-resend confirmation. | `test_p5_collaboration_race_probe.py` | Covered |
| Collaboration | Conflicting state routes to operator conflict resolution. | `test_p5_collaboration_race_probe.py` | Covered |
| Collaboration | Partial state routes to `operator-reconcile-partial-state`, not no-resend confirmation. | `test_p5_collaboration_race_probe.py` | Covered |
| Collaboration | Concurrent node deletion and `NODE_NOT_FOUND` classify as `user-modification`. | `test_p5_collaboration_race_probe.py`, `test_plugin_error_classification.js` | Covered |
| Attribution | Unavailable attribution keeps actor/revision `unknown`; authoritative attribution is preserved only when supplied. | `test_p5_collaboration_race_probe.py` | Covered |
| Expected state | Image fill SHA-256 is derived from actual `image_fill_report` bytes, not from the expected object. | `test_plugin_readback_uses_actual_image_bytes_for_expected_hash` | Covered |
| Expected state | Layout input aliases are normalized to readback field names. | `test_expected_checks_normalize_layout_and_keep_region_context` | Covered |
| Expected state | Bounds checks execute through `set_bounds` and survive rollback. | `test_edit_batch_region_bounds.js` | Covered |
| Expected state | Text runs accept expected-field subsets of actual styled runs. | `test_expected_region_checks_are_independent`, `p5_region_compensation_probe.py` | Covered |
| Region | Region membership is stored and read through plugin data. | `test_edit_batch_region_bounds.js` | Covered |
| Region | One failed region does not hide another matching region. | `test_reconciliation_reports_partial_region_failures` | Covered |
| Compensation | Same-job nodes outside the requested region are preserved. | `test_compensation_requires_exact_job_owner_and_region_markers` | Covered |
| Compensation | Missing region/owner evidence becomes `rollback-incomplete/manual-review`. | `test_compensation_requires_exact_job_owner_and_region_markers` | Covered |
| Rollback | Overlapping edits on one node restore in reverse order. | `test_edit_batch_rollback.js`, `test_layout_transaction_rollback.js` | Covered |
| Takeover | Explicit user takeover blocks automatic compensation. | `test_figma_adapter_edits.py` | Covered |
| Cleanup | Cleanup requires terminal ledger state and exact owner/job markers. | `test_write_job_ledger.py`, `test_ownership_marker_cleanup.js` | Covered |
| Cleanup | Unknown or pre-terminal jobs cannot dispatch cleanup automatically. | `test_cleanup_of_unknown_job_blocks_before_dispatch` | Covered |
| Unknown | Unknown writes are not replayed after plugin reconnect. | `test_bridge_fencing.py` | Covered |

## Evidence

Commands:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_permission_takeover_probe.py --out output\_p5_permission_takeover_round2
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_collaboration_race_probe.py --out output\_p5_collaboration_race_round2
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_region_compensation_probe.py --out output\_p5_region_compensation_round2
node tests\bridge\test_plugin_error_classification.js
node tests\bridge\test_edit_batch_region_bounds.js
C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\v2\test_p5_permission_takeover_probe.py tests\v2\test_p5_collaboration_race_probe.py tests\v2\test_p5_region_compensation_probe.py -q
```

| Artifact | Content hash | File SHA-256 |
|---|---|---|
| `output/_p5_permission_takeover_round2/result.json` | `8953e1d3a5dbf625ef8d5881ff9d41a1525a8ae5b666ff6f5f8e533225174451` | `f99890dcce5a45a5a0d8f63a199d0b5cd7e9e2cf5be3f6e63462e24429a6258` |
| `output/_p5_collaboration_race_round2/result.json` | `07c64403147664efdc7216939587df3bcb722888704060df9e9c881c6a8d3214` | `c2b524a3ea888bb87f273c13d5e962783da635f98652f4f986fd974f3ebbc212` |
| `output/_p5_region_compensation_round2/result.json` | `43495f49d3798ca4dab2a79bb55abe040b4542fed85edb5b6ac853181415d55a` | `0e893886c70fd0ff467f384f32855031a48053fc6bea87de893634dd06fc05dc` |

Fixed plugin source at this evidence point:

`figma_bridge/code.js` SHA-256
`11bb40dbe20add8ad3fd8ea4ca79c0e4b91f0cdf777d4a1e9500e1c75333cabd`

## Still Blocked

The following require fixed real accounts, controlled timing or an external
attribution source and remain blocked:

- real view-only and denied-write execution;
- deliberate real Figma rate limiting with an approved observation window;
- two real collaborators modifying the same target;
- real post-send modification and concurrent owned-node deletion;
- real collaborator takeover during a mutating batch;
- real upload interruption and incomplete rollback;
- authoritative actor/revision evidence from Figma or an approved external
  source.

## Non-Claims

- A matching deterministic outcome is not proof of a real Figma commit.
- `NODE_NOT_FOUND` classification is not proof that a collaborator deleted the
  node; it only selects the conservative manual-review branch.
- Local plugin-data region markers do not prove Figma's server-side ownership
  or attribution semantics.
- No result here satisfies the production Task 6/7 exit criteria.
