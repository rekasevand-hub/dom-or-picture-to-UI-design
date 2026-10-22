# P4 Sustained Write Backpressure

> Date: 2026-10-22  
> Status: `server-paced-writes-pass / per-client-admission-pass / deterministic-soak-pass / real-figma-60s-revalidation-pass`  
> Scope: sustained write dispatch, bounded admission, safe rejection,
> retry guidance, timeout degradation, and read-path isolation.

## 1. Problem

The prior real Figma write soak used four writers without client-side pacing.
All four reached iteration 169 and timed out with `outcome=unknown`:

```text
requested: 676
committed: 672
timeout/unknown: 4
```

The plugin promise queue later returned the delayed responses, but the bridge
could not safely attribute them. A one-writer rerun with a client-side 50ms
sleep completed 347/347 transactions. This proved pacing was required, but a
client-side convention alone could not protect the bridge from other clients.

Evidence:

- `output/_p4_real_bridge_write_soak_round1/figma_bridge_soak.json`
- `output/_p4_real_bridge_write_soak_round2/figma_bridge_soak.json`

## 2. Contract

The bridge now applies a global write policy per `BridgeHub`.

1. Known read-only actions bypass the write gate.
2. All other actions are conservatively classified as writes.
3. A write must acquire one of `max_write_queue` admission slots before an
   idempotency intent is journaled or a plugin send is attempted.
4. A write waits at most `write_queue_timeout` for its dispatch turn.
5. Only one write is dispatched until its terminal response. This prevents
   writes from accumulating in the plugin promise queue.
6. The next write is released no earlier than the configured minimum interval
   after the previous actual plugin dispatch.
7. Queue saturation or queue-wait timeout returns:

```json
{
  "code": "BRIDGE_WRITE_BACKPRESSURE",
  "outcome": "not-applied",
  "retryAfterMs": 50
}
```

The rejected request was not sent and has no terminal write intent. A client
may retry the same `clientId + requestId` after `retryAfterMs`.

8. A write timeout marks the hub write-degraded. New writes receive
   `BRIDGE_WRITE_BACKPRESSURE/not-applied` until the plugin reconnects.
9. The existing journal unknown-outcome rule remains unchanged. A command that
   was sent and timed out is never automatically replayed.
10. Per-client admission limits are keyed by the verified/declared `clientId`.
    A noisy client cannot occupy the entire global write queue.
11. Each client has a token bucket (`burst` + `min_interval_ms`) and a separate
    admitted-write cap. A limited client waits, while another client can use
    its own tokens and dispatch independently.
12. Per-client rejection occurs before journal intent and plugin send:

```json
{
  "code": "BRIDGE_CLIENT_RATE_LIMITED",
  "outcome": "not-applied",
  "retryAfterMs": 50
}
```

`FigmaBridgeError` exposes `code`, `outcome`, and `retry_after_ms` so callers do
not need to parse the error string.

## 3. Configuration

Settings live in `figma_bridge.config.json`:

| Field | Default | Meaning |
|---|---:|---|
| `server.write_pacing.min_interval_ms` | `50` | Minimum global dispatch interval after an actual plugin send |
| `server.write_pacing.queue_timeout_seconds` | `5` | Maximum wait for a dispatch turn |
| `server.write_pacing.max_queue` | `16` | Global admitted writes, including the active writer |
| `server.client_write_defaults.max_inflight` | `4` | Default admitted writes per client |
| `server.client_write_defaults.burst` | `4` | Default per-client token bucket capacity |
| `server.client_write_defaults.min_interval_ms` | `0` | Default per-client token refill interval |
| `server.client_write_limits.<clientId>` | `{}` | Optional per-client overrides |

Invalid or non-finite values fail at bridge startup. Environment overrides are
ignored unless `allow_env_overrides` is `true`. The 50ms global default follows
the successful real Figma single-writer run rather than the deterministic
soak's shorter test interval.

## 4. Verification

Protocol and adapter tests cover:

- concurrent writes remain single-file in the plugin;
- dispatch intervals are enforced;
- one client cannot admit more writes than its per-client cap;
- a rate-limited client cannot block another client's token bucket;
- rejection occurs before transaction/journal intent creation;
- queue-wait timeout is `not-applied` and creates no write intent;
- read commands bypass a blocked write;
- a timed-out write blocks new writes until plugin reconnect;
- `retryAfterMs` is returned and preserved by `FigmaBridgeError`;
- existing request correlation, idempotency, journal recovery, auth, and
  rollback tests remain green.

Full protocol result during this change: `35/35 passed`.

### Real Figma Revalidation

