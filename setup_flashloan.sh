#!/bin/bash
# FIX 243: Programmatic setup and secure token generator script
# This script sets up the FlashLoan Arbitrage Bot environment securely

set -e

echo "⚙️ Setting up FlashLoan Arbitrage Bot..."

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# 1. Create .env from template if missing
if [ ! -f .env ]; then
    echo "📝 Creating default .env file..."
    cat > .env << 'ENVEOF'
# Helius Configuration
HELIUS_API_KEY="YOUR_API_KEY"
HELIUS_WEBHOOK_ENABLED=true
WEBHOOK_PORT=3000

# RPC Configuration
RPC_URL_1="https://mainnet.helius-rpc.com/?api-key=YOUR_API_KEY"
MULTI_RPC_ENABLED=true

# MarginFi Configuration
MARGINFI_ACCOUNT=""
MARGINFI_PROGRAM_ID="MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"

# Trading Configuration
PAPER_TRADING_ONLY=true
MIN_PROFIT_SOL=0.0001
MAX_TIP_SOL=0.0005
SLIPPAGE_BPS=15

# Jito Configuration
JITO_SNIPER_ENABLED=false
JITO_TIP_PERCENTILE=75.0
JITO_MIN_TIP_LAMPORTS=10000
STRICT_JITO_MODE=true

# Security Tokens (auto-generated below if missing)
ENVEOF
    echo "✅ .env template created"
fi

# 2. Programmatically generate secure tokens
if ! grep -q "^BRIDGE_TOKEN=" .env 2>/dev/null; then
    BRIDGE_TOKEN=$(openssl rand -hex 16)
    echo "BRIDGE_TOKEN=$BRIDGE_TOKEN" >> .env
    echo "🔑 Secure BRIDGE_TOKEN generated"
fi

if ! grep -q "^HELIUS_WEBHOOK_SECRET=" .env 2>/dev/null; then
    WEBHOOK_SECRET=$(openssl rand -hex 16)
    echo "HELIUS_WEBHOOK_SECRET=$WEBHOOK_SECRET" >> .env
    echo "🔑 Secure HELIUS_WEBHOOK_SECRET generated"
fi

if ! grep -q "^HEALTH_TOKEN=" .env 2>/dev/null; then
    HEALTH_TOKEN=$(openssl rand -hex 16)
    echo "HEALTH_TOKEN=$HEALTH_TOKEN" >> .env
    echo "🔑 Secure HEALTH_TOKEN generated"
fi

if ! grep -q "^JITO_AUTH_KEY=" .env 2>/dev/null; then
    JITO_AUTH_KEY=$(openssl rand -hex 32)
    echo "JITO_AUTH_KEY=$JITO_AUTH_KEY" >> .env
    echo "🔑 Secure JITO_AUTH_KEY generated"
fi

# 3. Create required directories
mkdir -p logs backups data

# 4. Enable PM2 log rotation if PM2 is present (FIX 241)
if command -v pm2 &> /dev/null; then
    echo "🔄 PM2 detected! Installing and configuring pm2-logrotate module..."
    pm2 install pm2-logrotate || true
    pm2 set pm2-logrotate:max_size 50M || true
    pm2 set pm2-logrotate:retain 3 || true
    pm2 set pm2-logrotate:compress true || true
    pm2 set pm2-logrotate:dateFormat YYYY-MM-DD_HH-mm-ss || true
    echo "✅ PM2 log rotation configured (50MB max, 3 rotations)"
else
    echo "ℹ️ PM2 not found. Install PM2 for production: npm install -g pm2"
fi

# 5. Set restrictive permissions on .env
chmod 600 .env 2>/dev/null || true

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env and add your HELIUS_API_KEY and MARGINFI_ACCOUNT"
echo "2. Run: python arb_bot.py (for paper trading)"
echo "3. Or deploy with PM2: pm2 start ecosystem.config.js"
echo ""
echo "⚠️  IMPORTANT: Never commit .env or wallet.json to version control!"
