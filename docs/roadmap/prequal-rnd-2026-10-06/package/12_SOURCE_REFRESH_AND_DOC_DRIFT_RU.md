# Documentation / SDK / Endpoint Refresh Workflow

Before each campaign generation:

1. Open only official docs/repo/package sources.
2. Record `checked_at` and exact URL.
3. Record SDK/package minimum and exact tested version.
4. For programs: program ID, source commit, programdata/deployment hash if qualification-relevant.
5. For hosted APIs: base URL, required params, auth header, limits, response required paths.
6. Compare with prior SourceDossier semantic fingerprint.
7. If semantic change → increment `source_generation`; never overwrite old generation.
8. Run positive probe + negative probes (missing auth, 429, malformed body, stale slot, unknown enum).
9. Update source drift watchlist.
10. Campaign manifest pins exact generation.

Current watch items are in `data/source_drift_watchlist.csv`.
