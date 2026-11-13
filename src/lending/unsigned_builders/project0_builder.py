"""R03-D: conditional Project 0 (MarginFi) flash-loan bracket builder.

Pinned source: ``0dotxyz/p0-ts-sdk`` @ commit
``8a8353bb662459e5957b0cbbd2121f4fddb37fc3`` (git version 2.10.0, MIT).  The
pinned ``flash-loan.ts`` documents the bracket shape:

- ``lending_account_start_flashloan`` first (after optional compute budget),
  with ``endIndex = len(route_instructions) + 1``;
- route instructions in the middle (direct instructions only, no CPI wrapper);
- ``lending_account_end_flashloan`` last with repay accounting.

This builder is *conditional* by design and currently fail-closed in this
repository:

- without a caller-supplied pre-existing marginfi account identity it returns
  typed ``R03_OPERATOR_ACCOUNT_INPUT_REQUIRED`` (no account is bound here and
  creating one is forbidden);
- even with a supplied pre-existing account, the generated instruction builder
  module (account metas for start/end flashloan) is not vendored, so the
  outcome stays ``R03_MISSING_PINNED_BUILDER_ABI`` with no fabricated
  instruction bytes — only the pinned bracket certificate (endIndex math and
  PR-028 start/end discriminators) is produced.

This is never execution-ready and never creates accounts.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.lending.unsigned_builders.contract import (
    BuildStatus,
    BuilderSourcePin,
    ConformanceErrorCode,
    ConformanceViolation,
    SequenceItem,
    UnsignedBuilderError,
)
from src.providers.marginfi.pin import load_marginfi_contract_pin

PROJECT0_BUILDER_PROVIDER = "project-0"
PROJECT0_BUILDER_CHAIN = "solana"

PROJECT0_BUILDER_SOURCE_PIN = BuilderSourcePin(
    provider=PROJECT0_BUILDER_PROVIDER,
    chain=PROJECT0_BUILDER_CHAIN,
    repository="https://github.com/0dotxyz/p0-ts-sdk",
    commit="8a8353bb662459e5957b0cbbd2121f4fddb37fc3",
    version="2.10.0",
    license_label="MIT (pinned blobs 74ddb79ac9157570f967530cfae91acaa1bde5f5 / "
    "7d9952aef4b6183a8234eff0701ef04fbfced1bd)",
    source_paths=(
        "src/services/account/actions/flash-loan.ts",
        "src/models/client.ts",
    ),
    blob_sha1s=(
        "74ddb79ac9157570f967530cfae91acaa1bde5f5",
        "7d9952aef4b6183a8234eff0701ef04fbfced1bd",
    ),
    verified_offline=True,
)

START_FLASHLOAN_IX_NAME = "lending_account_start_flashloan"
END_FLASHLOAN_IX_NAME = "lending_account_end_flashloan"


@dataclass(frozen=True, slots=True)
class Project0BracketCertificate:
    """Pinned bracket math from ``makeFlashLoanTx`` ( endIndex = ixs + 1 )."""

    begin_index: int
    route_instruction_count: int
    end_index: int
    pinned_end_index: int
    start_flashloan_discriminator_hex: str
    end_flashloan_discriminator_hex: str

    def __post_init__(self) -> None:
        if type(self.begin_index) is not int or self.begin_index < 0:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                PROJECT0_BUILDER_PROVIDER,
                "begin_index must be a non-negative integer",
            )
        if (
            type(self.route_instruction_count) is not int
            or self.route_instruction_count < 0
        ):
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                PROJECT0_BUILDER_PROVIDER,
                "route_instruction_count must be a non-negative integer",
            )
        if self.end_index != self.begin_index + self.route_instruction_count + 1:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.BOOKEND_ORDER_INVALID,
                PROJECT0_BUILDER_PROVIDER,
                "end index must follow begin + route instructions (pinned "
                "endIndex = ixs.length + 1)",
            )
        if self.pinned_end_index != self.end_index:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.BOOKEND_ORDER_INVALID,
                PROJECT0_BUILDER_PROVIDER,
                "computed endIndex disagrees with the pinned endIndex math",
            )


@dataclass(frozen=True, slots=True)
class Project0BuildOutcome:
    """Conditional builder outcome; BLOCKED carries typed blockers only."""

    build_status: BuildStatus
    blockers: tuple[ConformanceViolation, ...]
    bracket_certificate: Project0BracketCertificate | None
    source_pin: BuilderSourcePin
    existing_account_used: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "blockers", tuple(self.blockers))
        if self.build_status is BuildStatus.BUILT_OFFLINE_UNQUALIFIED:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
                PROJECT0_BUILDER_PROVIDER,
                "Project 0 offline builds can never be BUILT without the "
                "generated instruction ABI and a bound pre-existing account",
            )
        if not self.blockers:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                PROJECT0_BUILDER_PROVIDER,
                "a blocked Project 0 outcome must carry typed blockers",
            )
        if self.bracket_certificate is not None and not self.existing_account_used:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
                PROJECT0_BUILDER_PROVIDER,
                "bracket certificate requires a bound pre-existing account",
            )


def _operator_account_blocker() -> ConformanceViolation:
    return ConformanceViolation(
        code=ConformanceErrorCode.OPERATOR_ACCOUNT_INPUT_REQUIRED,
        message=(
            "no pre-existing marginfi account is bound to this builder; "
            "account creation is forbidden and P0 discovery stays "
            "P0_EXISTING_ACCOUNT_UNKNOWN_READ_BANKS_ONLY"
        ),
        provider=PROJECT0_BUILDER_PROVIDER,
    )


def _missing_abi_blocker() -> ConformanceViolation:
    return ConformanceViolation(
        code=ConformanceErrorCode.MISSING_PINNED_BUILDER_ABI,
        message=(
            "generated start/end flashloan instruction builder module is "
            "absent from the pinned p0-ts-sdk offline kit; refusing to "
            "fabricate account metas"
        ),
        provider=PROJECT0_BUILDER_PROVIDER,
    )


def _pinned_discriminators() -> tuple[str, str]:
    pin = load_marginfi_contract_pin()
    start = pin.ix_discriminator(START_FLASHLOAN_IX_NAME).hex()
    end = pin.ix_discriminator(END_FLASHLOAN_IX_NAME).hex()
    return start, end


def build_project0_flashloan_plan(
    *,
    existing_marginfi_account: str | None,
    route_instructions: Sequence[SequenceItem] = (),
) -> Project0BuildOutcome:
    """Conditional builder: typed-BLOCKED in every state reachable offline.

    - ``existing_marginfi_account`` is None/blank -> ``BLOCKED_INPUT_REQUIRED``
      with ``R03_OPERATOR_ACCOUNT_INPUT_REQUIRED`` (no account bound; the
      account must be supplied pre-existing by the operator, never created).
    - with a supplied pre-existing account -> the pinned bracket certificate
      (begin/end order and endIndex math) is produced, but the outcome remains
      ``BLOCKED_MISSING_PINNED_BUILDER_ABI`` because the generated instruction
      module (account metas) is absent from the pinned kit.
    """

    PROJECT0_BUILDER_SOURCE_PIN.require_verified()
    if existing_marginfi_account is None or not existing_marginfi_account.strip():
        return Project0BuildOutcome(
            build_status=BuildStatus.BLOCKED_INPUT_REQUIRED,
            blockers=(_operator_account_blocker(),),
            bracket_certificate=None,
            source_pin=PROJECT0_BUILDER_SOURCE_PIN,
            existing_account_used=False,
        )
    _validate_marginfi_account(existing_marginfi_account.strip())
    route = tuple(route_instructions)
    start_hex, end_hex = _pinned_discriminators()
    begin_index = 0
    end_index = len(route) + 1
    certificate = Project0BracketCertificate(
        begin_index=begin_index,
        route_instruction_count=len(route),
        end_index=end_index,
        pinned_end_index=end_index,
        start_flashloan_discriminator_hex=start_hex,
        end_flashloan_discriminator_hex=end_hex,
    )
    return Project0BuildOutcome(
        build_status=BuildStatus.BLOCKED_MISSING_PINNED_BUILDER_ABI,
        blockers=(_missing_abi_blocker(),),
        bracket_certificate=certificate,
        source_pin=PROJECT0_BUILDER_SOURCE_PIN,
        existing_account_used=True,
    )


def _validate_marginfi_account(value: str) -> None:
    from solders.pubkey import Pubkey

    try:
        Pubkey.from_string(value)
    except Exception as exc:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            PROJECT0_BUILDER_PROVIDER,
            "supplied marginfi account is not a valid base58 pubkey",
        ) from exc


__all__ = [
    "END_FLASHLOAN_IX_NAME",
    "PROJECT0_BUILDER_CHAIN",
    "PROJECT0_BUILDER_PROVIDER",
    "PROJECT0_BUILDER_SOURCE_PIN",
    "START_FLASHLOAN_IX_NAME",
    "Project0BracketCertificate",
    "Project0BuildOutcome",
    "build_project0_flashloan_plan",
]
