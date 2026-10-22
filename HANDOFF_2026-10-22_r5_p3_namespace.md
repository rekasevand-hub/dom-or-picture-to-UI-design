# HANDOFF - R5-P3 Ownership Namespace, Client Identity and Ledger Lifecycle

**Date:** 2026-10-22  
**Worktree:** `D:\LLM-Data\Figma_auto_agent`  
**Branch:** `feature/precise-agent-router`  
**Status:** `namespace-slice-pass / client-identity-slice-pass / file-config-slice-pass / client-fairness-slice-pass / tls-slice-pass / plugin-auth-slice-pass / revocation-reconnect-slice-pass / secret-lifecycle-pass / attribution-boundary-pass / ledger-lifecycle-pass / r5-p3-production-not-admitted`  
**Commit:** none; the worktree contains unrelated pre-existing changes

## 1. Scope

This slice closes accidental ownership job-id collisions between distinct
clients while preserving BridgeHub transaction semantics:

- BridgeHub idempotency remains keyed by `(clientId, requestId)`;
- the plugin-visible transaction and marker id is deterministic and
  client-scoped;
- create, ledger, resume, cleanup, and journal replay use the same canonical
  id;
- bare legacy ids fail closed by default;
- when configured, a per-client token binds the claimed `clientId` before
  cache, namespace, write admission, or plugin dispatch.
- the business ledger now supports strict retention configuration, atomic
  terminal-history compaction, and explicit legacy client migration.

It does not enter R5-P5, start a soak, or claim production admission.

## 2. Namespace Contract

```text
r5job:v1:<base64url(canonical-clientId)>:<base64url(canonical-rawJobId)>
```

Rules:

- unpadded base64url is canonical and round-trips Unicode and separators;
- `clientId` is 1..128 characters after trimming;
- raw job id is 1..256 characters after trimming;
- parser rejects unknown versions, padding, empty segments, malformed
  encoding, non-canonical encoding, and client mismatch;
- `OwnedBatchCoordinator.create_owned_batch()` accepts a raw id, generates the
  canonical id before ledger append, and dispatches only the canonical id;
- canonical ids longer than BridgeHub's 256-character request-id limit use a
  stable SHA-256-derived request id while retaining the canonical transaction;
- an existing transaction cannot be re-dispatched under a different request
  id; BridgeHub fails closed before plugin send;
- `resume_job()` and cleanup validate the canonical id against the adapter's
  configured `clientId`.

Example:

```text
client-a + shared-raw
=> r5job:v1:Y2xpZW50LWE:c2hhcmVkLXJhdw

client-b + shared-raw
=> r5job:v1:Y2xpZW50LWI:c2hhcmVkLXJhdw
```

## 3. Main Changes

- `src/app/services/job_namespace.py`: pure format/parse/validation/migration
  contract.
- `src/app/services/rendering/write_job_ledger.py`: schema v2 records
  `raw_job_id` and `namespace_version`; v1 events remain readable; default
  bare-id rejection; coordinator uses canonical ids.
- `src/app/services/bridge_server.py`: validates ownership namespaces before
  dispatch; rejects cross-client namespaces; journal replay keeps same-raw
  cross-client transactions separate; verifies configured per-client tokens
  before plugin use.
- `src/app/services/bridge_config.py` and `figma_bridge.config.json`: one
  schema-validated file for ledger, server, and client settings.
- `src/app/services/bridge_server.py`: per-client admitted-write caps and token
  buckets; limits are applied before journal intent/plugin dispatch.
- `src/app/services/bridge_config.py`: server/client TLS configuration with
  cert/key/CA and client-certificate validation.
- server `SSLContext`; adapter `sslopt` for configured `wss://`.
- `/plugin` first-frame token authentication; Figma UI stores URL/token through
  `figma.clientStorage`.
- active plugin token recheck/revocation with close code `4004`; only a valid
  new plugin may replace the active socket.
- transaction attribution is explicitly `unavailable/unknown`.
- secret references (`env:` / `file:`), config ACL policy and atomic rotation are
  implemented.
- `src/app/services/attribution.py` provides an injectable attribution-provider
  stub; the default never fabricates actor/revision.
- `src/app/services/rendering/figma_adapter.py`: `apply_batch`,
  `cleanup_owned_job`, and `ownership_report` default to canonical ids;
  `client_token` adds identity headers; client URL/identity defaults come from
  the config file.
- `scripts/r5_p3_resume_soak.py`: deterministic cross-client same-raw
  scenarios.
- `scripts/figma_r5_p3_resume_probe.py`: real probe uses one stable client id
  across preclean, controlled timeout, resume, and cleanup.
- `scripts/figma_ownership_marker_probe.py`: new manifests store both raw and
  namespaced ids; old manifests require `--allow-legacy-job-id`.
- `scripts/r5_p3_client_identity_probe.py`: deterministic proof for
  missing/wrong/mismatch/valid client identity.
- `scripts/r5_p3_client_fairness_probe.py`: deterministic proof that one client
  cannot monopolize the queue and does not block another client's burst.
