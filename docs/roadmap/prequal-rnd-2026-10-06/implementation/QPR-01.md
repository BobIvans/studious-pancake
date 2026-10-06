# QPR-01 — canonical runtime/release/campaign identity

Canonical authority is `src/resources/runtime_authority.json`; `config/runtime_authority.json` is an exact byte mirror. Runtime bootstrap, release qualification and CampaignManifest consume its canonical JSON SHA256. Capabilities, rooted policy and market-source catalog generations are pinned in the same artifact. Generation changes require an explicit authority refresh. An installed wheel uses the same packaged resources. The historical `runtime_authority_map.json` is development inventory, not a release identity; PR queue lives in `config/development_queue.json`.

AUTH-001: implemented. AUTH-002: implemented. CLI-001: installed adapters use the shared parser-owned command identity; argument values named `run` cannot switch the dispatch. No signer/sender/submission authority was added.

CampaignManifest requires exact repository/main SHAs, policy/config digests and source-generation digests. Factory admission rejects dirty source trees and a main SHA that is not an ancestor. Different identities cannot be combined. Native campaign wiring follows in QPR-02; source intake follows in QPR-03. Production remains blocked by existing deployment, continuous-capture, holdout, cost and soak prerequisites.

Validation: 24 focused identity/authority/CLI tests and 26 installed-product/release/authority regression tests passed. CPython 3.13 wheel installed; `flashloan-bot run --mode disabled` and the installed authority outside the checkout returned the same digest.

Exact commit receipts are generated after each implementation commit outside the checkout to avoid self-referential SHA fields. R&D package remains the historical planning input; dispositions here describe current implementation.
