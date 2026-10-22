# P4 Production Gap Assessment

> Date: 2026-10-22  
> Status: `tls-current-scope-pass / plugin-auth-open / long-soak-deferred-to-user-cloud`  
> Scope: TLS, `/plugin` authentication, unknown readback attribution,
> cross-host fencing, and 24h/7d soak.

This document records production decisions that are intentionally outside the
server-side write-pacing patch. None of these items is closed by the current
deterministic write soak.

## 1. TLS

Current state:

- `figma_bridge.config.json` contains explicit server/client TLS sections.
- Server TLS builds a real `SSLContext`, loads cert/key, optional CA and
  optional client-certificate verification.
- `FigmaBridgeAdapter` uses `sslopt` with custom CA and optional client
  cert/key for `wss://`.
- A local loopback wss handshake and round trip pass.
- TLS remains disabled in the default local-development config.

Decision:

- TLS is available as an explicit deployment feature.
- Keep the bridge loopback-only until certificate provisioning, rotation and
  `/plugin` authentication are designed and exercised.
- Do not treat the test self-signed certificate as a production certificate
  management strategy.

Implemented contract:

1. Provide certificate/key paths and an explicit TLS-enabled startup mode.
2. Use a verified `wss://` client path; separate trust configuration for local
   development certificates.
3. Support optional CA and client certificate/key configuration.
4. Exercise command auth, plugin reconnect, timeout, and write pacing over TLS.

Still open:

- certificate provisioning and rotation;
- system trust-store/secret-manager integration;
- production TLS enforcement by default;
- re-running the full command/plugin timeout and pacing suite over TLS.

## 2. `/plugin` Authentication

Current state:

- The optional Bearer token applies only to `/command`.
- `server.plugin_token` can require a first-frame `/plugin` authentication
  message.
- Missing/wrong tokens close with code `4003` before attachment.
- The Figma plugin UI stores bridge URL/token in `figma.clientStorage`; the
  token is not placed in the URL.
- Token rotation/revocation rechecks the config and closes the active plugin
  with code `4004`; a wrong candidate cannot replace it.
- Real Figma UI save/close/reopen restored the token and reconnected.
- A combined local wss + auth + rotation + reconnect probe passes.
- Config secrets support env/file references, private file checks and atomic
  rotation.
- Empty `server.plugin_token` remains the local-development compatibility mode.

Decision:

- Keep `/plugin` local by default. Production deployments should configure a
  plugin token and `wss://`.
- Treat UI token provisioning and rotation as deployment operations until a
  stronger secret lifecycle is implemented.

Implemented contract:

1. A plugin-side token entry flow with no token echoed in logs or journal.
2. Constant-time handshake validation before `attach_plugin`.
3. Tests for missing and wrong credentials.

Still open:

- operator notification and stale-token recovery UX;
- automated token provisioning/rotation and audit;
- real two-human collaborator attribution (unavailable by Figma API).

## 3. Unknown Readback Attribution

Current state:

- Unknown transactions are read back from Figma.
- Text/name checks use SHA-256; visibility uses an explicit boolean.
- The bridge reports `matches-intended`, `partial-match`,
  `does-not-match-intended`, or `indeterminate`.
- The state remains `unknown`; readback never promotes a write to `committed`.

Why it is not commit attribution:

- Another collaborator can make the same edit.
- A later collaborator can overwrite the intended value.
- Figma readback does not provide an actor or write revision for the original
  plugin operation.
- Image fills and all layout mutations do not yet have complete expected-state
  checks.

Decision:

- Preserve the fail-closed rule: never automatically replay an unknown write.
- Treat readback as current-state evidence, not proof of ownership.
- A human reconciliation path is required when `does-not-match-intended` or
  partial coverage occurs under multiplayer edits.

Minimum next experiment:

1. Capture pre-intent state and immediate post-send readback where possible.
2. Add expected checks for image fill hashes and layout snapshots.
3. Run a controlled two-collaborator edit race and record whether the
   classification stays conservative.
4. Keep actor attribution explicitly unavailable unless Figma exposes an
   authoritative revision/actor source.

## 4. Cross-host Fencing

Current state:

- The journal lock prevents two local bridge processes from owning the same
  journal file on the tested Windows host.
- The lock is not a distributed lease.
- Network filesystem semantics, stale clients, process pauses, and partition
  behavior are unverified.

Decision:

- Do not place the journal on SMB/NFS and run multiple bridge hosts.
- A process-local file lock must not be described as a fencing token.

Minimum implementation contract:

1. Treat ownership as an external lease with monotonically increasing fencing
   tokens.
2. Fence every plugin dispatch or document mutation with the current token.
3. Test pause/resume, partition, stale owner, lease expiry, clock skew, and
   journal append failure.
4. Define a single-writer topology before attempting replication.

## 5. 24h/7d Soak

> Execution status: `deferred / waiting-for-user-cloud-server`, 2026-10-21.  
> The plan and cloud prerequisites are recorded in `P4_LONG_SOAK_BACKLOG.md`.

Current state:

- Real Figma readback: two 60-second rounds, 50,136 requests, zero failures;
  bridge RSS and handles did not show simple linear growth.
- Deterministic write pacing: 320 writes with no client sleep and a separate
  240-request saturation run.
- Real Figma write pacing: 960/960 transactions in 60 seconds with four
  writers and no client sleep; zero timeout/unknown.
- No multi-hour or multi-day run exists.

Decision:

- Use staged admission gates rather than jumping to a 7d marketing claim.
- A run passes only if requests drain, no unknown outcomes are unexplained,
  journal bounds hold, and bridge resource trends remain bounded.

Suggested stages:

| Stage | Duration | Required focus |
|---|---:|---|
| A | 1h | connection churn, write pacing, p99 tail |
| B | 24h | bridge RSS/handles, journal compaction, plugin reconnect |
| C | 7d | daily summaries, failure classification, renderer memory |

The Figma plugin renderer's memory cannot currently be measured from the bridge
process. A 24h/7d claim must state that limitation or add plugin-side
instrumentation.

Current action:

- Do not start a local 24h/7d run.
- The user will execute the staged long soak on a cloud server later.
- The backlog remains open until the cloud evidence bundle is reviewed.

## 6. Current Admission Statement

Allowed:

- local single-host, single-bridge, single-plugin development workflow;
- local or explicitly configured `wss://` transport with custom CA support;
- fail-closed unknown handling;
- bounded, paced writes with retryable backpressure.

Not allowed:

- public Internet exposure;
- untrusted LAN clients;
- multi-host ownership of one journal;
- automatic unknown-write replay;
- claiming collaborator-safe commit attribution;
- claiming 24h/7d stability from the current evidence.
