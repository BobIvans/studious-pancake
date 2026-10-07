# Provider Adapter Checklist

- [ ] Source dossier current and generation pinned
- [ ] Typed request builder shared with conformance probe
- [ ] Host/method allowlist
- [ ] TLS on, redirects off unless reviewed
- [ ] Secret reference only; no raw secrets in logs/body receipts
- [ ] Physical-attempt quota
- [ ] Retry consumes quota
- [ ] 401/403/429/5xx typed outcomes
- [ ] Bounded body/string/list sizes
- [ ] Required response paths and types
- [ ] Request fingerprint + response hash
- [ ] observed_at + available_at
- [ ] slot/root/sequence where applicable
- [ ] cancellation propagates
- [ ] source generation in every observation
- [ ] discovery-only default
- [ ] replay fixture from captured redacted/raw evidence
