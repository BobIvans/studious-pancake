"""SP-Q01 protocol admission receipts for installed financing dependencies.

The receipt is evidence-only. It cannot enable signing, submission, wallet
mutation, live trading, or network access. It upgrades the installed financing
manifest from an unstructured "qualified=true + opaque hash" claim to an exact
source/deployment/account/build/review-bound admission record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from src.lending.jupiter_lend import (
    JUPITER_FLASHLOAN_ADMIN_PDA,
    JUPITER_LEND_FLASHLOAN_IDL_BLOB,
    JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
    JUPITER_LEND_UPSTREAM_COMMIT,
    JUPITER_LEND_UPSTREAM_REPOSITORY,
)
from src.lending.slumlord import (
    SLUMLORD_INSTRUCTIONS_BLOB,
    SLUMLORD_LIBRARY_BLOB,
    SLUMLORD_PDA,
    SLUMLORD_PROGRAM_ID,
    SLUMLORD_UPSTREAM_COMMIT,
    SLUMLORD_UPSTREAM_REPOSITORY,
)

SCHEMA = "sp-q01.protocol-admission.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_ROLES = {"PRIMARY", "RENT"}
_ALLOWED_AVAILABILITY = {"OBSERVED_AVAILABLE"}
_MAX_EVIDENCE_WINDOW_SECONDS = 7 * 24 * 60 * 60


class ProtocolAdmissionError(ValueError):
    """Stable fail-closed protocol admission error."""


@dataclass(frozen=True, slots=True)
class AccountEvidence:
    address: str
    owner: str
    data_sha256: str
    slot: int
    executable: bool = False


@dataclass(frozen=True, slots=True)
class ManualReviewEvidence:
    review_id: str
    reviewers: tuple[str, ...]
    reviewed_at_utc: datetime
    approved: bool
    reviewed_artifact_sha256: str


@dataclass(frozen=True, slots=True)
class ProtocolAdmissionReceipt:
    role: str
    lender_id: str
    program_id: str
    upstream_repository: str
    upstream_commit: str
    interface_blobs: tuple[str, ...]
    build_artifact_sha256: str
    deployed_programdata_sha256: str
    availability_status: str
    rooted: bool
    observed_root_slot: int
    max_root_lag_slots: int
    accounts: tuple[AccountEvidence, ...]
    observed_at_utc: datetime
    valid_until_utc: datetime
    review: ManualReviewEvidence
    artifact_bundle_sha256: str
    receipt_sha256: str

    @property
    def source_identity(self) -> tuple[str, str, tuple[str, ...]]:
        return (
            self.upstream_repository,
            self.upstream_commit,
            self.interface_blobs,
        )


@dataclass(frozen=True, slots=True)
class ExpectedProtocolIdentity:
    role: str
    lender_id: str
    program_id: str
    upstream_repository: str
    upstream_commit: str
    interface_blobs: tuple[str, ...]
    required_account: str
    required_account_owner: str


def _sha256(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ProtocolAdmissionError(code)
    return value


def _git_object(value: object, code: str) -> str:
    if not isinstance(value, str) or _GIT_OBJECT.fullmatch(value) is None:
        raise ProtocolAdmissionError(code)
    return value


def _text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolAdmissionError(code)
    return value.strip()


def _integer(value: object, code: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ProtocolAdmissionError(code)
    return value


def _strict_bool(value: object, code: str) -> bool:
    if type(value) is not bool:
        raise ProtocolAdmissionError(code)
    return value


def _utc(value: object, code: str) -> datetime:
    text = _text(value, code)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtocolAdmissionError(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProtocolAdmissionError(code)
    return parsed.astimezone(UTC)


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def expected_identity(role: str) -> ExpectedProtocolIdentity:
    if role == "PRIMARY":
        return ExpectedProtocolIdentity(
            role="PRIMARY",
            lender_id="jupiter-lend",
            program_id=str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID),
            upstream_repository=JUPITER_LEND_UPSTREAM_REPOSITORY,
            upstream_commit=JUPITER_LEND_UPSTREAM_COMMIT,
            interface_blobs=(JUPITER_LEND_FLASHLOAN_IDL_BLOB,),
            required_account=str(JUPITER_FLASHLOAN_ADMIN_PDA),
            required_account_owner=str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID),
        )
    if role == "RENT":
        return ExpectedProtocolIdentity(
            role="RENT",
            lender_id="slumlord",
            program_id=str(SLUMLORD_PROGRAM_ID),
            upstream_repository=SLUMLORD_UPSTREAM_REPOSITORY,
            upstream_commit=SLUMLORD_UPSTREAM_COMMIT,
            interface_blobs=tuple(
                sorted((SLUMLORD_INSTRUCTIONS_BLOB, SLUMLORD_LIBRARY_BLOB))
            ),
            required_account=str(SLUMLORD_PDA),
            required_account_owner=str(SLUMLORD_PROGRAM_ID),
        )
    raise ProtocolAdmissionError("SP_Q01_ROLE_INVALID")


def _account(raw: object) -> AccountEvidence:
    if not isinstance(raw, Mapping):
        raise ProtocolAdmissionError("SP_Q01_ACCOUNT_EVIDENCE_REQUIRED")
    return AccountEvidence(
        address=_text(raw.get("address"), "SP_Q01_ACCOUNT_ADDRESS_REQUIRED"),
        owner=_text(raw.get("owner"), "SP_Q01_ACCOUNT_OWNER_REQUIRED"),
        data_sha256=_sha256(
            raw.get("data_sha256"),
            "SP_Q01_ACCOUNT_DATA_SHA256_INVALID",
        ),
        slot=_integer(raw.get("slot"), "SP_Q01_ACCOUNT_SLOT_INVALID"),
        executable=_strict_bool(
            raw.get("executable", False),
            "SP_Q01_ACCOUNT_EXECUTABLE_BOOLEAN_REQUIRED",
        ),
    )


def _review(raw: object) -> ManualReviewEvidence:
    if not isinstance(raw, Mapping):
        raise ProtocolAdmissionError("SP_Q01_MANUAL_REVIEW_REQUIRED")
    reviewers_raw = raw.get("reviewers")
    if (
        not isinstance(reviewers_raw, Sequence)
        or isinstance(reviewers_raw, (str, bytes))
        or not reviewers_raw
    ):
        raise ProtocolAdmissionError("SP_Q01_REVIEWERS_REQUIRED")
    reviewers = tuple(
        _text(value, "SP_Q01_REVIEWER_INVALID") for value in reviewers_raw
    )
    if len(set(reviewers)) != len(reviewers):
        raise ProtocolAdmissionError("SP_Q01_REVIEWERS_DUPLICATED")
    return ManualReviewEvidence(
        review_id=_text(raw.get("review_id"), "SP_Q01_REVIEW_ID_REQUIRED"),
        reviewers=reviewers,
        reviewed_at_utc=_utc(
            raw.get("reviewed_at_utc"),
            "SP_Q01_REVIEW_TIME_INVALID",
        ),
        approved=_strict_bool(
            raw.get("approved"),
            "SP_Q01_REVIEW_APPROVED_BOOLEAN_REQUIRED",
        ),
        reviewed_artifact_sha256=_sha256(
            raw.get("reviewed_artifact_sha256"),
            "SP_Q01_REVIEW_ARTIFACT_SHA256_INVALID",
        ),
    )


def _artifact_bundle_payload(
    *,
    role: str,
    lender_id: str,
    program_id: str,
    upstream_repository: str,
    upstream_commit: str,
    interface_blobs: Sequence[str],
    build_artifact_sha256: str,
    deployed_programdata_sha256: str,
    availability_status: str,
    rooted: bool,
    observed_root_slot: int,
    max_root_lag_slots: int,
    accounts: Sequence[AccountEvidence],
) -> Mapping[str, Any]:
    return {
        "role": role,
        "lender_id": lender_id,
        "program_id": program_id,
        "upstream_repository": upstream_repository,
        "upstream_commit": upstream_commit,
        "interface_blobs": tuple(sorted(interface_blobs)),
        "build_artifact_sha256": build_artifact_sha256,
        "deployed_programdata_sha256": deployed_programdata_sha256,
        "availability_status": availability_status,
        "rooted": rooted,
        "observed_root_slot": observed_root_slot,
        "max_root_lag_slots": max_root_lag_slots,
        "accounts": tuple(
            {
                "address": account.address,
                "owner": account.owner,
                "data_sha256": account.data_sha256,
                "slot": account.slot,
                "executable": account.executable,
            }
            for account in sorted(accounts, key=lambda item: item.address)
        ),
    }


def admission_artifact_bundle_sha256(payload: Mapping[str, Any]) -> str:
    accounts_raw = payload.get("accounts")
    if (
        not isinstance(accounts_raw, Sequence)
        or isinstance(accounts_raw, (str, bytes))
    ):
        raise ProtocolAdmissionError("SP_Q01_ACCOUNTS_REQUIRED")
    accounts = tuple(_account(item) for item in accounts_raw)
    return canonical_sha256(
        _artifact_bundle_payload(
            role=_text(payload.get("role"), "SP_Q01_ROLE_REQUIRED"),
            lender_id=_text(
                payload.get("lender_id"),
                "SP_Q01_LENDER_REQUIRED",
            ),
            program_id=_text(
                payload.get("program_id"),
                "SP_Q01_PROGRAM_REQUIRED",
            ),
            upstream_repository=_text(
                payload.get("upstream_repository"),
                "SP_Q01_UPSTREAM_REPOSITORY_REQUIRED",
            ),
            upstream_commit=_git_object(
                payload.get("upstream_commit"),
                "SP_Q01_UPSTREAM_COMMIT_INVALID",
            ),
            interface_blobs=tuple(
                _git_object(
                    item,
                    "SP_Q01_INTERFACE_BLOB_INVALID",
                )
                for item in payload.get("interface_blobs", ())
            ),
            build_artifact_sha256=_sha256(
                payload.get("build_artifact_sha256"),
                "SP_Q01_BUILD_SHA256_INVALID",
            ),
            deployed_programdata_sha256=_sha256(
                payload.get("deployed_programdata_sha256"),
                "SP_Q01_PROGRAMDATA_SHA256_INVALID",
            ),
            availability_status=_text(
                payload.get("availability_status"),
                "SP_Q01_AVAILABILITY_REQUIRED",
            ),
            rooted=_strict_bool(
                payload.get("rooted"),
                "SP_Q01_ROOTED_BOOLEAN_REQUIRED",
            ),
            observed_root_slot=_integer(
                payload.get("observed_root_slot"),
                "SP_Q01_ROOT_SLOT_INVALID",
            ),
            max_root_lag_slots=_integer(
                payload.get("max_root_lag_slots"),
                "SP_Q01_ROOT_LAG_INVALID",
            ),
            accounts=accounts,
        )
    )


def admission_receipt_sha256(payload: Mapping[str, Any]) -> str:
    normalized = dict(payload)
    normalized.pop("receipt_sha256", None)
    return canonical_sha256(normalized)


def validate_protocol_admission_receipt(
    raw: object,
    *,
    role: str,
    now_utc: datetime,
) -> ProtocolAdmissionReceipt:
    if not isinstance(raw, Mapping):
        raise ProtocolAdmissionError("SP_Q01_ADMISSION_RECEIPT_REQUIRED")
    if raw.get("schema_version") != SCHEMA:
        raise ProtocolAdmissionError("SP_Q01_ADMISSION_SCHEMA_MISMATCH")
    if role not in _ALLOWED_ROLES:
        raise ProtocolAdmissionError("SP_Q01_ROLE_INVALID")

    expected = expected_identity(role)
    receipt_role = _text(raw.get("role"), "SP_Q01_ROLE_REQUIRED")
    lender_id = _text(raw.get("lender_id"), "SP_Q01_LENDER_REQUIRED")
    program_id = _text(raw.get("program_id"), "SP_Q01_PROGRAM_REQUIRED")
    repository = _text(
        raw.get("upstream_repository"),
        "SP_Q01_UPSTREAM_REPOSITORY_REQUIRED",
    )
    commit = _git_object(
        raw.get("upstream_commit"),
        "SP_Q01_UPSTREAM_COMMIT_INVALID",
    )
    blobs_raw = raw.get("interface_blobs")
    if (
        not isinstance(blobs_raw, Sequence)
        or isinstance(blobs_raw, (str, bytes))
        or not blobs_raw
    ):
        raise ProtocolAdmissionError("SP_Q01_INTERFACE_BLOBS_REQUIRED")
    blobs = tuple(
        sorted(
            _git_object(value, "SP_Q01_INTERFACE_BLOB_INVALID")
            for value in blobs_raw
        )
    )
    build_sha = _sha256(
        raw.get("build_artifact_sha256"),
        "SP_Q01_BUILD_SHA256_INVALID",
    )
    programdata_sha = _sha256(
        raw.get("deployed_programdata_sha256"),
        "SP_Q01_PROGRAMDATA_SHA256_INVALID",
    )
    availability = _text(
        raw.get("availability_status"),
        "SP_Q01_AVAILABILITY_REQUIRED",
    )
    rooted = _strict_bool(
        raw.get("rooted"),
        "SP_Q01_ROOTED_BOOLEAN_REQUIRED",
    )
    root_slot = _integer(
        raw.get("observed_root_slot"),
        "SP_Q01_ROOT_SLOT_INVALID",
    )
    max_lag = _integer(
        raw.get("max_root_lag_slots"),
        "SP_Q01_ROOT_LAG_INVALID",
    )
    accounts_raw = raw.get("accounts")
    if (
        not isinstance(accounts_raw, Sequence)
        or isinstance(accounts_raw, (str, bytes))
        or not accounts_raw
    ):
        raise ProtocolAdmissionError("SP_Q01_ACCOUNTS_REQUIRED")
    accounts = tuple(_account(value) for value in accounts_raw)
    observed = _utc(
        raw.get("observed_at_utc"),
        "SP_Q01_OBSERVED_TIME_INVALID",
    )
    valid_until = _utc(
        raw.get("valid_until_utc"),
        "SP_Q01_VALID_UNTIL_INVALID",
    )
    review = _review(raw.get("manual_review"))
    artifact_bundle = _sha256(
        raw.get("artifact_bundle_sha256"),
        "SP_Q01_ARTIFACT_BUNDLE_SHA256_INVALID",
    )
    receipt_sha = _sha256(
        raw.get("receipt_sha256"),
        "SP_Q01_RECEIPT_SHA256_INVALID",
    )

    if (
        receipt_role != expected.role
        or lender_id != expected.lender_id
        or program_id != expected.program_id
    ):
        raise ProtocolAdmissionError("SP_Q01_PROTOCOL_ROLE_IDENTITY_MISMATCH")
    if (
        repository != expected.upstream_repository
        or commit != expected.upstream_commit
        or blobs != expected.interface_blobs
    ):
        raise ProtocolAdmissionError("SP_Q01_UPSTREAM_PIN_MISMATCH")
    if availability not in _ALLOWED_AVAILABILITY:
        raise ProtocolAdmissionError("SP_Q01_DEPLOYMENT_NOT_OBSERVED_AVAILABLE")
    if not rooted:
        raise ProtocolAdmissionError("SP_Q01_ROOTED_EVIDENCE_REQUIRED")

    account_by_address = {account.address: account for account in accounts}
    if len(account_by_address) != len(accounts):
        raise ProtocolAdmissionError("SP_Q01_DUPLICATE_ACCOUNT_EVIDENCE")
    required = account_by_address.get(expected.required_account)
    if required is None:
        raise ProtocolAdmissionError("SP_Q01_REQUIRED_ACCOUNT_MISSING")
    if required.owner != expected.required_account_owner:
        raise ProtocolAdmissionError("SP_Q01_REQUIRED_ACCOUNT_OWNER_MISMATCH")
    if any(account.slot > root_slot for account in accounts):
        raise ProtocolAdmissionError("SP_Q01_ACCOUNT_ABOVE_ROOT")
    if any(root_slot - account.slot > max_lag for account in accounts):
        raise ProtocolAdmissionError("SP_Q01_ACCOUNT_TOO_STALE_FOR_ROOT")

    if observed > valid_until:
        raise ProtocolAdmissionError("SP_Q01_EVIDENCE_TIME_ORDER_INVALID")
    if valid_until - observed > timedelta_seconds(
        _MAX_EVIDENCE_WINDOW_SECONDS
    ):
        raise ProtocolAdmissionError("SP_Q01_EVIDENCE_WINDOW_TOO_WIDE")
    normalized_now = now_utc.astimezone(UTC)
    if normalized_now > valid_until:
        raise ProtocolAdmissionError("SP_Q01_EVIDENCE_EXPIRED")
    if observed > normalized_now:
        raise ProtocolAdmissionError("SP_Q01_EVIDENCE_FROM_FUTURE")
    if not review.approved:
        raise ProtocolAdmissionError("SP_Q01_MANUAL_REVIEW_NOT_APPROVED")
    if review.reviewed_at_utc < observed or review.reviewed_at_utc > normalized_now:
        raise ProtocolAdmissionError("SP_Q01_REVIEW_TIME_OUTSIDE_EVIDENCE_WINDOW")

    computed_bundle = canonical_sha256(
        _artifact_bundle_payload(
            role=receipt_role,
            lender_id=lender_id,
            program_id=program_id,
            upstream_repository=repository,
            upstream_commit=commit,
            interface_blobs=blobs,
            build_artifact_sha256=build_sha,
            deployed_programdata_sha256=programdata_sha,
            availability_status=availability,
            rooted=rooted,
            observed_root_slot=root_slot,
            max_root_lag_slots=max_lag,
            accounts=accounts,
        )
    )
    if computed_bundle != artifact_bundle:
        raise ProtocolAdmissionError("SP_Q01_ARTIFACT_BUNDLE_HASH_MISMATCH")
    if review.reviewed_artifact_sha256 != artifact_bundle:
        raise ProtocolAdmissionError("SP_Q01_REVIEW_NOT_BOUND_TO_ARTIFACT")
    if admission_receipt_sha256(raw) != receipt_sha:
        raise ProtocolAdmissionError("SP_Q01_RECEIPT_HASH_MISMATCH")

    return ProtocolAdmissionReceipt(
        role=receipt_role,
        lender_id=lender_id,
        program_id=program_id,
        upstream_repository=repository,
        upstream_commit=commit,
        interface_blobs=blobs,
        build_artifact_sha256=build_sha,
        deployed_programdata_sha256=programdata_sha,
        availability_status=availability,
        rooted=rooted,
        observed_root_slot=root_slot,
        max_root_lag_slots=max_lag,
        accounts=accounts,
        observed_at_utc=observed,
        valid_until_utc=valid_until,
        review=review,
        artifact_bundle_sha256=artifact_bundle,
        receipt_sha256=receipt_sha,
    )


def timedelta_seconds(seconds: int):
    from datetime import timedelta

    return timedelta(seconds=seconds)


__all__ = [
    "AccountEvidence",
    "ExpectedProtocolIdentity",
    "ManualReviewEvidence",
    "ProtocolAdmissionError",
    "ProtocolAdmissionReceipt",
    "SCHEMA",
    "admission_artifact_bundle_sha256",
    "admission_receipt_sha256",
    "canonical_sha256",
    "expected_identity",
    "validate_protocol_admission_receipt",
]
