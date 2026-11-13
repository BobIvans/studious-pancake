# Project 0 optional existing account — zero-spend discovery
R02-P0 needs the **public Solana wallet/authority pubkey** associated with a previously created marginfi account, *not the private key, mnemonic, seed phrase or API key*. An existing **marginfi account PDA** is also useful if already known. Do not publish a wallet address in a public committed receipt without intentional user disclosure.

## Two modes
`protocol_only` (default): read dynamic bank snapshots, verified genesis / protocol market / fee; record `ACCOUNT_ELIGIBILITY_UNKNOWN`. Can run immediately, without asking for user data. Should never claim user can borrow a flash amount from P0.
`existing_account` (opt-in): accepts public authority and/or explicit account address at runtime via uncommitted .env or CLI, verifies existing marginfi PDA ownership+group from official `Project0Client.getAccountAddresses` or `deriveMarginfiAccount`, fetches account state for read-only proof, and matches bank tags and balances. Redact address in exported evidence unless user explicitly approves; hashes allow proof of stable identity without sharing wallet.

No `createMarginfiAccountTx`, no auto-deposit and no wallet transaction. No attempt to resurrect or spend funds from a previously compromised wallet; use only account public information.
If the user does not supply these data: mark `P0_ACCOUNT_BINDING_PENDING_USER` and continue other three readers. To remove that block later, ask for only the wallet *public address* (plus optional existing marginfi account *public address*). Do not require account creation with SOL rent.
