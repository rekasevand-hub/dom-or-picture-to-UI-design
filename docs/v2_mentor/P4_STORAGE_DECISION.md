# P4 Storage Decision

> Status: local pilot frozen; production backend selected for future design  
> Date: 2026-10-22

## Local Pilot

- Backend: explicit local filesystem directory.
- Layout: one atomic record directory per `trace_id`, plus a tombstone archive.
- Write order: validate runtime IR and audit bundle, commit the record with
  `fsync` and `os.replace`, and only then allow render dispatch.
- Idempotency: one key maps to one content hash; reuse with different content
  fails closed.
- Retention: `audit_metadata_expires_at` controls expiration.
- Protection: records containing unknown state are not purged by this pilot
  store.
- Production eligibility: `false`.

This backend is suitable only for a bounded single-host P5 pilot.

## Production Selection

Selected target architecture:

- PostgreSQL for delivery metadata, idempotency keys, retention indexes and
  audit access control;
- S3-compatible object storage with versioning, object lock where required and
  server-side encryption using a deployment KMS key;
- tenant isolation through tenant-scoped keys plus PostgreSQL row-level policy;
- immutable migration records with schema version and rollback compatibility;
- encrypted backups, point-in-time recovery and documented restore drills;
- metrics and audit events that never contain raw design text or secrets.

No local pilot file is silently promoted to this backend. Production requires a
separate implementation, migration test, permission test and restore exercise.
