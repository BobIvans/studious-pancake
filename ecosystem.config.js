// PM2 Ecosystem Config — Ultra Arb Bot
// Auto-restart every 12 hours to prevent memory leaks from WSS/aiohttp
module.exports = {
  apps: [{
    name: "ultra-arb",
    script: "arb_bot.py",
    interpreter: "python3",
    cron_restart: "0 */12 * * *",
    autorestart: true,
    max_restarts: 10,
    min_uptime: "30s",
    restart_delay: 5000,
    watch: false,
    env: {
      PYTHONUNBUFFERED: "1",
    },
    error_file: "logs/pm2-error.log",
    out_file: "logs/pm2-out.log",
    merge_logs: true,
    max_memory_restart: "500M",
  }]
};
