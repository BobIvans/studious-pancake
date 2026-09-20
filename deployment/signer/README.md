# PR-009 isolated signer deployment boundary

This directory describes a **status-only**, separately packaged signer image.
It has no key loader, provider/RPC client, transaction builder, or general
application dependency. The deny-all network policy and read-only filesystem
policy are mandatory, not examples.

`artifact-attestation.json` intentionally records that no image digest,
signature, or isolated KMS/HSM keystore attestation exists in this repository.
Consequently the signer and bounded canary remain unavailable. Do not replace
the missing marker with invented evidence or an `env:`/`file:` key reference.

## Rollback order

1. Deny signer IPC and keep the deployment network policy deny-all.
2. Revoke every unconsumed permit and move the canary to `CANARY_PAUSED`.
3. Preserve `UNKNOWN` and terminal outbox/settlement records without mutation.
4. Reconcile every in-flight intent from independent finalized evidence.
5. Only then revert signer binaries, policy, or release generation.
