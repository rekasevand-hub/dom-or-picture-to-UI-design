# Artifact Feedback Event Design

**Date:** 2026-10-31
**Status:** Proposed interface design; no storage or learning implementation
**Scope:** Whole-page generated artifact feedback

## Intent

Reserve a stable feedback contract for generated page artifacts without coupling
the current renderer to a particular storage backend, model, or taxonomy.

Feedback is collected at the whole artifact level. One page-level signal may be
used later to evaluate visual quality, layout, editable structure, semantic
component detection, and component grouping without forcing the user to inspect
every generated node.

The immediate deliverable is an interface design only. It does not add an API
endpoint, persistence layer, model call, automatic rule update, or training
loop.

## Feedback Values

Only two feedback values are supported:

- `positive`
- `negative`

No neutral value, score, star rating, or fixed reason taxonomy is introduced.

## Negative Reason

`negativeReason` is optional for negative feedback.

A user may submit `negative` immediately without selecting a reason. The reason
can be supplied later without creating a second page-level rating.

When present, `negativeReason` is a structured object rather than a fixed code:

```json
{
  "text": "页面头部背景和查询区域没有正确还原",
  "source": "llm-suggested",
  "suggestionSetId": "reason-set-001",
  "candidateIndex": 0
}
```

Fields:

| Field | Required | Meaning |
|---|---|---|
| `text` | yes | Final reason selected or entered by the user |
| `source` | yes | `llm-suggested` or `user-custom` |
| `suggestionSetId` | no | Identifies the generated candidate set used at selection time |
| `candidateIndex` | no | Zero-based selected candidate index when the source is `llm-suggested` |

No reason labels are hard-coded in this contract. Future reason suggestions may
change their wording, language, generation model, and ordering without a schema
migration.

## Artifact Feedback Event

### Positive Event

```json
{
  "schemaVersion": "artifact-feedback/1.0",
  "eventId": "feedback-001",
  "clientEventId": "browser-42f77f72",
  "artifactId": "artifact-ithome-001",
  "url": "https://www.ithome.com/0/823/017.htm",
  "captureSha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "designSha256": "123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0",
  "semanticSha256": "23456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef01",
  "feedback": "positive",
  "negativeReason": null,
  "reasonUpdatedAt": null,
  "createdAt": "2026-10-31T16:00:00+08:00"
}
```

### Negative Event Without Reason

```json
{
  "schemaVersion": "artifact-feedback/1.0",
  "eventId": "feedback-002",
  "clientEventId": "browser-7db31a55",
  "artifactId": "artifact-ithome-001",
  "url": "https://www.ithome.com/0/823/017.htm",
  "captureSha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "designSha256": "123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0",
  "semanticSha256": "23456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef01",
  "feedback": "negative",
  "negativeReason": null,
  "reasonUpdatedAt": null,
  "createdAt": "2026-10-31T16:05:00+08:00"
}
```

### Negative Event With Reason

```json
{
  "schemaVersion": "artifact-feedback/1.0",
  "eventId": "feedback-003",
  "clientEventId": "browser-466b2aa1",
  "artifactId": "artifact-stats-001",
  "url": "https://data.stats.gov.cn/",
  "captureSha256": "3456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef012",
  "designSha256": "456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123",
  "semanticSha256": "56789abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234",
  "feedback": "negative",
  "negativeReason": {
    "text": "查询区域识别成了组件，层级不合适",
    "source": "user-custom",
    "suggestionSetId": null,
    "candidateIndex": null
  },
  "reasonUpdatedAt": "2026-10-31T16:10:00+08:00",
  "createdAt": "2026-10-31T16:08:00+08:00"
}
```

## Identity And Version Correlation

| Field | Required | Meaning |
|---|---|---|
| `schemaVersion` | yes | Feedback schema version |
| `eventId` | yes | Server-generated feedback event identity |
| `clientEventId` | yes | Client-generated idempotency key |
| `artifactId` | yes | Identity of the generated page artifact |
| `url` | yes | Normalized source page URL |
| `captureSha256` | yes | SHA-256 identity of the capture bundle |
| `designSha256` | yes | Canonical SHA-256 identity of the DesignSpec |
| `semanticSha256` | yes | Canonical SHA-256 identity of the semantic component artifact |
| `feedback` | yes | `positive` or `negative` |
| `negativeReason` | no | Structured optional reason for negative feedback |
| `reasonUpdatedAt` | no | Time the optional reason was added or replaced |
| `createdAt` | yes | Time the page-level feedback event was created |

The hash tuple prevents feedback from silently carrying across a recapture,
DesignSpec regeneration, or semantic-classification change for the same URL.

`captureSha256` is the canonical SHA-256 of the capture bundle manifest.
`designSha256` and `semanticSha256` are canonical JSON hashes of their
corresponding artifacts.

`url` is normalized before storage:

- fragments are removed;
- obvious sensitive query values are redacted;
- the original artifact hashes remain the authoritative version identity.

## Interface Hook

The future implementation may expose:

```text
record_artifact_feedback(event) -> recorded event
update_negative_reason(event_id, negative_reason) -> updated event
```

A local JSON Lines adapter or an HTTP adapter may implement the same logical
contract. This document does not choose the production backend.

Recommended future HTTP shape:

```text
POST  /v1/artifact-feedback
PATCH /v1/artifact-feedback/{eventId}/negative-reason
```

`clientEventId` provides idempotency for retries. A repeated submission with the
same `clientEventId` must return the existing event instead of creating a
duplicate rating.

## Future Reason Suggestion Flow

This flow is explicitly deferred.

1. User submits `negative`.
2. The page-level event is recorded with `negativeReason: null`.
3. A future model reviews the page, source capture, DesignSpec, and semantic
   results and proposes three free-text reasons.
4. The UI presents those three candidates plus an `Other` free-text option.
5. The user may select or enter a reason, or leave the event without a reason.
6. A selected reason updates the same page-level feedback event and records
   `reasonUpdatedAt`.

The future model must not replace the page-level rating with component-level
labels. It may use component evidence to explain the whole-page result.

## Future Learning Boundary

Feedback events may later become a versioned evaluation corpus for:

- comparing semantic classifier versions;
- comparing DesignSpec and Figma renderer versions;
- ranking repeated component-group candidates;
- identifying page archetypes with insufficient evidence;
- evaluating the quality of future reason suggestions.

Positive or negative feedback must not directly modify production rules or
model weights in real time. Learning adoption requires versioned aggregation,
regression evaluation, and an explicit feature-flag decision.

## Validation Rules

- Reject unsupported `feedback` values.
- Reject missing or malformed version hashes.
- Reject `negativeReason` on positive feedback.
- Allow `negativeReason: null` for negative feedback.
- Require non-empty `negativeReason.text` when a reason object is present.
- Require a supported reason source.
- Treat a repeated `clientEventId` as an idempotent replay.
- Preserve unknown additive fields for forward compatibility.

## Non-Goals

- no feedback UI;
- no API server or database changes;
- no fixed negative-reason taxonomy;
- no automatic model or rule mutation;
- no component-level feedback in the first version;
- no claim that page-level feedback identifies the exact defective node;
- no change to current rendering or semantic defaults.