The existing Figma development plugin was connected to a fresh bridge journal
and the write probe was run with four workers, no client-side sleep, and the
default server policy:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe `
  scripts\figma_bridge_soak_probe.py `
  --out output\_p4_real_bridge_write_soak_round3 `
  --duration 60 `
  --concurrency 4 `
  --reconnect-every 100 `
  --mode write `
  --sleep-ms 0 `
  --journal output\_p4_server_paced_real_soak_round1\bridge-journal.jsonl
```

Result:

```text
status: pass
requested / succeeded / failed: 960 / 960 / 0
duration: 60.198s
requests/s: 15.947
p50 / p95 / p99 / max: 250.273 / 262.553 / 267.832 / 276.883ms
connections opened: 12
journal: 1,926 lines; 963 intents, 963 terminals, 0 unknown
bridge working set: 79.458 MiB
bridge handles: 424
content_hash: 6dc0196659991c1e2dc477ce3cd267c82e1621a4bf6f55904b36ecee8e5a724c
```

This run exceeds the previous 672 committed edits that preceded the
timeout/unknown failure. All 960 write transactions committed.

One command socket emitted a WebSocket keepalive-close stack trace during a
deliberate reconnect at request 200. The affected worker reconnected and no
command failed. This is retained as operational noise rather than hidden.

Evidence:

- `output/_p4_real_bridge_write_soak_round3/figma_bridge_soak.json`
- `output/_p4_server_paced_real_soak_round1/bridge-journal.jsonl`
- `output/_p4_server_paced_real_soak_round1/bridge.stderr.log`

### Unthrottled Multi-client Run

Deterministic harness:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe `
  scripts\bridge_write_backpressure_soak.py `
  --out output\_p4_write_backpressure_round2 `
  --requests 320 `
  --workers 16 `
  --max-write-queue 16 `
  --min-write-interval-ms 5 `
  --write-queue-timeout 2 `
  --plugin-latency-ms 2
```

Result:

```text
status: pass
completed: 320/320
safe rejections: 0
failed: 0
unknown: 0
max plugin write inflight: 1
min dispatch gap: 15ms
duration: 5.386s
p50 / p95 / p99: 266.656 / 300.854 / 321.405ms
journal: 640 events
content_hash: ac1ca01c1cacc6dccd16249667414a5eb04d99b30cbcb36c7422911168c346f2
```

### Deliberate Saturation

The stress run intentionally allowed only four admitted writes for 16 retrying
clients:

```text
status: pass
completed: 240/240
safe rejections: 32,218
safe same-request-id retries: 32,218
failed: 0
unknown: 0
max plugin write inflight: 1
duration: 3.922s
p50 / p95 / p99: 66.405 / 91.793 / 3891.153ms
journal: 480 events
content_hash: 6324c72e4965e96523dcde36b5808e618c24e30119d88eb963f0c15488b54bb7
```

The long p99 is expected under deliberate four-slot saturation and is not
reported as good latency. The important result is that saturation became a
retryable, not-applied response instead of a plugin-side timeout/unknown.

Evidence:

- `output/_p4_write_backpressure_round1/write_backpressure_soak.json`
- `output/_p4_write_backpressure_round2/write_backpressure_soak.json`
- `scripts/bridge_write_backpressure_soak.py`
- `output/_r5_p3_client_fairness_round1/r5_p3_client_fairness.json`
- `scripts/r5_p3_client_fairness_probe.py`

## 5. Timer Finding

The first implementation used one `asyncio.sleep(remaining)`. On Windows, a
20ms target occasionally woke after 15-16ms, producing a shorter than configured
dispatch gap. The gate now wakes in a loop and rechecks `time.monotonic()` until
the absolute `not_before` deadline is reached.

The soak still observes roughly 15-16ms as the effective Windows event-loop
floor for a 5ms target. The default 50ms interval remains above this floor.

## 6. Boundary

The deterministic evidence uses the production `BridgeHub` with a fake plugin.
The real run proves 60 seconds of paced Figma writes for this plugin build. It
does not prove:

- 24h/7d real Figma behavior under the new server-side policy;
- 24h/7d writer endurance;
- Internet-scale latency SLOs or multi-process fairness;
- TLS, `/plugin` authentication, multi-document routing, or cross-host
  fencing;
- write attribution under concurrent collaborators;
- correctness when a collaborator changes the same node while a write waits.

The new deterministic probe proves bounded per-client admission and token
bucket isolation inside one bridge process. It does not replace real Figma
permission/rate-limit/user-takeover runs or cross-host fairness evidence.

The next live step is a staged 1h / 24h / 7d run with resource and error
classification. A single 60-second pass is not long-duration admission.
