# R5 Production Reassessment

> Date: 2026-10-22  
> Status: `r5-p3-current-scope-complete / real-timeout-resume-pass / namespace-slice-pass / client-identity-slice-pass / file-config-slice-pass / client-fairness-slice-pass / tls-slice-pass / plugin-auth-slice-pass / revocation-reconnect-slice-pass / secret-lifecycle-pass / attribution-boundary-pass / ledger-lifecycle-pass / production-not-admitted`  
> Scope: remap the 2026-10-19 R5 production blockers to the current P1-P4
> implementation and close the first production-admission namespace gap.

Execution plan: `R5_P3_EXECUTION_PLAN.md`.

Gate inventory and verification vocabulary: `R5_GATE_MATRIX.md`.

Final 2026-10-22 admission review: `R5_PRODUCTION_ADMISSION_DECISION.md`.
Decision remains `not-admitted`; the P5 real rehearsal, fixed-registry pilot
and 1h/24h/7d cloud soak are not executed.

`current-scope` records bounded implementation evidence. It does not promote a
claim to `pilot-verified`, `verified-for:<scope>` or `production-admitted`.

## 1. Decision

R5 experiments remain closed for current scope, but the production backlog was
stale in several bridge areas. The current bridge already provides persistent
idempotency, rename/visibility, node removal, and parent fail-closed behavior,
so R5-P3 is no longer fully blocked by missing bridge commands.

R5-P3 is now partially unblocked. The first missing ownership primitive is
implemented at current scope:

- created nodes receive persistent plugin-data ownership markers;
- cleanup requires both owner and job id to match;
- nodes from another owner or another job are not removed;
- missing ownership marker support fails the creation transaction closed.
- owned job ids are scoped by `clientId`, so two clients can use the same raw
  id without sharing a bridge transaction or plugin marker.
- when configured, per-client tokens bind the claimed `clientId` before any
  cache, namespace, write admission, or plugin dispatch.
- bridge server and default-client settings are loaded from one schema-validated
  JSON file instead of a bridge-specific environment-variable command.
- per-client admitted-write caps and token buckets prevent one client from
  monopolizing the global queue while preserving single-plugin-writer dispatch.
- the same config file can enable verified server/client TLS with optional CA
  and client-certificate support.
- `/plugin` can require a first-frame token; the Figma UI stores URL/token in
  clientStorage and never places the token in the WebSocket URL.
- token rotation revokes the active plugin; wrong candidates cannot displace
  it; TLS + auth reconnect is exercised end to end.
- collaborator attribution is explicitly unavailable and never inferred from
  matching current state.
- secrets can use env/file references; direct secrets can require private file
  permissions; config rotation is atomic and validated.
- the business ledger now has schema-validated retention configuration,
  atomic terminal-history compaction, and explicit legacy client migration.

This does not make R5-P3 production-ready. Certificate/token lifecycle,
multiplayer attribution, region-level ownership mapping, and real
permission/rate-limit tests remain open.

## 2. Slice Status

| Slice | Previous status | Current reassessment |
|---|---|---|
| `P0-CONTRACT-CORE` | implemented current scope | unchanged, not default-path integrated |
| `P1-EVIDENCE-ADAPTER` | diagnostics/current canonical-output work | partial productionization; visual and cross-environment gates remain |
| `P2-PARTIAL-DELIVERY` | blocked by detector status | still blocked by real detector/coverage evidence |
| `P3-WRITE-LEDGER-RESUME` | blocked by bridge capabilities | current-scope ledger/resume, namespace, lifecycle retention and legacy migration implemented; production-not-admitted |
| `P4-PERSISTENCE-OPERATIONS` | blocked by storage policy | still blocked by backend, permission, TTL and migration decisions |
| `P5-PILOT-E2E` | blocked by P0-P4 | still blocked |

## 3. R5-P3 Blocker Remap

