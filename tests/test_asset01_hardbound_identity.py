"""ASSET-01: pre-capture identity safety + HARD_BOUND quote admission gate.

Acceptance (docs/roadmap/data-to-paper-readiness-2026-11-22/TASK_BACKLOG_V1.json):
- the pre-capture resolver parses/preserves identity evidence with typed
  unknowns, never upgrades unresolved candidates and never requires every
  discovery candidate to be HARD_BOUND;
- every HARD_BOUND asset/pool used by an exact quote carries current
  evidence refs, source generation, exact decimals/program/extensions and
  canonical pool/token/vault identity;
- unknown/inconsistent identity, unsupported Token-2022 semantics or
  missing proof return typed blockers (no ticker inference, no quote or
  route admission);
- positive/negative coverage: ticker collision, wrong mint/program/decimals,
  stale/missing owner evidence, token-program mismatch, pool token-order /
  vault mismatch, unsupported extensions.
"""

import pytest

from src.assets.resolution.hard_bound import (
    HardBoundIdentityBlocker,
    HardBoundPoolSpec,
    PoolTokenSpec,
    assert_no_ticker_collision,
    pre_capture_identity_view,
    require_hard_bound_pool,
)
from src.assets.resolution.evidence import Evidence
from src.assets.resolution.resolver import CandidateAsset
from src.research_economic_graph.registry import (
    SPL_TOKEN_PROGRAM,
    TOKEN_2022_PROGRAM,
)

pytestmark = pytest.mark.unit

GEN = "g" * 8
NOW = 1000.0


def evidence(generation=GEN, observed_at=NOW, negative=None):
    return Evidence(
        "rpc",
        "helius",
        "campaign-discovery",
        generation,
        observed_at,
        "a" * 64,
        "b" * 64,
        slot_or_checkpoint=1,
        negative_reason=negative,
    )


def candidate(
    identifier="So11111111111111111111111111111111111111112",
    symbol="WSOL",
    decimals=9,
    program=SPL_TOKEN_PROGRAM,
    authoritative=True,
    extensions=(),
    **kwargs,
):
    base = dict(
        chain="solana",
        identifier=identifier,
        symbol=symbol,
        decimals=decimals,
        program_or_package=program,
        evidence=evidence(),
        authoritative=authoritative,
        extensions=extensions,
    )
    base.update(kwargs)
    return CandidateAsset(**base)


def token_spec(
    identifier="So11111111111111111111111111111111111111112",
    decimals=9,
    program=SPL_TOKEN_PROGRAM,
    extensions=(),
    vault="V" * 44,
    vault_token_account="",
):
    return PoolTokenSpec(
        identifier=identifier,
        decimals=decimals,
        token_program=program,
        extensions=extensions,
        vault=vault,
        vault_token_account=vault_token_account,
    )


def pool_spec(
    base=None,
    quote=None,
    base_vault="V" * 44,
    quote_vault="W" * 44,
    refs=("evidence-1",),
    sha256="c" * 64,
    slot=123,
    generation=GEN,
):
    return HardBoundPoolSpec(
        chain="solana",
        pool_id="P" * 44,
        base=base or token_spec(),
        quote=quote
        or token_spec(
            identifier="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            decimals=6,
            vault="W" * 44,
        ),
        base_vault=base_vault,
        quote_vault=quote_vault,
        source_generation=generation,
        evidence_refs=refs,
        evidence_sha256=sha256,
        evidence_slot=slot,
    )


# --- pre-capture: safe view, typed unknowns, no upgrades --------------------


def test_precapture_preserves_identity_evidence_with_typed_unknowns():
    view = pre_capture_identity_view(candidate())
    assert view.decimals == 9
    assert view.token_program == SPL_TOKEN_PROGRAM
    assert view.unknowns == ()
    assert view.hard_bound is True


def test_precapture_never_upgrades_unresolved_candidate():
    unresolved = candidate(authoritative=False)
    view = pre_capture_identity_view(unresolved)
    assert view.decimals is None
    assert "decimals" in view.unknowns
    assert view.hard_bound is False
    assert "ASSET01_DECIMALS_UNKNOWN" in view.identity_blockers()


def test_discovery_candidates_are_not_required_to_be_hard_bound():
    # Pre-capture view of an unresolved candidate must not raise.
    view = pre_capture_identity_view(
        candidate(identifier="4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R")
    )
    # The pre-capture view never raises and never requires HARD_BOUND.
    assert view.identifier == "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"


def test_precapture_does_not_infer_identity_from_ticker():
    # A ticker alone is never treated as identity evidence.
    view = pre_capture_identity_view(candidate(symbol="USDC"))
    assert view.identifier != "USDC"
    assert view.symbol == "USDC"


def test_missing_decimals_is_never_marked_verified():
    view = pre_capture_identity_view(candidate(authoritative=False))
    assert view.decimals is None
    blockers = view.identity_blockers()
    assert "ASSET01_DECIMALS_UNKNOWN" in blockers


def test_legacy_spl_mint_with_extensions_recorded_as_inconsistency():
    view = pre_capture_identity_view(
        candidate(program=SPL_TOKEN_PROGRAM, extensions=("transfer-hook",))
    )
    assert "legacy-spl-mint-with-extensions" in view.notes
    assert view.hard_bound is False


