# GPR-03 measured problems and campaign limits

These are evidence-driven research notes. They do not authorize GPR-04+ work.
See `GPR-03_IMPLEMENTATION.md` and `gpr03-evidence/INDEX.json` for exact campaign
heads, retained raw bodies and replay commands.

| Problem | Observed evidence | Corrected or outstanding |
| --- | --- | --- |
| DeepBook guessed endpoint | Initial `/all_pools` HTTP 404, empty body | Corrected to official OpenAPI `/get_pools`; final 26 pools include all 9 seeds |
| Cetus deployed shape | Initial HTTP 200 code 0/data.lp_list rejected by old guessed shape | Corrected using immutable actual payload and official config; final 20 discovery rows |
| Scallop host | Initial general-host `/api/market/migrate` HTTP 404 JSON Cannot GET | Corrected to official SDK indexer host |
| Scallop content encoding | Intermediate HTTP 200 rejected unsupported negotiated encoding | Corrected supported Accept-Encoding; final gzip 99 structural rates |
| POST framing | Initial GraphQL HTTP 400 text “Header of type `content-length` was missing” | Explicit pinned public headers and exact serialized Content-Length added; same final error persists despite issued 123-byte request proof |
| Aftermath bulk size | Initial HTTP 200 >1 MiB; corrected final HTTP 200 gzip >2 MiB | Collection remains bounded and fails closed; complete response and markets unmeasured |
| Exact state independence | Only default public smoke state source; no configured independent non-smoke quorum | HARD_BOUND blocked; no checkpoint context, no dependent object reads issued |
| Depth and fees | All 9 indexed identities measured; 3 books have very sparse/wide levels | Root pool/indexer rows do not prove dynamic book, lot/tick, fee rules or exact pricing |
| Representation/metadata | Published identity registry preserved; standard metadata decoder exists | Reviewed current issuer/origin/bridge/decimals policy and production pool layouts still required |
| Residual comparability | Lending/share inputs collected; no verified AMM/router quotes or gold oracle | LST/market, representation basis, DeepBook/AMM and XAUM/XAU residuals remain unmeasured |

The original and intermediate captures remain separate immutable evidence,
including negative/non-JSON bodies, incomplete oversize outcomes, physical
admission/cost accounting and source provenance. No failure was converted to a
zero quote, fake pool, anomaly, receipt or promotion.

Missing optional runtime binding names were inspected for presence without
printing values: `SUI_GRAPHQL_ENDPOINT`, `SUI_GRPC_ENDPOINT`, `SUI_API_KEY`,
`SUI_RPC_URL`, `AFTERMATH_API_KEY`, `CETUS_API_KEY`, `SCALLOP_API_KEY`.
The implementation uses anonymous public read profiles and existing verified
TLS/proxy settings. A configured binding alone would not supply reviewed quorum,
representation or decoder authority. Credential values must remain in secure
environment settings, never chat, tracked evidence or this document.

The shared-quota lesson from the parallel stream was verified independently:
source-specific generations cannot be used as conflicting generations for one
durable external dependency pool. Separate source generation and shared reviewed
quota generation preserve both endpoint fences and aggregate accounting. Tests
cover in-memory and durable cap exhaustion/restart before physical send. Shared
provider governance owners are unchanged.

Before any future roadmap implementation, measure narrowed Aftermath targeting,
exact checkpoint state from independent providers, qualified book depth/fees and
unit/time comparable quote/rate/oracle observations. The wide indexed stable
books support a liquidity-quality investigation; they do not support a trading
or production-readiness claim.

## Offline remediation 2026-11-14 (agent/sui-gpr03-remediation)

Bounded transport: the shared transport now fails closed before any send when a
declared request Content-Length disagrees with the actual built body, and
tolerates missing, malformed and chunked-framed response Content-Length headers
by bounding the streamed body with the unchanged wire/response caps instead of
trusting the header; only a trusted over-cap declaration rejects before read.
The recorded 400/43-byte GraphQL rejection replays offline with the exact
123-byte request proof and complete typed negative capture
(`tests/test_gpr03_remediation.py`). The deployed endpoint interoperability is
still unmeasured and remains blocked pending live evidence.

Aftermath: the 2 MiB/60,000-node engineering subcap is retired; every source
now uses the shared 1 MiB/20,000-node bounded profile, the pinned bulk `{}`
request shape is unchanged, and oversized responses fail closed with a typed
reason. No field/range request parameter is source-pinned offline; a targeted
narrowed read requires a new immutable source pin before issuance.

Provider binding: `src/gpr_sui_shadow/providers.py` defines the typed evidence
requirements for two independent non-smoke gRPC/GraphQL providers (checkpoint
consistency and object-version provenance) with offline verification over
retained captures. Live binding stays typed
`BLOCKED(LIVE_SUI_PROVIDERS_NOT_AUTHORIZED)`; no offline code path can flip it.

Decoders: `src/gpr_sui_shadow/decoders.py` binds exact package/module/type
before decoding, decodes the pinned bounded pool layout with canonical ULEB128
u64 fields, and binds decimals back to retained `0x2::coin::CoinMetadata<T>`
BCS. Wrong package, unknown type, truncated/noncanonical BCS and invalid fee
fractions fail closed. The layout remains a reviewed test contract; the
dynamic-object book/fee layout binding is still missing for production.
