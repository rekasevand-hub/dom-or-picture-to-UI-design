# Grounding Reliability Runbook

> Status: `current-scope` implementation and controlled evidence  
> Grounding is the default image strategy. CV is an availability fallback only.  
> This runbook does not claim production provider availability or CV quality.

## Runtime Contract

Grounding uses a finite execution loop:

1. Hash the image bytes.
2. Form the cache key from image SHA-256, model, prompt SHA-256, strategy id,
   strategy version and cache namespace.
3. Try one eligible endpoint per attempt.
4. Retry only classified transient failures, with exponential backoff and
   jitter bounded by `VISION_MAX_BACKOFF_MS`.
5. Advance to another endpoint after transient or endpoint-auth failure.
6. Open an endpoint after consecutive transient failures and skip it until the
   cooldown permits one half-open probe.
7. Stop permanently at `VISION_MAX_ATTEMPTS`; there is no unbounded retry.

Malformed or empty model output is a response-contract failure. It does not
select CV.

## Configuration

| Setting | Default | Meaning |
|---|---:|---|
| `VISION_BASE_URLS` | `VISION_BASE_URL` or provider default | Comma-separated ordered endpoints |
| `VISION_TIMEOUT` | `120` | Per-request timeout in seconds |
| `VISION_MAX_ATTEMPTS` | `3` | Total invocations, range `1..10` |
| `VISION_RETRY_BASE_MS` | `250` | Initial backoff |
| `VISION_MAX_BACKOFF_MS` | `4000` | Backoff ceiling |
| `VISION_JITTER_RATIO` | `0.25` | Symmetric jitter fraction |
| `VISION_BREAKER_FAILURE_THRESHOLD` | `3` | Consecutive failures before open |
| `VISION_BREAKER_COOLDOWN_SECONDS` | `30` | Open duration before half-open |
| `VISION_CACHE_MAX_ENTRIES` | `64` | Bounded LRU size |
| `VISION_CACHE_TTL_SECONDS` | `300` | Cache lifetime |
| `VISION_CACHE_NAMESPACE` | `default` | Cache isolation namespace |
| `VISION_MAX_IMAGE_BYTES` | `26214400` | Input size guard |
| `VISION_MAX_RESPONSE_BYTES` | `5242880` | Raw response size guard |

Endpoint URLs and provider credentials must remain in approved configuration
or secret references. Do not put either in command evidence.

## Error Taxonomy

| Category | Examples | Retry | Fail over | CV fallback |
|---|---|---|---|---|
| `connection` | refused, reset, timeout | Yes, bounded | Yes | Yes after exhaustion |
| `rate-limit` | HTTP 429 | Yes, bounded | Yes | Yes after exhaustion |
| `server` | HTTP 500/502/503/504 | Yes, bounded | Yes | Yes after exhaustion |
| `authentication` | endpoint 401/403 | No same-endpoint loop | Yes | Yes only after all eligible endpoints fail |
| `request-invalid` | malformed request, HTTP 4xx other than auth/429 | No | No | No |
| `response-invalid` | invalid or empty structure JSON | No | No | No |
| `circuit-open` | no endpoint currently eligible | No | n/a | Yes; this is service unavailability |

Fallback is selected before design generation and before any Figma write.

## Observability

Required metrics:

- `grounding_unavailable_total`;
- `fallback_trigger_total`;
- `fallback_selection_accepted_total`;
- `fallback_write_before_block_total`;
- `fallback_latency_ms_p50`, `p95`, `p99`;
- `fallback_token_usage_total`;
- cache status and breaker state in the per-run reliability report;
- endpoint attempt count, retry count, final endpoint index and HTTP category in
  the per-run report.

`fallback_selection_accepted_total` means CV was selected after an availability
trigger. It does not mean the result passed product acceptance.

Cost remains `null` with `cost_status=unavailable-no-pricing-table` until a
versioned pricing table is configured. Cache hits record zero new provider
usage for that request.

## Proposed Alert Rules

These are local-pilot alert contracts, not deployed production alerts:

| Signal | Warning | Critical | Action |
|---|---|---|---|
| `grounding_unavailable_total` | increase > 5 in 10m | all eligible endpoints open > 5m | Keep CV fallback; inspect endpoint health |
| fallback latency p99 | > 30s | > 120s | Reduce timeout/attempt budget or disable unhealthy endpoint |
| fallback write-before-block | n/a | > 0 | Stop writes; a fallback decision occurred after dispatch |
| fallback selection failure | any failed CV selection | repeated failure | Block image export; do not retry malformed Grounding |
| cache isolation violation | any | any | Flush cache, stop image requests, investigate tenant keying |

## Operator Procedure

### Endpoint Outage

1. Confirm attempts are bounded and report an unavailable category.
2. Verify CV fallback selection is recorded before design/render.
3. Keep quality acceptance `not-evaluated` unless the normal product gates ran.
4. Do not infer general CV quality from a successful fallback selection.
5. Remove or repair the unhealthy endpoint only through configuration rotation.

### Breaker Open

1. Wait for cooldown or remove the endpoint from configuration.
2. Allow exactly one half-open probe through normal traffic.
3. A successful probe closes the breaker.
4. A failed probe reopens it; do not bypass the threshold.

### Malformed Grounding Output

1. Keep the route blocked.
2. Preserve the raw response only within the approved local evidence policy.
3. Do not send the request to CV automatically.
4. Correct the prompt/model or classify a new product policy before retrying.

### Cost Spike

1. Check cache hit rate and retry count.
2. Verify prompt and strategy versions did not invalidate the cache.
3. Cap attempts and endpoint count.
4. Do not estimate monetary cost without a configured pricing version.

## Evidence

Controlled reliability probe:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\grounding_reliability_probe.py `
  --out output\_production_admission_2026-10-26\grounding_reliability
```

Fallback observation:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\fallback_observability_probe.py `
  --out output\_production_admission_2026-10-26\fallback_observability
```

Metric contract:

```powershell
C:\Users\lzq\.conda\envs\omni\python.exe scripts\p4_observability_probe.py `
  --out output\_production_admission_2026-10-26\observability `
  --fallback-observation output\_production_admission_2026-10-26\fallback_observability\fallback_observability.json
```

## Non-Claims

- No real external Grounding provider availability is proven by the controlled
  probe.
- No fallback quality, visual acceptance, asset acceptance or generalization is
  proven by route selection.
- No production monetary cost is claimed.
- No deployed paging, dashboard or on-call ownership is claimed.
- No production admission follows from this runbook.
