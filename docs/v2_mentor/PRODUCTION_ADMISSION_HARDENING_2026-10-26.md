# Production Admission Hardening Evidence

> Date: 2026-10-27  
> Code revision: `5f25c00ef6f38778bf741bb1b260cf40bd0f0908+dirty`  
> Plugin code: `11bb40dbe20add8ad3fd8ea4ca79c0e4b91f0cdf777d4a1e9500e1c75333cabd`  
> Decision: `not-admitted`; one-hour runs are complete, but Q8-Q10, 24h/7d,
> real collaboration and production operations remain blocked.

## Intent

This round hardens the existing P5/P4 production-admission path without
returning to image/CV feature research. Grounding remains the default image
strategy. CV remains an availability fallback only, and its fresh-holdout
quality remains `0/3`.

The four evidence classes are independent:

1. Grounding reliability and fallback observability;
2. Figma collaboration, ownership, idempotency and recovery;
3. security boundaries;
4. long-running behavior.

No class substitutes for another, and no composite score is produced.

## Grounding Reliability

Implemented:

- ordered endpoint redundancy;
- finite retry with exponentiated, jittered and capped backoff;
- per-attempt timeout through the OpenAI-compatible client;
- per-endpoint circuit breaker with cooldown and one half-open probe;
- bounded TTL/LRU result cache;
- cache key over image, model, prompt, strategy, strategy version and tenant
  namespace;
- explicit `connection`, `timeout`, `rate-limit`, `server`, `authentication`,
  `request-invalid`, `response-invalid` and `circuit-open` categories;
- response/graph telemetry for attempts, final endpoint, breaker state, latency
  and token usage.

Evidence:

- `output/_production_admission_2026-10-26/grounding_reliability/result.json`
- content hash
  `b259b2f7f1d068b725105a39e2088be8563fac77bd8a3f7b2a22af1a5789a8b2`

Result: `pass-current-scope` for controlled in-process endpoint faults.

Non-claims: no real external provider availability, production network
latency, endpoint ownership or monetary cost.

## Fallback Observability

`fallback_observability.json` is written after provider selection and before
OCR supplements, design generation or any Figma write. It records:

- Grounding unavailable and fallback trigger;
- CV selection acceptance, explicitly not quality acceptance;
- trigger stage and `write_before_decision`;
- Grounding retry latency and token usage;
- unknown cost until a versioned pricing table exists;
- cache, attempt and retry status.

Evidence:

- `output/_production_admission_2026-10-26/fallback_observability/result.json`
- content hash
  `21bb84ee6a63857a1f4cb39882a186d03b0e6c1e816f2d498cbb8e1e75e5050f`
- `output/_production_admission_2026-10-26/observability/result.json`
- 21-metric content hash
  `53e3e309802a645ab6e4c578b8af1b283a73bab9e32f8767464bc57dd50c04ec`

Result: `verified-for:controlled-prewrite-fallback-observation`.

Non-claims: general CV quality and live fallback cost/latency.

## Collaboration and Recovery

The probe uses the existing `BridgeHub`, writer lease, persistent journal and
ownership namespace. The transport is a deterministic fake plugin; the bridge
and lease are real local components.

Observed:

- two clients using the same request id remain isolated and both commit;
- one plugin write is in flight at a time;
- an idempotent retry returns the cached result without a second dispatch;
- a newer plugin closes the old connection with code `4002`;
- a timed-out owned batch remains `unknown`;
- reconnect performs ownership readback and classifies
  `matches-intended` without resend;
- the unknown transaction and readback survive hub recreation.

Evidence:

- `output/_production_admission_2026-10-26/collaboration_bridge/result.json`
- content hash
  `326aebfe3c8b4a58a21dd478ccbf7fe1eff5e96422248091269613eefa03d3bf`

Result: `verified-for:controlled-bridge-collaboration`.

Non-claims: real collaborator actor/revision, real takeover timing,
two-account attribution, multi-tenant isolation or production admission.

## Security

Generated in-memory canaries were used. No `.env`, login state or real token
was read or persisted.

Observed:

- wrong plugin token fails with `4003`;
- missing command bearer token fails closed;
- wrong per-client token cannot act as another client;
- oversized messages and deep params fail before plugin dispatch;
- frame logs emit only message type, action and request id, never frame payload;
- token-like values, URL credentials/queries and action bodies are redacted
  from logs;
- Grounding cache namespaces produce different keys;
- TLS, secret rotation and client identity unit/integration tests pass.

Evidence:

- `output/_production_admission_2026-10-26/security/result.json`
- content hash
  `f99ee1c65ce447f13374e90f80c25c551c974fe86ca13bd4acde63d7214029c7`

Result: `verified-for:generated-canary-security-boundaries`.

