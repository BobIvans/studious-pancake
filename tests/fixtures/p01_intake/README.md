# P0-1 intake fixtures — synthetic, offline, provenance-pinned

All files in this directory are **synthetic test fixtures** (`SYNTHETIC_TEST`).
No live provider response was captured, copied or redacted into them. Row
shapes follow the checked-in official contract extracts:

- `docs/integrations/offline/solana-p0/SOLANA_DISCOVERY_SOURCES.md`
- `docs/integrations/offline/solana-p0/SOURCE_MANIFEST.json`

Addresses are deterministic placeholder pubkeys (repeated-byte `Pubkey`
values, same technique as `tests/native_cpmm_fixtures.py`); they are not real
accounts and must never be used as chain truth.

## Files

| File | Lane | Class |
|---|---|---|
| `dexscreener_positive.json` | DEX Screener `/tokens/v1` | positive |
| `dexscreener_drift.json` | DEX Screener | schema drift (missing `baseToken`) |
| `dexscreener_foreign_chain.json` | DEX Screener | negative (foreign `chainId`) |
| `raydium_positive_p1.json` | Raydium API V3 `/pools/info/list` | positive (page 1) |
| `raydium_positive_p2.json` | Raydium API V3 | positive (page 2) |
| `raydium_empty_page.json` | Raydium API V3 | positive-empty (stops page walk) |
| `raydium_429.json` | Raydium API V3 | negative (rate limited) |
| `raydium_schema_drift.json` | Raydium API V3 | negative (`success=false`) |
| `meteora_positive.json` | Meteora DLMM Data API `/pools` | positive |
| `meteora_drift.json` | Meteora DLMM Data API | schema drift (missing mints) |
| `manifest_positive.json` | Manifest `/tickers` | positive |
| `manifest_drift.json` | Manifest | schema drift (missing `ticker_id`) |

`fixture-manifest.json` pins the SHA-256 of every fixture at commit time;
`tests/test_p01_intake_cadence.py` verifies the pins before use, so any
unreviewed fixture mutation fails closed.
