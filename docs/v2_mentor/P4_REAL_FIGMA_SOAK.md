# P4 Real Figma Bridge Soak

> Date: 2026-10-21  
> Status: `readback-soak-pass / write-soak-pass-with-client-pacing / server-paced-real-60s-pass`  
> Scope: real Figma plugin, persistent bridge journal, four command
> connections, periodic reconnect, read-only `get_node_tree`.

## 1. Method

The probe creates one owned frame, then runs `get_node_tree` continuously for
60 seconds with four workers:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe `
  scripts\figma_bridge_soak_probe.py `
  --out output\_p4_real_bridge_soak_round1 `
  --duration 60 `
  --concurrency 4 `
  --reconnect-every 100 `
  --journal output\_p4_real_bridge_soak_round1\bridge-journal.jsonl
```

Each worker reconnects every 100 requests. The owned frame is removed after the
run. Measurement commands are read-only.

## 2. Results

| Round | Requests | Failed | req/s | p50 ms | p95 ms | p99 ms | max ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 24,923 | 0 | 415.343 | 9.112 | 11.698 | 15.485 | 318.687 |
| 2 | 25,213 | 0 | 420.162 | 8.970 | 11.352 | 16.032 | 374.303 |

Combined:

```text
requests: 50,136
failed: 0
duration: 120.014s
reconnect opens: 252 + 255
```

Round-2 content hash:

`21b2ec1c73da689b3156fa09d3977ba6901a0dfb365df6c8d4724849f0a55421`

## 3. Resource Observation

Bridge Python process:

| Point | Working set | Private bytes | Handles |
|---|---:|---:|---:|
| Baseline | 69.535 MiB | 529.430 MiB | not captured |
| After round 1 | 81.875 MiB | 541.562 MiB | 396 |
| After round 2 | 80.707 MiB | 540.395 MiB | 388 |

Round 2 did not increase memory or handle count relative to round 1. This does
not prove indefinite stability, but it rules out simple linear growth over the
observed 120 seconds.

After both rounds the compacted journal contained:

```text
lines: 1,978
bytes: 2,372,003
max_journal_events: 4,096
```

## 4. Real Write Transaction Soak

An unthrottled stress round with four writers reached 672 successful edits, then
all four requests at iteration 169 timed out with `outcome=unknown`. The plugin
queue later returned the delayed responses while the bridge correctly ignored
them. This showed that sustained writes require pacing; the raw round is retained
as a negative stress result.

The controlled rerun used one writer and 50ms between requests:

```text
requests: 347
failed: 0
duration: 20.025s
requests_per_second: 17.328
p50: 5.907ms
p95: 10.200ms
p99: 15.358ms
max: 31.481ms
connections opened: 4
journal events: 702
```

Each request was a one-action `apply_edit_batch(set_text)` transaction. All
returned `committed` and the owned frame was removed afterward.

The server-paced four-writer rerun used no client sleep:

```text
requests: 960
failed: 0
duration: 60.198s
requests/s: 15.947
p50 / p95 / p99: 250.273 / 262.553 / 267.832ms
unknown: 0
```

This is the real revalidation of the new bridge-side write gate. See
`P4_WRITE_BACKPRESSURE.md` for policy and evidence details.

### Server-side Write Pacing

The bridge now serializes writes globally, limits admitted writes, enforces a
minimum dispatch interval, and returns `BRIDGE_WRITE_BACKPRESSURE/not-applied`
with `retryAfterMs` before plugin dispatch. A deterministic production-hub soak
without client sleeps completed 320/320 writes with zero unknown and plugin
write concurrency of one:

```text
duration: 5.386s
requests/s: 59.414
p50 / p95 / p99: 266.656 / 300.854 / 321.405ms
max plugin write inflight: 1
unknown: 0
```

The real four-writer, no-client-sleep rerun subsequently passed 960/960. This
closes the short real revalidation only. See `P4_WRITE_BACKPRESSURE.md`.

## 5. Evidence

- `output/_p4_real_bridge_soak_round1/figma_bridge_soak.json`
- `output/_p4_real_bridge_soak_round2/figma_bridge_soak.json`
- `output/_p4_real_bridge_soak_round1/bridge-journal.jsonl`
- `output/_p4_real_bridge_write_soak_round1/figma_bridge_soak.json`
- `output/_p4_real_bridge_write_soak_round2/figma_bridge_soak.json`
- `output/_p4_real_bridge_write_soak_round3/figma_bridge_soak.json`
- `output/_p4_server_paced_real_soak_round1/bridge-journal.jsonl`
- `output/_p4_write_backpressure_round1/write_backpressure_soak.json`
- `output/_p4_write_backpressure_round2/write_backpressure_soak.json`

## 6. Boundary

This is a real Figma bridge soak, not a 24h or 7d endurance claim. Still open:

- multi-hour RSS/handle trend;
- plugin-side renderer memory;
- filesystem power loss and network filesystem behavior;
- multi-document and multiplayer workloads.

### Long-soak deferral

The 24h/7d runs are intentionally skipped for now. They are recorded as
`deferred / waiting-for-user-cloud-server` in `P4_LONG_SOAK_BACKLOG.md`.
No local long-duration run is pending.