Non-claims: production secret manager, ACL ownership, certificate lifecycle,
real token revocation or public exposure.

## Long-Running Evidence

| Run | Boundary | Status |
|---|---|---|
| Short dry run | In-process bridge rehearsal, under one hour | `rehearsal-pass`; not a soak pass |
| Real Figma round 1 | Local Figma Desktop, 4 writers | `fail` at 362.992s after four `PLUGIN_CONNECTION_CHANGED`; setup and exact cleanup passed |
| Real Figma round 2 | Local Figma Desktop, 1 writer | `fail` at 2,619.488s; one plugin-disconnect failure and cleanup blocked |
| Controlled round 4 | One hour, fake transport with 429/503/reconnect/unknown faults | `blocked-harness-defect`: report hid 32,618 failed requests |
| Controlled round 5 | Corrected zero-failure gate | `blocked`: 300s test lease expired, 32,598 lease rejections |
| Real Figma preflight round 5 | Fixed `pilot`, 4 writers, 10s | `pass`, zero failed writes and exact cleanup |
| Real Figma round 3 | Fixed `pilot`, 4 writers | `pass`; 57,039/57,039 writes, exact cleanup, audit mechanically passed with Q8-Q10 pending |
| Controlled round 6 | Lease TTL bounded above full duration | `pass-current-scope`; 0 failures, 429/503/reconnect/unknown recovery covered |

The controlled round records 5/15/30/60-minute checkpoints, p50/p95/p99,
journal size, ledger events, queue depth, RSS and handles. A short run can only
be `rehearsal-pass`; it cannot be promoted to a one-hour soak.

Round 4 is retained as negative evidence:

- `output/_production_admission_2026-10-26/soak_1h_controlled_round4/result.json`
- content hash
  `3a378689981fd44f7ca62c2c50d8299c7915412c731253f3992a37c0e26e88c9`
- 35,606 attempts but 32,618 failed; the report incorrectly passed because the
  zero-failure check was missing.

The harness now fails on any unexplained request failure. A queued write now
re-reads the current plugin after write admission, and a 5-second forced
reconnect rehearsal completed 251 requests with zero failures and 10 takeovers.

Round 5 is retained as another blocked run:

- `output/_production_admission_2026-10-26/soak_1h_controlled_round5/result.json`
- content hash
  `2a54bdab08ec67b49f2b83be76fe70804e0cb8562c4356012b6414c8716e400e`
- 32,598 `WRITER_LEASE_REQUIRED` failures after the 300-second test lease
  expired;
- queue, RSS, handle and latency bounds held, but the zero-failure gate
  correctly refused the run.

The bounded soak now derives a lease TTL longer than the requested duration.

Final controlled round 6 passed:

- `output/_production_admission_2026-10-26/soak_1h_controlled_round6/result.json`
- content hash
  `5f292b8a8132212ffd63686da4bc4a80e02162dff8e7e4dbeb13330e8330d251`
- 35,881 attempts: 34,446 committed and 1,435 safe rejections;
- 717 HTTP-429 controls and 718 HTTP-503 controls;
- 12 plugin reconnects; one controlled unknown reconciled without resend;
- zero unexplained failures and empty queues;
- p50/p95/p99: `25.573 / 52.078 / 64.828 ms`;
- RSS growth `68,444,160B`, handles `-14`;
- five-minute checkpoints cover 300 through 3,600 seconds.

The real Figma round-1 failure is retained:

- `output/_production_admission_2026-10-26/soak_1h_real_figma/figma_bridge_soak.json`
- content hash
  `30153a96f61be32acf19b174bd83a7ec9f11c4f957f0470227c5f910b36f5d54`
- 5,758/5,762 succeeded, four failed after a live plugin connection change;
- setup ownership `1/1 + 1/1` verified, cleanup exact.

The single-writer retry also failed:

- `output/_production_admission_2026-10-26/soak_1h_real_figma_round2/figma_bridge_soak.json`
- content hash
  `9d5c165992889bf9b50f718d2270e93e1dc1ffb2258b459890b0654a02723984`
- 41,434/41,435 writes succeeded before the plugin socket closed;
- p50/p95/p99: `62.805 / 71.103 / 79.797 ms`;
- setup ownership passed, but cleanup could not dispatch because the plugin did
  not reconnect;
- the report is `fail`, not `blocked-pending-rulings`.

Operators must reconnect the fixed development plugin, verify the retained
root/text ownership jobs, and perform exact owned-job cleanup before another
run.

The final real retry passed after the plugin fix and the depth-1 cleanup
readback change:

- `output/_production_admission_2026-10-26/soak_1h_real_figma_round3/figma_bridge_soak.json`
- content hash
  `01e5d4984598bc1815a2cfef01060c68b79905833d18b1e4bc213057f4c7da3a`
