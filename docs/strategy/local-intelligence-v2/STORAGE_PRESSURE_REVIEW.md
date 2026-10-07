# PR #577 storage-pressure review

Audited main: `663a18b1b34d9aa1a7706fe8a39837659b5e1ac6` (merge of PR #574).
The manager remains a projection over AGG-02;
it creates no competing raw, episode, quota or lifecycle store.

The existing repeated installed paper supervisor is the scheduling owner. It
checks the source's explicit pressure port before the durable batch begins and
after typed admission-blocked results or exceptions have unwound. A3 preserves
that typed reason in its durable terminal record, and the canonical authority
records pressure pause incidents. Both installed entrypoints return a blocked
exit code when the supervisor pauses. No journal background thread is added.

The reviewed installed draft source and bounded native CPMM capture do not expose
a long-running AGG-02 raw journal plus complete retention inventory. That deployed
raw-collection binding is explicitly `BLOCKED_NOT_WIRED`; the source capability
must come from the owner, and neither paths nor proof inventory are guessed.
`StoragePressureBoundary` is the callable adapter for an owner providing those
facts. CORE-V1 materialization and A3 forward it to the existing supervisor.

Manager safety fixes:

- NORMAL only measures; it does not open a writable journal, create a directory
  or create a lock file.
- One mutating pressure cycle holds an advisory lock on the existing journal
  inode across CLI/supervisor processes. SQLite append is never the trigger site.
- Candidate selection checks actual owner availability, gap and pin facts,
  rejects duplicate records and excludes the supplied evidence-reference set.
- Compaction preflight reserves payload, envelope/proof metadata, WAL expansion
  and fixed overhead on the measured filesystem. Outputs elsewhere are rejected.
- Pressure plans, original clocks, selected events and terminal receipts are
  persisted by stable batch identity. Input rebinding fails closed. Prepared
  tombstones and completed owner offloads resume without duplicate archives.
- Exact archive replay is independently checked even on cached receipt reuse.
- Post-operation physical CRITICAL pressure still pauses admission, even when
  the logical inline-payload target was met. No physical shrink is invented.
- CLI pause verdicts exit with 3; installed supervisor pause exits with 7.

Tests cover byte thresholds/hysteresis, pins, complete reference inventories,
owner age, no-mutation NORMAL, headroom, duplicate records, exact replay,
cross-process exclusion, crashes after offload and before terminal publication,
stable retry, corrupt cached archives, CLI dry-run/execute, supervisor batch and
typed-blocked triggers, append rollback and canonical durable blocker records.

No merge is authorized by this review. Verify the current PR head and every
required CI result before considering acceptance; real long-running raw binding
remains separately blocked until its canonical owner supplies the port.