| Previous blocker | Current capability | Status |
|---|---|---|
| Service-side idempotency | JSONL write-ahead intent, fingerprint conflict, completed replay, timeout unknown | implemented current scope |
| Reliable ownership marker | `figma_auto_agent.owner` and `figma_auto_agent.job_id` plugin data | implemented current scope, deterministic |
| Node-level deletion | Existing broad `remove_nodes_by_name`; new exact `cleanup_owned_job` | implemented current scope |
| Visibility / rename | `set_visibility` / `set_name` plus transaction rollback | implemented current scope |
| Missing parent | `PARENT_NOT_FOUND` before attach | fail-closed and tested |
| Resume after send | Durable ledger, unknown ownership readback, reconcile-no-resend, real controlled-timeout evidence | implemented current scope |
| Region compensation | Edit/create rollback and exact job cleanup exist | region-level ownership mapping and policy still open |
| Real permission/rate-limit/user takeover | Not exercised | open |
| Same-name and multiplayer concurrency | Not resolved | open |
| Cross-client raw job-id collision | Deterministic `clientId` namespace plus optional per-client token binding | implemented current scope when client tokens are configured; default remains anonymous |
| Ledger retention/migration | Strict `ledger` config, atomic terminal-history compaction, explicit client mapping and dry-run migration | implemented current scope; cross-process fencing and marker/journal migration remain open |

## 4. First R5-P3 Slice

Plugin-data marker contract:

```text
figma_auto_agent.owner  = figma_auto_agent
figma_auto_agent.job_id = r5job:v1:<base64url-client>:<base64url-raw-job>
```

Creation behavior:

1. `apply_batch` requires a non-empty `transactionId`.
2. Every successfully created node is marked before the action is considered
   complete.
3. Marker failure triggers rollback of nodes already created in that batch.
4. A committed response includes an `ownership` receipt with marker version,
   owner, job id, and marked count.

Cleanup behavior:

1. `cleanup_owned_job` requires an explicit `jobId`.
2. Traversal is read-only until nodes are collected.
3. A node is removed only when both owner and job markers match.
4. The response reports `matched`, `removed`, and per-node failures.
5. Different owner and different job nodes remain untouched.

Adapter:

### Global Ownership Job Namespace

The plugin-visible ownership id is now a deterministic, versioned namespace:

```text
r5job:v1:<base64url(canonical-clientId)>:<base64url(canonical-rawJobId)>
```

Properties:

- canonical unpadded base64url components round-trip exactly, including
  Unicode and separator characters;
- parser validation rejects non-canonical segments, unknown versions,
  padding, empty components, and client mismatch;
- `OwnedBatchCoordinator` generates the namespace before ledger append and
  plugin dispatch;
- the business ledger schema v2 stores `raw_job_id` and
  `namespace_version`, while retaining schema v1 read compatibility;
- BridgeHub still keys idempotency by `(clientId, requestId)` and stores the
  canonical id as the global transaction key;
- max-length canonical ids use a stable SHA-256-derived request id when they
  exceed BridgeHub's 256-character request-id limit;
- an existing canonical transaction cannot be re-dispatched under a different
  request id; BridgeHub returns `TRANSACTION_ID_CONFLICT` before plugin send;
- adapter, BridgeHub, and ledger reject bare ownership ids by default;
- `allow_legacy_job_ids=True` is the explicit compatibility path for old
  bridge/ledger/marker state; standalone bridge startup accepts the same
  opt-in through `FIGMA_BRIDGE_ALLOW_LEGACY_JOB_IDS=1`. New writes should not
  use it.

Deterministic namespace evidence:

```text
status: pass
jobs: 7
cross-client raw id: shared-raw
client-a canonical: r5job:v1:Y2xpZW50LWE:c2hhcmVkLXJhdw
client-b canonical: r5job:v1:Y2xpZW50LWI:c2hhcmVkLXJhdw
distinct: true
plugin writes: 2
duplicate side effects: 0
report content hash: 813428fe2c380a104650c1d1ab67d8951adcbb3b8a8cbe1d7ec8ca516a0f190e
```