- `scripts/r5_p3_tls_probe.py`: real local loopback wss handshake evidence.
- `scripts/r5_p3_plugin_auth_probe.py`: deterministic plugin socket auth evidence.
- `scripts/r5_p3_tls_plugin_auth_probe.py`: combined wss/auth/rotation/reconnect
  evidence.
- `scripts/r5_p3_multiplayer_attribution_probe.py`: attribution-boundary
  evidence.
- `scripts/rotate_figma_bridge_config.py`: atomic validated rotation.
- `src/app/services/rendering/write_job_ledger.py`: retention config, protected
  state policy, validated atomic compaction, sanitized legacy migration, and
  conflict detection.
- `scripts/migrate_write_job_ledger.py`: operator dry-run/apply CLI with an
  explicit legacy-client mapping and report-only field/count/hash output.
- `scripts/r5_p3_ledger_lifecycle_probe.py`: deterministic migration,
  compaction, protected-state, receipt, and fingerprint evidence.

## 4. Migration and Compatibility

New writes must use namespaces. There is no silent migration of old markers or
bridge journal records; business-ledger migration is explicit.

- New ledger/bridge/adapter state defaults to rejecting bare ownership ids.
- Existing pre-namespace state can be read or continued only with explicit
  `allow_legacy_job_ids=True` on the relevant component.
- The standalone bridge reads `server.allow_legacy_job_ids` from
  `figma_bridge.config.json`; the default is disabled.
- `migrate_legacy_job_id(raw_id, client_id=...)` deterministically creates a
  new namespace for new jobs.
- `scripts/migrate_write_job_ledger.py` migrates legacy business-ledger state
  only. Its mapping is legacy `client_id` -> target `client_id`; dry-run is
  default, and apply is atomic and conflict-safe.

```powershell
# dry-run (default)
python scripts\migrate_write_job_ledger.py `
  --source output\_bridge_state\legacy-write-jobs.jsonl `
  --target output\_bridge_state\write-jobs.jsonl `
  --client-map legacy-client-map.json

