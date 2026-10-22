# P4 Optional Command Authentication

> Date: 2026-10-22  
> Status: `optional-bearer-auth-pass / per-client-identity-current-scope`  
> Scope: authenticate `/command` clients without changing the local Figma
> development plugin connection.

## 1. Configuration

All bridge and default-client settings live in:

```text
figma_bridge.config.json
```

Authentication fields:

```json
{
  "allow_env_overrides": false,
  "server": {
    "auth_token": "<optional-shared-secret>",
    "client_tokens": {
      "client-a": "<secret-a>",
      "client-b": "<secret-b>"
    }
  },
  "client": {
    "url": "ws://localhost:8765",
    "client_id": "client-a",
    "client_token": "<secret-a>",
    "auth_token": "<optional-shared-secret>",
    "allow_legacy_job_ids": false
  }
}
```

`FigmaBridgeAdapter` reads the `client` section by default. Explicit
constructor arguments override file values.

When `allow_env_overrides` is `false`, bridge/client environment variables are
ignored. When `true`, the previous `FIGMA_BRIDGE_*` variables can override file
values for CI or emergency operations.

When no shared or per-client token is configured, local anonymous behavior
remains available for development.

Secrets may use `env:VARIABLE` or `file:path` references. Production should
enable `security.require_secret_references` and, when direct/file secrets are
used, `security.require_secure_file_permissions`. Use
`scripts/rotate_figma_bridge_config.py` for atomic validated rotation.

`FIGMA_BRIDGE_CONFIG` may select a different config file when explicitly
needed; normal startup requires no variables.

## 2. Protocol

Authenticated clients connect with:

```http
Authorization: Bearer <shared-secret>
```

Missing or incorrect credentials return:

```text
code: UNAUTHORIZED
outcome: not-applied
```

The comparison uses `hmac.compare_digest`.

With per-client tokens configured, `/command` also requires:

```http
X-Figma-Client-Id: <clientId>
X-Figma-Client-Token: <per-client-secret>
```

Identity is verified after parsing the command but before cache lookup,
namespace validation, write admission, or plugin dispatch.

```text
missing headers:         CLIENT_IDENTITY_REQUIRED
header/payload mismatch: CLIENT_IDENTITY_MISMATCH
wrong/unknown token:     CLIENT_IDENTITY_INVALID
```

The per-client token is not written to the bridge journal.

Plugin tokens are separate:

- `server.plugin_token` configures first-frame `/plugin` auth;
- `server.plugin_token_recheck_seconds` revokes the active plugin on rotation;
- the Figma UI persists URL/token in `figma.clientStorage`;
- real Figma save/close/reopen restored the token and reconnected.

## 3. Scope

Protected:

- `/command`;
- all command actions, including bridge-local transaction-status queries.

Not protected by this token:

- `/plugin` uses a separate `server.plugin_token` first-frame handshake;
- the plugin UI stores its URL/token in `figma.clientStorage`.

With `server.plugin_token` empty, the plugin endpoint remains compatible with
local development. Configure both plugin authentication and TLS before any
non-loopback exposure.

## 4. Verification

Tests cover:

- missing token;
- wrong token;
- correct token;
- adapter header construction;
- per-client token mapping parsing;
- missing/wrong/mismatched/correct client identity;
- token absence from journal.
- missing/wrong/correct plugin first-frame token;
- plugin URL/token persistence in clientStorage.
- secret references, permission policy, atomic rotation and UI revocation.

The token is not written to the bridge journal.

Real bridge smoke:

```text
missing token: UNAUTHORIZED
wrong token:   UNAUTHORIZED
correct token: font_report success, textNodes=136
```

Bridge logs showed plugin responses only for the correct-token request.

Per-client identity deterministic evidence:

```text
output/_r5_p3_client_identity_round1/r5_p3_client_identity.json
content hash: 3289725b55042212dc6c9756db4cda06b6727e8155cc8ceffd337452ba3008e0
```

## 5. Remaining Boundary

Command authentication remains independent from transport. Config-backed TLS
now exists, but production trust and lifecycle remain open:

- certificate provisioning, trust-store integration and rotation;
- `/plugin` authentication;
- internet exposure policy;
- per-client token provisioning, storage and rotation;
- default fail-closed production configuration;
- multi-tenant authorization and document-scoped permissions.
