"""PR-153 / NF-361..364: schema evolution and decoder conformance."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .common import artifact, fail_closed, canonical_hash, require_sha256, require_text, sorted_unique


def register_schema_version(
    schema_id: str,
    schema_kind: str,
    version: str,
    schema_payload: Mapping[str, object],
):
    sid = require_text(schema_id, "schema_id")
    kind = require_text(schema_kind, "schema_kind")
    ver = require_text(version, "version")
    schema_hash = canonical_hash(dict(schema_payload))
    return artifact(
        child="PR-153",
        nf="NF-361",
        action="register_schema_version",
        subject_id=sid,
        payload={"schema_kind": kind, "version": ver, "schema_sha256": schema_hash},
    )


def diff_idl_account_layout(
    schema_id: str,
    previous_fields: Sequence[str],
    current_fields: Sequence[str],
):
    sid = require_text(schema_id, "schema_id")
    before = set(sorted_unique(previous_fields))
    after = set(sorted_unique(current_fields))
    return artifact(
        child="PR-153",
        nf="NF-362",
        action="diff_idl_account_layout",
        subject_id=sid,
        payload={
            "added": tuple(sorted(after - before)),
            "removed": tuple(sorted(before - after)),
            "unchanged": tuple(sorted(before & after)),
            "breaking": bool(before - after),
        },
    )


def migrate_decoder_contract(
    decoder_id: str,
    from_schema_sha256: str,
    to_schema_sha256: str,
    migration_steps: Sequence[str],
):
    did = require_text(decoder_id, "decoder_id")
    old = require_sha256(from_schema_sha256, "from_schema_sha256")
    new = require_sha256(to_schema_sha256, "to_schema_sha256")
    steps = sorted_unique(migration_steps)
    if old == new and steps:
        return fail_closed(
            child="PR-153",
            nf="NF-363",
            action="migrate_decoder_contract",
            subject_id=did,
            reason="INCONSISTENT_STATE",
            payload={"from": old, "to": new, "steps": steps},
        )
    return artifact(
        child="PR-153",
        nf="NF-363",
        action="migrate_decoder_contract",
        subject_id=did,
        payload={"from": old, "to": new, "steps": steps},
    )


def replay_schema_conformance(
    schema_id: str,
    expected_result_sha256: str,
    observed_result_sha256: str,
):
    sid = require_text(schema_id, "schema_id")
    expected = require_sha256(expected_result_sha256, "expected_result_sha256")
    observed = require_sha256(observed_result_sha256, "observed_result_sha256")
    if expected != observed:
        return fail_closed(
            child="PR-153",
            nf="NF-364",
            action="replay_schema_conformance",
            subject_id=sid,
            reason="UNSUPPORTED_VERSION",
            payload={"expected": expected, "observed": observed},
        )
    return artifact(
        child="PR-153",
        nf="NF-364",
        action="replay_schema_conformance",
        subject_id=sid,
        payload={"expected": expected, "observed": observed},
    )
