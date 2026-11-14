"""Streaming offline datasets over the existing MDE availability/cache owners.

This view does not acquire data or run a second market runtime. Input origin is
an offline fixture; real acquisition needs a separately qualified provider owner.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterator

from src.market.cache import DerivedCacheKey, GenerationBoundCache
from .contracts import NormalizedObservation, select_as_of

SCHEMA = "occ.research-observation.v1"
MAX_RECORD_BYTES = 1024 * 1024  # Frame budget, never a total dataset record cap.


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("REGULAR_DATASET_REQUIRED")
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            hasher.update(block)
    return hasher.hexdigest()


def unique_json(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def bad_constant(_value):
        raise ValueError("NON_FINITE_JSON_NUMBER")

    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=bad_constant
    )


@dataclass(frozen=True, slots=True)
class ResearchObservation:
    observation: NormalizedObservation
    payload_bytes: bytes
    anchor: str
    upstream_families: tuple[str, ...]

    @property
    def payload(self) -> dict[str, Any]:
        return unique_json(self.payload_bytes)

    @property
    def opportunity_id(self) -> str:
        return digest(
            {
                "instrument": self.observation.instrument_id,
                "instrument_version": self.observation.instrument_version,
                "anchor": self.anchor,
                "payload": self.observation.raw_payload_hash,
            }
        )


def iter_observations(path: Path) -> Iterator[ResearchObservation]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("REGULAR_DATASET_REQUIRED")
    with path.open("rb") as stream:
        while raw := stream.readline(MAX_RECORD_BYTES + 1):
            if len(raw) > MAX_RECORD_BYTES:
                raise ValueError("DATASET_RECORD_BUDGET_EXCEEDED")
            item = unique_json(raw)
            if not isinstance(item, dict) or set(item) != {
                "schema",
                "origin",
                "observation",
                "payload",
                "anchor",
                "upstream_families",
            }:
                raise ValueError("DATASET_RECORD_SCHEMA")
            if item["schema"] != SCHEMA or item["origin"] != "OFFLINE_FIXTURE":
                raise ValueError("REAL_ACQUISITION_RECEIPT_REQUIRED")
            families = item["upstream_families"]
            if (
                not isinstance(item["anchor"], str)
                or not item["anchor"]
                or not isinstance(families, list)
                or not families
                or not all(isinstance(f, str) and f for f in families)
                or len(set(families)) != len(families)
                or not isinstance(item["payload"], dict)
            ):
                raise ValueError("DATASET_PROVENANCE_REQUIRED")
            obs = NormalizedObservation(**item["observation"])
            if type(obs.missing) is not bool:
                raise ValueError("MISSING_OBSERVATION_BOOLEAN_REQUIRED")
            payload = canonical(item["payload"])
            if hashlib.sha256(payload).hexdigest() != obs.raw_payload_hash:
                raise ValueError("RAW_PAYLOAD_DIGEST_MISMATCH")
            yield ResearchObservation(
                obs, payload, item["anchor"], tuple(sorted(families))
            )


class ResearchDatasetView:
    """Frozen reference plus the installed generation-aware derived cache."""

    def __init__(self, path: Path, expected_digest: str, *, cache=None):
        self.path, self.expected_digest = path, expected_digest
        self.cache = cache if cache is not None else GenerationBoundCache()
        self.verify()

    def verify(self) -> None:
        if file_digest(self.path) != self.expected_digest:
            raise ValueError("DATASET_SOURCE_DRIFT")

    def decisions(self, *, cutoff: int, max_age: int, anchor: str):
        if (
            type(cutoff) is not int
            or cutoff < 0
            or type(max_age) is not int
            or max_age < 0
        ):
            raise ValueError("INTEGER_CLOCK_BUDGET_REQUIRED")
        self.verify()
        # Derived on-disk index has no record-count cap and no durable authority.
        # Selection delegates to the installed MDE revision/availability owner.
        with tempfile.TemporaryDirectory(prefix="occ-pit-") as directory:
            db = sqlite3.connect(str(Path(directory) / "index.sqlite3"))
            try:
                db.execute(
                    "CREATE TABLE latest(instrument TEXT, observation TEXT, value BLOB, PRIMARY KEY(instrument, observation))"
                )
                for row in iter_observations(self.path):
                    obs = row.observation
                    admitted, _ = select_as_of((obs,), cutoff=cutoff)
                    if not admitted:
                        continue
                    key = (obs.instrument_id, obs.observation_id)
                    prior = db.execute(
                        "SELECT value FROM latest WHERE instrument=? AND observation=?",
                        key,
                    ).fetchone()
                    if prior is not None:
                        previous = NormalizedObservation(**unique_json(prior[0]))
                        if previous.revision_id == obs.revision_id and previous != obs:
                            raise ValueError("CONFLICTING_OBSERVATION_REVISION")
                        chosen, _ = select_as_of((previous, obs), cutoff=cutoff)
                        obs = chosen[0]
                    db.execute(
                        "INSERT OR REPLACE INTO latest VALUES (?,?,?)",
                        (*key, canonical(asdict(obs))),
                    )
                for row in iter_observations(self.path):
                    obs = row.observation
                    selected, proof = select_as_of((obs,), cutoff=cutoff)
                    prior = db.execute(
                        "SELECT value FROM latest WHERE instrument=? AND observation=?",
                        (obs.instrument_id, obs.observation_id),
                    ).fetchone()
                    reason = (
                        "NOT_AVAILABLE_AT_DECISION"
                        if not selected
                        else (
                            "SUPERSEDED_REVISION"
                            if prior is None or unique_json(prior[0]) != asdict(obs)
                            else (
                                "MISSING_OBSERVATION"
                                if obs.missing
                                else (
                                    "ANCHOR_INCOMPATIBLE"
                                    if row.anchor != anchor
                                    else (
                                        "STALE_OBSERVATION"
                                        if cutoff - obs.event_at > max_age
                                        else None
                                    )
                                )
                            )
                        )
                    )
                    yield row, reason, asdict(proof)
            finally:
                db.close()
        self.verify()

    def cache_key(self, *, cutoff: int, policy_digest: str) -> DerivedCacheKey:
        return DerivedCacheKey(
            "occ-research", str(cutoff), policy_digest, self.expected_digest, "offline"
        )


def compare_provider_views(rows: tuple[ResearchObservation, ...]) -> dict[str, Any]:
    anchors = {row.anchor for row in rows}
    values = {row.observation.value_atoms for row in rows}
    families = sorted({family for row in rows for family in row.upstream_families})
    # Shared upstream sets overlap, so a wrapper is never an independent vote.
    independent = all(
        set(left.upstream_families).isdisjoint(right.upstream_families)
        for i, left in enumerate(rows)
        for right in rows[i + 1 :]
    )
    return {
        "status": (
            "UNKNOWN"
            if not rows or len(anchors) != 1 or len(values) != 1
            else "AGREEMENT"
        ),
        "independent_views": independent and len(rows) > 1,
        "upstream_families": families,
        "observation_count": len(rows),
    }
