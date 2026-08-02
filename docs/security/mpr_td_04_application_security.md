# MPR-TD-04 application-security closure

The new security boundary provides strict bounded JSON decoding, duplicate-key and non-finite-number rejection, owned-root path resolution, atomic bounded writes, pre-extraction ZIP/TAR validation, argument-vector subprocess policy, and deny-by-default URL admission.

These primitives remain sender-free. They do not load keys, sign messages, submit transactions, or authorize unrestricted network access.

The committed attack-surface manifest covers the new release/security boundaries. Repository-wide historical scripts and compatibility modules are not falsely declared migrated; the verifier reports predecessor and external-artifact blockers separately.
