import os, pytest

def test_marginfi_readonly_contract_check_opt_in():
    if not os.getenv("MARGINFI_READONLY_RPC_URL"):
        pytest.skip("set MARGINFI_READONLY_RPC_URL to run read-only mainnet contract validation; no signing/sending is performed")
