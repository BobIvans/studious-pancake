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
    max_memory_restart: "1024M", // ФИКС: Даем боту дышать в моменты пиковой нагрузки
    kill_timeout: 30000, // 30s graceful shutdown before SIGKILL
  }]
};