Evidence:

- `output/_r5_p3_namespace_round1/r5_p3_resume_soak.json`

This closes accidental collisions between distinct `clientId` values. The
namespace layer alone does not prevent a caller from claiming another client's
`clientId`; the following token-binding layer addresses that when configured.

### Authenticated Client Identity

The bridge can bind the namespace identity to a server-known per-client token:

```json
{
  "server": {
    "client_tokens": {
      "client-a": "<secret-a>",
      "client-b": "<secret-b>"
    }
  },
  "client": {
    "client_id": "client-a",
    "client_token": "<secret-a>"
  }
}
```

The adapter sends:

```text
X-Figma-Client-Id: <clientId>
X-Figma-Client-Token: <per-client-secret>
```

When the bridge mapping is configured, identity is checked before idempotency,
namespace validation, write admission, or plugin dispatch:

```text
missing headers:          CLIENT_IDENTITY_REQUIRED
header/payload mismatch:  CLIENT_IDENTITY_MISMATCH
wrong or unknown token:   CLIENT_IDENTITY_INVALID
valid binding:            command proceeds
```

The shared optional `FIGMA_BRIDGE_TOKEN` remains independent. With no
per-client mapping, the existing local anonymous development behavior remains
unchanged. Tokens use constant-time comparison and are not written to the
bridge journal.

Deterministic evidence:

```text
status: pass
missing/wrong/mismatch/valid checks: pass
journal secret absent: true
report content hash: 3289725b55042212dc6c9756db4cda06b6727e8155cc8ceffd337452ba3008e0
file SHA-256: 2cc9c8dc7dc7ceb5f248a556c961597cc0f1044be5bccaae5e7c1146f1ad5230
```

Evidence:

- `output/_r5_p3_client_identity_round1/r5_p3_client_identity.json`

This closes namespace spoofing for correctly deployed configurations. It does
not make the default anonymous mode production-authenticated, encrypt the
connection, authenticate `/plugin`, or provide token rotation.

### File-backed Configuration

`figma_bridge.config.json` is the normal source of truth for:

- server host/port, timeout, idempotency TTL and journal;
- message/cache/journal bounds and exclusive lock;
- shared and per-client authentication;
- legacy ownership opt-in;
- business-ledger path, bounds, terminal retention and legacy-read policy;
- write pacing;
- default client URL, timeout, identity and auth.

The command is now the ordinary:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe -m src.app.services.bridge_server
```

No `FIGMA_BRIDGE_*` environment variables are required. The config has
`allow_env_overrides: false` by default; environment values are ignored unless
that setting is explicitly changed to `true`.

Validation is fail-closed for unknown fields, invalid types, invalid ports,
empty client tokens, malformed client URLs, and non-positive bounds. Relative
journal and ledger paths resolve against the config file directory.

`FIGMA_BRIDGE_CONFIG` can select an alternate file for tests or isolated runs,
but it is not required for normal operation. Controlled-timeout probe
subprocesses generate sanitized runtime config files instead of passing secrets
or policy through environment variables.

### Per-client Admission and Fairness

The bridge now applies per-client limits before journal intent and plugin send:

```json
{
  "server": {
    "client_write_defaults": {
      "max_inflight": 4,
      "burst": 4,
      "min_interval_ms": 0
    },
    "client_write_limits": {}
  }
}
```

- `max_inflight` caps active plus waiting writes for one verified `clientId`;
- token buckets cap bursts and refill at `min_interval_ms`;
- waiting for client tokens does not hold the global dispatch lock;
- the global single-writer, global interval and idempotency cache remain
  authoritative;
- rejection is `BRIDGE_CLIENT_RATE_LIMITED/not-applied` before intent creation.

Deterministic evidence:

```text
status: pass
other client completed: true
rejected before transaction intent: true
burst-limited client deferred: true
content hash: 7e06cc0f77028842b9fa3553d2e3ffcdc3d934d59cead73c94525c9525ce3877
file SHA-256: eece42ad6824b06f575a6582be1e5375b007825e7cfd2b095945a4ded944380e
```

Evidence:

- `output/_r5_p3_client_fairness_round1/r5_p3_client_fairness.json`

This closes bounded in-process fairness for configured clients. Real Figma
rate-limit behavior, multi-process fairness, collaborator races and cross-host
fencing remain open.

### TLS and wss Transport

Server and client TLS settings live in `figma_bridge.config.json`. Enabled
server TLS requires existing cert/key files; client TLS requires `wss://` and
supports custom CA and optional mutual-TLS cert/key.

