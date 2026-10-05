# Rolling 120–160 Pair Universe

Цель — не “выбрать только самые прибыльные” и получить selection bias. Universe должен иметь несколько классов:

- 50–60% high-liquidity/high-activity candidates;
- 15–20% cross-venue dispersion candidates;
- 10–15% new/changed pools;
- ~20% negative controls / stable baselines.

Score inputs могут приходить из бесплатных discovery sources:
- volume/liquidity references;
- pool count / venue diversity;
- price dispersion;
- transaction activity;
- freshness/data completeness;
- newly created pools.

Но before exact route evaluation:
- mint/program/venue identity verify on-chain;
- exact rooted state required;
- indexed price never substituted for amount-specific output.

Schema: `data/hot_pair_universe.schema.json`.