# apply only after reviewing the dry-run counts/hashes
python scripts\migrate_write_job_ledger.py ... --apply
```
- The existing `figma_ownership_marker_probe.py` command warns users by
  requiring `--allow-legacy-job-id` for a manifest that only contains a raw id.
- Old Figma nodes with raw marker values are not rewritten; they remain a
  legacy compatibility path, not evidence of namespace migration.

Client identity compatibility:

- no per-client token mapping preserves local anonymous
  development behavior;
- when `server.client_tokens` is configured, identity headers become mandatory;
- `server.auth_token` remains an independent optional shared Bearer token;
- per-client secrets are never persisted to journals or reports.

Central configuration:

- normal startup is `python -m src.app.services.bridge_server`;
- no bridge environment variables are required;
- `allow_env_overrides: false` is the default;
- `FIGMA_BRIDGE_CONFIG` only selects an alternate file when explicitly needed.
- TLS is disabled by default and can be enabled in the same file.
- `server.plugin_token` is empty by default; when set, plugin authentication is
  mandatory before attachment.
- `server.plugin_token_recheck_seconds` controls active connection revocation.
- UI handles `4004` as revoked and stops old-token retry.
- the config `ledger` section controls path, retention trigger, compact minimum,
  terminal retention, and explicit legacy reads.

## 5. Verification

```text
full Python suite: 431 passed
bridge Node scripts: 17/17 passed
node --check figma_bridge/code.js: pass
py_compile changed Python modules/scripts: pass
deterministic namespace soak: pass
```

Coverage includes:

- namespace round-trip and malformed input;
- default legacy rejection in adapter, BridgeHub, and ledger;
- explicit legacy bridge opt-in;
- create batch canonical dispatch;
- ledger duplicate/content conflict;
- resume and cleanup canonical ids;
- cross-client same-raw create isolation;
- bridge journal replay for both same-raw transactions.
- duplicate coordinator calls do not trigger a second plugin write;
- transaction-id reuse under a new request id fails closed;
- per-client token identity: missing/wrong/mismatch/valid;
- client identity secret absent from bridge journal.
- file-backed server/default-client config and strict validation.
- per-client admission rejection before intent and token-bucket fairness.
- configured server/client TLS and a real local wss handshake.
- plugin first-frame auth and clientStorage persistence tests.
- plugin takeover fencing and token rotation from the latest config file.
- active-token revocation, combined TLS/auth reconnect and attribution boundary.
- secret references/ACL, atomic rotation and real Figma revocation/recovery.
- terminal-only retention compaction; protected nonterminal/unknown state is
  never removed automatically.
- compaction candidate validation, fsync, `os.replace`, replace-failure
  rollback, torn-tail tolerance, and interior-corruption fail-closed behavior.
- legacy migration dry-run, atomic apply, same-raw cross-client aliases,
  explicit mapping, collision/conflict failure, and report sanitization.

Evidence:

- `output/_r5_p3_namespace_round1/r5_p3_resume_soak.json`
- report content hash:
  `813428fe2c380a104650c1d1ab67d8951adcbb3b8a8cbe1d7ec8ca516a0f190e`
- file SHA-256:
  `9574b2f769a6ceba9c5bec69287c451795cc9fe3547bde1bc68e28e3ba16d54f`
- client identity report:
  `output/_r5_p3_client_identity_round1/r5_p3_client_identity.json`
- client identity content hash:
  `3289725b55042212dc6c9756db4cda06b6727e8155cc8ceffd337452ba3008e0`
- client identity file SHA-256:
  `2cc9c8dc7dc7ceb5f248a556c961597cc0f1044be5bccaae5e7c1146f1ad5230`
- client fairness report:
  `output/_r5_p3_client_fairness_round1/r5_p3_client_fairness.json`
- client fairness content hash:
  `7e06cc0f77028842b9fa3553d2e3ffcdc3d934d59cead73c94525c9525ce3877`
- client fairness file SHA-256:
  `eece42ad6824b06f575a6582be1e5375b007825e7cfd2b095945a4ded944380e`
- TLS report:
  `output/_r5_p3_tls_round1/r5_p3_tls_probe.json`
- TLS content hash:
  `9ce4eae23a2aaa5b131ecca7a30df04044952ee52ce98d663e249df633364a8c`
- TLS file SHA-256:
  `8c1972d1e9e2e82563cb1bf60bf2419da7aa676c6abd73413bbb6428f10327f1`
- plugin auth/rotation report:
  `output/_r5_p3_plugin_auth_round2/r5_p3_plugin_auth.json`
- plugin auth/rotation content hash:
  `86a1859a1f17ca2588f7c27bf789d11fd8dcfab3630dd58a522876df86c80027`
- plugin auth/rotation file SHA-256:
  `9afb37f9528f902d0ad53b4364dbffb78798fea32b2fbf59b175d10279069f4c`
- real Figma UI save/reopen report:
  `output/_r5_p3_real_plugin_ui_round1/figma_ui_config_probe.json`
- real UI report content hash:
  `ca22cb3475c5d641231db7a7d6e1ca3cffe98e66402c0797d637f22a77a73d64`
- combined TLS/auth report:
  `output/_r5_p3_tls_plugin_auth_round2/r5_p3_tls_plugin_auth.json`
- combined TLS/auth content hash:
  `86151a9ef89b4f05904cadbedd218ae863be1420736ddeb242459df26b92b722`
- attribution report:
  `output/_r5_p3_multiplayer_attribution_round2/r5_p3_multiplayer_attribution.json`
- attribution content hash:
  `284022e78d14a3951e0402abc0004b92adace1d6f04b5f6164873ae0e2a1f164`
- real revocation/recovery report:
  `output/_r5_p3_real_plugin_revocation_round2/figma_ui_revocation_probe.json`
- revocation content hash:
  `18a460f0f1f2666bc1b3d95e819958bbdd8d89fb539bb70b3c5d1cac0db12af0`
- ledger lifecycle report:
  `output/_r5_p3_ledger_lifecycle_round1/report.json`
- ledger lifecycle content hash:
  `cd6dcef35fab8bde8eef3a74eb8cafab7cc77ff24e428edf8f7f851b5ab86cb3`
- ledger lifecycle report file SHA-256:
  `33ce9cfb0aca98a672155bffb255590a5fa868bd80f94c97cfca0000054c7c85`
- migration candidate SHA-256:
  `54ca7f70b8a91306c05b651edb6722beabf9e6808460bd0909b5b2cbbcc81dff`
- compacted ledger SHA-256:
  `712766fb9dd9f472842fef98f8d5f5428f665969c8d64df85dcfd774c1d89e0f`

Soak result:

```text
jobs: 7
committed: 2
reconciled without resend: 1
manual review: 3
duplicate job conflicts: 1
cross-client same raw id distinct: true
plugin write calls: 2
duplicate side effects: 0
```

## 6. Remaining Production Blockers

- default configuration remains anonymous; per-client tokens must be deployed
  explicitly.
- certificate/token lifecycle, production trust-store integration, and default
  fail-closed production configuration remain open.
- operator revocation notifications, stale-token UX and automated token
  rotation remain open.
- automatic certificate provisioning/rotation and external secret-manager
  integration remain open.
- real two-human Figma collaborator attribution is unavailable by contract;
  current-state equality does not prove actor or revision.
- certificate provisioning/rotation, trust-store integration and private-key
  permissions remain open; the test self-signed certificate is not a
  production trust strategy.
- the config file becomes a secret-bearing artifact when real tokens are filled;
  file ACLs and secret-manager integration are not implemented.
- fairness is proven within one bridge process; cross-process/cross-host
  fairness and real Figma rate-limit behavior remain open.
- Multiplayer attribution and two-collaborator races are not exercised.
- Permission denial, Figma rate limiting, and user takeover are not exercised.
- Same-name and cross-document concurrency remain open.
- ledger compaction is instance-locked, not cross-process fenced; terminal
  purge policy and marker/bridge-journal migration remain undecided.
- R5-P4 storage policy and production certificate/token lifecycle remain open.

## 7. Next

The next production-admission slice should close cross-process ledger fencing,
terminal purge/backup policy, certificate/token lifecycle, and
two-collaborator reconciliation policy. Do not start R5-P5 or 24h/7d soak from
this handoff.