# --- ticker collision --------------------------------------------------------


def test_ticker_collision_is_a_typed_blocker():
    a = pre_capture_identity_view(
        candidate(
            symbol="USDX", identifier="So11111111111111111111111111111111111111112"
        )
    )
    b = pre_capture_identity_view(
        candidate(
            symbol="USDX", identifier="4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
        )
    )
    with pytest.raises(HardBoundIdentityBlocker, match="ASSET01_TICKER_COLLISION"):
        assert_no_ticker_collision((a, b))


def test_same_symbol_same_mint_is_not_a_collision():
    a = pre_capture_identity_view(candidate(symbol="WSOL"))
    assert_no_ticker_collision((a, pre_capture_identity_view(candidate())))


# --- HARD_BOUND pool admission -----------------------------------------------


def test_hard_bound_pool_admits_positive_identity():
    admission = require_hard_bound_pool(
        pool_spec(
            base=token_spec(vault="V" * 44, vault_token_account="V" * 44),
            quote=token_spec(
                identifier="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                decimals=6,
                vault="W" * 44,
                vault_token_account="W" * 44,
            ),
        )
    )
    assert admission.ok is True
    assert admission.blockers == ()


def test_wrong_mint_and_decimals_are_typed_blockers():
    admission = require_hard_bound_pool(
        pool_spec(base=token_spec(identifier="", decimals=255))
    )
    assert "ASSET01_BASE_IDENTITY_UNKNOWN" in admission.blockers
    assert "ASSET01_BASE_DECIMALS_UNKNOWN" in admission.blockers
    assert admission.ok is False


def test_token_program_mismatch_blocks_admission():
    admission = require_hard_bound_pool(
        pool_spec(base=token_spec(program="TokenXYZinvalidprogramidxxxxxxxxxx"))
    )
    assert "ASSET01_BASE_TOKEN_PROGRAM_MISMATCH" in admission.blockers


def test_stale_or_missing_owner_evidence_blocks_admission():
    missing = pool_spec(refs=(), sha256=None, slot=None, generation="")
    admission = require_hard_bound_pool(missing)
    assert "ASSET01_POOL_EVIDENCE_MISSING" in admission.blockers
    assert "ASSET01_POOL_EVIDENCE_HASH_INVALID" in admission.blockers
    assert "ASSET01_POOL_EVIDENCE_SLOT_MISSING" in admission.blockers
    assert "ASSET01_SOURCE_GENERATION_MISSING" in admission.blockers


def test_pool_token_order_mismatch_blocks_admission():
    base = token_spec(vault="V" * 44)
    # Pool wires the base side to the quote vault: order mismatch.
    admission = require_hard_bound_pool(pool_spec(base=base, base_vault="W" * 44))
    assert "ASSET01_POOL_TOKEN_ORDER_MISMATCH" in admission.blockers


def test_vault_identity_mismatch_blocks_admission():
    base = token_spec(vault="V" * 44, vault_token_account="X" * 44)
    admission = require_hard_bound_pool(pool_spec(base=base))
    assert any(
        b.startswith("ASSET01_VAULT_IDENTITY_MISMATCH") for b in admission.blockers
    )


def test_unsupported_extensions_and_transfer_semantics_block():
    hook = token_spec(program=TOKEN_2022_PROGRAM, extensions=("transfer-hook",))
    admission = require_hard_bound_pool(pool_spec(base=hook))
    assert any(
        b.startswith("ASSET01_BASE_TOKEN_2022_TRANSFER_SEMANTICS_UNSUPPORTED")
        for b in admission.blockers
    )
    unknown = token_spec(program=TOKEN_2022_PROGRAM, extensions=("mystery-extension",))
    admission = require_hard_bound_pool(pool_spec(base=unknown))
    assert (
        "ASSET01_BASE_TOKEN_2022_EXTENSION_UNSUPPORTED:mystery-extension"
        in admission.blockers
    )
    supported = token_spec(program=TOKEN_2022_PROGRAM, extensions=("token-metadata",))
    admission = require_hard_bound_pool(pool_spec(base=supported))
    assert not any("EXTENSION" in b for b in admission.blockers)


def test_token_2022_without_extension_evidence_is_unknown():
    admission = require_hard_bound_pool(
        pool_spec(base=token_spec(program=TOKEN_2022_PROGRAM, extensions=()))
    )
    assert "ASSET01_BASE_TOKEN_2022_EXTENSIONS_UNKNOWN" in admission.blockers


def test_shared_vault_and_collapsed_sides_block():
    same = "V" * 44
    admission = require_hard_bound_pool(pool_spec(base_vault=same, quote_vault=same))
    assert any(
        b == "ASSET01_VAULT_IDENTITY_MISMATCH:shared" for b in admission.blockers
    )


# --- research universe is not narrowed ----------------------------------------


def test_registry_load_is_unchanged_by_the_gate():
    # The gate is admission-only; the broad research universe still loads.
    from src.research_economic_graph.registry import AssetRegistry

    registry = AssetRegistry.load()
    assert isinstance(registry.configuration, dict)
    assert registry.assets, "broad research universe still loads"
