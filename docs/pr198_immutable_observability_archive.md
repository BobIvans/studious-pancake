# PR-198 — Immutable segmented observability archive

## Boundary

The authoritative observability export is now a sequence of immutable,
content-addressed JSONL segments. The historical `events.jsonl` output remains
available only as a non-authoritative compatibility artifact and cannot satisfy
archive verification or release evidence.

## Segment identity

Each segment identity binds the database epoch, outbox range, ordered event IDs,
UTC date/event partition, content SHA-256, schema/redaction/tool versions,
release ID and PolicyBundle hash. The immutable object key is:

```text
date_utc=<date>/event_type=<type>/segment=<first>-<last>-<sha256>.jsonl
```

Publication uses a restrictive temporary file, file `fsync`, an atomic
no-replace hard-link publication and directory `fsync`. An existing object is
never replaced; an identical object is treated as idempotent, while conflicting
bytes fail closed.

## Claim and commit protocol

`ArchiveCoordinator` creates a SQLite-fenced claim with a monotonically
increasing fencing token and lease. Claim items are unique by outbox ID and event
ID, so concurrent exporters cannot own the same row.

For every partition the exporter:

1. writes and validates the immutable segment;
2. publishes it without replacement;
3. commits the authoritative manifest, ordered event linkage and outbox CAS in
   one database transaction;
4. records remote object acknowledgement when an archive uploader is required.

Every authoritative manifest is stored in both the PR-198 archive schema and the
legacy `export_manifest` index. The mutable compatibility file is deliberately
not inserted as authoritative evidence.

## Recovery

At startup the exporter expires stale leases, removes stale claim-owned temp
files and scans published segments without committed manifests. A valid orphan
is checksum-verified, parsed, rebound to the exact pending events through a new
fenced recovery claim and committed without rewriting the object. Active claims
are left untouched. Corrupt or conflicting orphan content fails closed.

Required remote acknowledgements are retryable after a local commit. The stored
ack binds archive name, object key, object version and the exact segment digest.

## Verification

`verify_archive()` checks:

- segment path confinement and existence;
- content SHA-256 and JSONL validity;
- event count and ordered event linkage;
- exactly-once outbox coverage for the PR-198 archive epoch;
- required remote acknowledgement;
- explicit non-authoritative status of the legacy aggregate file.

## Focused checks

```bash
python -m pytest tests/test_pr132_observability_integrity.py -q
python -m pytest tests/test_pr198_immutable_observability_export.py -q
python -m black --check \
  src/observability/archive.py \
  src/observability/export.py \
  tests/test_pr198_immutable_observability_export.py
```

The patch does not enable paper/live execution, provider calls, sender paths or
release approval. It only hardens offline observability archive truth.
