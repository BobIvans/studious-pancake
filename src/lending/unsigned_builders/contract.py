"""R03-00: frozen conformance contract for protocol-specific unsigned builders.

This module is the coordinator-frozen interface that every R03 provider builder
(Jupiter Lend, Kamino, NAVI PTB, Project 0) must satisfy.  It is deliberately
sender-free and network-free:

- it never signs, sends, submits, or promotes capital;
- it never creates accounts/ATAs/obligations/positions;
- ``build_status`` is strictly separated from ``capacity_status``: an unsigned
  offline build (``BUILT_OFFLINE_UNQUALIFIED``) is never a live-capital route
  and there is deliberately no execution-ready capacity member in this contract;
- every plan/result binds an immutable :class:`BuilderSourcePin` so SDK
  conformance claims remain traceable to a pinned official source;
- ``UNKNOWN`` is never coerced to zero: an unknown required repayment is
  recorded as ``None``, never as ``0``.

Fail-closed conformance checks provided here (account order, bookend presence,
bookend ordering, hot-potato receipt lifecycle, PTB package identity) must be
run by every provider before any plan is returned as built.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import re
from typing import Sequence

from solders.pubkey import Pubkey

UNSIGNED_BUILDERS_CONTRACT_VERSION = "r03.unsigned-builders.v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX_RE = re.compile(r"^(?:0[xX])?[0-9a-fA-F]+$")

U64_MAX = (1 << 64) - 1
U8_MAX = (1 << 8) - 1


class BuildStatus(StrEnum):
    """Offline build outcome. Never implies live execution readiness."""

    BUILT_OFFLINE_UNQUALIFIED = "built_offline_unqualified"
    BLOCKED_INPUT_REQUIRED = "blocked_input_required"
    BLOCKED_MISSING_PINNED_BUILDER_ABI = "blocked_missing_pinned_builder_abi"
    BLOCKED_CONFORMANCE = "blocked_conformance"


class CapacityStatus(StrEnum):
    """Live-capital capacity status, kept strictly separate from build status.

    Deliberately contains no execution-ready member: R-03 cannot admit a
    built plan to live capital.  R-02 must pass independently before any
    built plan may be attached to a live-capital candidate.
    """

    NOT_EVALUATED = "not_evaluated"
    PENDING_R02_CAPACITY_GATE = "pending_r02_capacity_gate"
    CAPACITY_UNQUALIFIED = "capacity_unqualified"


class ConformanceErrorCode(StrEnum):
    """Typed, fail-closed conformance/blocker codes."""

    SOURCE_PIN_UNVERIFIED = "R03_SOURCE_PIN_UNVERIFIED"
    CONTRACT_VERSION_MISMATCH = "R03_CONTRACT_VERSION_MISMATCH"
    PROGRAM_ID_MISMATCH = "R03_PROGRAM_ID_MISMATCH"
    ACCOUNT_ORDER_MISMATCH = "R03_ACCOUNT_ORDER_MISMATCH"
    BOOKEND_MISSING = "R03_BOOKEND_MISSING"
    DUPLICATE_BOOKEND = "R03_DUPLICATE_BOOKEND"
    BOOKEND_ORDER_INVALID = "R03_BOOKEND_ORDER_INVALID"
    AMOUNT_MISMATCH = "R03_AMOUNT_MISMATCH"
    REPAYMENT_BELOW_PRINCIPAL = "R03_REPAYMENT_BELOW_PRINCIPAL"
    REPAY_INDEX_OVERFLOW = "R03_REPAY_INDEX_OVERFLOW"
    NEEDS_ACCOUNT_SETUP = "R03_NEEDS_ACCOUNT_SETUP"
    MISSING_PINNED_BUILDER_ABI = "R03_MISSING_PINNED_BUILDER_ABI"
    OPERATOR_ACCOUNT_INPUT_REQUIRED = "R03_OPERATOR_ACCOUNT_INPUT_REQUIRED"
    HOT_POTATO_UNCONSUMED = "R03_HOT_POTATO_UNCONSUMED"
    HOT_POTATO_DUPLICATE_DISCHARGE = "R03_HOT_POTATO_DUPLICATE_DISCHARGE"
    HOT_POTATO_ORDER_INVALID = "R03_HOT_POTATO_ORDER_INVALID"
    COIN_TYPE_MISMATCH = "R03_COIN_TYPE_MISMATCH"
    PACKAGE_ID_MISMATCH = "R03_PACKAGE_ID_MISMATCH"
    PTB_VERSION_UNKNOWN = "R03_PTB_VERSION_UNKNOWN"
    PTB_AMOUNT_INVALID = "R03_PTB_AMOUNT_INVALID"
    PTB_OBJECT_CONFLICT = "R03_PTB_OBJECT_CONFLICT"
    PTB_REQUIRED_OBJECT_MISSING = "R03_PTB_REQUIRED_OBJECT_MISSING"
    BUILD_CAPACITY_ADMIXTURE = "R03_BUILD_CAPACITY_ADMIXTURE"
    INVALID_INPUT = "R03_INVALID_INPUT"


def assert_no_execution_ready_capacity_member() -> None:
    """Guard: this contract must never gain an execution-ready capacity member.

    R03 unsigned builds are conformance evidence only; live qualification is
    owned by R-02/R-05.  Raises if a future edit introduces an admitting
    capacity status by accident.
    """

    forbidden = ("execution_ready", "execution-ready", "live_admitted")
    for member in CapacityStatus.__members__:
        normalized = member.lower()
        if any(token in normalized for token in forbidden):
            raise UnsignedBuilderError(
                (
                    ConformanceViolation(
                        code=ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
                        message=(
                            "CapacityStatus must never contain an "
                            "execution-ready member"
                        ),
                        provider="contract",
                    ),
                )
            )


@dataclass(frozen=True, slots=True)
class ConformanceViolation:
    code: ConformanceErrorCode
    message: str
    provider: str


class UnsignedBuilderError(ValueError):
    """Fail-closed unsigned-builder conformance error."""

    def __init__(self, violations: Sequence[ConformanceViolation]) -> None:
        normalized = tuple(violations)
        if not normalized:
            normalized = (
                ConformanceViolation(
                    code=ConformanceErrorCode.INVALID_INPUT,
                    message="unsigned builder error without typed violation",
                    provider="contract",
                ),
            )
        rendered = "; ".join(
            f"{violation.code.value}({violation.provider}): {violation.message}"
            for violation in normalized
        )
        super().__init__(rendered)
        self.violations = normalized

    @classmethod
    def single(
        cls,
        code: ConformanceErrorCode,
        provider: str,
        message: str,
    ) -> "UnsignedBuilderError":
        return cls((ConformanceViolation(code=code, message=message, provider=provider),))


def _require_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT, "contract", f"{label} is required"
        )
    return value


def _validate_pubkey(value: str, label: str) -> str:
    _require_text(value, label)
    try:
        Pubkey.from_string(value)
    except Exception as exc:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            "contract",
            f"{label} is not a valid base58 pubkey",
        ) from exc
    return value


def _validate_object_id(value: str, label: str) -> str:
    """Normalize a Sui object id/address to canonical ``0x`` + 64 lowercase hex.

    Sui addresses are 32-byte values whose leading zeros may be omitted in the
    literal form (e.g. the pinned SDK passes ``0x05`` SuiSystemState and
    ``0x06`` Clock); shorthand literals are left-padded here so all
    comparisons are canonical.
    """

    _require_text(value, label)
    raw = value.strip()
    if raw.lower().startswith("0x"):
        raw = raw[2:]
    if (
        not raw
        or len(raw) > 64
        or any(char not in "0123456789abcdef" for char in raw.lower())
    ):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            "contract",
            f"{label} must be a 32-byte Sui object id",
        )
    return "0x" + raw.lower().rjust(64, "0")


def _canonical_payload(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: _canonical_payload(getattr(value, name))
            for name in value.__dataclass_fields__
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_payload(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical_payload(item) for key, item in sorted(value.items())}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise UnsignedBuilderError.single(
        ConformanceErrorCode.INVALID_INPUT,
        "contract",
        f"non-canonical payload type {type(value).__name__}",
    )


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            _canonical_payload(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class BuilderSourcePin:
    """Immutable pinned official SDK/source identity for one builder."""

    provider: str
    chain: str
    repository: str
    commit: str
    version: str
    license_label: str
    source_paths: tuple[str, ...]
    blob_sha1s: tuple[str, ...] = ()
    verified_offline: bool = False

    def __post_init__(self) -> None:
        _require_text(self.provider, "source_pin.provider")
        _require_text(self.chain, "source_pin.chain")
        _require_text(self.repository, "source_pin.repository")
        if not _SHA1_RE.fullmatch(self.commit):
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.SOURCE_PIN_UNVERIFIED,
                self.provider,
                "source pin commit must be a lowercase 40-hex git sha",
            )
        _require_text(self.version, "source_pin.version")
        _require_text(self.license_label, "source_pin.license_label")
        if not self.source_paths:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.SOURCE_PIN_UNVERIFIED,
                self.provider,
                "source pin must list at least one pinned source path",
            )
        for blob in self.blob_sha1s:
            if not _SHA1_RE.fullmatch(blob):
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.SOURCE_PIN_UNVERIFIED,
                    self.provider,
                    "source pin blob hashes must be lowercase 40-hex",
                )
        if len(self.blob_sha1s) > len(self.source_paths):
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.SOURCE_PIN_UNVERIFIED,
                self.provider,
                "more blob hashes than pinned source paths",
            )

    @property
    def digest(self) -> str:
        return canonical_hash(self)

    def require_verified(self) -> None:
        if not self.verified_offline:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.SOURCE_PIN_UNVERIFIED,
                self.provider,
                "source pin is not verified offline; refusing to build",
            )


@dataclass(frozen=True, slots=True)
class AccountMetaSpec:
    """One ordered account meta in a pinned Solana bookend layout."""

    pubkey: str
    is_signer: bool
    is_writable: bool

    def __post_init__(self) -> None:
        _validate_pubkey(self.pubkey, "account meta pubkey")

    @property
    def flags(self) -> tuple[bool, bool]:
        return (self.is_signer, self.is_writable)


class BookendKind(StrEnum):
    BORROW = "borrow"
    REPAY = "repay"


@dataclass(frozen=True, slots=True)
class UnsignedSolanaBookend:
    """One ABI-conformant unsigned bookend instruction (borrow or repay)."""

    kind: BookendKind
    program_id: str
    discriminator_hex: str
    data_hex: str
    account_metas: tuple[AccountMetaSpec, ...]
    amount_base_units: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.program_id, "bookend program_id")
        _validate_pubkey(self.program_id, "bookend program_id")
        _require_text(self.discriminator_hex, "bookend discriminator_hex")
        _require_text(self.data_hex, "bookend data_hex")
        raw = bytes.fromhex(self.data_hex)
        if not raw.startswith(bytes.fromhex(self.discriminator_hex)):
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                "contract",
                "bookend data must start with its discriminator",
            )
        if len(self.account_metas) == 0:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                "contract",
                "bookend must carry ordered account metas",
            )
        if self.amount_base_units is not None:
            if type(self.amount_base_units) is not int or self.amount_base_units <= 0:
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.INVALID_INPUT,
                    "contract",
                    "bookend amount must be a positive integer or None",
                )
            if self.amount_base_units > U64_MAX:
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.INVALID_INPUT,
                    "contract",
                    "bookend amount exceeds u64",
                )

    @property
    def meta_fingerprint(self) -> str:
        return canonical_hash(self.account_metas)

    def to_sequence_item(self) -> "SequenceItem":
        return SequenceItem(program_id=self.program_id, data_hex=self.data_hex)


@dataclass(frozen=True, slots=True)
class SequenceItem:
    """Opaque program/data pair used for instruction-order conformance."""

    program_id: str
    data_hex: str

    def __post_init__(self) -> None:
        _require_text(self.program_id, "sequence item program_id")
        _validate_pubkey(self.program_id, "sequence item program_id")
        _require_text(self.data_hex, "sequence item data_hex")
        try:
            bytes.fromhex(self.data_hex)
        except ValueError as exc:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                "contract",
                "sequence item data_hex must be hex",
            ) from exc

    @classmethod
    def from_solders_instruction(cls, instruction: object) -> "SequenceItem":
        return cls(
            program_id=str(instruction.program_id),  # type: ignore[attr-defined]
            data_hex=bytes(instruction.data).hex(),  # type: ignore[attr-defined]
        )


@dataclass(frozen=True, slots=True)
class BookendCertificate:
    """Result of a fail-closed bookend sequence check."""

    borrow_index: int
    repay_index: int

    @property
    def intervening_instruction_count(self) -> int:
        return self.repay_index - self.borrow_index - 1


@dataclass(frozen=True, slots=True)
class PtArgument:
    """One PTB command argument, normalized for deterministic replay."""

    kind: str  # "object_id" | "result_ref" | "pure"
    value: str
    type_tag: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "object_id":
            object.__setattr__(self, "value", _validate_object_id(self.value, "ptb object argument"))
        elif self.kind == "result_ref":
            _require_text(self.value, "ptb result_ref")
            parts = self.value.split(":")
            if len(parts) != 3 or parts[0] != "result":
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.INVALID_INPUT,
                    "contract",
                    "result_ref must be 'result:<command>:<output>'",
                )
            for part in parts[1:]:
                if not part.isdigit():
                    raise UnsignedBuilderError.single(
                        ConformanceErrorCode.INVALID_INPUT,
                        "contract",
                        "result_ref indices must be numeric",
                    )
        elif self.kind == "pure":
            _require_text(self.value, "ptb pure argument")
            payload = self.value.split(":", 1)
            if len(payload) == 2 and payload[0] == "u64":
                try:
                    amount = int(payload[1])
                except ValueError as exc:
                    raise UnsignedBuilderError.single(
                        ConformanceErrorCode.PTB_AMOUNT_INVALID,
                        "contract",
                        "pure u64 argument is not an integer",
                    ) from exc
                if not 0 <= amount <= U64_MAX:
                    raise UnsignedBuilderError.single(
                        ConformanceErrorCode.PTB_AMOUNT_INVALID,
                        "contract",
                        "pure u64 argument is out of range",
                    )
        else:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                "contract",
                f"unknown PTB argument kind {self.kind}",
            )


@dataclass(frozen=True, slots=True)
class PtCommand:
    """One unsigned PTB command (moveCall shape) in canonical order."""

    name: str
    target: str  # "<package>::<module>::<function>"
    type_arguments: tuple[str, ...]
    arguments: tuple[PtArgument, ...]
    result_names: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.name, "ptb command name")
        _require_text(self.target, "ptb command target")
        segments = self.target.split("::")
        if len(segments) != 3 or not all(segments):
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                "contract",
                "ptb target must be '<package>::<module>::<function>'",
            )
        _validate_object_id(segments[0], "ptb target package")
        for type_argument in self.type_arguments:
            _require_text(type_argument, "ptb type argument")
        if len(self.result_names) != len(set(self.result_names)):
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                "contract",
                "ptb command result names must be unique",
            )

    @property
    def package_id(self) -> str:
        return self.target.split("::")[0]

    @property
    def function_name(self) -> str:
        return self.target.split("::")[2]


RECEIPT_TYPE_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class HotPotatoReceipt:
    """One PTB hot-potato receipt that must be discharged in the same PTB."""

    result_ref: str
    producer_command_index: int
    consumed_by_command_index: int | None = None
    receipt_type: str = RECEIPT_TYPE_UNKNOWN

    def __post_init__(self) -> None:
        PtArgument(kind="result_ref", value=self.result_ref)
        if type(self.producer_command_index) is not int or self.producer_command_index < 0:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                "contract",
                "receipt producer index must be a non-negative integer",
            )
        if self.consumed_by_command_index is not None:
            if (
                type(self.consumed_by_command_index) is not int
                or self.consumed_by_command_index < 0
            ):
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.INVALID_INPUT,
                    "contract",
                    "receipt consumer index must be a non-negative integer",
                )
        if self.receipt_type != RECEIPT_TYPE_UNKNOWN:
            _require_text(self.receipt_type, "receipt_type")


@dataclass(frozen=True, slots=True)
class PtBuildResult:
    """Unsigned Sui PTB build outcome with hot-potato lifecycle evidence."""

    provider: str
    package_id: str
    config_version: int | None
    commands: tuple[PtCommand, ...]
    receipt: HotPotatoReceipt | None
    source_pin: BuilderSourcePin
    blockers: tuple[ConformanceViolation, ...] = ()
    build_status: BuildStatus = BuildStatus.BLOCKED_INPUT_REQUIRED
    capacity_status: CapacityStatus = CapacityStatus.NOT_EVALUATED
    contract_version: str = UNSIGNED_BUILDERS_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.provider, "ptb provider")
        object.__setattr__(self, "commands", tuple(self.commands))
        object.__setattr__(self, "blockers", tuple(self.blockers))
        if self.contract_version != UNSIGNED_BUILDERS_CONTRACT_VERSION:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.CONTRACT_VERSION_MISMATCH,
                self.provider,
                "unsupported unsigned-builders contract version",
            )
        self.source_pin.require_verified()
        _validate_object_id(self.package_id, "ptb package_id")
        if self.capacity_status not in CapacityStatus:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
                self.provider,
                "capacity_status is not a contract capacity status",
            )
        if self.build_status is BuildStatus.BUILT_OFFLINE_UNQUALIFIED:
            if not self.commands:
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
                    self.provider,
                    "a built PTB result must carry commands (no fake PASS)",
                )
            if self.blockers:
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
                    self.provider,
                    "a built PTB result must not carry blockers",
                )
            if self.config_version not in (1, 2):
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.PTB_VERSION_UNKNOWN,
                    self.provider,
                    "built PTB requires verified config version 1 or 2",
                )
            if self.receipt is None or self.receipt.consumed_by_command_index is None:
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.HOT_POTATO_UNCONSUMED,
                    self.provider,
                    "built PTB must record a discharged hot-potato receipt",
                )
        else:
            if self.commands:
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
                    self.provider,
                    "a blocked PTB result must never carry commands (no fake PASS)",
                )
            if not self.blockers:
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.INVALID_INPUT,
                    self.provider,
                    "a blocked PTB result must carry a typed blocker",
                )

    @property
    def build_fingerprint(self) -> str:
        return canonical_hash(self)


def check_ptb_package(commands: Sequence[PtCommand], package_id: str) -> None:
    """Fail closed when any command targets another package."""

    normalized = _validate_object_id(package_id, "ptb package")
    for command in commands:
        if command.package_id != normalized:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.PACKAGE_ID_MISMATCH,
                "contract",
                f"command {command.name} targets {command.package_id}, expected {normalized}",
            )


def check_hot_potato_receipt(
    commands: Sequence[PtCommand],
    receipt: HotPotatoReceipt,
) -> None:
    """Fail-closed hot-potato lifecycle: produced once, consumed exactly once,
    consumed strictly after production, never dropped at PTB end."""

    uses: list[int] = []
    for index, command in enumerate(commands):
        for argument in command.arguments:
            if argument.kind == "result_ref" and argument.value == receipt.result_ref:
                uses.append(index)
    if len(uses) == 0:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.HOT_POTATO_UNCONSUMED,
            "contract",
            "hot-potato receipt is never discharged in the same PTB",
        )
    if len(uses) > 1:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.HOT_POTATO_DUPLICATE_DISCHARGE,
            "contract",
            f"hot-potato receipt discharged {len(uses)} times",
        )
    if uses[0] <= receipt.producer_command_index:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.HOT_POTATO_ORDER_INVALID,
            "contract",
            "receipt must be discharged by a later command than its producer",
        )
    if receipt.consumed_by_command_index is not None and (
        receipt.consumed_by_command_index != uses[0]
    ):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.HOT_POTATO_ORDER_INVALID,
            "contract",
            "recorded consumer index does not match actual discharge",
        )


def check_bookend_sequence(
    *,
    provider: str,
    program_id: str,
    sequence: Sequence[SequenceItem],
    borrow_discriminator_hex: str,
    repay_discriminator_hex: str,
) -> BookendCertificate:
    """Fail-closed bookend presence/order check over a final instruction order.

    - exactly one borrow bookend and one repay bookend (BOOKEND_MISSING /
      DUPLICATE_BOOKEND);
    - a discriminator match under a different program id is a hard
      PROGRAM_ID_MISMATCH (wrong program/package);
    - borrow strictly before repay (BOOKEND_ORDER_INVALID).
    """

    _require_text(provider, "provider")
    _validate_pubkey(program_id, "program_id")
    borrow_disc = bytes.fromhex(_require_text(borrow_discriminator_hex, "borrow discriminator"))
    repay_disc = bytes.fromhex(_require_text(repay_discriminator_hex, "repay discriminator"))
    borrow_indexes: list[int] = []
    repay_indexes: list[int] = []
    for index, item in enumerate(sequence):
        raw = bytes.fromhex(item.data_hex)
        is_borrow = raw.startswith(borrow_disc)
        is_repay = raw.startswith(repay_disc)
        if not is_borrow and not is_repay:
            continue
        if item.program_id != program_id:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.PROGRAM_ID_MISMATCH,
                provider,
                f"bookend-shaped instruction at {index} belongs to {item.program_id}",
            )
        if is_borrow:
            borrow_indexes.append(index)
        if is_repay:
            repay_indexes.append(index)
    if len(borrow_indexes) != 1 or len(repay_indexes) != 1:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.BOOKEND_MISSING,
            provider,
            f"expected exactly one borrow and one repay bookend, "
            f"found {len(borrow_indexes)} borrow and {len(repay_indexes)} repay",
        )
    if borrow_indexes[0] >= repay_indexes[0]:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.BOOKEND_ORDER_INVALID,
            provider,
            "borrow bookend must strictly precede repay bookend",
        )
    return BookendCertificate(borrow_index=borrow_indexes[0], repay_index=repay_indexes[0])


def check_account_order(
    *,
    provider: str,
    borrow_bookend: UnsignedSolanaBookend,
    repay_bookend: UnsignedSolanaBookend,
) -> None:
    """Borrow and repay bookends must bind the exact same ordered metas."""

    if borrow_bookend.meta_fingerprint != repay_bookend.meta_fingerprint:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.ACCOUNT_ORDER_MISMATCH,
            provider,
            "borrow and repay bookends bind different ordered account metas",
        )
    if borrow_bookend.account_metas[0].is_signer is not True:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.ACCOUNT_ORDER_MISMATCH,
            provider,
            "first bookend account must be the payer/signer",
        )


def _validated_build_status_pair(
    provider: str,
    build_status: BuildStatus,
    capacity_status: CapacityStatus,
    blockers: Sequence[ConformanceViolation],
    built: bool,
) -> None:
    if build_status is BuildStatus.BUILT_OFFLINE_UNQUALIFIED:
        if blockers:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
                provider,
                "a built plan must not carry blockers",
            )
        if not built:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
                provider,
                "a built plan must carry its unsigned instructions",
            )
    else:
        if not blockers:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                provider,
                "a blocked plan must carry a typed blocker",
            )
        if built:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
                provider,
                "a blocked plan must never carry instructions (no fake PASS)",
            )


@dataclass(frozen=True, slots=True)
class UnsignedBorrowPlan:
    """Unsigned borrow bookend plan for one pinned Solana provider."""

    provider: str
    chain: str
    source_pin: BuilderSourcePin
    asset_id: str
    principal_base_units: int
    bookend: UnsignedSolanaBookend | None
    required_repayment_base_units: int | None = None  # None = UNKNOWN, never 0
    state_fingerprint: str = ""
    blockers: tuple[ConformanceViolation, ...] = ()
    build_status: BuildStatus = BuildStatus.BLOCKED_INPUT_REQUIRED
    capacity_status: CapacityStatus = CapacityStatus.NOT_EVALUATED
    contract_version: str = UNSIGNED_BUILDERS_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.provider, "borrow plan provider")
        _require_text(self.chain, "borrow plan chain")
        _require_text(self.asset_id, "borrow plan asset_id")
        self.source_pin.require_verified()
        if type(self.principal_base_units) is not int or self.principal_base_units <= 0:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                self.provider,
                "principal must be a positive integer",
            )
        if self.required_repayment_base_units is not None:
            if type(self.required_repayment_base_units) is not int:
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.INVALID_INPUT,
                    self.provider,
                    "required repayment must be integer or None (unknown)",
                )
            if self.required_repayment_base_units <= 0:
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.REPAYMENT_BELOW_PRINCIPAL,
                    self.provider,
                    "zero repayment is forbidden; unknown must be recorded as None",
                )
            if self.required_repayment_base_units < self.principal_base_units:
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.REPAYMENT_BELOW_PRINCIPAL,
                    self.provider,
                    "required repayment cannot be below principal",
                )
        if self.state_fingerprint and not _SHA256_RE.fullmatch(self.state_fingerprint):
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                self.provider,
                "state fingerprint must be lowercase sha256 when provided",
            )
        object.__setattr__(self, "blockers", tuple(self.blockers))
        _validated_build_status_pair(
            self.provider,
            self.build_status,
            self.capacity_status,
            self.blockers,
            built=self.bookend is not None,
        )
        if self.contract_version != UNSIGNED_BUILDERS_CONTRACT_VERSION:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.CONTRACT_VERSION_MISMATCH,
                self.provider,
                "unsupported unsigned-builders contract version",
            )

    @property
    def build_fingerprint(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True, slots=True)
class UnsignedRepayPlan:
    """Unsigned repay bookend plan bound to its borrow bookend."""

    provider: str
    chain: str
    source_pin: BuilderSourcePin
    asset_id: str
    bookend: UnsignedSolanaBookend | None
    borrow_bookend: UnsignedSolanaBookend | None
    required_repayment_base_units: int | None = None  # None = UNKNOWN, never 0
    borrow_index_u8_required: bool = False
    state_fingerprint: str = ""
    blockers: tuple[ConformanceViolation, ...] = ()
    build_status: BuildStatus = BuildStatus.BLOCKED_INPUT_REQUIRED
    capacity_status: CapacityStatus = CapacityStatus.NOT_EVALUATED
    contract_version: str = UNSIGNED_BUILDERS_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.provider, "repay plan provider")
        _require_text(self.chain, "repay plan chain")
        _require_text(self.asset_id, "repay plan asset_id")
        self.source_pin.require_verified()
        if self.required_repayment_base_units is not None:
            if type(self.required_repayment_base_units) is not int:
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.INVALID_INPUT,
                    self.provider,
                    "required repayment must be integer or None (unknown)",
                )
            if self.required_repayment_base_units <= 0:
                raise UnsignedBuilderError.single(
                    ConformanceErrorCode.REPAYMENT_BELOW_PRINCIPAL,
                    self.provider,
                    "zero repayment is forbidden; unknown must be recorded as None",
                )
        if self.state_fingerprint and not _SHA256_RE.fullmatch(self.state_fingerprint):
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                self.provider,
                "state fingerprint must be lowercase sha256 when provided",
            )
        object.__setattr__(self, "blockers", tuple(self.blockers))
        built = (
            self.bookend is not None
            and self.borrow_bookend is not None
        )
        _validated_build_status_pair(
            self.provider,
            self.build_status,
            self.capacity_status,
            self.blockers,
            built=built,
        )
        if self.contract_version != UNSIGNED_BUILDERS_CONTRACT_VERSION:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.CONTRACT_VERSION_MISMATCH,
                self.provider,
                "unsupported unsigned-builders contract version",
            )
        if self.bookend is not None and self.borrow_bookend is not None:
            check_account_order(
                provider=self.provider,
                borrow_bookend=self.borrow_bookend,
                repay_bookend=self.bookend,
            )

    @property
    def build_fingerprint(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True, slots=True)
class FinalizedUnsignedSolanaPlan:
    """Final unsigned message plan after fail-closed sequence resolution."""

    provider: str
    program_id: str
    sequence: tuple[SequenceItem, ...]
    certificate: BookendCertificate
    borrow_plan: UnsignedBorrowPlan
    repay_plan: UnsignedRepayPlan
    contract_version: str = UNSIGNED_BUILDERS_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.provider, "finalized plan provider")
        object.__setattr__(self, "sequence", tuple(self.sequence))
        if not self.sequence:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.BOOKEND_MISSING,
                self.provider,
                "finalized sequence must not be empty",
            )
        if self.contract_version != UNSIGNED_BUILDERS_CONTRACT_VERSION:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.CONTRACT_VERSION_MISMATCH,
                self.provider,
                "unsupported unsigned-builders contract version",
            )

    @property
    def sequence_fingerprint(self) -> str:
        return canonical_hash(self.sequence)


def finalize_unsigned_solana_plan(
    *,
    provider: str,
    program_id: str,
    borrow_plan: UnsignedBorrowPlan,
    repay_plan: UnsignedRepayPlan,
    sequence: Sequence[SequenceItem],
    borrow_discriminator_hex: str,
    repay_discriminator_hex: str,
) -> FinalizedUnsignedSolanaPlan:
    """Resolve the final ordering and fail closed on any conformance breach."""

    if borrow_plan.build_status is not BuildStatus.BUILT_OFFLINE_UNQUALIFIED:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
            provider,
            "cannot finalize a non-built borrow plan",
        )
    if repay_plan.build_status is not BuildStatus.BUILT_OFFLINE_UNQUALIFIED:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
            provider,
            "cannot finalize a non-built repay plan",
        )
    if borrow_plan.provider != provider or repay_plan.provider != provider:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PROGRAM_ID_MISMATCH,
            provider,
            "borrow/repay plans belong to another provider",
        )
    certificate = check_bookend_sequence(
        provider=provider,
        program_id=program_id,
        sequence=sequence,
        borrow_discriminator_hex=borrow_discriminator_hex,
        repay_discriminator_hex=repay_discriminator_hex,
    )
    assert borrow_plan.bookend is not None and repay_plan.bookend is not None
    if sequence[certificate.borrow_index] != borrow_plan.bookend.to_sequence_item():
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.BOOKEND_MISSING,
            provider,
            "borrow bookend in final sequence differs from the built borrow plan",
        )
    if sequence[certificate.repay_index] != repay_plan.bookend.to_sequence_item():
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.BOOKEND_MISSING,
            provider,
            "repay bookend in final sequence differs from the built repay plan",
        )
    if (
        borrow_plan.bookend.amount_base_units is not None
        and repay_plan.bookend.amount_base_units is not None
        and borrow_plan.bookend.amount_base_units != repay_plan.bookend.amount_base_units
    ):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.AMOUNT_MISMATCH,
            provider,
            "borrow and repay bookend amounts differ",
        )
    check_account_order(
        provider=provider,
        borrow_bookend=borrow_plan.bookend,
        repay_bookend=repay_plan.bookend,
    )
    if repay_plan.borrow_index_u8_required and certificate.borrow_index > U8_MAX:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.REPAY_INDEX_OVERFLOW,
            provider,
            f"absolute borrow index {certificate.borrow_index} does not fit u8",
        )
    return FinalizedUnsignedSolanaPlan(
        provider=provider,
        program_id=program_id,
        sequence=tuple(sequence),
        certificate=certificate,
        borrow_plan=borrow_plan,
        repay_plan=repay_plan,
    )


__all__ = [
    "RECEIPT_TYPE_UNKNOWN",
    "UNSIGNED_BUILDERS_CONTRACT_VERSION",
    "AccountMetaSpec",
    "BookendCertificate",
    "BookendKind",
    "BuildStatus",
    "BuilderSourcePin",
    "CapacityStatus",
    "ConformanceErrorCode",
    "ConformanceViolation",
    "FinalizedUnsignedSolanaPlan",
    "HotPotatoReceipt",
    "PtArgument",
    "PtBuildResult",
    "PtCommand",
    "SequenceItem",
    "UnsignedBorrowPlan",
    "UnsignedRepayPlan",
    "UnsignedSolanaBookend",
    "UnsignedBuilderError",
    "assert_no_execution_ready_capacity_member",
    "canonical_hash",
    "check_account_order",
    "check_bookend_sequence",
    "check_hot_potato_receipt",
    "check_ptb_package",
    "finalize_unsigned_solana_plan",
]