The server constructs an `SSLContext` from the file. The adapter passes
`sslopt` to websocket-client. A real local loopback handshake and round trip
pass.

Deterministic evidence:

```text
status: pass
handshake: true
round trip: true
content hash: 9ce4eae23a2aaa5b131ecca7a30df04044952ee52ce98d663e249df633364a8c
file SHA-256: 8c1972d1e9e2e82563cb1bf60bf2419da7aa676c6abd73413bbb6428f10327f1
```

Evidence:

- `output/_r5_p3_tls_round1/r5_p3_tls_probe.json`

TLS is not enabled by default. Production certificate provisioning/rotation,
system trust-store integration, `/plugin` authentication and a full TLS rerun
of timeout/write-pacing scenarios remain open.

### Plugin Socket Authentication

`server.plugin_token` in `figma_bridge.config.json` controls `/plugin`
authentication. When configured:

```json
{"type": "auth", "token": "<plugin-secret>"}
```

must be the first WebSocket frame. Missing/wrong tokens receive
`PLUGIN_AUTH_FAILED` and close code `4003` before attachment. Successful auth
returns `{"type":"auth-ok"}`.

The Figma plugin UI now exposes bridge URL and plugin token fields and persists
them through `figma.clientStorage`. The token is not put in the URL or bridge
journal.

Deterministic evidence:

```text
status: pass
missing/wrong rejected: true
valid accepted: true
optional mode unchanged: true
old token rejected after rotation: true
new token accepted: true
content hash: 86a1859a1f17ca2588f7c27bf789d11fd8dcfab3630dd58a522876df86c80027
file SHA-256: 9afb37f9528f902d0ad53b4364dbffb78798fea32b2fbf59b175d10279069f4c
```

Evidence:

- `output/_r5_p3_plugin_auth_round2/r5_p3_plugin_auth.json`

This closes the code-level open `/plugin` socket. The following sections cover
active-token revocation, real Figma UI save/reopen, combined TLS+auth reconnect
and attribution boundaries.

### Revocation and Real Figma UI Reopen

`server.plugin_token_recheck_seconds` polls the latest token. When it changes or
is removed, the active plugin is closed with code `4004`. A wrong candidate
cannot replace the current plugin; a valid candidate can.

The real Figma development plugin UI was exercised:

1. test token entered and saved through `figma.clientStorage`;
2. plugin connected;
3. plugin window closed;
4. plugin reopened through Figma quick actions;
5. token restored and plugin reconnected.

Evidence:

- `output/_r5_p3_real_plugin_ui_round1/figma_ui_config_probe.json`
- content hash:
  `ca22cb3475c5d641231db7a7d6e1ca3cffe98e66402c0797d637f22a77a73d64`
- screenshot:
  `output/_r5_p3_real_plugin_ui_round1/plugin_ui_reopened.jpg`
- cleared token:
  `output/_r5_p3_real_plugin_ui_round1/plugin_ui_token_cleared.jpg`

The test token was cleared from config and clientStorage afterward.

### Operator Revocation UX and Secret Lifecycle

The UI now distinguishes:

- `4004`: token rotated/revoked; stop reconnect and request a new token;
- `4003`: authentication failure; stop reconnect;
- ordinary close: bounded automatic reconnect.

Secret management now supports:

