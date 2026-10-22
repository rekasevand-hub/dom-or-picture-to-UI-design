# P4 Persistent Journal Soak

> Date: 2026-10-21  
> Status: `1000-request-journal-soak-pass`  
> Scope: concurrent BridgeHub command path, fsync journal, cache eviction,
> compaction, and restart replay.

## 1. Run

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe `
  scripts\bridge_journal_soak.py `
  --out output\_p4_journal_soak_round1 `
  --requests 1000 `
  --concurrency 32 `
  --max-cache-entries 128 `
  --max-journal-events 256
```

The harness uses the real `BridgeHub`, persistent JSONL journal, fsync append,
cache eviction, compaction, and a deterministic echo plugin. It does not execute
Figma Plugin API calls.

## 2. Result

```text
status: pass
requested: 1000
completed: 1000
failed: 0
pending: 0
scope_pending: 0
cache_entries: 128
journal_events: 180 (limit 256)
replay_cache_entries: 128
requests_per_second: 533.919
peak_traced_memory: 2.077 MiB
content_hash: 18ea48c20c3fa8c7941b04dfdc9341f7e54fd43a13429c4942901d4c9846bd6d
```

Evidence:

`output/_p4_journal_soak_round1/bridge_journal_soak.json`

## 3. Checks

- every request completed with the expected echo/index;
- pending and scope-pending maps returned to zero;
- idempotency cache stayed at its configured bound;
- compacted journal stayed below its event limit;
- a new hub reconstructed 128 completed entries from the same journal;
- traced Python heap peak stayed bounded for this run.

## 4. Boundary

This is a deterministic short-duration soak, not a production endurance test.
The follow-up real Figma run is documented in `P4_REAL_FIGMA_SOAK.md`.
Still open:

- 24h/7d process RSS and connection leak observation;
- real Figma plugin latency and failure injection under sustained load;
- filesystem power-loss behavior;
- network filesystem and multi-host journal behavior.
