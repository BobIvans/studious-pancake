from src.venues.pump.events import PumpEvent, PUMP_EVENT_TYPES


def test_pump_event_record_is_sanitized_and_typed():
    event = PumpEvent(
        event_type="pump_quote_created",
        mint="Mint111",
        slot=123,
        manifest_checksum="abc",
        account_hash="def",
        lifecycle="bonding_active",
        reason_code=None,
        amounts={"exact_in_amount": 100, "net_out_amount": 90},
    )
    record = event.as_record()
    assert record["event_type"] in PUMP_EVENT_TYPES
    assert "wire" not in record and "rpc" not in record
    assert record["amounts"]["net_out_amount"] == 90
