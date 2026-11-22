"""Campaign evidence facade over the existing durable raw stream authority.

No second SQLite factory. One campaign per journal; negative events and physical
attempt reservations survive restart. Replay uses retained bytes only.
"""

import errno
import json
import sqlite3
import time
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

# Shared POSIX-exact flock binding (R11 follow-up): standard-library fcntl on
# POSIX, msvcrt.locking-based shim on win32.  Platform-conditional sys.platform
# guard and the POSIX-equivalence argument live in the compat module.
from src.platform_compat.flock import fcntl
from src.market.streams import RawStreamEvent, RecoverableStreamJournal
from .identity import CampaignManifest, canonical_bytes, digest

# STRICT STORAGE CEILING (owner security-closure item R-A): storage_bytes_max
# is a strict physical ceiling.  Before ANY write, the reservation charges the
# campaign footprint with an analytically derived worst-case bound of the
# growth a single SQLite append transaction can produce, so the post-commit
# actual footprint provably cannot exceed the approved cap:
#
#   journal_growth_bound(row_len, page) =
#       row_len                                  # row content
#       + page                                   # partial tail page in the DB file
#       + (ceil(row_len / page) + 8) * (page + 24)
#                                                # one WAL frame (page + 24 B
#                                                # frame header) per modified
#                                                # page: row pages + db-size
#                                                # page + B-tree index pages
#                                                # (O(log n) depth, capped
#                                                # by the +8 frame margin)
#
# Auto-checkpoint only moves WAL frames back into the database file, so the
# DB+WAL sum is conserved and the bound holds across checkpoints.  page_size
# is read from the journal connection at runtime (PRAGMA page_size), never
# assumed.  Post-commit reconciliation remains as a backstop: if an assumption
# is ever violated, the over-commitment fails closed and blocks every
# subsequent write — the budget can never be silently exceeded.
_JOURNAL_WAL_FRAME_HEADER_BYTES = 24
_JOURNAL_WAL_MARGIN_FRAMES = 8


# Conservative pre-write creation/growth reserves for the campaign stores
# (owner security-closure round 3, item 2).  These are charged by the CLI
# BEFORE any persistent campaign artifact is created, so the approved
# storage_bytes_max covers the whole campaign footprint from the first byte:
#   - ledger: schema SQL + meta rows + reserve/finalize records + WAL/SHM
#   - evidence journal: schema SQL + indexes + WAL/SHM
#   - authority store: schema SQL + WAL/SHM
# They are intentionally over-reserved (fail-closed direction); the
# post-write reconciliations catch any under-reservation and block.
LEDGER_CREATION_RESERVE_BYTES = 131_072
JOURNAL_CREATION_RESERVE_BYTES = 262_144
AUTHORITY_CREATION_RESERVE_BYTES = 262_144


