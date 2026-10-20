/* pm2 config for the public Node gateway on port 3015.
 *
 *   pm2 start ecosystem.config.cjs
 *
 * The FastAPI API and OMR worker still run in Docker (compose.pm2.yml), so
 * this process only needs Node. Use the one-command helper instead if you
 * want the backend containers started too:
 *
 *   pnpm pm2:start
 */
const path = require("node:path");

const envFile = path.join(__dirname, ".env");
try {
  if (typeof process.loadEnvFile === "function") process.loadEnvFile(envFile);
} catch {
  // .env is optional; defaults below still work.
}

const port = process.env.PORT || "3015";
const apiPort = process.env.API_HOST_PORT || "8000";

module.exports = {
  apps: [
    {
      name: "scoreomr",
      script: "apps/web/server.mjs",
      args: `--port ${port}`,
      cwd: __dirname,
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      max_restarts: 20,
      restart_delay: 2000,
      kill_timeout: 10000,
      merge_logs: true,
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      // Only the web tier's own settings go into pm2's process env. Keeping
      // deployment secrets out of this object avoids writing them
      // into ~/.pm2/dump.pm2 on `pm2 save`; server.mjs loads .env itself.
      env: {
        NODE_ENV: "production",
        PORT: port,
        API_HOST_PORT: apiPort,
        API_ORIGIN: process.env.API_ORIGIN || `http://127.0.0.1:${apiPort}`,
        TLS_CERT_FILE: process.env.TLS_CERT_FILE || "",
        TLS_KEY_FILE: process.env.TLS_KEY_FILE || "",
        EDGE_TRUST_PROXY: process.env.EDGE_TRUST_PROXY || "0",
      },
    },
  ],
};
