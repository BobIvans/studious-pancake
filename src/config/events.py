import asyncio

# Shared event triggers to avoid circular imports between arb_bot and ingest modules
lst_webhook_trigger = asyncio.Queue()