- 57,039/57,039 writes succeeded over `3,600.217s`;
- p50/p95/p99: `250.319 / 266.497 / 317.157 ms`;
- setup and exact cleanup verified;
- journal bounded at `2,365 / 4,096` events;
- `p5_evidence_audit.py` mechanical pass with claim
  `blocked-pending-rulings` for Q8, Q9 and Q10.

Non-claims:

- 24-hour and seven-day soak were not started;
- real collaborator timing is still unavailable;
- a local real-Figma hour cannot replace the cloud staged soak;
- plugin-renderer memory remains unmeasured unless the run provides it.

## Operational Thresholds

For the controlled profile:

- maximum unreconciled unknown: `0`;
- write p99: `<= 5000 ms`;
- RSS growth: `<= 256 MiB`;
- handle growth: `<= 256`;
- journal and business ledger: `<= 4096` retained events;
- `fallback_write_before_block_total`: `0`;
- fallback p99 warning at `30s`, critical at `120s`;
- any cache-isolation failure is critical.

Detailed actions are in `GROUNDING_RELIABILITY_RUNBOOK.md` and
`P4_OPERATIONS_RUNBOOK.md`.

## Artifact File Hashes

Code and plugin inputs:

| Input | SHA-256 |
|---|---|
| Bridge server | `ebdd9ce65f65e9cc789b76b99d68fd208ea507403b79480336f18767348c8b35` |
| Real-Figma soak probe | `2ad2e0615fa3cad1316d03ee75d2d67b52d9eee900f384a38576143580445c2d` |
| Controlled soak probe | `8365f9a81b078d39947b9a606ead1018f04427877c876bac62c340bb0e9628fd` |
| Figma plugin `code.js` | `11bb40dbe20add8ad3fd8ea4ca79c0e4b91f0cdf777d4a1e9500e1c75333cabd` |
| Figma plugin `manifest.json` | `171af398536fd984b5e246bb0154b497de74f29e7faa38d0aff6d6bef643fa65` |

| Artifact | SHA-256 |
|---|---|
| Grounding reliability result | `a7210d75a74b91bca51c541518b29803108087037459e207ccb016ac1d59c320` |
| Fallback observation result | `e167f38bf25edee794b06d2281dfb4074b5ec1674df5e998640590096064ffb4` |
| Collaboration probe result | `993d9a688045560a6152f67b04b422b2faa16b9647c76eecfa04975534e8a5ee` |
| Security probe result | `0e25f912a88f58beed03fc99a9133071187fda540a90900423853dcfef44ce2c` |
| Observability result | `1a4c054691cca3dd202dde09dc3396c25fef289f22e7fc10d7e16b482bdf4a48` |
| Controlled 1h result | `283610f69b453376a990c2410ac64a654711973f085b02105a2347864780b29c` |
| Controlled 1h checkpoints | `8b0885613a28c085677db2ef956ec4a4e63970ca5537ddc6d5b944ca26246fa9` |
| Real Figma 1h result | `c508a34b1dc5cc6f1290b3175156352eba45c9c2ef9127b157f29b26accfc66a` |
| Real Figma evidence audit | `4ca0a6ae82991c4f3078dee32c056cd3c355ebe33af03bbd2a9d04aa02c71585` |

## Verification Commands

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\grounding_reliability_probe.py `
  --out output\_production_admission_2026-10-26\grounding_reliability
C:\Users\lzq\.conda\envs\omni\python.exe scripts\fallback_observability_probe.py `
  --out output\_production_admission_2026-10-26\fallback_observability
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_collaboration_bridge_probe.py `
  --out output\_production_admission_2026-10-26\collaboration_bridge
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p5_security_probe.py `
  --out output\_production_admission_2026-10-26\security
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p4_observability_probe.py `
  --out output\_production_admission_2026-10-26\observability `
  --fallback-observation output\_production_admission_2026-10-26\fallback_observability\fallback_observability.json
```

Final test run: `792 passed` for `tests/v2`; Python compile, Ruff, plugin
syntax and focused Node bridge tests pass.

## Admission Decision

Current decision remains `not-admitted`.

Reasons:

- Q8-Q10 remain unresolved, so the real 1h run is not `pilot-verified-for`;
- 24-hour and seven-day soak remain `not-run`;
- real two-collaborator attribution and timing remain unavailable;
- production secret manager, certificate lifecycle, ACL ownership and remote
  monitoring remain undeployed;
- production storage backend and restore drill remain incomplete.

The next trigger is resolution of Q8-Q10 and acceptance of the fixed-registry
P5 pilot. Production admission then requires the environment-bound gaps above
to be closed or explicitly excluded from a narrower release scope.
