"""AGG-12 sender-free multichain strategy qualification contracts.

The module deliberately stops at deterministic, offline admission. It does not
fetch chain state, hold signing keys, build executable transactions/PTBs, sign,
or submit. Chain adapters materialize the evidence consumed here; this module
checks dialect identity, exact integer economics, resource/state continuity and
strategy-specific invariants before a candidate may proceed to a downstream
chain qualification boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
import re
from typing import Mapping, Sequence

from src.economics.exact_amounts import strict_int

AGG12_SCHEMA = "agg12.multichain-offline-qualification.v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class Agg12Error(ValueError):
    """Malformed AGG-12 evidence or an unsafe implicit assumption."""


class ChainDialect(StrEnum):
    EVM = "evm"
    SUI = "sui"
    STARKNET = "starknet-cairo"
    APTOS = "aptos-move"


class ResearchDisposition(StrEnum):
    RESEARCH_ONLY = "research_only"
    OFFLINE_SUPPORTED = "offline_supported"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    nf_id: str
    admitted: bool
    blockers: tuple[str, ...]
    evidence_digest: str
    conservative_net_units: int | None = None
    live_enabled: bool = False


@dataclass(frozen=True, slots=True)
class ChainAsset:
    chain_id: str
    dialect: ChainDialect
    identifier: str
    decimals: int
    generation: str

    def __post_init__(self) -> None:
        _text(self.chain_id, "chain_id")
        _text(self.identifier, "identifier")
        _text(self.generation, "generation")
        decimals = strict_int(self.decimals, field="decimals")
        if not 0 <= decimals <= 255:
            raise Agg12Error("decimals must fit u8")

    @property
    def identity(self) -> str:
        return (
            f"{self.dialect.value}:{self.chain_id}:"
            f"{self.identifier}:{self.decimals}:{self.generation}"
        )


@dataclass(frozen=True, slots=True)
class ChainResearchDossier:
    chain_id: str
    dialect: ChainDialect
    adapter_dialect: ChainDialect
    official_state_api: bool
    official_simulation_api: bool
    executable_primitives: tuple[str, ...]
    native_gas_asset: str | None
    sdk_license: str | None
    deployment_evidence_sha256: str | None
    signing_model: str
    finality_model: str
    resource_model: str
    access_available: bool
    bridge_required: bool = False

    def __post_init__(self) -> None:
        _text(self.chain_id, "chain_id")
        _text(self.signing_model, "signing_model")
        _text(self.finality_model, "finality_model")
        _text(self.resource_model, "resource_model")
        _text_tuple(
            self.executable_primitives,
            "executable_primitives",
            allow_empty=True,
        )
        if self.native_gas_asset is not None:
            _text(self.native_gas_asset, "native_gas_asset")
        if self.sdk_license is not None:
            _text(self.sdk_license, "sdk_license")
        if self.deployment_evidence_sha256 is not None:
            _sha256(
                self.deployment_evidence_sha256,
                "deployment_evidence_sha256",
            )
        for name in (
            "official_state_api",
            "official_simulation_api",
            "access_available",
            "bridge_required",
        ):
            if type(getattr(self, name)) is not bool:
                raise Agg12Error(f"{name} must be bool")


@dataclass(frozen=True, slots=True)
class ChainResearchVerdict:
    chain_id: str
    disposition: ResearchDisposition
    blockers: tuple[str, ...]
    evidence_digest: str
    live_enabled: bool = False


@dataclass(frozen=True, slots=True)
class RouteLeg:
    protocol: str
    pool_or_market: str
    model_family: str
    input_asset: ChainAsset
    output_asset: ChainAsset
    amount_in: int
    guaranteed_out: int
    fee_units: int
    state_before_sha256: str
    state_after_sha256: str
    shared_resource_id: str

    def __post_init__(self) -> None:
        _text(self.protocol, "protocol")
        _text(self.pool_or_market, "pool_or_market")
        _text(self.model_family, "model_family")
        _text(self.shared_resource_id, "shared_resource_id")
        _positive(self.amount_in, "amount_in")
        _nonnegative(self.guaranteed_out, "guaranteed_out")
        _nonnegative(self.fee_units, "fee_units")
        _sha256(self.state_before_sha256, "state_before_sha256")
        _sha256(self.state_after_sha256, "state_after_sha256")
        if self.input_asset.chain_id != self.output_asset.chain_id:
            raise Agg12Error("route leg cannot cross chains atomically")
        if self.input_asset.dialect is not self.output_asset.dialect:
            raise Agg12Error("route leg cannot change chain dialect")


@dataclass(frozen=True, slots=True)
class EvmCycleEvidence:
    legs: tuple[RouteLeg, ...]
    funded_gas_units: int
    required_gas_units: int
    approval_cost_base_units: int
    flash_fee_base_units: int
    conservative_net_base_units: int
    deployment_current: bool
    callback_repaid: bool


@dataclass(frozen=True, slots=True)
class CollateralFirstEvidence:
    mechanism: str
    deployment_current: bool
    terms_current: bool
    access_permitted: bool
    collateral_units: int
    collateral_sale_output_units: int
    debt_units: int
    funding_units: int
    gas_cost_base_units: int
    callback_permitted: bool
    collateral_delivered_before_debt: bool
    residual_debt_units: int
    noncash_reward_units: int = 0


@dataclass(frozen=True, slots=True)
class BasketComponent:
    asset: ChainAsset
    received_units: int
    executable_exit_base_units: int | None


@dataclass(frozen=True, slots=True)
class BasketEvidence:
    deployment_current: bool
    mandatory_components: tuple[BasketComponent, ...]
    redemption_input_base_units: int
    redemption_fee_base_units: int
    other_cost_base_units: int


@dataclass(frozen=True, slots=True)
class LendingAwareEvidence:
    deployment_current: bool
    permission_current: bool
    vault_health_current: bool
    requested_units: int
    borrow_capacity_units: int
    swap_output_base_units: int
    repay_base_units: int
    total_cost_base_units: int
    residual_debt_units: int


@dataclass(frozen=True, slots=True)
class VaultEvidence:
    deployment_current: bool
    share_units: int
    preview_assets: int
    max_redeem_assets: int
    executable_redeem_assets: int
    synchronous: bool
    queue_delay_seconds: int
    conservative_rounding: bool
    total_cost_base_units: int
    dex_exit_base_units: int


@dataclass(frozen=True, slots=True)
class DynamicFeeEvidence:
    deployment_current: bool
    fee_rule_active: bool
    direction: str
    fee_bps: int
    amount_in: int
    guaranteed_out: int
    other_cost_base_units: int
    state_before_sha256: str
    state_after_sha256: str


@dataclass(frozen=True, slots=True)
class NettingEvidence:
    deployment_current: bool
    unlock_lock_verified: bool
    gross_external_spread_base_units: int
    transfer_savings_base_units: int
    total_cost_base_units: int
    residual_obligation_units: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PendleEvidence:
    deployment_current: bool
    pt_expiry: int
    yt_expiry: int
    matched_expiry: int
    exchange_index_sha256: str
    immediate_settlement: bool
    executable_market: bool
    atomic_surplus_base_units: int
    future_yield_units: int
    total_cost_base_units: int


@dataclass(frozen=True, slots=True)
class FlashMintEvidence:
    deployment_current: bool
    minted_units: int
    mint_cap_units: int
    psm_capacity_units: int
    returned_units: int
    executable_exit_base_units: int
    total_cost_base_units: int
    residual_debt_units: int


@dataclass(frozen=True, slots=True)
class LlammaEvidence:
    deployment_current: bool
    band_state_sha256: str
    collateral_components: tuple[BasketComponent, ...]
    debt_base_units: int
    total_cost_base_units: int


@dataclass(frozen=True, slots=True)
class IntentEvidence:
    deployment_current: bool
    signature_valid: bool
    taker_permitted: bool
    expires_at_unix: int
    now_unix: int
    user_min_out_units: int
    user_out_units: int
    onboarding_complete: bool
    bond_cost_base_units: int
    solver_gas_base_units: int
    solver_gross_surplus_base_units: int
    partial_fill_obligation_satisfied: bool


@dataclass(frozen=True, slots=True)
class OptInBackrunEvidence:
    source_authorized: bool
    relay_current: bool
    consent_bound: bool
    hints_complete: bool
    user_conditions_satisfied: bool
    no_sandwich: bool
    no_oracle_manipulation: bool
    conservative_surplus_base_units: int
    total_cost_base_units: int


@dataclass(frozen=True, slots=True)
class SuiObjectTransition:
    object_id: str
    before_version: int
    after_version: int
    liquidity_before: int
    liquidity_after: int


@dataclass(frozen=True, slots=True)
class SuiCycleEvidence:
    deployment_current: bool
    route_legs: tuple[RouteLeg, ...]
    object_transitions: tuple[SuiObjectTransition, ...]
    borrowed_units: int
    returned_units: int
    gas_budget_units: int
    required_gas_units: int
    taker_fee_base_units: int
    conservative_net_base_units: int


@dataclass(frozen=True, slots=True)
class GasBidOption:
    gas_bid_units: int
    network_cost_base_units: int
    protocol_taker_fee_base_units: int
    conservative_output_base_units: int

    @property
    def conservative_net_base_units(self) -> int:
        return (
            self.conservative_output_base_units
            - self.network_cost_base_units
            - self.protocol_taker_fee_base_units
        )


@dataclass(frozen=True, slots=True)
class GasFeeChoice:
    option: GasBidOption | None
    decision: AdmissionDecision


def build_starknet_aptos_adapters(
    starknet: ChainResearchDossier,
    aptos: ChainResearchDossier,
) -> tuple[ChainResearchVerdict, ChainResearchVerdict]:
    """NF-269: admit separate Cairo/Move evidence, never EVM/Sui aliases."""

    if starknet.dialect is not ChainDialect.STARKNET:
        raise Agg12Error("starknet dossier must use Starknet/Cairo dialect")
    if aptos.dialect is not ChainDialect.APTOS:
        raise Agg12Error("aptos dossier must use Aptos/Move dialect")
    return (
        _qualify_chain_dossier(starknet, "NF-269"),
        _qualify_chain_dossier(aptos, "NF-269"),
    )


def evaluate_emerging_chain(
    dossier: ChainResearchDossier,
) -> ChainResearchVerdict:
    """NF-270: preserve negative findings and require access/deployment evidence."""

    return _qualify_chain_dossier(dossier, "NF-270")


def qualify_evm_cycle(evidence: EvmCycleEvidence) -> AdmissionDecision:
    """NF-272: exact 2-5 hop EVM cycle with shared-state continuity."""

    blockers: list[str] = []
    if not 2 <= len(evidence.legs) <= 5:
        blockers.append("EVM_CYCLE_HOP_COUNT_UNSUPPORTED")
    blockers.extend(
        _route_blockers(
            evidence.legs,
            ChainDialect.EVM,
            require_cycle=True,
        )
    )
    if not evidence.deployment_current:
        blockers.append("EVM_DEPLOYMENT_UNQUALIFIED")
    if not evidence.callback_repaid:
        blockers.append("EVM_CALLBACK_REPAYMENT_UNPROVEN")
    _nonnegative(evidence.funded_gas_units, "funded_gas_units")
    _nonnegative(evidence.required_gas_units, "required_gas_units")
    _nonnegative(
        evidence.approval_cost_base_units,
        "approval_cost_base_units",
    )
    _nonnegative(evidence.flash_fee_base_units, "flash_fee_base_units")
    claimed_net = strict_int(
        evidence.conservative_net_base_units,
        field="conservative_net_base_units",
    )
    route_bound = claimed_net
    if evidence.legs:
        route_bound = (
            evidence.legs[-1].guaranteed_out
            - evidence.legs[0].amount_in
            - evidence.approval_cost_base_units
            - evidence.flash_fee_base_units
        )
        if claimed_net > route_bound:
            blockers.append("EVM_CLAIMED_NET_EXCEEDS_ROUTE_BOUND")
    net = min(claimed_net, route_bound)
    if evidence.funded_gas_units < evidence.required_gas_units:
        blockers.append("EVM_GAS_NOT_FUNDED")
    if net <= 0:
        blockers.append("EVM_CONSERVATIVE_NET_NONPOSITIVE")
    return _decision("NF-272", evidence, blockers, net)


def qualify_compound_stock(
    evidence: CollateralFirstEvidence,
) -> AdmissionDecision:
    """NF-273: Compound stock sale, excluding absorb points from cash profit."""

    return _qualify_collateral_first(
        "NF-273",
        evidence,
        mechanism="compound-buy-collateral",
        require_callback=False,
    )


def qualify_sky_callback(
    evidence: CollateralFirstEvidence,
) -> AdmissionDecision:
    """NF-274: collateral-first Sky auction callback with current terms."""

    return _qualify_collateral_first(
        "NF-274",
        evidence,
        mechanism="sky-auction-callback",
        require_callback=True,
    )


def qualify_morpho_preliq(
    evidence: CollateralFirstEvidence,
) -> AdmissionDecision:
    """NF-275: permissioned collateral-before-debt pre-liquidation path."""

    return _qualify_collateral_first(
        "NF-275",
        evidence,
        mechanism="morpho-pre-liquidation",
        require_callback=True,
    )


def qualify_bold_basket(evidence: BasketEvidence) -> AdmissionDecision:
    """NF-276: value every mandatory redemption component via executable exit."""

    blockers: list[str] = []
    if not evidence.deployment_current:
        blockers.append("BASKET_DEPLOYMENT_UNQUALIFIED")
    if not evidence.mandatory_components:
        blockers.append("BASKET_COMPONENTS_MISSING")
    total_exit = 0
    for index, component in enumerate(evidence.mandatory_components):
        _nonnegative(
            component.received_units,
            f"component[{index}].received_units",
        )
        if component.executable_exit_base_units is None:
            blockers.append(f"BASKET_COMPONENT_{index}_EXIT_UNKNOWN")
            continue
        _nonnegative(
            component.executable_exit_base_units,
            f"component[{index}].executable_exit_base_units",
        )
        total_exit += component.executable_exit_base_units
    _positive(
        evidence.redemption_input_base_units,
        "redemption_input_base_units",
    )
    _nonnegative(
        evidence.redemption_fee_base_units,
        "redemption_fee_base_units",
    )
    _nonnegative(evidence.other_cost_base_units, "other_cost_base_units")
    net = (
        total_exit
        - evidence.redemption_input_base_units
        - evidence.redemption_fee_base_units
        - evidence.other_cost_base_units
    )
    if net <= 0:
        blockers.append("BASKET_CONSERVATIVE_NET_NONPOSITIVE")
    return _decision("NF-276", evidence, blockers, net)


def qualify_eulerswap(
    evidence: LendingAwareEvidence,
) -> AdmissionDecision:
    """NF-277: lending-aware swap with exact capacity and repayment."""

    blockers = _lending_aware_blockers(evidence, prefix="EULERSWAP")
    net = (
        evidence.swap_output_base_units
        - evidence.repay_base_units
        - evidence.total_cost_base_units
    )
    if net <= 0:
        blockers.append("EULERSWAP_CONSERVATIVE_NET_NONPOSITIVE")
    return _decision("NF-277", evidence, blockers, net)


def qualify_erc4626(evidence: VaultEvidence) -> AdmissionDecision:
    """NF-278: preview is informative; synchronous executable redeem is authority."""

    blockers: list[str] = []
    if not evidence.deployment_current:
        blockers.append("ERC4626_DEPLOYMENT_UNQUALIFIED")
    for name in (
        "share_units",
        "preview_assets",
        "max_redeem_assets",
        "executable_redeem_assets",
        "queue_delay_seconds",
        "total_cost_base_units",
        "dex_exit_base_units",
    ):
        _nonnegative(getattr(evidence, name), name)
    if not evidence.synchronous or evidence.queue_delay_seconds:
        blockers.append("ERC4626_ASYNC_REDEEM_NOT_ATOMIC_EXIT")
    if evidence.executable_redeem_assets > evidence.max_redeem_assets:
        blockers.append("ERC4626_REDEEM_EXCEEDS_CAPACITY")
    if evidence.preview_assets < evidence.executable_redeem_assets:
        blockers.append("ERC4626_EXECUTABLE_REDEEM_EXCEEDS_PREVIEW")
    if not evidence.conservative_rounding:
        blockers.append("ERC4626_ROUNDING_NOT_CONSERVATIVE")
    net = evidence.dex_exit_base_units - evidence.total_cost_base_units
    if net <= 0:
        blockers.append("ERC4626_CONSERVATIVE_NET_NONPOSITIVE")
    return _decision("NF-278", evidence, blockers, net)


def qualify_stablesurge(
    evidence: DynamicFeeEvidence,
) -> AdmissionDecision:
    """NF-279: use active directional fee state and bind the post-trade state."""

    blockers: list[str] = []
    if not evidence.deployment_current:
        blockers.append("DYNAMIC_FEE_DEPLOYMENT_UNQUALIFIED")
    if not evidence.fee_rule_active:
        blockers.append("DYNAMIC_FEE_RULE_INACTIVE")
    _text(evidence.direction, "direction")
    _bounded_bps(evidence.fee_bps, "fee_bps")
    _positive(evidence.amount_in, "amount_in")
    _nonnegative(evidence.guaranteed_out, "guaranteed_out")
    _nonnegative(
        evidence.other_cost_base_units,
        "other_cost_base_units",
    )
    _sha256(evidence.state_before_sha256, "state_before_sha256")
    _sha256(evidence.state_after_sha256, "state_after_sha256")
    if evidence.state_before_sha256 == evidence.state_after_sha256:
        blockers.append("DYNAMIC_FEE_STATE_TRANSITION_UNPROVEN")
    fee_units = _ceil_mul_div(
        evidence.amount_in,
        evidence.fee_bps,
        10_000,
    )
    net = (
        evidence.guaranteed_out
        - evidence.amount_in
        - fee_units
        - evidence.other_cost_base_units
    )
    if net <= 0:
        blockers.append("DYNAMIC_FEE_CONSERVATIVE_NET_NONPOSITIVE")
    return _decision("NF-279", evidence, blockers, net)


def qualify_netting(evidence: NettingEvidence) -> AdmissionDecision:
    """NF-280: transfer savings are cost savings, never independent spread."""

    blockers: list[str] = []
    if not evidence.deployment_current:
        blockers.append("NETTING_DEPLOYMENT_UNQUALIFIED")
    if not evidence.unlock_lock_verified:
        blockers.append("NETTING_UNLOCK_LOCK_UNPROVEN")
    _nonnegative(
        evidence.gross_external_spread_base_units,
        "gross_external_spread_base_units",
    )
    _nonnegative(
        evidence.transfer_savings_base_units,
        "transfer_savings_base_units",
    )
    _nonnegative(
        evidence.total_cost_base_units,
        "total_cost_base_units",
    )
    if any(
        strict_int(x, field="residual_obligation_units") != 0
        for x in evidence.residual_obligation_units
    ):
        blockers.append("NETTING_RESIDUAL_OBLIGATION")
    if evidence.gross_external_spread_base_units <= 0:
        blockers.append("NETTING_SAVINGS_ARE_NOT_SPREAD")
    net = (
        evidence.gross_external_spread_base_units
        - evidence.total_cost_base_units
    )
    if net <= 0:
        blockers.append("NETTING_CONSERVATIVE_NET_NONPOSITIVE")
    return _decision("NF-280", evidence, blockers, net)


def qualify_pendle(evidence: PendleEvidence) -> AdmissionDecision:
    """NF-281: immediate matched PT/YT/SY rights; future yield is excluded."""

    blockers: list[str] = []
    if not evidence.deployment_current:
        blockers.append("PENDLE_DEPLOYMENT_UNQUALIFIED")
    for name in ("pt_expiry", "yt_expiry", "matched_expiry"):
        _positive(getattr(evidence, name), name)
    _sha256(evidence.exchange_index_sha256, "exchange_index_sha256")
    _nonnegative(evidence.future_yield_units, "future_yield_units")
    _nonnegative(
        evidence.total_cost_base_units,
        "total_cost_base_units",
    )
    net = (
        strict_int(
            evidence.atomic_surplus_base_units,
            field="atomic_surplus_base_units",
        )
        - evidence.total_cost_base_units
    )
    if (
        evidence.pt_expiry != evidence.yt_expiry
        or evidence.pt_expiry != evidence.matched_expiry
    ):
        blockers.append("PENDLE_EXPIRY_RIGHTS_MISMATCH")
    if not evidence.immediate_settlement:
        blockers.append("PENDLE_SETTLEMENT_NOT_IMMEDIATE")
    if not evidence.executable_market:
        blockers.append("PENDLE_EXECUTABLE_MARKET_MISSING")
    if net <= 0:
        blockers.append("PENDLE_ATOMIC_NET_NONPOSITIVE")
    return _decision("NF-281", evidence, blockers, net)


def qualify_flashmint_psm(
    evidence: FlashMintEvidence,
) -> AdmissionDecision:
    """NF-282: mint cap, PSM capacity, burn and full cost closure."""

    blockers: list[str] = []
    if not evidence.deployment_current:
        blockers.append("FLASHMINT_DEPLOYMENT_UNQUALIFIED")
    for name in (
        "minted_units",
        "mint_cap_units",
        "psm_capacity_units",
        "returned_units",
        "executable_exit_base_units",
        "total_cost_base_units",
        "residual_debt_units",
    ):
        _nonnegative(getattr(evidence, name), name)
    if evidence.minted_units <= 0:
        blockers.append("FLASHMINT_ZERO_PRINCIPAL")
    if evidence.minted_units > evidence.mint_cap_units:
        blockers.append("FLASHMINT_CAP_EXCEEDED")
    if evidence.minted_units > evidence.psm_capacity_units:
        blockers.append("FLASHMINT_PSM_CAPACITY_EXCEEDED")
    if (
        evidence.returned_units < evidence.minted_units
        or evidence.residual_debt_units
    ):
        blockers.append("FLASHMINT_NOT_FULLY_RETURNED")
    net = (
        evidence.executable_exit_base_units
        - evidence.total_cost_base_units
    )
    if net <= 0:
        blockers.append("FLASHMINT_CONSERVATIVE_NET_NONPOSITIVE")
    return _decision("NF-282", evidence, blockers, net)


def qualify_llamma(evidence: LlammaEvidence) -> AdmissionDecision:
    """NF-283: current bands and every collateral component require exact exit."""

    blockers: list[str] = []
    if not evidence.deployment_current:
        blockers.append("LLAMMA_DEPLOYMENT_UNQUALIFIED")
    _sha256(evidence.band_state_sha256, "band_state_sha256")
    _nonnegative(evidence.debt_base_units, "debt_base_units")
    _nonnegative(
        evidence.total_cost_base_units,
        "total_cost_base_units",
    )
    total_exit = 0
    if not evidence.collateral_components:
        blockers.append("LLAMMA_COLLATERAL_COMPONENTS_MISSING")
    for index, component in enumerate(evidence.collateral_components):
        if component.executable_exit_base_units is None:
            blockers.append(f"LLAMMA_COMPONENT_{index}_EXIT_UNKNOWN")
            continue
        _nonnegative(
            component.executable_exit_base_units,
            "executable_exit_base_units",
        )
        total_exit += component.executable_exit_base_units
    net = (
        total_exit
        - evidence.debt_base_units
        - evidence.total_cost_base_units
    )
    if net <= 0:
        blockers.append("LLAMMA_CONSERVATIVE_NET_NONPOSITIVE")
    return _decision("NF-283", evidence, blockers, net)


def qualify_intent_fill(evidence: IntentEvidence) -> AdmissionDecision:
    """NF-284: signature/access/expiry/user minimum plus solver costs."""

    blockers: list[str] = []
    for name in (
        "expires_at_unix",
        "now_unix",
        "user_min_out_units",
        "user_out_units",
        "bond_cost_base_units",
        "solver_gas_base_units",
        "solver_gross_surplus_base_units",
    ):
        _nonnegative(getattr(evidence, name), name)
    if not evidence.deployment_current:
        blockers.append("INTENT_DEPLOYMENT_UNQUALIFIED")
    if not evidence.signature_valid:
        blockers.append("INTENT_SIGNATURE_INVALID")
    if not evidence.taker_permitted:
        blockers.append("INTENT_TAKER_NOT_PERMITTED")
    if evidence.now_unix >= evidence.expires_at_unix:
        blockers.append("INTENT_EXPIRED")
    if evidence.user_out_units < evidence.user_min_out_units:
        blockers.append("INTENT_USER_MINIMUM_VIOLATED")
    if not evidence.onboarding_complete:
        blockers.append("INTENT_SOLVER_ONBOARDING_MISSING")
    if not evidence.partial_fill_obligation_satisfied:
        blockers.append("INTENT_PARTIAL_FILL_OBLIGATION_OPEN")
    net = (
        evidence.solver_gross_surplus_base_units
        - evidence.bond_cost_base_units
        - evidence.solver_gas_base_units
    )
    if net <= 0:
        blockers.append("INTENT_SOLVER_NET_NONPOSITIVE")
    return _decision("NF-284", evidence, blockers, net)


def qualify_optin_backrun(
    evidence: OptInBackrunEvidence,
) -> AdmissionDecision:
    """NF-285: consented orderflow only; sandwich/oracle manipulation fail closed."""

    blockers: list[str] = []
    checks = {
        "BACKRUN_SOURCE_NOT_AUTHORIZED": evidence.source_authorized,
        "BACKRUN_RELAY_NOT_CURRENT": evidence.relay_current,
        "BACKRUN_CONSENT_NOT_BOUND": evidence.consent_bound,
        "BACKRUN_HINTS_INCOMPLETE": evidence.hints_complete,
        "BACKRUN_USER_CONDITIONS_UNSATISFIED": (
            evidence.user_conditions_satisfied
        ),
        "BACKRUN_SANDWICH_FORBIDDEN": evidence.no_sandwich,
        "BACKRUN_ORACLE_MANIPULATION_FORBIDDEN": (
            evidence.no_oracle_manipulation
        ),
    }
    blockers.extend(code for code, ok in checks.items() if not ok)
    _nonnegative(
        evidence.total_cost_base_units,
        "total_cost_base_units",
    )
    gross = strict_int(
        evidence.conservative_surplus_base_units,
        field="conservative_surplus_base_units",
    )
    net = gross - evidence.total_cost_base_units
    if net <= 0:
        blockers.append("BACKRUN_CONSERVATIVE_NET_NONPOSITIVE")
    return _decision("NF-285", evidence, blockers, net)


def qualify_sui_book(evidence: SuiCycleEvidence) -> AdmissionDecision:
    """NF-286: Sui PTB cycle with exact coin and shared-object continuity."""

    blockers: list[str] = []
    if not evidence.deployment_current:
        blockers.append("SUI_DEPLOYMENT_UNQUALIFIED")
    blockers.extend(
        _route_blockers(
            evidence.route_legs,
            ChainDialect.SUI,
            require_cycle=True,
        )
    )
    _nonnegative(evidence.borrowed_units, "borrowed_units")
    _nonnegative(evidence.returned_units, "returned_units")
    _nonnegative(evidence.gas_budget_units, "gas_budget_units")
    _nonnegative(evidence.required_gas_units, "required_gas_units")
    _nonnegative(
        evidence.taker_fee_base_units,
        "taker_fee_base_units",
    )
    claimed_net = strict_int(
        evidence.conservative_net_base_units,
        field="conservative_net_base_units",
    )
    route_bound = claimed_net
    if evidence.route_legs:
        if evidence.route_legs[0].amount_in != evidence.borrowed_units:
            blockers.append("SUI_BORROW_ROUTE_INPUT_MISMATCH")
        route_bound = (
            evidence.route_legs[-1].guaranteed_out
            - evidence.returned_units
            - evidence.taker_fee_base_units
        )
        if claimed_net > route_bound:
            blockers.append("SUI_CLAIMED_NET_EXCEEDS_ROUTE_BOUND")
    net = min(claimed_net, route_bound)
    if evidence.returned_units < evidence.borrowed_units:
        blockers.append("SUI_BORROW_NOT_REPAID")
    if evidence.gas_budget_units < evidence.required_gas_units:
        blockers.append("SUI_GAS_NOT_FUNDED")
    blockers.extend(
        _sui_object_blockers(
            evidence.object_transitions,
            required_resource_ids=tuple(
                leg.shared_resource_id for leg in evidence.route_legs
            ),
        )
    )
    if net <= 0:
        blockers.append("SUI_CONSERVATIVE_NET_NONPOSITIVE")
    return _decision("NF-286", evidence, blockers, net)


def choose_sui_gas_option(
    options: Sequence[GasBidOption],
    *,
    fee_rule_active: bool,
    deployment_generation: str,
    fee_rule_generation: str,
) -> GasFeeChoice:
    """NF-287: choose best constrained net, never highest gas bid by default."""

    blockers: list[str] = []
    _text(deployment_generation, "deployment_generation")
    _text(fee_rule_generation, "fee_rule_generation")
    if not fee_rule_active:
        blockers.append("SUI_FEE_RULE_INACTIVE")
    if deployment_generation != fee_rule_generation:
        blockers.append("SUI_FEE_RULE_GENERATION_STALE")
    normalized = tuple(options)
    if not normalized:
        blockers.append("SUI_GAS_OPTIONS_EMPTY")
    for index, option in enumerate(normalized):
        _nonnegative(
            option.gas_bid_units,
            f"options[{index}].gas_bid_units",
        )
        _nonnegative(
            option.network_cost_base_units,
            f"options[{index}].network_cost_base_units",
        )
        _nonnegative(
            option.protocol_taker_fee_base_units,
            f"options[{index}].protocol_taker_fee_base_units",
        )
        _nonnegative(
            option.conservative_output_base_units,
            f"options[{index}].conservative_output_base_units",
        )
    best = max(
        normalized,
        key=lambda x: x.conservative_net_base_units,
        default=None,
    )
    net = (
        best.conservative_net_base_units
        if best is not None
        else None
    )
    if best is not None and best.conservative_net_base_units <= 0:
        blockers.append("SUI_GAS_OPTION_NET_NONPOSITIVE")
    decision = _decision(
        "NF-287",
        {
            "options": normalized,
            "fee_rule_active": fee_rule_active,
            "deployment_generation": deployment_generation,
            "fee_rule_generation": fee_rule_generation,
        },
        blockers,
        net,
    )
    return GasFeeChoice(
        option=best if decision.admitted else None,
        decision=decision,
    )


def _qualify_chain_dossier(
    dossier: ChainResearchDossier,
    nf_id: str,
) -> ChainResearchVerdict:
    blockers: list[str] = []
    if dossier.adapter_dialect is not dossier.dialect:
        blockers.append("CHAIN_DIALECT_ADAPTER_MISMATCH")
    if (
        dossier.dialect in {ChainDialect.STARKNET, ChainDialect.APTOS}
        and dossier.adapter_dialect is ChainDialect.EVM
    ):
        blockers.append("CHAIN_EVM_ABI_REUSE_FORBIDDEN")
    if not dossier.official_state_api:
        blockers.append("CHAIN_OFFICIAL_STATE_API_UNAVAILABLE")
    if not dossier.official_simulation_api:
        blockers.append("CHAIN_OFFICIAL_SIMULATION_API_UNAVAILABLE")
    if not dossier.executable_primitives:
        blockers.append("CHAIN_EXECUTABLE_PRIMITIVES_UNPROVEN")
    if dossier.native_gas_asset is None:
        blockers.append("CHAIN_NATIVE_GAS_ASSET_UNVERIFIED")
    if dossier.sdk_license is None:
        blockers.append("CHAIN_SDK_LICENSE_UNREVIEWED")
    if dossier.deployment_evidence_sha256 is None:
        blockers.append("CHAIN_DEPLOYMENT_EVIDENCE_MISSING")
    if not dossier.access_available:
        blockers.append("CHAIN_ACCESS_UNAVAILABLE")
    disposition = (
        ResearchDisposition.OFFLINE_SUPPORTED
        if not blockers
        else ResearchDisposition.RESEARCH_ONLY
    )
    return ChainResearchVerdict(
        chain_id=dossier.chain_id,
        disposition=disposition,
        blockers=tuple(dict.fromkeys(blockers)),
        evidence_digest=_digest(
            {"nf_id": nf_id, "dossier": dossier}
        ),
        live_enabled=False,
    )


def _route_blockers(
    legs: Sequence[RouteLeg],
    dialect: ChainDialect,
    *,
    require_cycle: bool,
) -> list[str]:
    blockers: list[str] = []
    if not legs:
        return ["ROUTE_EMPTY"]
    for index, leg in enumerate(legs):
        if (
            leg.input_asset.dialect is not dialect
            or leg.output_asset.dialect is not dialect
        ):
            blockers.append(f"LEG_{index}_DIALECT_MISMATCH")
        if index:
            prev = legs[index - 1]
            if prev.output_asset != leg.input_asset:
                blockers.append(
                    f"LEG_{index}_ASSET_CONTINUITY_BROKEN"
                )
            if leg.amount_in > prev.guaranteed_out:
                blockers.append(
                    f"LEG_{index}_INPUT_EXCEEDS_PRIOR_OUTPUT"
                )
    if (
        require_cycle
        and legs[0].input_asset != legs[-1].output_asset
    ):
        blockers.append("ROUTE_NOT_CLOSED")
    seen: dict[str, RouteLeg] = {}
    for index, leg in enumerate(legs):
        prior = seen.get(leg.shared_resource_id)
        if (
            prior is not None
            and prior.state_after_sha256
            != leg.state_before_sha256
        ):
            blockers.append(
                f"LEG_{index}_SHARED_RESOURCE_STATE_RESET"
            )
        seen[leg.shared_resource_id] = leg
    return blockers


def _qualify_collateral_first(
    nf_id: str,
    evidence: CollateralFirstEvidence,
    *,
    mechanism: str,
    require_callback: bool,
) -> AdmissionDecision:
    blockers: list[str] = []
    if evidence.mechanism != mechanism:
        blockers.append("COLLATERAL_MECHANISM_MISMATCH")
    if not evidence.deployment_current:
        blockers.append("COLLATERAL_DEPLOYMENT_UNQUALIFIED")
    if not evidence.terms_current:
        blockers.append("COLLATERAL_TERMS_STALE")
    if not evidence.access_permitted:
        blockers.append("COLLATERAL_ACCESS_NOT_PERMITTED")
    if require_callback and not evidence.callback_permitted:
        blockers.append("COLLATERAL_CALLBACK_NOT_PERMITTED")
    if (
        require_callback
        and not evidence.collateral_delivered_before_debt
    ):
        blockers.append("COLLATERAL_FIRST_ORDER_UNPROVEN")
    for name in (
        "collateral_units",
        "collateral_sale_output_units",
        "debt_units",
        "funding_units",
        "gas_cost_base_units",
        "residual_debt_units",
        "noncash_reward_units",
    ):
        _nonnegative(getattr(evidence, name), name)
    if evidence.funding_units < evidence.debt_units:
        blockers.append("COLLATERAL_FUNDING_INSUFFICIENT")
    if evidence.residual_debt_units:
        blockers.append("COLLATERAL_RESIDUAL_DEBT")
    net = (
        evidence.collateral_sale_output_units
        - evidence.debt_units
        - evidence.gas_cost_base_units
    )
    if net <= 0:
        blockers.append("COLLATERAL_CONSERVATIVE_NET_NONPOSITIVE")
    return _decision(nf_id, evidence, blockers, net)


def _lending_aware_blockers(
    evidence: LendingAwareEvidence,
    *,
    prefix: str,
) -> list[str]:
    blockers: list[str] = []
    if not evidence.deployment_current:
        blockers.append(f"{prefix}_DEPLOYMENT_UNQUALIFIED")
    if not evidence.permission_current:
        blockers.append(f"{prefix}_PERMISSION_MISSING")
    if not evidence.vault_health_current:
        blockers.append(f"{prefix}_VAULT_HEALTH_STALE")
    for name in (
        "requested_units",
        "borrow_capacity_units",
        "swap_output_base_units",
        "repay_base_units",
        "total_cost_base_units",
        "residual_debt_units",
    ):
        _nonnegative(getattr(evidence, name), name)
    if evidence.requested_units > evidence.borrow_capacity_units:
        blockers.append(f"{prefix}_CAPACITY_EXCEEDED")
    if evidence.repay_base_units < evidence.requested_units:
        blockers.append(f"{prefix}_REPAYMENT_BELOW_BORROW")
    if evidence.residual_debt_units:
        blockers.append(f"{prefix}_RESIDUAL_DEBT")
    return blockers


def _sui_object_blockers(
    transitions: Sequence[SuiObjectTransition],
    *,
    required_resource_ids: Sequence[str] = (),
) -> list[str]:
    blockers: list[str] = []
    if required_resource_ids and not transitions:
        blockers.append("SUI_OBJECT_TRANSITIONS_MISSING")
    seen: dict[str, SuiObjectTransition] = {}
    for index, transition in enumerate(transitions):
        _text(transition.object_id, "object_id")
        _nonnegative(
            transition.before_version,
            "before_version",
        )
        _positive(transition.after_version, "after_version")
        _nonnegative(
            transition.liquidity_before,
            "liquidity_before",
        )
        _nonnegative(
            transition.liquidity_after,
            "liquidity_after",
        )
        if transition.after_version <= transition.before_version:
            blockers.append(
                f"SUI_OBJECT_{index}_VERSION_NOT_ADVANCED"
            )
        prior = seen.get(transition.object_id)
        if prior is not None:
            if prior.after_version != transition.before_version:
                blockers.append(
                    f"SUI_OBJECT_{index}_VERSION_CHAIN_BROKEN"
                )
            if (
                prior.liquidity_after
                != transition.liquidity_before
            ):
                blockers.append(
                    f"SUI_OBJECT_{index}_LIQUIDITY_RESET"
                )
        seen[transition.object_id] = transition
    required = tuple(required_resource_ids)
    if len(transitions) != len(required):
        blockers.append("SUI_SHARED_RESOURCE_TRANSITION_COUNT_MISMATCH")
    for access_index, resource_id in enumerate(required):
        if access_index >= len(transitions):
            blockers.append(
                "SUI_SHARED_RESOURCE_TRANSITION_MISSING:"
                f"{access_index}:{resource_id}"
            )
            continue
        if transitions[access_index].object_id != resource_id:
            blockers.append(
                "SUI_SHARED_RESOURCE_TRANSITION_SEQUENCE_MISMATCH:"
                f"{access_index}:{resource_id}"
            )
    return blockers


def _decision(
    nf_id: str,
    evidence: object,
    blockers: Sequence[str],
    net: int | None,
) -> AdmissionDecision:
    unique = tuple(dict.fromkeys(blockers))
    return AdmissionDecision(
        nf_id=nf_id,
        admitted=not unique,
        blockers=unique,
        evidence_digest=_digest(
            {"nf_id": nf_id, "evidence": evidence}
        ),
        conservative_net_units=net,
        live_enabled=False,
    )


def _digest(value: object) -> str:
    return sha256(
        _stable_json(_jsonable(value)).encode()
    ).hexdigest()


def _jsonable(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: _jsonable(getattr(value, name))
            for name in value.__dataclass_fields__
        }
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Agg12Error(f"{field} must be non-empty text")
    return value


def _text_tuple(
    value: tuple[str, ...],
    field: str,
    *,
    allow_empty: bool = False,
) -> None:
    if not isinstance(value, tuple):
        raise Agg12Error(f"{field} must be a tuple")
    if not allow_empty and not value:
        raise Agg12Error(f"{field} must not be empty")
    if any(
        not isinstance(item, str) or not item.strip()
        for item in value
    ):
        raise Agg12Error(
            f"{field} must contain non-empty text"
        )
    if len(value) != len(set(value)):
        raise Agg12Error(
            f"{field} must not contain duplicates"
        )


def _sha256(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not _HEX64.fullmatch(value)
    ):
        raise Agg12Error(
            f"{field} must be a lowercase sha256 digest"
        )
    return value


def _nonnegative(value: object, field: str) -> int:
    number = strict_int(value, field=field)
    if number < 0:
        raise Agg12Error(f"{field} must be non-negative")
    return number


def _positive(value: object, field: str) -> int:
    number = strict_int(value, field=field)
    if number <= 0:
        raise Agg12Error(f"{field} must be positive")
    return number


def _bounded_bps(value: object, field: str) -> int:
    number = strict_int(value, field=field)
    if not 0 <= number <= 10_000:
        raise Agg12Error(
            f"{field} must be in [0,10000]"
        )
    return number


def _ceil_mul_div(
    value: int,
    numerator: int,
    denominator: int,
) -> int:
    _nonnegative(value, "value")
    _nonnegative(numerator, "numerator")
    _positive(denominator, "denominator")
    return (
        value * numerator + denominator - 1
    ) // denominator


__all__ = [
    "AGG12_SCHEMA",
    "AdmissionDecision",
    "Agg12Error",
    "BasketComponent",
    "BasketEvidence",
    "ChainAsset",
    "ChainDialect",
    "ChainResearchDossier",
    "ChainResearchVerdict",
    "CollateralFirstEvidence",
    "DynamicFeeEvidence",
    "EvmCycleEvidence",
    "FlashMintEvidence",
    "GasBidOption",
    "GasFeeChoice",
    "IntentEvidence",
    "LendingAwareEvidence",
    "LlammaEvidence",
    "NettingEvidence",
    "OptInBackrunEvidence",
    "PendleEvidence",
    "ResearchDisposition",
    "RouteLeg",
    "SuiCycleEvidence",
    "SuiObjectTransition",
    "VaultEvidence",
    "build_starknet_aptos_adapters",
    "choose_sui_gas_option",
    "evaluate_emerging_chain",
    "qualify_bold_basket",
    "qualify_compound_stock",
    "qualify_erc4626",
    "qualify_eulerswap",
    "qualify_evm_cycle",
    "qualify_flashmint_psm",
    "qualify_intent_fill",
    "qualify_llamma",
    "qualify_morpho_preliq",
    "qualify_netting",
    "qualify_optin_backrun",
    "qualify_pendle",
    "qualify_sky_callback",
    "qualify_stablesurge",
    "qualify_sui_book",
]
