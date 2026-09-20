from __future__ import annotations

from dataclasses import replace

import pytest

from src.multichain import (
    AaveFinancingAdapter,
    AaveFlashMode,
    AssetDelta,
    AssetRef,
    CetusFinancingAdapter,
    CetusFlashKind,
    ChainCapabilityRegistry,
    ChainDialect,
    ChainEvidence,
    DeepBookFinancingAdapter,
    DeploymentRef,
    DodoFinancingAdapter,
    DodoPoolKind,
    Effect,
    EvmBlockRef,
    EvmCall,
    EvmExecutionAdapter,
    EvmFinality,
    EvmNonceLease,
    EvmOperationPlan,
    EvmProtocolEvidence,
    EvmSimulationEvidence,
    EvmStateAdapter,
    EvmStateFrame,
    ExactAssetAmount,
    FlashMintAdapter,
    FlashMintCapacity,
    MorphoFinancingAdapter,
    MultiChainError,
    NetSettlementAdapter,
    NetSettlementDialect,
    SettlementDomain,
    SuiAdditionalFinancingAdapter,
    SuiHotPotatoObligation,
    SuiObjectKind,
    SuiObjectRef,
    SuiPtbAdapter,
    SuiPtbOperation,
    SuiPtbPlan,
    SuiStateFrame,
    qualify_chain,
    require_single_chain_atomic_scope,
)


pytestmark = pytest.mark.unit

H1 = "1" * 64
H2 = "2" * 64
ADDR_A = "0x" + "11" * 20
ADDR_B = "0x" + "22" * 20
OBJ_A = "0x" + "aa" * 32
OBJ_B = "0x" + "bb" * 32
OBJ_C = "0x" + "cc" * 32
PKG = "0x" + "dd" * 32


def _deployment(protocol: str, chain: str = "base-mainnet") -> DeploymentRef:
    return DeploymentRef(
        protocol=protocol,
        chain_key=chain,
        deployment_id=f"{protocol}-deployment",
        version="test-v1",
        interface_digest=H1,
        artifact_digest=H2,
        generation="fixture-generation",
    )


def _asset(chain: str = "base-mainnet", name: str = "USDC") -> AssetRef:
    return AssetRef(
        chain_key=chain,
        asset_id=name,
        atomic_unit="unit",
        decimals=6,
        generation="fixture",
    )


def _evm_evidence(protocol: str) -> EvmProtocolEvidence:
    return EvmProtocolEvidence(
        deployment=_deployment(protocol),
        contract_address=ADDR_A,
        callback_sender=ADDR_A,
        source_ref="fixture:protocol",
    )


def _evm_frame() -> EvmStateFrame:
    return EvmStateFrame(
        chain_key="base-mainnet",
        block=EvmBlockRef(
            chain_id=8453,
            number=100,
            block_hash="0x" + "ab" * 32,
            parent_hash="0x" + "cd" * 32,
            finality=EvmFinality.SAFE,
        ),
        deployment=_deployment("aave"),
        interface_digest=H1,
        proxy_implementation=ADDR_B,
        state_digest=H2,
    )


def test_packaged_registry_is_multichain_and_default_off() -> None:
    registry = ChainCapabilityRegistry.packaged()

    assert registry.chain("base-mainnet").dialect is ChainDialect.EVM
    assert registry.chain("sui-mainnet").dialect is ChainDialect.SUI
    assert registry.capability("base-mainnet:aave").externally_executable is False
    with pytest.raises(MultiChainError, match="EFFECT_NOT_ALLOWED"):
        registry.require_effect("base-mainnet:aave", Effect.SEND)


def test_evm_state_rejects_wrong_chain_and_detects_reorg() -> None:
    registry = ChainCapabilityRegistry.packaged()
    frame = _evm_frame()

    assert (
        EvmStateAdapter.admit(
            chain=registry.chain("base-mainnet"),
            expected_chain_id=8453,
            frame=frame,
        )
        is frame
    )
    with pytest.raises(MultiChainError, match="CHAIN_ID_MISMATCH"):
        EvmStateAdapter.admit(
            chain=registry.chain("base-mainnet"),
            expected_chain_id=1,
            frame=frame,
        )
    changed = replace(frame.block, block_hash="0x" + "ef" * 32)
    assert "same-height-hash-changed" in EvmStateAdapter.reorg_reasons(
        frame.block,
        changed,
    )


