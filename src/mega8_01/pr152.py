"""PR-152 / NF-357..360: on-chain program/deployment attestation."""

from __future__ import annotations

from collections.abc import Sequence

from .common import artifact, fail_closed, require_non_negative_int, require_sha256, require_text, sorted_unique


def attest_program_binary(
    program_id: str,
    program_data_sha256: str,
    loader_state: str,
    upgrade_authority: str | None,
    observed_slot: int,
    valid_until_slot: int,
):
    pid = require_text(program_id, "program_id")
    binary_hash = require_sha256(program_data_sha256, "program_data_sha256")
    loader = require_text(loader_state, "loader_state")
    observed = require_non_negative_int(observed_slot, "observed_slot")
    valid_until = require_non_negative_int(valid_until_slot, "valid_until_slot")
    if valid_until < observed:
        return fail_closed(
            child="PR-152",
            nf="NF-357",
            action="attest_program_binary",
            subject_id=pid,
            reason="STALE_EVIDENCE",
            payload={"observed_slot": observed, "valid_until_slot": valid_until},
        )
    authority = None if upgrade_authority is None else require_text(upgrade_authority, "upgrade_authority")
    return artifact(
        child="PR-152",
        nf="NF-357",
        action="attest_program_binary",
        subject_id=pid,
        payload={
            "program_data_sha256": binary_hash,
            "loader_state": loader,
            "upgrade_authority": authority,
            "observed_slot": observed,
            "valid_until_slot": valid_until,
        },
    )


def track_upgrade_authority(
    program_id: str,
    previous_authority: str | None,
    current_authority: str | None,
    slot: int,
):
    pid = require_text(program_id, "program_id")
    observed_slot = require_non_negative_int(slot, "slot")
    previous = None if previous_authority is None else require_text(previous_authority, "previous_authority")
    current = None if current_authority is None else require_text(current_authority, "current_authority")
    return artifact(
        child="PR-152",
        nf="NF-358",
        action="track_upgrade_authority",
        subject_id=pid,
        payload={
            "previous_authority": previous,
            "current_authority": current,
            "changed": previous != current,
            "slot": observed_slot,
        },
    )


def detect_deployment_drift(
    program_id: str,
    expected_binary_sha256: str,
    observed_binary_sha256: str,
    expected_loader_state: str,
    observed_loader_state: str,
):
    pid = require_text(program_id, "program_id")
    expected_hash = require_sha256(expected_binary_sha256, "expected_binary_sha256")
    observed_hash = require_sha256(observed_binary_sha256, "observed_binary_sha256")
    expected_loader = require_text(expected_loader_state, "expected_loader_state")
    observed_loader = require_text(observed_loader_state, "observed_loader_state")
    changed = expected_hash != observed_hash or expected_loader != observed_loader
    payload = {
        "expected_binary_sha256": expected_hash,
        "observed_binary_sha256": observed_hash,
        "expected_loader_state": expected_loader,
        "observed_loader_state": observed_loader,
        "changed": changed,
    }
    if changed:
        return fail_closed(
            child="PR-152",
            nf="NF-359",
            action="detect_deployment_drift",
            subject_id=pid,
            reason="IDENTITY_MISMATCH",
            payload=payload,
        )
    return artifact(
        child="PR-152",
        nf="NF-359",
        action="detect_deployment_drift",
        subject_id=pid,
        payload=payload,
    )


def revoke_capabilities_on_program_change(
    program_id: str,
    deployment_changed: bool,
    capabilities: Sequence[str],
):
    pid = require_text(program_id, "program_id")
    names = sorted_unique(capabilities)
    if deployment_changed:
        return fail_closed(
            child="PR-152",
            nf="NF-360",
            action="revoke_capabilities_on_program_change",
            subject_id=pid,
            reason="IDENTITY_MISMATCH",
            payload={"revoked_capabilities": names, "deployment_changed": True},
        )
    return artifact(
        child="PR-152",
        nf="NF-360",
        action="revoke_capabilities_on_program_change",
        subject_id=pid,
        payload={"revoked_capabilities": (), "deployment_changed": False},
    )
