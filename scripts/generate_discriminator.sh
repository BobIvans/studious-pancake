#!/bin/bash

# Generate discriminator for executeArbitrage instruction
# Anchor uses: sha256(namespace::instruction_name)[..8]
echo "executeArbitrage discriminator:"
echo -n "global:execute_arbitrage" | sha256sum | head -c 16 | xxd -r -p | xxd -i

echo ""
echo "Update the EXECUTE_ARBITRAGE_DISCRIMINATOR in arb_bot.py with the bytes above"