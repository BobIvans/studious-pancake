# Project0 / MarginFi Rebind Plan

## External truth checked 2026-10-06
- `@mrgnlabs/marginfi-client-v2` deprecated since 2026-03-15.
- Program 0.1.10 changed flash-loan/health/account-transfer wire layouts on 2026-08-25.
- Program 0.1.11 introduced new Scope/exchange-rate oracle setups; `@0dotxyz/p0-ts-sdk >= 2.8.0` required.

## Repo split
Catalog truth is current after PR #566, but deployment conformance still pins old source commits/build artifacts.

## New dossier must bind
1. official Project0 docs URL;
2. p0-ts-sdk exact package version + package integrity;
3. protocol source repository + exact source commit;
4. current production program ID + group;
5. programdata account + deployment slot + upgrade authority state;
6. deployed binary SHA256;
7. current IDL/instruction layout;
8. every oracle setup supported by banks used in campaign;
9. golden flash-loan start/end + health simulation vectors;
10. RPC snapshot generation;
11. differential results vs SDK/reference;
12. sender-free simulation only until promotion gate.

## Crucial rule
Do not silently reinterpret old pinned vectors as Project0 proof. Old vectors remain historical and fail closed for new source generation.
