"""Focused validation regressions; these do not prove runtime integration."""

from types import MappingProxyType

import pytest

from src.runtime_authority import (
    RuntimeAuthorityError,
    SemanticCommandIdentity,
    SemanticIdempotencyLedger,
    evaluate_runtime_authority_map,
    load_default_authority_map,
)


def identity(**overrides):
    values = dict(
        attempt_id="attempt-1",
        attempt_generation=1,
        candidate_id="candidate-1",
        reservation_id="reservation-1",
        policy_bundle_hash="a" * 64,
        payload_hash="b" * 64,
    )
    values.update(overrides)
    return SemanticCommandIdentity(**values)


def test_none_still_loads_the_reviewed_default():
    assert evaluate_runtime_authority_map(None).accepted


@pytest.mark.parametrize("payload", [{}, MappingProxyType({})])
def test_explicit_empty_map_is_not_a_default(payload):
    result = evaluate_runtime_authority_map(payload)
    assert not result.accepted
    assert "RUNTIME_AUTHORITY_SCHEMA_INVALID" in result.blockers


def test_falsey_mapping_is_still_validated_as_supplied():
    class FalseyDict(dict):
        def __bool__(self):
            return False

    payload = FalseyDict(load_default_authority_map())
    payload["schema_version"] = "wrong-version"
    assert not evaluate_runtime_authority_map(payload).accepted


@pytest.mark.parametrize("payload", [[], False, True, 0, "", [("x", 1)]])
def test_non_mapping_payload_raises_contract_error(payload):
    with pytest.raises(RuntimeAuthorityError):
        evaluate_runtime_authority_map(payload)


@pytest.mark.parametrize(
    "field",
    [
        "attempt_id",
        "candidate_id",
        "reservation_id",
        "policy_bundle_hash",
        "payload_hash",
    ],
)
@pytest.mark.parametrize(
    "bad_value", [17, True, None, 0.5, b"value", [], {}, "", "   "]
)
def test_string_identity_fields_require_nonblank_strings(field, bad_value):
    with pytest.raises(RuntimeAuthorityError):
        identity(**{field: bad_value})


@pytest.mark.parametrize("bad_generation", [0, -1, True, False, 1.5, "1", None])
def test_generation_remains_a_positive_integer_not_bool(bad_generation):
    with pytest.raises(RuntimeAuthorityError):
        identity(attempt_generation=bad_generation)


@pytest.mark.parametrize("bad_key", [17, True, 0.5, [], {}, None, "", "   ", ("key",)])
def test_idempotency_key_requires_a_nonblank_string(bad_key):
    with pytest.raises(RuntimeAuthorityError):
        SemanticIdempotencyLedger().record(bad_key, identity())


def test_valid_identity_digest_is_stable_and_not_mutated():
    left = identity()
    right = identity()
    assert left.digest() == right.digest()
    assert len(left.digest()) == 64
    assert left.attempt_generation == 1


def test_valid_same_process_replay_is_idempotent():
    ledger = SemanticIdempotencyLedger()
    assert ledger.record("request-1", identity()) is False
    assert ledger.record("request-1", identity()) is True


def test_valid_key_with_changed_semantics_remains_rejected():
    ledger = SemanticIdempotencyLedger()
    ledger.record("request-1", identity())
    with pytest.raises(RuntimeAuthorityError, match="IDEMPOTENCY_SEMANTIC_CONFLICT"):
        ledger.record("request-1", identity(candidate_id="different"))


def test_live_override_stays_denied():
    payload = load_default_authority_map()
    payload["active_composition_root"]["live_enabled"] = True
    assert not evaluate_runtime_authority_map(payload).accepted