- `env:VARIABLE`;
- `file:relative-or-absolute-path`;
- `security.require_secret_references`;
- `security.require_secure_file_permissions`;
- POSIX mode checks and conservative Windows `icacls` checks;
- atomic rotation via `scripts/rotate_figma_bridge_config.py`.

Real Figma exercise:

```text
old token connected
config rotated while bridge was running
active plugin closed with 4004
UI showed revoked and stopped old-token retry
new token saved
plugin reconnected
test token cleared afterward
```

Evidence:

- `output/_r5_p3_real_plugin_revocation_round2/figma_ui_revocation_probe.json`
- content hash:
  `18a460f0f1f2666bc1b3d95e819958bbdd8d89fb539bb70b3c5d1cac0db12af0`

### Combined TLS, Auth and Rotation

A real local wss server exercised TLS handshake, plugin first-frame auth,
command round trip, old-token revocation and new-token reconnect.

```text
status: pass
tls/auth/round-trip/revocation/reconnect: all true
content hash: 86151a9ef89b4f05904cadbedd218ae863be1420736ddeb242459df26b92b722
file SHA-256: 9f72ca1c5596b7553705e0bbafd6034b6d399423756877078ee7fd5c992660f2
```

Evidence:

- `output/_r5_p3_tls_plugin_auth_round2/r5_p3_tls_plugin_auth.json`

### Multiplayer Attribution Boundary

Transaction payloads now declare:

```json
{
  "attribution": {
    "status": "unavailable",
    "actor": "unknown",
    "revision": "unknown"
  }
}
```

Matching readback can reconcile current state without resend, but it cannot
prove which collaborator caused the write. The transaction remains unknown.
The `AttributionProvider` contract is the future extension point; the default
provider always reports unavailable and any provider error fails closed.

Evidence:

- `output/_r5_p3_multiplayer_attribution_round2/r5_p3_multiplayer_attribution.json`
- content hash:
  `284022e78d14a3951e0402abc0004b92adace1d6f04b5f6164873ae0e2a1f164`

Real two-human attribution remains unavailable because the Figma Plugin API
does not expose an authoritative actor/revision source.

```python
adapter.cleanup_owned_job(job_id)
adapter.ownership_report(job_id)
```

Resumable real Figma probe:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe `
  scripts\figma_ownership_marker_probe.py `
  --out output\_r5_ownership_marker_round1 `
  --phase create

# Reload the development plugin or close/reopen the document.

C:\Users\lzq\.conda\envs\omni\python.exe `
  scripts\figma_ownership_marker_probe.py `
  --out output\_r5_ownership_marker_round1 `
  --phase verify

C:\Users\lzq\.conda\envs\omni\python.exe `
  scripts\figma_ownership_marker_probe.py `
  --out output\_r5_ownership_marker_round1 `
  --phase cleanup
```

## 5. Verification

Tests cover:

- ownership markers on every created node;
- committed ownership receipt;
- exact cleanup of the requested job;
- retention of a same-job node with a different owner;
- retention of a same-owner node with a different job;
- rejection of empty cleanup job id;
- creation rollback still passing after marker integration;
- adapter command payload;
- namespace round-trip, canonical validation, and legacy rejection;
- create/ledger/resume/cleanup always use the canonical id;
- two clients using the same raw id produce distinct bridge transactions and
  distinct ledger records;
- bridge journal replay retains both same-raw cross-client transactions.
- client identity tokens are required when configured and are absent from the
  journal;
- missing, wrong, header/payload-mismatched, and valid per-client identities
  are covered deterministically.
- terminal retention compacts only expired terminal history and preserves every
  protected nonterminal state;
- compaction candidate validation and replace-failure behavior preserve the old
  ledger;
- legacy migration dry-run, atomic apply, same-raw cross-client mapping,
  conflict failure, and sanitized reports are covered.

Relevant evidence:

