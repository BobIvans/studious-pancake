Storage capacity update: default data-storage limits doubled.
Source: b42203f2126571e52e7ca20d8485030b405527ac
Nominal data allowance 8–30 GB -> 16–60 GB, bounded by real spare disk.
Usable spare disk share 50% -> 100%, after reserve max(30 GB, 25% of total disk).
Parquet partition 10,000 -> 20,000 rows; payload 64 -> 128 MiB.
Repository blob 8 -> 16 MiB; portable archive content 512 -> 1024 MiB.
Current measured allowance: 409777152 bytes;
status STORAGE_PRESSURE. This does not enlarge physical disk.

No oldest-25% deletion policy or background eviction loop is installed.
Pruning remains an explicit verified operation, minimum age 24 hours by default,
with pins, complete references, samples, compaction and exact replay checked.
Eligible inline payloads are offloaded into exact Parquet, not permanently erased.
Journal admission is capped only when max_journal_bytes is explicitly supplied;
explicit caller caps are honored as supplied and uncapped owners stay uncapped.

Verification: 42 focused tests, 29-source mypy, full offline repository gate;
100 exact replay events, 96 reversible archives, protected evidence preserved.
Dependencies unchanged; the prior online dependency audit passed.
Real Mainnet campaign and remote CI remain unverified; no merge performed.