def test_evm_nonce_is_bound_to_one_economic_intent() -> None:
    registry = ChainCapabilityRegistry.packaged()
    frame = _evm_frame()
    plan = EvmOperationPlan(
        chain_key="base-mainnet",
        chain_id=8453,
        sender=ADDR_B,
        nonce=7,
        state_digest=H2,
        calls=(EvmCall(ADDR_A, "0x1234"),),
        gas_limit=250_000,
        max_fee_per_gas=10,
        max_priority_fee_per_gas=2,
    )
    lease = EvmNonceLease(8453, ADDR_B, 7, plan.digest)

    assert EvmExecutionAdapter.compile(
        chain=registry.chain("base-mainnet"),
        frame=frame,
        plan=plan,
        nonce_lease=lease,
    ) == plan.digest

    changed = replace(plan, calls=(EvmCall(ADDR_A, "0x5678"),))
    with pytest.raises(MultiChainError, match="NONCE_INTENT_CONFLICT"):
        lease.require_same_intent(changed)


def test_simulation_cannot_claim_landing() -> None:
    with pytest.raises(MultiChainError, match="SIMULATION_NOT_LANDING_PROOF"):
        EvmSimulationEvidence(
            plan_digest=H1,
            state_digest=H2,
            block_hash="0x" + "ab" * 32,
            success=True,
            gas_used=10,
            landed=True,
        )


def test_aave_simple_and_callback_identity() -> None:
    principal = ExactAssetAmount(_asset(), 1_000_000)
    obligation = AaveFinancingAdapter.prepare(
        evidence=_evm_evidence("aave"),
        mode=AaveFlashMode.SIMPLE,
        receiver=ADDR_B,
        initiator=ADDR_B,
        expected_initiator=ADDR_B,
        principals=(principal,),
        premium_bps=5,
        reserve_caps={"USDC": 2_000_000},
    )

    assert obligation.debts[0].repayment_units == 1_000_500
    obligation.require_callback(ADDR_A)
    with pytest.raises(MultiChainError, match="CALLBACK_SENDER_MISMATCH"):
        obligation.require_callback(ADDR_B)

    with pytest.raises(
        MultiChainError,
        match="AAVE_SIMPLE_SINGLE_ASSET_REQUIRED",
    ):
        AaveFinancingAdapter.prepare(
            evidence=_evm_evidence("aave"),
            mode=AaveFlashMode.SIMPLE,
            receiver=ADDR_B,
            initiator=ADDR_B,
            expected_initiator=ADDR_B,
            principals=(principal, principal),
            premium_bps=5,
            reserve_caps={"USDC": 3_000_000},
        )


def test_morpho_singleton_capacity_is_explicit() -> None:
    principal = ExactAssetAmount(_asset(), 100)
    with pytest.raises(MultiChainError, match="MORPHO_CAPACITY_EXCEEDED"):
        MorphoFinancingAdapter.prepare(
            evidence=_evm_evidence("morpho"),
            receiver=ADDR_B,
            principal=principal,
            singleton_capacity=99,
            fee_units=0,
        )


def test_dodo_tracks_base_and_quote_debts() -> None:
    base = ExactAssetAmount(_asset(name="BASE"), 100)
    quote = ExactAssetAmount(_asset(name="QUOTE"), 200)
    obligation = DodoFinancingAdapter.prepare(
        evidence=_evm_evidence("dodo"),
        pool_kind=DodoPoolKind.DVM,
        receiver=ADDR_B,
        base_principal=base,
        quote_principal=quote,
        base_fee_units=1,
        quote_fee_units=2,
        base_capacity=500,
        quote_capacity=500,
    )

    assert [item.repayment_units for item in obligation.debts] == [101, 202]


