"""Adversarial provider instructions reach the actual atomic planner."""

import base64
from dataclasses import replace

import pytest

from src.planning.atomic_marginfi_jupiter import (
    AtomicMarginfiJupiterPlanner,
    AtomicPlannerError,
)
from src.planning.instruction_firewall import (
    ASSOCIATED_TOKEN_PROGRAM_ID,
    SPL_TOKEN_PROGRAM_ID,
    InstructionFirewallPolicy,
    InstructionFirewallError,
    InstructionRole,
    validate_raw_provider_instruction,
)
from src.providers.jupiter.router import JupiterRawInstruction, RawAccountMeta
from tests.test_pr034_atomic_marginfi_jupiter import (
    NOW,
    PAYER,
    SWAP_PROGRAM,
    _VerifiedMarginfiProvider,
    _pk,
    _policy,
    _request,
)


def _instruction(program, data, accounts):
    return JupiterRawInstruction(
        str(program), tuple(accounts), base64.b64encode(data).decode(), "external"
    )


@pytest.mark.parametrize(
    "case",
    [
        "unknown-program",
        "unknown-signer",
        "writable-payer",
        "authority",
        "transfer-output",
        "unknown-token-tag",
        "unknown-ata-tag",
    ],
)
def test_atomic_planner_rejects_provider_instruction_attacks(case):
    request = _request()
    payer = RawAccountMeta(str(PAYER), True, False)
    attacker = RawAccountMeta(str(_pk(55)), False, True)
    program = SWAP_PROGRAM
    data = b"opaque-reviewed-route"
    accounts = (payer,)
    policy = _policy()
    if case == "unknown-program":
        program = _pk(54)
    elif case == "unknown-signer":
        accounts = (RawAccountMeta(str(_pk(55)), True, False),)
    elif case == "writable-payer":
        accounts = (RawAccountMeta(str(PAYER), True, True),)
    else:
        program = SPL_TOKEN_PROGRAM_ID
        data = {
            "authority": b"\x06",
            "transfer-output": b"\x03" + (500).to_bytes(8, "little"),
            "unknown-token-tag": b"\xff",
            "unknown-ata-tag": b"\xff",
        }[case]
        accounts = (payer, attacker)
        if case == "unknown-ata-tag":
            program = ASSOCIATED_TOKEN_PROGRAM_ID
        # Demonstrates that allowing a program does not authorize unsafe bytes.
        policy = replace(
            policy, allowed_program_ids=(*policy.allowed_program_ids, program)
        )
    bad = _instruction(program, data, accounts)
    request = replace(request, leg_a=replace(request.leg_a, other_instructions=(bad,)))
    planner = AtomicMarginfiJupiterPlanner(
        _VerifiedMarginfiProvider(), policy, clock=lambda: NOW
    )
    with pytest.raises(AtomicPlannerError):
        planner.plan(request)


def test_unknown_program_requires_explicit_reviewed_policy():
    raw = _instruction(
        SWAP_PROGRAM, b"opaque", (RawAccountMeta(str(PAYER), True, False),)
    )
    with pytest.raises(InstructionFirewallError, match="explicit reviewed"):
        validate_raw_provider_instruction(
            raw, InstructionFirewallPolicy(payer=str(PAYER)), role=InstructionRole.SWAP
        )
    finding = validate_raw_provider_instruction(
        raw,
        InstructionFirewallPolicy(
            payer=str(PAYER), reviewed_program_ids=(str(SWAP_PROGRAM),)
        ),
        role=InstructionRole.SWAP,
    )
    assert finding.semantic_class == "explicitly-reviewed-provider-program"
