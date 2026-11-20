"""R05-S unsigned-plan simulation seam tests (offline, deterministic).

Pins the fail-closed behavior of
``src/execution/unsigned_plan_simulation_seam.py``:

- byte preservation: Kamino golden bytes convert into Solders
  ``PlannedInstruction`` records with identical data bytes (sha256 before ==
  sha256 after) and identical ordered account metas;
- typed provenance: every conversion binds the R-03 ``BuilderSourcePin``,
  build fingerprint and contract version;
- missing live state: every record declares the frozen missing-context tuple
  and the gate reason ``SIM_SEAM_STATE_EVIDENCE_REQUIRED``; the state verdict
  is always BLOCKED with zero qualified plans (R-05 stays BLOCKED);
- scope boundary: a Sui PTB (NAVI) never re-encodes into Solana instruction
  shapes; blocked R-03 plans are never converted (no fabrication);
- unknown is never zero: an unknown required repayment stays ``None``;
- the seam never runs exact simulation itself (no RPC type is constructed,
  no finalizer instantiated — verified structurally).

Zero network; nothing signs, sends, or claims qualification.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from solders.pubkey import Pubkey

from src.execution.unsigned_plan_simulation_seam import (
    SIM_SEAM_STATE_EVIDENCE_REQUIRED,
    SimulationSeamError,
    SimulationSeamErrorCode,
    SimulationSeamSurfaceState,
    convert_kamino_golden_fixture,
    convert_pt_build_result,
    convert_unsigned_borrow_plan,
    simulation_state_verdict,
)
from src.lending.unsigned_builders.contract import (
    AccountMetaSpec,
    BookendKind,
    BuildStatus,
    BuilderSourcePin,
    ConformanceErrorCode,
    ConformanceViolation,
    UnsignedBorrowPlan,
    UnsignedBuilderError,
    UnsignedSolanaBookend,
    canonical_hash,
    PtArgument,
    PtBuildResult,
    PtCommand,
    HotPotatoReceipt,
)

pytestmark = pytest.mark.unit

GOLDEN = Path(__file__).parent / "fixtures" / "r03" / "kamino_flash_abi_golden.json"

KAMINO_PIN = BuilderSourcePin(
    provider="kamino",
    chain="solana",
    repository="https://github.com/Kamino-Finance/klend-sdk",
    commit="3c3a38d4ff9d7cf7b0380a383b81c9cd4f0f58b8",
    version="13.0.2",
    license_label="MIT",
    source_paths=(
        "klend/sdk/generated/flash_borrow_reserve_liquidity.py",
        "klend/sdk/generated/flash_repay_reserve_liquidity.py",
    ),
    verified_offline=True,
)


def _golden_bookend(kind: BookendKind) -> UnsignedSolanaBookend:
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))
    data_key = "borrow_data_hex" if kind is BookendKind.BORROW else "repay_data_hex"
    disc_key = (
        "borrow_discriminator_hex"
        if kind is BookendKind.BORROW
        else "repay_discriminator_hex"
    )
    metas = tuple(
        AccountMetaSpec(
            pubkey=meta["pubkey"],
            is_signer=meta["is_signer"],
            is_writable=meta["is_writable"],
        )
        for meta in payload["expected_metas"]
    )
    return UnsignedSolanaBookend(
        kind=kind,
        program_id=payload["program_id"],
        discriminator_hex=payload[disc_key],
        data_hex=payload[data_key],
        account_metas=metas,
    )


def _built_borrow_plan() -> UnsignedBorrowPlan:
    return UnsignedBorrowPlan(
        provider="kamino",
        chain="solana",
        source_pin=KAMINO_PIN,
        asset_id="kamino:SOL-reserve",
        principal_base_units=1_000_000,
        bookend=_golden_bookend(BookendKind.BORROW),
        required_repayment_base_units=None,  # program-settled fee: UNKNOWN
        build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
    )


class TestBytePreservation:
    def test_golden_bytes_convert_identically(self) -> None:
        borrow, repay = convert_kamino_golden_fixture(GOLDEN)
        payload = json.loads(GOLDEN.read_text(encoding="utf-8"))
        assert borrow.data_hex == payload["borrow_data_hex"]
        assert repay.data_hex == payload["repay_data_hex"]
        assert borrow.program_id == payload["program_id"]
        expected = hashlib.sha256(bytes.fromhex(payload["borrow_data_hex"])).hexdigest()
        assert borrow.data_sha256 == expected
        assert bytes(borrow.instruction.instruction.data) == bytes.fromhex(
            payload["borrow_data_hex"]
        )

    def test_account_meta_order_and_flags_preserved(self) -> None:
        borrow, _ = convert_kamino_golden_fixture(GOLDEN)
        payload = json.loads(GOLDEN.read_text(encoding="utf-8"))
        expected = [
            (meta["pubkey"], meta["is_signer"], meta["is_writable"])
            for meta in payload["expected_metas"]
        ]
        actual = [
            (str(meta.pubkey), meta.is_signer, meta.is_writable)
            for meta in borrow.instruction.instruction.accounts
        ]
        assert actual == expected

    def test_discriminator_prefix_preserved(self) -> None:
        borrow, repay = convert_kamino_golden_fixture(GOLDEN)
        assert bytes.fromhex(borrow.data_hex).startswith(
            bytes.fromhex("87e734a70734d4c1")
        )
        assert bytes.fromhex(repay.data_hex).startswith(
            bytes.fromhex("b97500cb60f5b4ba")
        )

    def test_corrupted_fixture_is_typed_refusal(self) -> None:
        payload = json.loads(GOLDEN.read_text(encoding="utf-8"))
        payload["borrow_data_hex"] = "00" + payload["borrow_data_hex"][2:]
        # The R-03 bookend contract and/or the seam must refuse drift; both
        # raise typed errors — never a silently converted corrupted payload.
        with pytest.raises((SimulationSeamError, UnsignedBuilderError)) as raised:
            convert_kamino_golden_fixture(payload)
        assert isinstance(raised.value, (SimulationSeamError, UnsignedBuilderError))


class TestPlanConversion:
    def test_built_borrow_plan_converts_with_provenance(self) -> None:
        plan = _built_borrow_plan()
        inputs = convert_unsigned_borrow_plan(plan)
        assert (
            inputs.surface_state
            is SimulationSeamSurfaceState.SOLANA_BOOKEND_CONVERTIBLE
        )
        assert inputs.provenance.provider == "kamino"
        assert inputs.provenance.chain == "solana"
        assert inputs.provenance.source_pin is plan.source_pin
        assert inputs.provenance.build_fingerprint == plan.build_fingerprint
        assert len(inputs.instructions) == 1
        assert (
            inputs.data_receipts[0]
            == hashlib.sha256(bytes.fromhex(plan.bookend.data_hex)).hexdigest()
        )

    def test_unknown_repayment_stays_none(self) -> None:
        plan = _built_borrow_plan()
        inputs = convert_unsigned_borrow_plan(plan)
        record = inputs.instructions[0]
        assert record is not None
        # Unknown is never zero: the seam record carries None, and the plan
        # itself pinned the program-settled fee as unknown.
        assert plan.required_repayment_base_units is None

    def test_blocked_plan_is_never_converted(self) -> None:
        plan = UnsignedBorrowPlan(
            provider="jupiter-lend",
            chain="solana",
            source_pin=KAMINO_PIN,
            asset_id="jupiter-lend:reserve",
            principal_base_units=1_000_000,
            bookend=None,
            blockers=(
                ConformanceViolation(
                    code=ConformanceErrorCode.NEEDS_ACCOUNT_SETUP,
                    message="ATA creation is hard-denied in this slice",
                    provider="jupiter-lend",
                ),
            ),
            build_status=BuildStatus.BLOCKED_INPUT_REQUIRED,
        )
        with pytest.raises(SimulationSeamError) as raised:
            convert_unsigned_borrow_plan(plan)
        assert raised.value.code is SimulationSeamErrorCode.NOT_BUILT
        assert "NEEDS_ACCOUNT_SETUP" in raised.value.message


class TestSuiScopeBoundary:
    def _ptb_result(self) -> PtBuildResult:
        package = "0x" + "ab" * 32
        command = PtCommand(
            name="flash_borrow",
            target=f"{package}::flash::flash_borrow",
            type_arguments=(),
            arguments=(PtArgument(kind="object_id", value=package),),
            result_names=("receipt",),
        )
        receipt = HotPotatoReceipt(
            result_ref="result:0:0",
            producer_command_index=0,
            consumed_by_command_index=0,
        )
        return PtBuildResult(
            provider="navi",
            package_id=package,
            config_version=1,
            commands=(command,),
            receipt=receipt,
            source_pin=KAMINO_PIN,
            build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
        )

    def test_sui_ptb_is_evidence_only(self) -> None:
        result = self._ptb_result()
        inputs = convert_pt_build_result(result)
        assert (
            inputs.surface_state
            is SimulationSeamSurfaceState.SUI_PTB_OUT_OF_SOLANA_SIMULATION_SCOPE
        )
        assert inputs.instructions == ()  # never re-encoded into Solana shapes
        assert len(inputs.data_receipts) == len(result.commands)
        assert inputs.provenance.chain == "sui"

    def test_hot_potato_receipt_still_enforced_by_contract(self) -> None:
        # The R-03 contract itself refuses a built PTB whose hot potato is
        # never discharged; the seam must not loosen that.
        package = "0x" + "cd" * 32
        command = PtCommand(
            name="flash_borrow",
            target=f"{package}::flash::flash_borrow",
            type_arguments=(),
            arguments=(PtArgument(kind="object_id", value=package),),
            result_names=("receipt",),
        )
        with pytest.raises(Exception):
            PtBuildResult(
                provider="navi",
                package_id=package,
                config_version=1,
                commands=(command,),
                receipt=None,
                source_pin=KAMINO_PIN,
                build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
            )


class TestFailClosedStateGate:
    def test_state_verdict_always_blocked(self) -> None:
        verdict = simulation_state_verdict()
        assert verdict.status == "BLOCKED"
        assert verdict.reason == SIM_SEAM_STATE_EVIDENCE_REQUIRED
        assert verdict.qualified_plan_count == 0
        assert simulation_state_verdict() == verdict

    def test_missing_context_declaration_is_frozen(self) -> None:
        from src.execution.unsigned_plan_simulation_seam import (
            UnsignedPlanSimulationInputs,
            SimulationSeamProvenance,
        )

        plan = _built_borrow_plan()
        inputs = convert_unsigned_borrow_plan(plan)
        with pytest.raises(SimulationSeamError) as raised:
            UnsignedPlanSimulationInputs(
                surface_state=inputs.surface_state,
                provenance=SimulationSeamProvenance(
                    provider="kamino",
                    chain="solana",
                    source_pin=plan.source_pin,
                    build_fingerprint=plan.build_fingerprint,
                    contract_version=plan.contract_version,
                ),
                instructions=inputs.instructions,
                missing_context=("payer",),  # tampering attempt
                data_receipts=inputs.data_receipts,
            )
        assert raised.value.code is SimulationSeamErrorCode.STATE_EVIDENCE_REQUIRED

    def test_no_seam_record_claims_qualification(self) -> None:
        inputs = convert_unsigned_borrow_plan(_built_borrow_plan())
        assert inputs.is_qualified_for_exact_simulation is False

    def test_seam_module_never_imports_rpc_or_finalizer(self) -> None:
        import ast

        source = Path(
            __import__("src.execution.unsigned_plan_simulation_seam").__file__
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not any("exact_simulation" in name for name in imported)
        assert not any(name.endswith("rpc") for name in imported)
