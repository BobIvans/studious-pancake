// PM2 Ecosystem Config — Ultra Arb Bot
// Auto-restart every 12 hours to prevent memory leaks from WSS/aiohttp
//
// Log Rotation: Install pm2-logrotate to prevent log files from growing unbounded.
// Run: pm2 install pm2-logrotate && pm2 set pm2-logrotate:max_size 50M && pm2 set pm2-logrotate:retain 3
//
// Alternatively, use logrotate with this config in /etc/logrotate.d/ultra-arb:
//   /path/to/project/logs/*.log {
//     hourly
//     rotate 3
//     compress
//     missingok
//     notifempty
//     copytruncate
//   }
module.exports = {
  apps: [{
    name: "ultra-arb",
    script: "arb_bot.py",
    interpreter: "python3",
    cron_restart: "0 4 * * 1", // Понедельник утро — минимальная волатильность
    autorestart: true,
    max_restarts: 10,
    min_uptime: "120s", // Боту нужно время на warm-up ATA и ALTs
    restart_delay: 5000,
    exp_backoff_restart_delay: 200, // Экспоненциальный бек-офф при падениях
    kill_timeout: 30000, // 30s — время для graceful shutdown & flush DB
    watch: false,
    env: {
      PYTHONUNBUFFERED: "1",
    },
    error_file: "logs/pm2-error.log",
    out_file: "logs/pm2-out.log",
    merge_logs: true,
    max_memory_restart: "2048M", // Даем боту дышать при пиковой нагрузке вебхуков
  }]
};
