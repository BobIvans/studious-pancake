#!/bin/bash

echo "🔧 Helius Webhook Setup Helper"
echo "=============================="
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "❌ .env file not found. Please create it first."
    exit 1
fi

# Load environment variables
export $(grep -v '^#' .env | xargs)

if [ -z "$HELIUS_API_KEY" ]; then
    echo "❌ HELIUS_API_KEY not set in .env"
    exit 1
fi

WEBHOOK_URL="http://localhost:${WEBHOOK_PORT:-3000}/webhook"

echo "📡 Webhook URL: $WEBHOOK_URL"
echo ""

echo "📋 Monitored Addresses:"
echo "- Pump.fun Migration: 39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"
echo "- PumpSwap Program: PSwapMdSai8tjrEXcxFeQth87xC4rRsa4timeHavmc"
echo "- BelieveApp Meteora DBC: dbcij3LWUppTiACKHVKtjUi2Vn3JBmXu4quMErSMFpN"
echo "- Meteora DLMM: LBUZKhRxPF3XUpBCjp4YzTKgLLjggiJWUna9LZJRQD3"
echo "- Raydium AMM v4: 675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
echo "- LetsBonk LaunchLab: LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"
echo ""

echo "🚀 To setup webhook in Helius:"
echo "1. Go to https://dashboard.helius.dev/"
echo "2. Create new webhook"
echo "3. Set URL: $WEBHOOK_URL"
echo "4. Add the addresses above to Account Addresses"
echo "5. Select Transaction events"
echo "6. Enable webhook"
echo ""

echo "🔍 To test webhook:"
echo "curl -X GET http://localhost:${WEBHOOK_PORT:-3000}/health"
echo ""

echo "📊 To monitor:"
echo "curl -X GET http://localhost:${WEBHOOK_PORT:-3000}/arbitrage/stats"
echo "curl -X GET http://localhost:${WEBHOOK_PORT:-3000}/events"
echo ""

echo "✅ Setup complete! Start the webhook server with:"
echo "python webhook_server.py"