def test_flash_mint_is_limited_by_exit_capacity() -> None:
    principal = ExactAssetAmount(_asset(name="GHO"), 100)
    with pytest.raises(MultiChainError, match="FLASH_MINT_CAPACITY_EXCEEDED"):
        FlashMintAdapter.prepare(
            evidence=_evm_evidence("flash-mint"),
            receiver=ADDR_B,
            principal=principal,
            capacity=FlashMintCapacity(
                max_flash_loan=1_000,
                facilitator_remaining=1_000,
                psm_exit_capacity=99,
            ),
            fee_units=0,
        )


def test_net_settlement_requires_zero_residual() -> None:
    domain = SettlementDomain(
        "balancer-domain",
        NetSettlementDialect.BALANCER_V3,
        _deployment("balancer-v3"),
    )
    adapter = NetSettlementAdapter(domain)
    trace = adapter.begin(ADDR_A)
    trace = adapter.apply(
        trace,
        domain=domain,
        delta=AssetDelta(_asset(), 5),
    )
    with pytest.raises(MultiChainError, match="SETTLEMENT_RESIDUAL_NONZERO"):
        adapter.finalize(trace)
    trace = adapter.apply(
        trace,
        domain=domain,
        delta=AssetDelta(_asset(), -5),
    )
    assert adapter.finalize(trace).settled is True


def test_net_settlement_cannot_cross_domains() -> None:
    left = SettlementDomain(
        "balancer-domain",
        NetSettlementDialect.BALANCER_V3,
        _deployment("balancer-v3"),
    )
    right = SettlementDomain(
        "uniswap-domain",
        NetSettlementDialect.UNISWAP_V4,
        _deployment("uniswap-v4"),
    )
    adapter = NetSettlementAdapter(left)
    trace = adapter.begin(ADDR_A)

    with pytest.raises(
        MultiChainError,
        match="CROSS_SETTLEMENT_DOMAIN_FORBIDDEN",
    ):
        adapter.apply(
            trace,
            domain=right,
            delta=AssetDelta(_asset(), 1),
        )


def _sui_frame() -> SuiStateFrame:
    return SuiStateFrame(
        chain_key="sui-mainnet",
        checkpoint=100,
        epoch=1,
        objects=(
            SuiObjectRef(
                object_id=OBJ_A,
                version=7,
                digest="gas-digest",
                kind=SuiObjectKind.OWNED,
                type_tag="0x2::coin::Coin<0x2::sui::SUI>",
                balance_units=1_000_000,
            ),
            SuiObjectRef(
                object_id=OBJ_B,
                version=5,
                digest="pool-digest",
                kind=SuiObjectKind.SHARED,
                type_tag="0x42::pool::Pool",
            ),
        ),
    )


def test_sui_ptb_rejects_stale_gas_object() -> None:
    plan = SuiPtbPlan(
        chain_key="sui-mainnet",
        checkpoint=100,
        gas_object_id=OBJ_A,
        gas_object_version=6,
        gas_budget_mist=100,
        operations=(SuiPtbOperation("noop", PKG),),
        obligations=(),
        shared_object_ids=(),
    )
    with pytest.raises(MultiChainError, match="SUI_STALE_OBJECT_VERSION"):
        SuiPtbAdapter.compile(_sui_frame(), plan)


def test_sui_hot_potato_must_close_in_same_ptb() -> None:
    principal = ExactAssetAmount(_asset("sui-mainnet", "SUI"), 100)
    debt = SuiHotPotatoObligation(
        obligation_id="loan-1",
        protocol="cetus",
        principal=principal,
        repayment_units=101,
        receipt_type="cetus::flash_loan::Receipt",
        deployment=_deployment("cetus", "sui-mainnet"),
    )
    plan = SuiPtbPlan(
        chain_key="sui-mainnet",
        checkpoint=100,
        gas_object_id=OBJ_A,
        gas_object_version=7,
        gas_budget_mist=100,
        operations=(SuiPtbOperation("borrow", PKG),),
        obligations=(debt,),
        shared_object_ids=(OBJ_B,),
    )
    with pytest.raises(MultiChainError, match="SUI_HOT_POTATO_NOT_CLOSED"):
        SuiPtbAdapter.compile(_sui_frame(), plan)


