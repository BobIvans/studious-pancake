# PR-047 wallet and account ownership checklist

## Wallet

- verify the public key on `mainnet-beta` through two independent read-only
  sources;
- record the integer lamport balance at the checklist timestamp;
- verify `observed balance >= protected reserve + fee buffer`;
- confirm the signer is referenced through `env:`, absolute `file:/...`, or
  `keychain:` and is not embedded in config, logs or the manifest;
- confirm the runtime identity has only the intended signing permission;
- confirm the human rotation owner and emergency revocation path.

The checklist does not fund the wallet. Funding is a separate human-controlled
operation and must not be automated by PR-047.

## RPC account

- identify the organization and billing owner;
- verify the endpoint belongs to the intended account/project;
- verify mainnet access, quota and rotation ownership;
- confirm no personal or expired project owns the production endpoint.

## Provider accounts

For Jupiter and any enabled discovery provider, record account/project identity,
billing owner, credential reference, quota tier and rotation owner. Discovery
access does not imply execution capability.

## Jito account

- verify the intended endpoint/account and billing owner;
- verify UUID/API credential ownership and rotation responsibility;
- verify tip/payment policy belongs to the canary release policy;
- keep submission disabled until PR-046 evidence and all PR-047 gates pass.

## Evidence hygiene

Use opaque account identifiers and secret references. Do not record API keys,
passphrases, signatures, private keys, seed phrases or signed transaction bytes.
