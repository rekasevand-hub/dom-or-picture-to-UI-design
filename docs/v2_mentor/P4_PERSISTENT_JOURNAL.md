# P4 Persistent Idempotency and Transaction Journal

> Date: 2026-10-21  
> Status: `exclusive-single-instance-persistent-recovery-and-readback-pass`  
> Scope: durable idempotency cache, write-ahead command intents, transaction
> terminal states, restart recovery, bounded compaction, exclusive file lock.

## 1. Journal

The bridge persists idempotency and transaction state in JSONL:

```text
output/_bridge_state/bridge-journal.jsonl
```

Override with:

```text
FIGMA_BRIDGE_JOURNAL=<path>
```

Use `off`, `memory`, `none`, or `disabled` to run without persistence.

Every command with a stable `requestId` appends an `intent` record before the
plugin send, including:

- `clientId` and `requestId`;
- canonical payload fingerprint;
- action;
- optional `transactionId`;
- timestamp.

The bridge appends a `terminal` record after a successful response, timeout, or
disconnect. Every append is flushed and `fsync`ed. Request params and file
payloads are not written to the journal.

## 2. Recovery Semantics

On startup:

- completed terminal records within idempotency TTL are replayed without
  contacting Figma;
- a persisted fingerprint conflict still returns `IDEMPOTENCY_KEY_CONFLICT`;
- an `intent` without a terminal record becomes `REQUEST_OUTCOME_UNKNOWN` with
  `outcome=unknown`, preventing blind replay;
- `apply_batch` and `apply_edit_batch` transaction states are restored from the
  terminal response, including `committed`, `rejected`, `rolled-back`,
  `rollback-incomplete`, and `unknown`;
- torn or malformed trailing JSONL records are ignored while earlier valid
  records remain recoverable.

The recovery result does not prove what Figma actually committed. It proves
that the bridge must report the write as unknown rather than risk a duplicate.

### Unknown Transaction Readback

For `apply_edit_batch`, the intent stores only the target node IDs extracted
from action params. When the bridge restarts and the plugin reconnects:

1. unknown transactions with targets are selected;
2. `get_node_tree` is sent for each target;
3. results or per-node errors are appended as a `readback` journal event;
4. the transaction state remains `unknown`.

This provides authoritative Figma readback evidence without claiming that the
write committed. `bridge_transaction_status` returns the state, target IDs,
readback payload, readback timestamp, and intent-match classification.

For `set_text`, `set_name`, and visibility edits, the intent stores expected
checks without raw text or names:

- SHA-256 of expected `characters`;
- SHA-256 of expected `name`;
- explicit expected boolean for visibility.

After readback, the bridge reports:

- `matches-intended`;
- `partial-match`;
- `does-not-match-intended`;
- `indeterminate`.

These values describe whether the current document matches the hashed intent.
They do not prove commit attribution when another collaborator could have made
the same change.

## 3. Bounds

Journal growth is controlled by:

- `max_cache_entries`, default `1024`;
- `max_journal_events`, default `4096`;
- idempotency TTL, default `60s`.

When the event threshold is exceeded, the journal is rewritten atomically from
the current pending intents, completed cache, and transaction terminal states.

The production bridge also owns:

```text
output/_bridge_state/bridge-journal.jsonl.lock
```

The lock uses `msvcrt.locking` on Windows and `fcntl.flock` on POSIX. It is
acquired before journal replay and held for the bridge process lifetime. A
second bridge using the same journal fails closed before opening the network
port.

Write admission happens before an intent is appended. A request rejected by
the bounded write queue or queue-wait timeout returns
`BRIDGE_WRITE_BACKPRESSURE/not-applied` and leaves no sent-write intent. Only
the write holding a dispatch slot appends the intent and sends to the plugin.

## 4. Verification

`tests/v2/test_bridge_protocol.py` now covers:

- completed idempotency replay after hub recreation;
- fingerprint conflict after restart;
- interrupted intent recovery as `REQUEST_OUTCOME_UNKNOWN`;
- transaction terminal-state recovery;
- malformed trailing journal records;
- bounded compaction;
- exclusive journal lock and release/reaquisition;
- automatic unknown-transaction readback, intent-match classification, and
  local status query;
- sensitive expected text/name values are stored only as hashes;
- real loopback WebSocket round trip and existing concurrency behavior.

Current protocol test result: `35/35 passed`.

Real bridge restart smoke:

- `clientId=p4-journal-smoke-client`;
- `requestId=p4-journal-restart-20261021-2242`;
- first `font_report` call used Figma and completed in `46.042ms`;
- after stopping and restarting the bridge, the same request returned in
  `0.680ms`;
- the restarted bridge log contained the Python command but no second plugin
  response, proving the result came from the journal;
- the production journal contained one `intent` and one `terminal` record.

Real process-lock smoke:

- the first bridge acquired the journal lock and served the plugin;
- a second bridge process failed with `JournalLockError` before listening;
- after stopping the first bridge, the next process acquired the same lock and
  started normally.

Real status-query smoke:

```text
transactionId: p3-runtime-fault-injection
state: rolled-back
recovered: true
```

The query was served by the bridge from the persisted journal without routing
the status request to the Figma plugin.

1000-request soak:

```text
1000/1000 completed
pending=0, scope_pending=0
cache=128, journal=180/256
restart replay=128
533.919 requests/s
peak traced heap=2.077 MiB
```

See `P4_JOURNAL_SOAK.md`.

Two consecutive 60-second real Figma readback rounds:

```text
requests=50,136
failed=0
round-1 RSS=81.875 MiB, handles=396
round-2 RSS=80.707 MiB, handles=388
journal=1,978 events after compaction
```

See `P4_REAL_FIGMA_SOAK.md`.

## 5. Remaining Boundary

The journal enforces one bridge process per local journal file. It does not yet
provide:

- cross-host fencing or network-filesystem lock guarantees;
- multi-host journal replication;
- commit attribution under concurrent collaborators;
- expected-state checks for image fills and every layout mutation;
- 24h/7d real Figma RSS and plugin-renderer leak observation;
- a power-loss test at the filesystem/hardware level;
- multi-document tenant routing.
- real Figma revalidation of the new server-side write pacing policy;

Do not describe this as distributed idempotency or automatic write recovery.
The safe rule remains: an unknown outcome is not automatically replayed.
