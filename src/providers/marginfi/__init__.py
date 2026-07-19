"""PR-023 QUARANTINE: fixture-only MarginFi provider pending binary conformance."""

__runtime_capability__ = "fixture-only"
__quarantined__ = True
from .provider import MarginfiFlashLoanProvider
from .pin import MarginfiContractPin, load_marginfi_contract_pin
from .errors import MarginfiRejection, MarginfiRejectionCode

__all__ = ["MarginfiFlashLoanProvider", "MarginfiContractPin", "load_marginfi_contract_pin", "MarginfiRejection", "MarginfiRejectionCode"]
