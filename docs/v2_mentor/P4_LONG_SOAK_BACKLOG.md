# P4 24h/7d Long Soak Backlog

> Recorded: 2026-10-21  
> Status: `deferred / waiting-for-user-cloud-server`  
> Owner: user-operated cloud environment  
> Current action: do not start a local 24h/7d run

## 1. Decision

The 24h and 7d Figma soak runs are intentionally deferred. The user will run
them later on a cloud server. This document preserves the planned scope,
required environment, evidence contract, and admission boundaries.

This deferral does not close RR-009 or any long-duration production claim.

## 2. Environment Requirements

The cloud host must provide:

- an interactive Windows desktop session capable of running Figma Desktop;
- the same Figma development plugin build used by the 60-second real run;
- a logged-in Figma account with access to the owned probe document/page;
- the project worktree or an exact patch/bundle containing the tested commit;
- persistent disk for `output/` and the bridge journal;
- a stable loopback bridge port, default `8765`;
- a supervisor that restarts the bridge after a crash and records restart time;
- periodic collection of bridge process RSS, private bytes, handle count, and
  journal size;
- either manual collection of Figma renderer memory or plugin-side
  instrumentation. The bridge cannot currently measure Figma renderer memory.

Do not expose the current `/plugin` endpoint to the Internet. TLS,
`/plugin` authentication, and cross-host fencing remain unclosed.

## 3. Required Pre-Run Work

Before starting the 24h stage:

1. Freeze the bridge write-policy values and plugin build identity.
2. Define a run id and evidence directory, for example:

   ```text
   output/_p4_cloud_soak_24h/<run-id>/
   output/_p4_cloud_soak_7d/<run-id>/
   ```

3. Record baseline bridge RSS, private bytes, handles, journal lines/bytes, and
   free disk.
4. Confirm there are no unexplained pending or unknown transactions.
5. Confirm the probe owns only its named root and cleanup is scoped.
6. Run the 1h staged pilot first. Do not jump directly to 7d.
7. Define abort thresholds before the run. Do not tune them after observing a
   failure.

## 4. Run Commands

Before the staged run, create or edit the single bridge config file with a
dedicated journal and frozen write policy:

```text
figma_bridge.config.json
  server.journal_path = D:\figma_soak\journal\bridge-journal.jsonl
  server.write_pacing.min_interval_ms = 50
  server.write_pacing.queue_timeout_seconds = 5
  server.write_pacing.max_queue = 16
```

Then start the normal command without bridge environment variables:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m src.app.services.bridge_server
```

Staged write soak shape:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\figma_bridge_soak_probe.py `
  --out output\_p4_cloud_soak_24h\<run-id> `
  --duration 86400 `
  --concurrency 4 `
  --reconnect-every 100 `
  --mode write `
  --sleep-ms 0 `
  --journal D:\figma_soak\journal\bridge-journal.jsonl
```

For 7d, use a separate evidence directory and duration `604800`. Run the same
monitor and checkpoint policy.

## 5. Checkpoints

| Stage | Minimum checkpoints |
|---|---|
| 1h pilot | 5m, 15m, 30m, 60m |
| 24h | 1h, 6h, 12h, 24h |
| 7d | daily, plus 24h/72h/168h summaries |

At each checkpoint retain:

- completed requests, failed requests, safe backpressure rejections, retries;
- timeout and unknown counts;
- p50/p95/p99/max latency;
- bridge RSS/private bytes/handles;
- journal line count, byte size, and last successful compaction;
- plugin reconnect count and bridge restart count;
- Figma renderer memory if instrumentation is available;
- host free disk and any OS-level warnings.

## 6. Admission Criteria

A stage is admissible only when:

- every request is completed or explicitly classified;
- no unknown outcome remains unexplained;
- safe backpressure retries use the same `clientId + requestId`;
- journal size remains bounded and replay does not duplicate writes;
- bridge RSS and handles show no convincing unbounded monotonic growth;
- reconnect/restart behavior is recorded rather than omitted;
- the owned probe root is removed and cleanup leaves no probe node;
- the report explicitly states whether Figma renderer memory was measured.

Passing 24h does not imply 7d admission. Passing either stage does not close
multiplayer attribution, cross-host fencing, TLS, or `/plugin` authentication.

## 7. Evidence Bundle

Preserve:

- the final `figma_bridge_soak.json` and its content hash;
- `bridge-journal.jsonl`, journal lock metadata, bridge stdout/stderr;
- checkpoint CSV/JSON and host metrics;
- bridge process id/start-stop timestamps;
- Figma/plugin build identity and write-policy values;
- failure screenshots or logs, if any;
- a closeout summary with pass/fail and residual limitations.

## 8. Current State

- Local short real run: 960/960 committed in 60 seconds, zero unknown.
- 1h pilot: not run.
- 24h: not run, deferred to user cloud server.
- 7d: not run, deferred to user cloud server.
