from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .redaction import fingerprint, sanitize

class ReasonCode(str, Enum):
    SIGNAL_NO_EDGE="SIGNAL_NO_EDGE"; DEDUP_DUPLICATE="DEDUP_DUPLICATE"; QUOTA_EXHAUSTED="QUOTA_EXHAUSTED"; PROVIDER_UNHEALTHY="PROVIDER_UNHEALTHY"; STALE_QUOTE="STALE_QUOTE"; CONTRACT_FIXTURE_MISMATCH="CONTRACT_FIXTURE_MISMATCH"
    LIQUIDITY_INSUFFICIENT="LIQUIDITY_INSUFFICIENT"; ROUTE_NOT_FOUND="ROUTE_NOT_FOUND"; VENUE_DISABLED="VENUE_DISABLED"; MINT_TOKEN2022_UNSUPPORTED="MINT_TOKEN2022_UNSUPPORTED"
    CAPITAL_INSUFFICIENT="CAPITAL_INSUFFICIENT"; FEE_TOO_HIGH="FEE_TOO_HIGH"; RISK_LIMIT="RISK_LIMIT"; PLAN_INVALID="PLAN_INVALID"; COMPILE_FAILED="COMPILE_FAILED"; ALT_MISSING="ALT_MISSING"; TX_SIZE_LIMIT="TX_SIZE_LIMIT"; CU_LIMIT="CU_LIMIT"
    SIMULATION_INSTRUCTION_ERROR="SIMULATION_INSTRUCTION_ERROR"; SIMULATION_CU_EXCEEDED="SIMULATION_CU_EXCEEDED"; SIMULATION_ACCOUNT_ERROR="SIMULATION_ACCOUNT_ERROR"; SIMULATION_SLIPPAGE_MIN_OUT="SIMULATION_SLIPPAGE_MIN_OUT"; SIMULATION_FLASH_LOAN_REPAYMENT="SIMULATION_FLASH_LOAN_REPAYMENT"
    SUBMISSION_REJECTED="SUBMISSION_REJECTED"; JITO_BUNDLE_REJECTED="JITO_BUNDLE_REJECTED"; RPC_ERROR="RPC_ERROR"; BLOCKHASH_EXPIRED="BLOCKHASH_EXPIRED"; AMBIGUOUS_SUBMISSION="AMBIGUOUS_SUBMISSION"; RECONCILIATION_MISSING="RECONCILIATION_MISSING"
    CONFIG_INVALID="CONFIG_INVALID"; DISABLED_SHADOW_ONLY="DISABLED_SHADOW_ONLY"; INTERNAL_UNCLASSIFIED="INTERNAL_UNCLASSIFIED"; OBSERVABILITY_DURABLE_WRITE_FAILED="OBSERVABILITY_DURABLE_WRITE_FAILED"; LEGACY_IMPORTED_INCOMPLETE="LEGACY_IMPORTED_INCOMPLETE"

@dataclass(frozen=True)
class ReasonSpec:
    code: ReasonCode; terminal: bool; retryability: str; owner_stage: str; public_message: str; required_evidence: tuple[str,...]; funnel_bucket: str

def _spec(c, terminal, stage, bucket, evidence=()): return ReasonSpec(c, terminal, "descriptive_only", stage, c.value.lower().replace("_"," "), tuple(evidence), bucket)
REASON_REGISTRY = {c: _spec(c, c.name not in {"AMBIGUOUS_SUBMISSION"}, c.name.split("_")[0].lower(), c.name.split("_")[0].lower()) for c in ReasonCode}
REASON_REGISTRY[ReasonCode.AMBIGUOUS_SUBMISSION] = _spec(ReasonCode.AMBIGUOUS_SUBMISSION, False, "submission", "ambiguous", ("submission_evidence",))
REASON_REGISTRY[ReasonCode.RECONCILIATION_MISSING] = _spec(ReasonCode.RECONCILIATION_MISSING, False, "reconciliation", "ambiguous", ("attempt_id",))

_KEYWORDS = [("quota", ReasonCode.QUOTA_EXHAUSTED),("429",ReasonCode.QUOTA_EXHAUSTED),("blockhash",ReasonCode.BLOCKHASH_EXPIRED),("slippage",ReasonCode.SIMULATION_SLIPPAGE_MIN_OUT),("repay",ReasonCode.SIMULATION_FLASH_LOAN_REPAYMENT),("cu",ReasonCode.CU_LIMIT),("compute",ReasonCode.CU_LIMIT),("liquidity",ReasonCode.LIQUIDITY_INSUFFICIENT),("route",ReasonCode.ROUTE_NOT_FOUND),("rpc",ReasonCode.RPC_ERROR),("jito",ReasonCode.JITO_BUNDLE_REJECTED)]

def classify_exception(exc: BaseException) -> tuple[ReasonCode, dict]:
    text = f"{type(exc).__name__}: {exc}".lower()
    for needle, code in _KEYWORDS:
        if needle in text: return code, {"error": sanitize(exc)}
    return ReasonCode.INTERNAL_UNCLASSIFIED, {"error_fingerprint": fingerprint(text), "error": sanitize(exc)}
