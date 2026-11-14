# ATOMICITY_RESEARCH — TON has no provable native flash-loan primitive (typed negative-evidence note)

**Type:** `ATOMICITY_RESEARCH` (typed research note; negative claim with pinned official citations)
**Retrieved:** 2026-11-14 UTC
**Claim class:** negative claim about TON network semantics, relevant to any future flash-capital graph edge.
**Frozen consequence:** `execution_class=TON_ASYNC_MULTI_CONTRACT`, `verification_state=DISCOVERY_ONLY`, `executable=False` remain correct for every TON record; TON stays research-only.

## The negative claim

TON provides **no native flash-loan primitive** equivalent to the EVM pattern (a single atomic transaction in which borrow -> use -> repay is executed and provably revertible as a whole). No official TON documentation describes such a primitive. What the official documentation *does* establish — each point pinned below — is an execution model in which the EVM flash-loan pattern's required precondition (whole-chain cross-contract atomicity with rollback) does not exist.

## Pinned official evidence chain

1. **One TON transaction touches exactly one account; EVM-style cross-contract atomicity is explicitly contrasted as absent.**
   Source: TON docs, "Coming from Ethereum", https://docs.ton.org/from-ethereum (also indexed as https://docs.ton.org/llms/from-ethereum/content.md), retrieved 2026-11-14. Verbatim: "Compared to Ethereum, where multiple messages and state changes on different contracts can be processed within the same atomic transaction, a TON transaction only changes state for one account, processing a single message." And: "one transaction on Ethereum usually corresponds to several transactions on TON." And: "The same operation on TON consists of a sequence of more than 10 transactions." (Page as captured 2026-11-14; docs.ton.org is a continuously updated documentation site without per-page version numbers or a public Git blob pin — page capture is URL+date pinned, `docs_page_capture` hash policy per `SOURCE_MANIFEST.json`.)
2. **Outgoing messages are actions of one transaction; failures surface via a separate bounce phase, not via whole-chain rollback.**
   Source: TON docs, "Execution phases", https://docs.ton.org/llms/foundations/phases/content.md, retrieved 2026-11-14. Verbatim: actions (including `action_send_msg`, "Sends a message") are executed "in the order in which they were created"; "the transaction may revert or skip the action, depending on its mode"; and the bounce phase triggers when "the failed action must have flag 16 set". Rollback scope in the official text is per-action/per-transaction, never a chain of cross-contract transactions.
3. **Multi-contract operations are multi-transaction traces (n transactions need at least n-1 messages).**
   Source: TON docs, "Messages and transactions overview", https://docs.ton.org/llms/foundations/messages/overview/content.md, retrieved 2026-11-14. Verbatim: "a trace cannot continue without messages: if it contains `n` transactions it must contain at least `n-1` messages." Cross-contract borrowing (lender -> router -> venues -> repay) is therefore a trace spanning many separately-finalized transactions across possibly different blocks/shards, with no documented mechanism to atomically revert the trace.
4. **Official venue documentation corroborates the async model rather than an atomic primitive.** Omniston (STON.fi RFQ) exposes quote/escrow/order settlement flows (`quote.settlementData.$case` = `swap` or `order`, escrow transfer building, HTLC secret disclosure) — settlement *infrastructure* spanning transactions, not an atomic borrow primitive: https://docs.ston.fi/developer-section/omniston/swap/v1beta8, retrieved 2026-11-14.

## Typed gaps (honest unknowns; unknown is not zero)

- `MISSING_PIN` (verbatim statement): no official TON documentation page states verbatim "flash loans are not supported". The negative claim above is a **structural consequence** of pinned architecture (points 1-3), not a quoted sentence. Any stronger phrasing in reports must keep this typed gap.
- `MISSING_PIN` (upstream change): docs.ton.org pages are unversioned captures (URL + retrieval date only). A future TON upgrade introducing a documented atomic/flash primitive would invalidate this note; re-verification is required before any capital-graph edge is created for TON.
- Community-documented workarounds (e.g. bounce-message "simulated atomicity") are **not** pinned here and are not evidence: fixtures are never live evidence, and nothing community-written is official-source evidence.

## Consequence for the repository

- The financing dimension of the TON research graph has **no pinned atomic-borrow edge**; flash-capital capacity for TON remains unknown/absent-by-default, never inferred from routing or quote APIs (R-09 acceptance: "Do not infer atomic flash liquidity from routing APIs").
- If any future source claims TON atomic borrowing, it must arrive with its own versioned dossier, official pins, and fail-closed qualification — this note is the negative baseline it has to refute.
