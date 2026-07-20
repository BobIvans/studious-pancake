from __future__ import annotations
import hashlib
from dataclasses import dataclass
from .models import Instruction, TipPolicy, ExecutionErrorCode

SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"


@dataclass(frozen=True, slots=True)
class TipValidationResult:
    account: str
    lamports: int
    instruction_count: int
    amount_hash: str


def validate_exactly_one_tip(
    instructions: tuple[Instruction, ...],
    policy: TipPolicy,
    approved_accounts: set[str],
) -> TipValidationResult:
    if (
        policy.lamports <= 0
        or not policy.tip_account
        or policy.tip_account not in approved_accounts
    ):
        raise ValueError(ExecutionErrorCode.TIP_POLICY_REJECTED.value)
    tips = [ix for ix in instructions if ix.kind == "tip"]
    if len(tips) != 1:
        raise ValueError(ExecutionErrorCode.TIP_POLICY_REJECTED.value)
    tip = tips[0]
    if (
        policy.tip_account not in tip.accounts
        or str(policy.lamports).encode() not in tip.data
    ):
        raise ValueError(ExecutionErrorCode.TIP_POLICY_REJECTED.value)
    return TipValidationResult(
        str(policy.tip_account),
        policy.lamports,
        1,
        hashlib.sha256(str(policy.lamports).encode()).hexdigest(),
    )
