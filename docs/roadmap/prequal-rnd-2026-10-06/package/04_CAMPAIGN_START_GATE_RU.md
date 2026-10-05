# Campaign-Start Gate

До первого реального run НЕ нужно закрывать весь production debt. Нужны следующие invariants:

1. **Read-only boundary:** signer/sender/submission недоступны.
2. **Campaign identity:** current git SHA + runtime authority + policy bundle + source generations.
3. **Source dossier:** каждый внешний source имеет auth/quota/terms/schema/provenance contract.
4. **Discovery isolation:** indexed/aggregator data не становится exact edge.
5. **Durable journal:** сохраняются raw/hash/request/slot/time + failures/gaps.
6. **Replay isolation:** replay не делает network requests.
7. **Quota:** retry = physical attempt; budget не refill при restart.
8. **Single-source honesty:** можно собирать данные с 1 RPC, но status только exploratory/BLOCKED.
9. **Docs freshness:** current docs checked before run.
10. **Unknown semantics fail closed:** неизвестная fee/oracle/token extension/cost не превращается в 0.

Machine-readable: `data/acceptance_gates.json` → `CAMPAIGN_START_V1`.