- `tests/bridge/test_ownership_marker_cleanup.js`
- `tests/bridge/test_batch_rollback.js`
- `tests/v2/test_figma_bridge_text_metrics.py`
- `tests/v2/test_figma_adapter_edits.py`
- `tests/v2/test_job_namespace.py`
- `tests/v2/test_write_job_ledger.py`
- `tests/v2/test_write_job_ledger_lifecycle.py`
- `tests/v2/test_migrate_write_job_ledger_cli.py`
- `tests/v2/test_r5_p3_ledger_lifecycle_probe.py`
- `tests/v2/test_bridge_protocol.py`
- `scripts/figma_ownership_marker_probe.py`
 
Focused regression: `55 passed`.  
Protocol tests: `33 passed`.  
Full Python suite: `342 passed`.  
Bridge Node scripts: 15/15 passed.

Revocation/reconnect/secrets/UI/attribution rerun: `412 passed`; Node bridge scripts: 17/17 passed.

Ledger lifecycle rerun: `431 passed`; Node bridge scripts: 17/17 passed.

### Real Figma Session Result

The current development plugin loaded the new actions and the three probe
phases passed in one real Figma session:

```text
job id: r5-ownership-marker-20261022
created: FRAME 46:6, RECTANGLE 46:7
create ownership receipt: marked 2
verify ownership readback: matched 2/2
cleanup: matched 2, removed 2, failed 0
post-cleanup ownership readback: matched 0
bridge journal: 14 lines, 0 unknown
bridge errors: none
```

Report hashes:

- create: `a26236a5ccc346b430121b0842107dccd653d6f21f6fe5a91c86f7a9f0a181da`
- verify: `b9f43a2b08076b40f1664073358b1dacb89a4b8fb9b7e88ad61fea1abcd58a5c`
- cleanup: `e5589b2b844789e8f2aaea3c78c607a8d80512f5befd11cf9bb2d2d5346803e6`

Evidence:

- `output/_r5_ownership_marker_round1/figma_ownership_marker_create.json`
- `output/_r5_ownership_marker_round1/figma_ownership_marker_verify.json`
- `output/_r5_ownership_marker_round1/figma_ownership_marker_cleanup.json`
- `output/_r5_ownership_marker_round1/bridge-journal.jsonl`

This proves create, readback, and exact cleanup on the real Figma document in
one session.

### Real Figma Plugin Reload Result

The retained nodes were created before a development-plugin restart:

```text
job id: r5-ownership-reload-20261022
created: FRAME 48:8, RECTANGLE 48:9
pre-reload marker readback: 2/2
post-reload marker readback: 2/2
cleanup: matched 2, removed 2, failed 0
post-cleanup readback: 0
bridge journal: 12 lines, 0 unknown
bridge errors: none
```

Report hashes:

- create: `c07563ccdfeb4d07fb9afd509351da3ded27b7eef6e5c50c3abdacb1fb75dfd7`
- post-reload verify: `8729525d34305dc6b69c88a09b2b0521647cffa4bca20a195c0c1a667d55caf0`
- cleanup: `0f2a8de6cba208521a7e78a2106529e362fd3e362bf9ee028c7f771637a1331b`

This closes marker persistence across a development-plugin reload. Document
close/reopen persistence was verified separately below.

### Real Figma Document Reopen Result

The document was saved, closed, reopened from `Recently closed`, and the
development plugin was restarted:

```text
job id: r5-ownership-reopen-20261022
created: FRAME 48:10, RECTANGLE 48:11
post-reopen marker readback: 2/2
cleanup: matched 2, removed 2, failed 0
post-cleanup readback: 0
bridge journal: 12 lines, 0 unknown
bridge errors: none
```

Report hashes:

- create: `749f35feb8c79d7128d00142fb8eaf524a23a78acf4dd76df7b41ba342903f6d`
- post-reopen verify: `a5fdeea20f37063d73e72a12ca32af5c1b9cb5bc024a69aae16032f52164cbd5`
- cleanup: `6674695989b8bfcfcfab3f74c64ffc63f331af0509b6dc596a04d2b32126ff9a`

Evidence:

