# NEW-MEGA-PR-02 V7 follow-up start

This draft branch is a narrow V7 follow-up for **NEW-MEGA-PR-02**.

It exists because the roadmap-level start thread is already open in PR #410, while Audit V7 adds three concrete provider-plane defects that deserve a separate reviewable checkpoint:

- `IMPL-98` — canonical recording/config readers still use check-then-open TOCTOU patterns
- `IMPL-100` — durable Jupiter quota persists monotonic timestamps across reboot
- `IMPL-101` — durable Jupiter account policy is not persisted, so conflicting managers can enforce different limits

This start slice is intentionally fail-closed and does **not** claim that NEW-MEGA-PR-02 is complete.
It does **not** enable live trading, signer paths, sender paths, submission, or private-key handling.

## Planned implementation follow-up

1. Replace security-sensitive file reads with a single-open `O_NOFOLLOW` / `fstat` / `read` / `fstat` boundary.
2. Replace reboot-unsafe monotonic persistence with trusted wall/epoch time plus boot/session identity, or conservative restart reconstruction.
3. Persist one immutable/versioned policy fingerprint per Jupiter API account and fail closed on conflicting policy opens.
4. Bind quota/cooldown/cache state to one durable account-wide authority shared across processes and restarts.
5. Add focused negative tests for path-swap attacks, rebooted quota reconstruction, and conflicting manager policy opens.

## Review posture

Treat this PR as a V7 addendum thread for NEW-MEGA-PR-02, not as the full mega-PR closure.