def journal_growth_bound(row_len: int, page_size: int) -> int:
    """Conservative worst-case DB+WAL byte growth of one append transaction."""

    if row_len <= 0 or page_size <= 0:
        raise ValueError("journal growth bound requires positive sizes")
    row_pages = -(-row_len // page_size)
    wal_frames = row_pages + _JOURNAL_WAL_MARGIN_FRAMES
    return (
        row_len + page_size + wal_frames * (page_size + _JOURNAL_WAL_FRAME_HEADER_BYTES)
    )


# Ledger reserve/finalize transactions are small rows; reserve their
# worst-case page/WAL growth against the default SQLite page size (the
# ledger store does not override it).
LEDGER_TRANSACTION_RESERVE_BYTES = 2 * journal_growth_bound(2048, 4096)


def artifact_footprint_bytes(paths) -> int:
    """Filesystem byte sum over an explicit path list (missing = 0, never assumed)."""

    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except FileNotFoundError:
            pass
    return total


def reconcile_materialized_artifacts(actual_paths, budgets) -> int:
    """SECURITY CLOSURE v3 backstop: a store that just materialized must fit
    the approved budget immediately (its reserves were computed with the
    4096 page-size assumption; reconciliation uses actual bytes)."""

    actual = artifact_footprint_bytes(actual_paths)
    if budgets is not None and actual > budgets.storage_bytes_max:
        raise ValueError("CAMPAIGN_STORAGE_BUDGET_EXCEEDED")
    return actual


SUPPORTED_SQLITE_PAGE_SIZE = 4096


def require_supported_page_size(db_path: Path, *, store: str) -> None:
    """Fail closed on an unsupported SQLite page size BEFORE that store writes.

    SECURITY CLOSURE v3 (page-size enforcement): the preflight reserve is
    derived from a 4096-byte page. All three campaign stores (journal, ledger,
    authority) must therefore be checked independently. ``sqlite_page_size``
    returns ``None`` for a not-yet-created file, which will be created with the
    supported default; an existing store with any other page size is rejected
    before its constructor can perform persistent writes.
    """

    size = sqlite_page_size(db_path)
    if size is not None and size != SUPPORTED_SQLITE_PAGE_SIZE:
        raise ValueError(f"CAMPAIGN_{store}_PAGE_SIZE_UNSUPPORTED")


def sqlite_page_size(db_path: Path) -> int | None:
    """Actual SQLite page size of a persisted store (read-only; None if absent).

    SECURITY CLOSURE v3: page sizes are measured, never assumed — the
    preflight reserves use the 4096 default, and this helper produces the
    durable measured receipt for journal/ledger/authority.
    """

    if not db_path.exists():
        return None
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        return int(connection.execute("PRAGMA page_size").fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        connection.close()


@dataclass(frozen=True)
class CampaignBudgets:
    """Operator-approved campaign-global budgets (CAM-04 / review point 4).

    Values come only from the signed approved plan; unknown or unbounded
    values fail closed at construction.
    """

    rpc_physical_attempts_max: int
    storage_bytes_max: int
    external_data_spend_usd_max: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.rpc_physical_attempts_max, int) or not (
            0 < self.rpc_physical_attempts_max <= 100_000
        ):
            raise ValueError("CAMPAIGN_ATTEMPT_BUDGET_UNBOUNDED")
        if not isinstance(self.storage_bytes_max, int) or not (
            0 < self.storage_bytes_max <= 2**30
        ):
            raise ValueError("CAMPAIGN_STORAGE_BUDGET_UNBOUNDED")
        if self.external_data_spend_usd_max != 0:
            raise ValueError("CAMPAIGN_PAID_SPEND_FORBIDDEN")

    @classmethod
    def from_plan_budgets(cls, budgets: dict) -> "CampaignBudgets":
        return cls(
            rpc_physical_attempts_max=budgets["rpc_physical_attempts_max"],
            storage_bytes_max=budgets["storage_bytes_max"],
            external_data_spend_usd_max=budgets["external_data_spend_usd_max"],
        )


def prepare_event(
    source, campaign_id, payload, *, available_at_ns, observed_at_ns, previous_events
):
    """Build the exact event and its EXACT serialized row length.

    The row length replicates the journal INSERT serialization byte-for-byte
    (``json.dumps(asdict(event), sort_keys=True)``): the payload is carried as
    a nested JSON string, so quotes/backslashes are escaped a second time and
    the reservation must account for the serialized row, not the canonical
    payload (owner security-closure item 1).
    """

    from dataclasses import asdict

    body = {**payload, "campaign_manifest_hash": campaign_id}
    encoded = canonical_bytes(body)
    is_blob = len(encoded) > 750_000
    name = digest(body) if is_blob else None
    if is_blob:
        stored = {
            "kind": "blob_reference",
            "raw_payload_ref": name,
            "raw_payload_hash": name,
            "campaign_manifest_hash": campaign_id,
        }
    else:
        stored = body
    previous = [e for e in previous_events if e.source == source]
    event = RawStreamEvent(
        source,
        campaign_id,
        1,
        previous[-1].cursor + 1 if previous else 1,
        available_at_ns,
        observed_at_ns,
        source,
        "prequal.observation.v1",
        canonical_bytes(stored).decode(),
        digest(stored),
        previous[-1].block_hash if previous else "GENESIS",
    )
    serialized_row = json.dumps(asdict(event), sort_keys=True)
    return encoded, is_blob, name, event, len(serialized_row)


class CampaignEvidenceStore:
    def __init__(
        self,
        journal: RecoverableStreamJournal,
        manifest: CampaignManifest,
        *,
        wall_ns=time.time_ns,
        campaign_budgets: CampaignBudgets | None = None,
        ledger_path: Path | None = None,
        extra_artifacts: tuple[Path, ...] = (),
    ):
        self.wall_ns = wall_ns
        self.journal = journal
        self.manifest = manifest
        self.campaign_budgets = campaign_budgets
        # The approval replay ledger lives in the same campaign output
        # directory, so it is part of the SAME storage_bytes_max scope (no
        # separate limit/retention — the unified campaign budget covers it).
        self.ledger_path = Path(ledger_path) if ledger_path is not None else None
        # Explicitly enumerated remaining campaign artifacts (e.g.
        # campaign-manifest.json, campaign-start-blocked.json, report.json):
        # the storage ceiling scope is the WHOLE campaign footprint and no
        # campaign file is excluded from accounting.
        self.extra_artifacts = tuple(Path(p) for p in extra_artifacts)
        # Outstanding creation reservations (owner closure round 4): named
        # byte reserves for campaign stores that are NOT yet materialized
        # (e.g. authority.sqlite).  They are durable journal events, so a
        # restart cannot let journal appends consume a store's reserved
        # budget, and they are released only when the store is materialized
        # and reconciled against its actual DB/WAL/SHM footprint.
        db_path = journal.db.execute("PRAGMA database_list").fetchone()[2]
        self.db_path = Path(db_path)
        self.lock_path = Path(db_path + ".campaign-lock")
        self.blob_dir = Path(db_path + ".blobs")
        self.page_size = int(journal.db.execute("PRAGMA page_size").fetchone()[0])
        if self.campaign_budgets is not None and self.page_size != (
            SUPPORTED_SQLITE_PAGE_SIZE
        ):
            # The CLI preflight reservation is derived from the documented
            # default page size; unsupported configurations are rejected
            # before any persistent write instead of silently under-reserving.
            raise ValueError("CAMPAIGN_JOURNAL_PAGE_SIZE_UNSUPPORTED")
        retained = journal.events(available_at_ns=2**63 - 1)
        for e in retained:
            if e.partition != manifest.campaign_id:
                raise ValueError("CAMPAIGN_GENERATION_MISMATCH")
        if not retained:
            self.append(
                "campaign",
                {"kind": "manifest", "manifest": manifest.to_dict()},
                observed_at_ns=self.wall_ns(),
            )

    def campaign_storage_bytes(self) -> int:
        """Aggregate campaign artifact footprint (review point 4).

        Includes the journal database, its WAL/SHM sidecars, the campaign
        lock file, every blob/staging file, the approval replay ledger
        database with its WAL/SHM sidecars, and every explicitly enumerated
        extra campaign artifact (manifest JSON, blocked receipt, report).
        Filesystem truth only; a missing file counts as zero, never as an
        assumed value.
        """

        ledger_paths: tuple[Path, ...] = ()
        if self.ledger_path is not None:
            ledger_paths = (
                self.ledger_path,
                Path(str(self.ledger_path) + "-wal"),
                Path(str(self.ledger_path) + "-shm"),
            )
        return artifact_footprint_bytes(
            (
                self.db_path,
                Path(str(self.db_path) + "-wal"),
                Path(str(self.db_path) + "-shm"),
                self.lock_path,
                *ledger_paths,
                *self.extra_artifacts,
            )
        ) + (
            sum(f.stat().st_size for f in self.blob_dir.glob("*"))
            if self.blob_dir.exists()
            else 0
        )

    def append(
        self,
        source: str,
        payload: dict,
        *,
        observed_at_ns: int,
        available_at_ns: int | None = None,
    ) -> str:
        """Serialize every event append across processes/threads (CAM-04).

        The previous per-attempt-only lock left plain appends' cursor
        allocation unserialized (race hypothesis, REPRODUCTION_REQUIRED);
        routing every append through the same cross-process flock makes
        reservations and writes share one boundary.
        """

        with self.lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return self._append_unlocked(
                    source,
                    payload,
                    observed_at_ns=observed_at_ns,
                    available_at_ns=available_at_ns,
                )
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _append_unlocked(
        self,
        source: str,
        payload: dict,
        *,
        observed_at_ns: int,
        available_at_ns: int | None = None,
    ) -> str:
        available = (
            max(observed_at_ns, self.wall_ns())
            if available_at_ns is None
            else available_at_ns
        )
        previous_events = self.journal.events(available_at_ns=2**63 - 1)
        encoded, is_blob, name, event, row_len = prepare_event(
            source,
            self.manifest.campaign_id,
            payload,
            available_at_ns=available,
            observed_at_ns=observed_at_ns,
            previous_events=previous_events,
        )
        blob_bytes = len(encoded) if is_blob else 0
        if self.campaign_budgets is not None:
            # STRICT PHYSICAL CEILING: reserve the exact serialized journal
            # row (nested-JSON escaping included) plus the exact blob bytes,
            # bounded by journal_growth_bound for DB/WAL/index page growth,
            # BEFORE any write.
            projected = (
                self.campaign_storage_bytes()
                + blob_bytes
                + journal_growth_bound(row_len, self.page_size)
            )
            if projected > self.campaign_budgets.storage_bytes_max:
                # SECURITY CLOSURE v3: the authority store is materialized
                # before the evidence journal, so the projection above is
                # charged its real bytes; no append can spend a reserve
                # belonging to a store that is not yet on disk.
                raise ValueError("CAMPAIGN_STORAGE_BUDGET_EXHAUSTED")
        if is_blob:
            self.blob_dir.mkdir(exist_ok=True)
            target = self.blob_dir / (name + ".json")
            if target.exists():
                if target.is_symlink() or target.read_bytes() != encoded:
                    raise ValueError("EVIDENCE_BLOB_HASH_MISMATCH")
            else:
                size = sum(f.stat().st_size for f in self.blob_dir.glob("*.json"))
                if size + len(encoded) > self.journal.max_payload_bytes:
                    raise ValueError("EVIDENCE_BLOB_STORAGE_BUDGET_EXHAUSTED")
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=self.blob_dir, suffix=".tmp", delete=False
                    ) as handle:
                        temporary = Path(handle.name)
                        handle.write(encoded)
                        handle.flush()
                        os.fsync(handle.fileno())
                    try:
                        os.link(temporary, target)
                    except FileExistsError:
                        if target.is_symlink() or target.read_bytes() != encoded:
                            raise ValueError("EVIDENCE_BLOB_HASH_MISMATCH")
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
                if os.name == "posix":
                    # getattr keeps the POSIX-only open flag static-analysis
                    # clean under win32 mypy (mypy does not narrow os.name);
                    # on POSIX it resolves to os.O_DIRECTORY exactly.
                    fd = os.open(self.blob_dir, getattr(os, "O_DIRECTORY", 0))
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                # win32: os.open cannot open a directory handle.  The blob
                # bytes are fsynced above before the hardlink, and NTFS
                # journals the link metadata, so a lost dirent cannot
                # corrupt retained evidence: replay fails closed on a
                # missing or mismatched blob reference.  POSIX keeps the
                # exact directory-fsync durability step.
        self.journal.append(event)
        if self.campaign_budgets is not None:
            # Reconcile actual filesystem sizes after commit; over-commitment
            # fails closed and blocks every subsequent reservation (the
            # reconciled event itself stays persisted — documented semantics).
            if self.campaign_storage_bytes() > self.campaign_budgets.storage_bytes_max:
                raise ValueError("CAMPAIGN_STORAGE_BUDGET_EXCEEDED")
        return event.identity

    def claim_attempt(self, profile) -> None:
        if (
            dict(self.manifest.source_generations).get(profile.profile_id)
            != profile.generation
        ):
            raise ValueError("SOURCE_GENERATION_MISMATCH")
        # Serialize campaign-cap reservations across cooperating processes.
        with self.lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                events = self.replay()
                attempts = [e for e in events if e.get("kind") == "attempt"]
                spent = sum(
                    e.get("provider_id") == profile.profile_id for e in attempts
                )
                if spent >= profile.campaign_attempt_cap:
                    raise ValueError("CAMPAIGN_ATTEMPT_BUDGET_EXHAUSTED")
                if self.campaign_budgets is not None:
                    # Campaign-global physical attempt cap: every provider
                    # profile and every retry consumes the same durable pool.
                    if len(attempts) >= self.campaign_budgets.rpc_physical_attempts_max:
                        raise ValueError("CAMPAIGN_GLOBAL_ATTEMPT_BUDGET_EXHAUSTED")
                    # Storage reservation for the attempt event happens in
                    # _append_unlocked (universal for every append).
                self._append_unlocked(
                    profile.profile_id,
                    {
                        "kind": "attempt",
                        "provider_id": profile.profile_id,
                        "source_generation": profile.generation,
                    },
                    observed_at_ns=self.wall_ns(),
                )
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def replay(self) -> tuple[dict, ...]:
        events = self.journal.events(available_at_ns=2**63 - 1)
        for e in events:
            if e.partition != self.manifest.campaign_id:
                raise ValueError("CAMPAIGN_GENERATION_MISMATCH")
            # The underlying journal is immutable by contract, verify hashes on replay.
            if digest(json.loads(e.payload_json)) != e.block_hash:
                raise ValueError("EVIDENCE_HASH_MISMATCH")
        return tuple(self.expand(e.payload_json) for e in events)

    def expand(self, serialized):
        body = json.loads(serialized)
        if body.get("kind") == "blob_reference":
            name = body["raw_payload_ref"]
            if (
                not isinstance(name, str)
                or len(name) != 64
                or any(c not in "0123456789abcdef" for c in name)
            ):
                raise ValueError("EVIDENCE_BLOB_REFERENCE_INVALID")
            target = self.blob_dir / (name + ".json")
            if target.is_symlink():
                raise ValueError("EVIDENCE_BLOB_REFERENCE_INVALID")
            body = json.loads(target.read_text())
            if digest(body) != name:
                raise ValueError("EVIDENCE_BLOB_HASH_MISMATCH")
        if body.get("campaign_manifest_hash") != self.manifest.campaign_id:
            raise ValueError("CAMPAIGN_GENERATION_MISMATCH")
        return body

    @property
    def head(self):
        return digest(
            [asdict(e) for e in self.journal.events(available_at_ns=2**63 - 1)]
        )


def redact_payload(value, headers):
    """Preserve public response shape, removing credential reflections only."""
    secrets: list[str] = []
    for name, token in (headers or {}).items():
        if name.lower() in ("authorization", "x-api-key") and token:
            secrets.extend((token, token.removeprefix("Bearer ")))
    forbidden = {
        "authorization",
        "apikey",
        "secret",
        "password",
        "accesstoken",
        "privatekey",
    }

    def clean(item):
        if isinstance(item, dict):
            return {
                k: (
                    "<redacted>"
                    if "".join(c for c in str(k).lower() if c.isalnum()) in forbidden
                    else clean(v)
                )
                for k, v in item.items()
            }
        if isinstance(item, list):
            return [clean(v) for v in item]
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, "<redacted>")
        return item

    return clean(value)
