# Source Plug-in Architecture

## Objective
Подключение нового источника должно занимать один dossier + один adapter, а не изменение десяти unrelated modules.

```text
SourceDossier
   ↓ validate
ProviderProfile
   ↓ governed transport/quota/auth
SourceProbe
   ↓
DiscoveryAdapter OR RootedStateAdapter OR OracleAdapter OR ProtocolAdapter
   ↓
Canonical Observation Envelope
   ↓
Evidence Journal
```

## Canonical Observation Envelope
Обязательные поля:
- `source_id`, `source_generation`;
- `provider`, `operator`, `correlation_group`;
- `request_fingerprint`, `response_hash`;
- `observed_at`, `available_at`;
- `slot/root/sequence` when relevant;
- `raw_payload_ref/hash`;
- `data_role = discovery|reference|exact-state|oracle|protocol`;
- `quality_state = accepted|rejected|stale|gap|drift|rate-limited|unauthorized`;
- `schema_generation`;
- `campaign_manifest_hash`.

## Promotion ladder
`RESEARCH_CANDIDATE → DISCOVERY_ONLY → ROOTED_REFERENCE → EXACT_SHADOW → QUALIFIED_SHADOW`

No source jumps stages because “API returned 200”.

## Blank slots
`data/free_source_slots.csv` and `data/blank_source_slots.json` contain 64 intentionally empty source slots. Fill them without changing schema. Default role is discovery-only.
