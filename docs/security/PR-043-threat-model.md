# PR-043 threat model: wallet/key isolation and supply chain

## Scope boundary

PR-043 is a security hardening slice. It does not enable live trading, add a
sender, compile a new transaction path, or introduce a keypair loader. The goal
is to make the next live-gate work require an isolated signer boundary and a
repeatable supply-chain review.

## Assets protected

- Solana wallet signing authority.
- Jito authentication credential.
- Unsigned transaction message identity before signing.
- Runtime configuration, redacted status/log output, and fixtures.
- Production image dependency set, SBOM, license inventory, and provenance.

## Trust boundaries

1. **Planner/runtime boundary:** detectors and planners may produce unsigned
   message evidence, but they must not receive a signing handle.
2. **Signer boundary:** an unsigned message must pass `SignerPolicy.evaluate`
   before any isolated signer adapter can sign it.
3. **Provider boundary:** Jupiter/RPC/Jito responses remain untrusted until
   schema, slot, allowlist, and replay checks accept them.
4. **Configuration boundary:** production uses references such as `env:`,
   `file:`, or `keychain:`; inline private key material is forbidden.
5. **Artifact boundary:** production images require dependency audit policy,
   SBOM, license inventory, and signed provenance evidence before promotion.

## Threats and fail-closed controls

| Threat | Control in this PR |
| --- | --- |
| Inline Phantom/Solana key in env/config/log | `src.security.secret_scan` reports redacted findings and never logs values. |
| Unsigned message swapped before signing | `SignerPolicy` binds permit to SHA-256 of the exact unsigned bytes. |
| Malicious route adds an unknown program | `SignerPolicy` rejects non-allowlisted program IDs before signing. |
| Oversized or empty unsigned message | `SignerPolicy` rejects before signer handoff. |
| RPC/API poisoning or malicious schema | Threat remains outside signer and must still pass provider/schema gates; malicious fixtures are documented and tested fail-closed. |
| Critical dependency CVE | `DependencyAuditPolicy` blocks vulnerabilities at or above critical severity. |
| Unknown vulnerability severity | Default policy fails closed on unknown severity. |
| Missing SBOM/license/provenance for release | `config/security_supply_chain_policy.json` records these as production requirements. |
| Credential rotation not rehearsed | `docs/security/key_rotation_runbook.md` defines the drill. |

## Non-goals

- No private key decryption, storage, or signing implementation.
- No cloud KMS, macOS Keychain, HSM, or hardware-wallet integration.
- No networked vulnerability scanning from CI in this PR.
- No automatic live promotion based on green security tests.

## Future integration hooks

- The live sender should accept only a `SignerPolicyPermit` plus an isolated
  signer reference, never raw key material.
- PR-045/PR-046 should require the security gate before release/canary.
- PR-047 should attach SBOM, image signature, license inventory, and rotation
  drill evidence to the release manifest.
