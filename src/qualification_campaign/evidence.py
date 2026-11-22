"""Campaign evidence facade over the existing durable raw stream authority.

No second SQLite factory. One campaign per journal; negative events and physical
attempt reservations survive restart. Replay uses retained bytes only.
"""

import errno
import json
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

# Reservation overhead: projected bytes reserved per new retained event on
# top of the encoded payload.  SQLite grows the database and its WAL in page
# increments, so one append transaction can add a few pages of journal/WAL
# bytes beyond the encoded payload; the slack bounds that single-transaction
# growth.  Actual filesystem sizes are reconciled after commit: any
# over-commitment fails closed (CAMPAIGN_STORAGE_BUDGET_EXCEEDED) and blocks
# every subsequent reservation — the budget can never be silently exceeded.
_STORAGE_RESERVATION_SLACK = 16384


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


class CampaignEvidenceStore:
    def __init__(
        self,
        journal: RecoverableStreamJournal,
        manifest: CampaignManifest,
        *,
        wall_ns=time.time_ns,
        campaign_budgets: CampaignBudgets | None = None,
        ledger_path: Path | None = None,
    ):
        self.wall_ns = wall_ns
        self.journal = journal
        self.manifest = manifest
        self.campaign_budgets = campaign_budgets
        # The approval replay ledger lives in the same campaign output
        # directory, so it is part of the SAME storage_bytes_max scope (no
        # separate limit/retention — the unified campaign budget covers it).
        self.ledger_path = Path(ledger_path) if ledger_path is not None else None
        db_path = journal.db.execute("PRAGMA database_list").fetchone()[2]
        self.db_path = Path(db_path)
        self.lock_path = Path(db_path + ".campaign-lock")
        self.blob_dir = Path(db_path + ".blobs")
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
        lock file, every blob/staging file, and — when wired by the CLI —
        the approval replay ledger database with its WAL/SHM sidecars.
        Filesystem truth only; a missing file counts as zero, never as an
        assumed value.
        """

        total = 0
        ledger_paths: tuple[Path, ...] = ()
        if self.ledger_path is not None:
            ledger_paths = (
                self.ledger_path,
                Path(str(self.ledger_path) + "-wal"),
                Path(str(self.ledger_path) + "-shm"),
            )
        for path in (
            self.db_path,
            Path(str(self.db_path) + "-wal"),
            Path(str(self.db_path) + "-shm"),
            self.lock_path,
            *ledger_paths,
        ):
            try:
                total += path.stat().st_size
            except FileNotFoundError:
                pass
        if self.blob_dir.exists():
            total += sum(f.stat().st_size for f in self.blob_dir.glob("*"))
        return total

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
        body = {**payload, "campaign_manifest_hash": self.manifest.campaign_id}
        stored = body
        encoded = canonical_bytes(body)
        if self.campaign_budgets is not None:
            # Universal reservation for EVERY append, inline and blob alike
            # (owner review CAM-04 fix): projected campaign footprint growth
            # is reserved before any write under the same cross-process
            # serialization.  storage_bytes_max is the single limit of the
            # WHOLE campaign artifact footprint, including the approval
            # replay ledger and its sidecars.
            projected = (
                self.campaign_storage_bytes()
                + len(encoded)
                + _STORAGE_RESERVATION_SLACK
            )
            if projected > self.campaign_budgets.storage_bytes_max:
                raise ValueError("CAMPAIGN_STORAGE_BUDGET_EXHAUSTED")
        if len(encoded) > 750_000:
            if len(encoded) > 16 * 1024 * 1024:
                raise ValueError("EVIDENCE_BLOB_TOO_LARGE")
            self.blob_dir.mkdir(exist_ok=True)
            name = digest(body)
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
            stored = {
                "kind": "blob_reference",
                "raw_payload_ref": name,
                "raw_payload_hash": name,
                "campaign_manifest_hash": self.manifest.campaign_id,
            }
        previous = [
            e
            for e in self.journal.events(available_at_ns=2**63 - 1)
            if e.source == source
        ]
        event = RawStreamEvent(
            source,
            self.manifest.campaign_id,
            1,
            previous[-1].cursor + 1 if previous else 1,
            available,
            observed_at_ns,
            source,
            "prequal.observation.v1",
            canonical_bytes(stored).decode(),
            digest(stored),
            previous[-1].block_hash if previous else "GENESIS",
        )
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