def test_sui_linear_object_cannot_be_consumed_twice() -> None:
    plan = SuiPtbPlan(
        chain_key="sui-mainnet",
        checkpoint=100,
        gas_object_id=OBJ_A,
        gas_object_version=7,
        gas_budget_mist=100,
        operations=(
            SuiPtbOperation("a", PKG, consumes=(OBJ_C,)),
            SuiPtbOperation("b", PKG, consumes=(OBJ_C,)),
        ),
        obligations=(),
        shared_object_ids=(OBJ_B,),
    )
    with pytest.raises(MultiChainError, match="SUI_OBJECT_DOUBLE_CONSUME"):
        SuiPtbAdapter.compile(_sui_frame(), plan)


def test_deepbook_loan_and_book_use_share_capacity() -> None:
    principal = ExactAssetAmount(_asset("sui-mainnet", "USDC"), 80)
    with pytest.raises(
        MultiChainError,
        match="DEEPBOOK_SHARED_CAPACITY_EXCEEDED",
    ):
        DeepBookFinancingAdapter.prepare(
            deployment=_deployment("deepbook", "sui-mainnet"),
            principal=principal,
            pool_capacity=100,
            same_pool_trade_input=30,
            fee_units=0,
            receipt_type="deepbook::flash::Receipt",
        )


def test_cetus_flashloan_and_flashswap_have_distinct_receipts() -> None:
    principal = ExactAssetAmount(_asset("sui-mainnet", "USDC"), 80)
    loan = CetusFinancingAdapter.prepare(
        deployment=_deployment("cetus", "sui-mainnet"),
        kind=CetusFlashKind.FLASH_LOAN,
        principal=principal,
        fee_units=1,
    )
    swap = CetusFinancingAdapter.prepare(
        deployment=_deployment("cetus", "sui-mainnet"),
        kind=CetusFlashKind.FLASH_SWAP,
        principal=principal,
        fee_units=1,
    )

    assert loan.receipt_type != swap.receipt_type


def test_sui_protocol_receipts_are_not_interchangeable() -> None:
    principal = ExactAssetAmount(_asset("sui-mainnet", "USDC"), 80)
    with pytest.raises(MultiChainError, match="SUI_RECEIPT_PROTOCOL_MISMATCH"):
        SuiAdditionalFinancingAdapter.prepare(
            deployment=_deployment("navi", "sui-mainnet"),
            principal=principal,
            available_capacity=100,
            fee_units=1,
            receipt_type="scallop::flash::Receipt",
        )


def test_cross_chain_atomicity_is_rejected() -> None:
    assert require_single_chain_atomic_scope(("base-mainnet",)) == "base-mainnet"
    with pytest.raises(MultiChainError, match="CROSS_CHAIN_ATOMICITY_FORBIDDEN"):
        require_single_chain_atomic_scope(("base-mainnet", "sui-mainnet"))


def test_chain_qualification_is_scoped_and_never_enables_live() -> None:
    registry = ChainCapabilityRegistry.packaged()
    evidence = ChainEvidence(
        chain_key="base-mainnet",
        profile_id="agg11-base-aave-fixture",
        dialect=ChainDialect.EVM,
        state_proof=True,
        math_proof=True,
        simulation_proof=True,
        economics_proof=True,
        permission_proof=True,
        gas_or_fee_proof=True,
        finality_proof=True,
    )
    verdict = qualify_chain(
        registry=registry,
        chain_key="base-mainnet",
        profile_id=evidence.profile_id,
        capability_ids=("base-mainnet:aave",),
        evidence=evidence,
    )

    assert verdict.live_enabled is False
    assert verdict.externally_qualified is False
    assert "GENESIS_NOT_PINNED" in verdict.blockers
    assert any("DEPLOYMENT_NOT_PINNED" in item for item in verdict.blockers)
