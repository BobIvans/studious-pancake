#!/bin/bash
# ============================================================
# Layer 4 — DNS TTL Hardcoding: write Jito/Helius IPs to /etc/hosts
# Eliminates DNS TTL expiry latency (20-50ms every 5 minutes)
#
# Run once (requires sudo):
#   sudo bash setup_dns_hardcode.sh
# Refresh macOS resolver cache after:
#   sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder
# ============================================================

set -euo pipefail

ENTRIES=$(cat << 'IPTABLE'
# ── Jito Block Engine — resolved 2026-05-21 ────────────────────────────────
64.130.59.205   ny.mainnet.block-engine.jito.wtf
64.130.57.104   frankfurt.mainnet.block-engine.jito.wtf
64.130.55.169   amsterdam.mainnet.block-engine.jito.wtf
64.130.57.92    tokyo.mainnet.block-engine.jito.wtf
# ── Helius + Solana RPC ────────────────────────────────────────────────────
172.64.151.87   mainnet.helius-rpc.com
64.130.57.92    api.mainnet-beta.solana.com
# ── Jupiter / CloudFront CDN ───────────────────────────────────────────────
65.9.46.26      d2ep0jztibvcq.cloudfront.net
IPTABLE
)

echo ">>> Appending hardcoded DNS entries to /etc/hosts ..."
printf "%s\n" "$ENTRIES" | sudo tee -a /etc/hosts > /dev/null

echo ">>> Verifying entries in /etc/hosts:"
grep -E "block-engine|helius|solana|cloudfront" /etc/hosts || echo "(not found — check above)"

echo ""
echo ">>> Flushing macOS resolver cache..."
sudo dscacheutil -flushcache 2>/dev/null || true
sudo killall -HUP mDNSResponder 2>/dev/null || true
echo ""
echo ">>> Done. DNS resolution is now hardcoded (zero latency, forever)."
