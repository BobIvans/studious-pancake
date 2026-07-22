# PR-195 — Authoritative database schema epochs

This slice adds a fail-closed SQLite product-identity and migration-authority
boundary and applies it to a new authoritative observability-store entrypoint.
It does not enable live trading or claim that every repository database family
has already migrated to the contract.

## Reproduced defect

The legacy observability migration writes `schema_migrations` using an upsert
that updates an existing checksum. A database with a manually added table can
therefore be reopened, have the new schema checksum adopted, retain the rogue
table, and still pass the minimum-column schema doctor.

## Database identity

`database_identity_pr195` is a singleton immutable product header binding:

- database UUID;
- product ID and schema family;
- environment and cluster genesis;
- creating release;
- application schema version and database epoch;
- reader/writer compatibility ranges;
- exact source-derived schema manifest;
- snapshot digest of legacy migration metadata.

A database created for observability cannot be opened as opportunity-dedup or
another store product. A future or unsupported epoch fails before a runtime
write.

## Migration evidence

`migration_ledger_pr195` is append-only and hash chained. Every row binds the
migration ID, source and target epochs, script checksum, resulting exact schema
checksum, release, fencing token and prior migration hash. Rewriting a row
breaks verification rather than becoming the new expected state.

The legacy `schema_migrations` rows are inserted only when absent. Existing rows
are never updated by the authoritative wrapper. Their ordered digest is sealed
into database identity so later modification fails closed.

## Exact schema manifest

The expected observability manifest is generated from the source schema in a
separate in-memory database. Runtime compares the target database's complete
normalized `sqlite_master` contract, including tables, indexes, triggers and
views. This rejects:

- rogue tables or foreign product tables;
- unexpected indexes, triggers or views;
- extra columns;
- wrong types, defaults or constraints even when required column names remain.

The target database never defines its own expected checksum.

## Startup-only migration and fencing

`AuthoritativeObservabilityStore` has two explicit modes:

- migration mode: requires a migration owner, obtains a durable fencing token,
  applies schema work and records immutable evidence;
- runtime mode: performs verification only and never creates or repairs schema.

An active migration lease blocks runtime readiness. A stale owner cannot append
a migration after its fencing token is replaced.

## Verification

Focused tests cover:

- the reproduced rogue-table checksum-adoption regression;
- foreign product identity on one SQLite path;
- exact constraint drift with the same column names;
- immutable legacy and PR-195 migration history;
- future epoch rejection;
- active and lost migration fences;
- runtime no-auto-migration behavior;
- duplicate configured database paths.

Suggested verification:

```bash
python -m pytest \
  tests/test_pr195_database_schema_authority.py \
  tests/test_pr195_authoritative_observability_store.py -q
python -m compileall -q src tests
python scripts/verify_repo.py
```

## Remaining integration

Follow-up PR-195 work must cut every production store over to this authority,
assign one reviewed path per product, run migrations through the deployment
controller, declare expand/contract compatibility, inject partial-migration and
lease-loss failures, and bind schema identity into release evidence. The legacy
`ObservabilityStore` remains available for compatibility until that explicit
composition cutover is reviewed.