- `output/_r5_ownership_marker_document_reopen_round1/figma_ownership_marker_create.json`
- `output/_r5_ownership_marker_document_reopen_round1/figma_ownership_marker_verify.json`
- `output/_r5_ownership_marker_document_reopen_round1/figma_ownership_marker_cleanup.json`
- `output/_r5_ownership_marker_document_reopen_round1/bridge-journal.jsonl`

### Unknown create-batch ownership readback

BridgeHub now stores the ownership job id and expected created-node count in the
`apply_batch` intent. If that transaction recovers as unknown after restart, the
reconnect reconciliation sends `ownership_report` and persists:

- ownership job id and expected created-node count;
- ownership readback payload;
- `matches-intended / partial-match / does-not-match-intended / indeterminate`;
- readback timestamp.

The transaction state remains `unknown`. Ownership readback supports a later
explicit resume decision but does not auto-promote the write to committed.

### Business Ledger and Resume Contract

Tasks 2-7 of `R5_P3_EXECUTION_PLAN.md` are implemented current scope:

- immutable write-job state and resume-decision contracts;
- fsync-backed JSONL business ledger referencing bridge transaction ids;
- duplicate job id/content conflict failure;
- malformed trailing-record tolerance;
- write-ahead `planned -> inflight -> terminal` coordination;
- unknown + complete ownership -> `reconcile-no-resend`;
- unknown + partial/absent ownership -> manual review;
- commit/reject/rollback terminal classification;
- job-scoped cleanup receipt and cleanup-failure escalation;
- deterministic failure-injection soak.

The deterministic soak result:

```text
status: pass
jobs: 6
committed: 1
reconciled without resend: 1
manual review: 3
duplicate job conflicts: 1
duplicate side effects: 0
plugin write calls: 1
content_hash: 227076774d5c258d1d9a4ff8bd880b5adf0240a87d041c68739d742f617cbc8d
```

Evidence:

- `output/_r5_p3_resume_round1/r5_p3_resume_soak.json`
- `src/app/services/rendering/write_job_ledger.py`
- `tests/v2/test_write_job_ledger.py`
- `tests/v2/test_r5_p3_resume_soak.py`

This proves the conservative deterministic state machine. Real controlled
timeout evidence follows; cross-host job-id uniqueness remains open.

### Ledger Retention, Compaction and Legacy Migration

`figma_bridge.config.json` now has a strict root `ledger` section:

```json
{
  "ledger": {
    "path": "output/_bridge_state/write-jobs.jsonl",
    "max_events": 4096,
    "terminal_retention_days": 30,
    "compact_min_events": 256,
    "allow_legacy_read": false
  }
}
```

`WriteJobLedger` can be built from this section. Terminal history older than
retention collapses to its latest snapshot; the latest fingerprint, resume
decision, node ids, and cleanup receipt remain available. Planned, inflight,
unknown, resume-required, and rollback-incomplete events are retained in full.

Compaction uses a same-directory temporary file, write + `fsync`, complete
candidate parse/state validation, then `os.replace`. An injected replace
failure leaves the original bytes unchanged. Torn trailing JSONL is ignored,
while corruption before the tail fails closed.

Legacy migration maps explicit legacy `client_id` values to target clients.
Two clients may use the same raw id without collision because migration groups
by `(client_id, raw job id)` before applying the namespace. Dry-run is default;
apply is atomic. Reports contain field names, counts, and source/candidate/report
hashes only. Action payloads, text, secrets, raw ids, and source client ids are
not emitted.

Deterministic evidence:

```text
status: pass
migration source events: 8
migrated jobs: 6
compaction events: 8 -> 7
protected jobs: 5
cross-client same raw id distinct: true
cleanup receipt preserved: true
duplicate fingerprint conflict preserved: true
report content hash: cd6dcef35fab8bde8eef3a74eb8cafab7cc77ff24e428edf8f7f851b5ab86cb3
report file SHA-256: 33ce9cfb0aca98a672155bffb255590a5fa868bd80f94c97cfca0000054c7c85
```

