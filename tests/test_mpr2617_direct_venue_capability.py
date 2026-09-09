from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from src.direct_venue.mpr2617 import (
    CapabilityState,
    DirectRouteLeg,
    DirectVenueError,
    InstructionAccount,
    ORCA_LICENSE_CLASS,
    ORCA_REVIEWED_SOURCE_COMMIT,
    ORCA_SOURCE_REPOSITORY,
    ORCA_WHIRLPOOLS_PROGRAM_ID,
    OrcaWhirlpoolProof,
    RootedAccountEvidence,
    RouteMode,
    TokenIdentity,
    VenueCapability,
    VenueCapabilityRegistry,
    VenueFamily,
    build_orca_capability,
    qualify_orca_offline,
    qualify_route,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
GENESIS = "e" * 64
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
POOL = "HJPjoWUrhoZzk9SyQd6A4MKM7NYbTW1ySFVxj7uM3f6w"
MINT_A = "So11111111111111111111111111111111111111112"
MINT_B = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
VAULT_A = "3uJcA7J5YvMfWTGxGdV3aKX5eAkKtgW6iwN3P5xV7GmS"
VAULT_B = "7mNwvjTVqugBVDv4DjJ6Tj7RrS8SmWm9cZPiGm7P2ZyA"
TICK_0 = "2pKKxQ4jEDvHH1bRdpF3xBqdRVPRxtD7nVLQ6QMu9WSe"
TICK_1 = "9wXqq3hCkBjgvxMXYSmrH78ahF96iN2C8mK6yMWGjMgU"
AUTH = "4vJ9JU1bJJE96FWSJKvHsmmFZAcgeEQC9xNTDgBms4qN"


def _account(
    address: str,
    sha: str = SHA_A,
    *,
    owner: str = ORCA_WHIRLPOOLS_PROGRAM_ID,
) -> RootedAccountEvidence:
    return RootedAccountEvidence(address, owner, 100, 100, sha, "gen-1")


def _accounts() -> tuple[InstructionAccount, ...]:
    return (
        InstructionAccount(AUTH, False, True, "token_authority"),
        InstructionAccount(POOL, True, False, "whirlpool"),
        InstructionAccount(VAULT_A, True, False, "token_vault_a"),
        InstructionAccount(VAULT_B, True, False, "token_vault_b"),
        InstructionAccount(TICK_0, True, False, "tick_array_0"),
        InstructionAccount(TICK_1, True, False, "tick_array_1"),
        InstructionAccount(TOKEN_PROGRAM, False, False, "token_program"),
    )


def _digest_accounts(accounts: tuple[InstructionAccount, ...]) -> str:
    payload = [
        {
            "address": item.address,
            "writable": item.writable,
            "signer": item.signer,
            "role": item.role,
        }
        for item in accounts
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _proof(**overrides: object) -> OrcaWhirlpoolProof:
    accounts = _accounts()
    values: dict[str, object] = {
        "source_commit": ORCA_REVIEWED_SOURCE_COMMIT,
        "source_repository": ORCA_SOURCE_REPOSITORY,
        "license_class": ORCA_LICENSE_CLASS,
        "program_id": ORCA_WHIRLPOOLS_PROGRAM_ID,
        "pool": _account(POOL),
        "token_a": TokenIdentity(MINT_A, TOKEN_PROGRAM, 9),
        "token_b": TokenIdentity(MINT_B, TOKEN_PROGRAM, 6),
        "vault_a": _account(VAULT_A, SHA_B),
        "vault_b": _account(VAULT_B, SHA_C),
        "tick_spacing": 64,
        "fee_rate_ppm": 3000,
        "protocol_fee_rate_bps": 100,
        "sqrt_price_x64": 1 << 64,
        "liquidity": 10**12,
        "tick_arrays": (_account(TICK_0, SHA_B), _account(TICK_1, SHA_C)),
        "tick_array_start_indexes": (-5632, 0),
        "quote_math_version": "orca-core-reviewed-generation",
        "quote_vector_sha256": SHA_D,
        "local_quote_out": 995_000,
        "reference_quote_out": 995_000,
        "amount_in": 1_000_000,
        "minimum_out": 990_000,
        "instruction_data_sha256": SHA_A,
        "instruction_accounts": accounts,
        "expected_instruction_accounts_sha256": _digest_accounts(accounts),
        "provider_identity": "governed-rpc:fixture-evidence-only",
        "provider_budget_receipt_sha256": SHA_B,
        "evidence_generation": "gen-1",
        "license_review_approved": True,
    }
    values.update(overrides)
    return OrcaWhirlpoolProof(**values)


def _cap(
    state: CapabilityState = CapabilityState.SHADOW_QUALIFIED,
    **overrides: object,
) -> VenueCapability:
    values: dict[str, object] = {
        "capability_id": "orca:one-pool:a-to-b",
        "venue": VenueFamily.ORCA_WHIRLPOOLS,
        "cluster": "mainnet-beta",
        "genesis_sha256": GENESIS,
        "pool_or_market": POOL,
        "input_mint": MINT_A,
        "output_mint": MINT_B,
        "deployment_generation": (
            f"{ORCA_WHIRLPOOLS_PROGRAM_ID}@{ORCA_REVIEWED_SOURCE_COMMIT}"
        ),
        "account_layout_version": "gen-1",
        "instruction_family": "whirlpool-swap-exact-in",
        "quote_math_version": "orca-core-reviewed-generation",
        "evidence_sha256": SHA_D,
        "instruction_data_sha256": SHA_A,
        "instruction_accounts_sha256": SHA_B,
        "state": state,
        "expires_at_unix": 2_000_000_000,
    }
    values.update(overrides)
    return VenueCapability(**values)


def _leg(capability: VenueCapability, **overrides: object) -> DirectRouteLeg:
    values: dict[str, object] = {
        "venue": capability.venue,
        "capability_hash": capability.capability_hash,
        "pool_or_market": capability.pool_or_market,
        "input_mint": capability.input_mint,
        "output_mint": capability.output_mint,
        "amount_in": 1_000_000,
        "guaranteed_min_out": 990_000,
        "evidence_generation": capability.deployment_generation,
        "instruction_data_sha256": capability.instruction_data_sha256,
        "instruction_accounts_sha256": capability.instruction_accounts_sha256,
    }
    values.update(overrides)
    return DirectRouteLeg(**values)


def test_orca_current_program_and_source_generation_can_offline_verify() -> None:
    ok, blockers = qualify_orca_offline(_proof())
    assert ok is True
    assert blockers == ()


def test_orca_source_or_program_drift_blocks() -> None:
    ok, blockers = qualify_orca_offline(_proof(source_commit="1" * 40))
    assert ok is False
    assert "ORCA_SOURCE_COMMIT_NOT_REVIEWED_GENERATION" in blockers
    with pytest.raises(DirectVenueError, match="program id"):
        _proof(program_id=MINT_A)


def test_license_review_is_fail_closed() -> None:
    ok, blockers = qualify_orca_offline(_proof(license_review_approved=False))
    assert ok is False
    assert "ORCA_COMMERCIAL_LICENSE_REVIEW_REQUIRED" in blockers


def test_local_quote_differential_mismatch_blocks() -> None:
    ok, blockers = qualify_orca_offline(_proof(local_quote_out=994_999))
    assert not ok
    assert "ORCA_LOCAL_REFERENCE_QUOTE_MISMATCH" in blockers


def test_tick_array_root_generation_and_order_vector_are_bound() -> None:
    stale = replace(_account(TICK_1, SHA_C), root_slot=101)
    ok, blockers = qualify_orca_offline(
        _proof(tick_arrays=(_account(TICK_0, SHA_B), stale))
    )
    assert not ok
    assert "ORCA_ROOT_SLOT_MISMATCH" in blockers

    ok, blockers = qualify_orca_offline(
        _proof(instruction_accounts=tuple(reversed(_accounts())))
    )
    assert not ok
    assert "ORCA_INSTRUCTION_ACCOUNT_VECTOR_MISMATCH" in blockers


def test_unsupported_token_extension_blocks() -> None:
    bad = TokenIdentity(
        MINT_A, TOKEN_PROGRAM, 9, unsupported_extensions_present=True
    )
    ok, blockers = qualify_orca_offline(_proof(token_a=bad))
    assert not ok
    assert "ORCA_UNSUPPORTED_TOKEN_EXTENSION" in blockers


def test_offline_proof_materializes_only_offline_verified_capability() -> None:
    cap = build_orca_capability(
        _proof(),
        input_is_a=True,
        genesis_sha256=GENESIS,
        expires_at_unix=2_000_000_000,
    )
    assert cap.state is CapabilityState.OFFLINE_VERIFIED
    assert cap.venue is VenueFamily.ORCA_WHIRLPOOLS


def test_registry_rejects_wildcard_revoked_expired_or_unqualified_shadow() -> None:
    with pytest.raises(DirectVenueError, match="wildcard"):
        replace(_cap(), capability_id="all")

    revoked = _cap(revoked=True)
    with pytest.raises(DirectVenueError, match="revoked"):
        VenueCapabilityRegistry((revoked,)).require_for_mode(
            revoked.capability_hash, RouteMode.SHADOW, now_unix=1
        )

    expired = _cap(expires_at_unix=10)
    with pytest.raises(DirectVenueError, match="expired"):
        VenueCapabilityRegistry((expired,)).require_for_mode(
            expired.capability_hash, RouteMode.SHADOW, now_unix=10
        )

    offline = _cap(CapabilityState.OFFLINE_VERIFIED)
    with pytest.raises(DirectVenueError, match="insufficient"):
        VenueCapabilityRegistry((offline,)).require_for_mode(
            offline.capability_hash, RouteMode.SHADOW, now_unix=1
        )


def test_route_combinations_are_explicit_not_n_by_n() -> None:
    orca = _cap()
    registry = VenueCapabilityRegistry((orca,))
    leg = _leg(orca)
    result = qualify_route(
        (leg,),
        registry,
        mode=RouteMode.SHADOW,
        now_unix=1,
        allowed_combinations=frozenset({(VenueFamily.ORCA_WHIRLPOOLS,)}),
    )
    assert result.accepted

    blocked = qualify_route(
        (leg,),
        registry,
        mode=RouteMode.SHADOW,
        now_unix=1,
        allowed_combinations=frozenset(
            {(VenueFamily.JUPITER, VenueFamily.JUPITER)}
        ),
    )
    assert not blocked.accepted
    assert "ROUTE_COMBINATION_NOT_QUALIFIED" in blocked.blockers


def test_route_capability_hash_prevents_pool_replay() -> None:
    cap = _cap()
    registry = VenueCapabilityRegistry((cap,))
    result = qualify_route(
        (_leg(cap, pool_or_market=VAULT_A),),
        registry,
        mode=RouteMode.SHADOW,
        now_unix=1,
        allowed_combinations=frozenset({(VenueFamily.ORCA_WHIRLPOOLS,)}),
    )
    assert not result.accepted
    assert "LEG_0_POOL_MISMATCH" in result.blockers


def test_second_leg_input_is_backed_by_first_guaranteed_output() -> None:
    first = _cap()
    second = replace(
        _cap(),
        capability_id="orca:b-to-a",
        input_mint=MINT_B,
        output_mint=MINT_A,
        evidence_sha256=SHA_C,
        instruction_data_sha256=SHA_C,
    )
    registry = VenueCapabilityRegistry((first, second))
    result = qualify_route(
        (
            _leg(first, guaranteed_min_out=900_000),
            _leg(second, amount_in=900_001),
        ),
        registry,
        mode=RouteMode.SHADOW,
        now_unix=1,
        allowed_combinations=frozenset(
            {(VenueFamily.ORCA_WHIRLPOOLS, VenueFamily.ORCA_WHIRLPOOLS)}
        ),
    )
    assert not result.accepted
    assert "LEG_0_OUTPUT_DOES_NOT_BACK_NEXT_INPUT" in result.blockers


def test_capability_evidence_or_generation_mutation_invalidates_route() -> None:
    cap = _cap()
    registry = VenueCapabilityRegistry((cap,))
    result = qualify_route(
        (
            _leg(
                cap,
                instruction_data_sha256=SHA_B,
                evidence_generation="other",
            ),
        ),
        registry,
        mode=RouteMode.SHADOW,
        now_unix=1,
        allowed_combinations=frozenset({(VenueFamily.ORCA_WHIRLPOOLS,)}),
    )
    assert "LEG_0_INSTRUCTION_DATA_MISMATCH" in result.blockers
    assert "LEG_0_GENERATION_MISMATCH" in result.blockers

    account_result = qualify_route(
        (_leg(cap, instruction_accounts_sha256=SHA_C),),
        registry,
        mode=RouteMode.SHADOW,
        now_unix=1,
        allowed_combinations=frozenset({(VenueFamily.ORCA_WHIRLPOOLS,)}),
    )
    assert "LEG_0_INSTRUCTION_ACCOUNTS_MISMATCH" in account_result.blockers


def test_production_mode_never_enables_live_from_this_gate() -> None:
    cap = _cap(CapabilityState.PRODUCTION_QUALIFIED)
    registry = VenueCapabilityRegistry((cap,))
    result = qualify_route(
        (_leg(cap),),
        registry,
        mode=RouteMode.PRODUCTION,
        now_unix=1,
        allowed_combinations=frozenset({(VenueFamily.ORCA_WHIRLPOOLS,)}),
    )
    assert result.accepted
    assert result.live_enabled is False