Evidence:

- `output/_r5_p3_ledger_lifecycle_round1/report.json`
- `output/_r5_p3_ledger_lifecycle_round1/migration-dry-run.json`
- `output/_r5_p3_ledger_lifecycle_round1/migration-apply.json`
- `output/_r5_p3_ledger_lifecycle_round1/compaction.json`

This closes deterministic business-ledger lifecycle behavior in one process.
It does not migrate existing Figma plugin markers or bridge journal records,
provide a cross-process compaction fence, or define eventual terminal purge.

### Real Controlled-timeout Resume Result

Task 8 used the real Figma plugin:

1. a normal bridge pre-cleaned the exact job;
2. a short-timeout bridge sent one `apply_batch` and returned
   `PLUGIN_TIMEOUT/unknown`;
3. the plugin later committed the already-sent create and wrote its marker;
4. a normal bridge restarted from the same journal and auto-read ownership;
5. the ledger produced `reconcile-no-resend`;
6. the exact job was cleaned.

Result:

```text
status: pass
bridge state: unknown
owner marker readback: matches-intended, 1/1
resume action: reconcile-no-resend
resend allowed: false
journal apply_batch intents: 1
journal unknown transactions: 1
duplicate side effects: 0
cleanup: matched 1, removed 1, failed 0
post-cleanup markers: 0
content_hash: 50704b1647c5d266517046526eaa411a9e7ff8c5e53bf23ca728522f60543d29
```

Evidence:

- `output/_r5_p3_real_resume_round4/figma_r5_p3_resume.json`
- `output/_r5_p3_real_resume_round4/bridge-journal.jsonl`
- `output/_r5_p3_real_resume_round4/write-jobs.jsonl`
- `output/_r5_p3_real_resume_round4/bridge-short-timeout.stderr.log`
- `output/_r5_p3_real_resume_round4/bridge-normal-resume.stderr.log`

## 6. Remaining Work

The next R5-P3 increments are:

1. Define certificate and token/config secret lifecycle and rotation;
   keep anonymous/cleartext mode development-only.
2. Exercise permission denial, rate limiting, user takeover, same-name
   collisions, and two-collaborator races.
3. Add cross-process ledger compaction fencing, define terminal purge policy,
   and decide whether legacy Figma markers/bridge journal records need separate
   migration.
4. Define secure storage/permissions for the config file when real secrets are
   present.

## 7. Admission Statement

Allowed:

- use marked nodes only for owned probe/job cleanup in controlled runs;
- treat marker/cleanup failure as fail-closed;
- describe R5-P3 as `completed-for-current-scope`;
- use the ledger/resume state machine for limited controlled pilots.
- use the deterministic namespace for controlled multi-client job isolation
  when each client uses a distinct configured `clientId`.
- use per-client token binding only with secret provisioning and rotation
  owned by the deployment environment.
- use configured `wss://` only with deployment-managed certificate trust and
  lifecycle.
- use configured plugin tokens with deployment-managed provisioning and
  rotation.
- use ledger compaction and legacy business-ledger migration in a controlled
  single-process run with a reviewed dry-run mapping.

Not allowed:

- claim multiplayer-safe ownership;
- claim namespace uniqueness is an authenticated security boundary;
- claim the default anonymous mode or cleartext transport is production-safe;
- claim test self-signed certificates are a production certificate-management
  strategy;
- claim configured plugin auth is complete without rotation and stale-token
  recovery validation;
- use `cleanup_owned_job` as a general-purpose deletion API;
- claim cross-process ledger compaction safety or migrate Figma markers/journal
  through the business-ledger migration tool;
- claim R5-P3 is production-admitted or `verified`;
- mark R5 experiments as `verified`.

Any future admission statement must cite the relevant `R5_GATE_MATRIX.md`
rows, environment, evidence hash and residual-risk disposition. Conditional
rows are excluded from the fixed Chromium pilot unless the product scope
explicitly adds the corresponding promise.
