#!/usr/bin/env node
/**
 * Local development orchestrator. Starts the FastAPI API, the OMR worker and
 * Vite with one command. Everything writes into .dev-data, so the checkout
 * stays disposable.  OMR_MOCK=true by default; pass OMR_MOCK=false to use
 * Audiveris / homr installed on the host.
 */
import { spawn } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const backend = path.join(root, "services/backend");
const python = path.join(backend, ".venv/bin/python");

if (!existsSync(python)) {
  console.error("Python environment missing. Run `pnpm setup` first.");
  process.exit(1);
}

// Load optional local settings from .env when present.
const envFile = path.join(root, ".env");
if (existsSync(envFile) && typeof process.loadEnvFile === "function") {
  try {
    process.loadEnvFile(envFile);
  } catch {
    // A malformed .env should not prevent the dev stack from booting.
  }
}

const apiPort = process.env.API_PORT || "8000";
const webPort = process.env.WEB_PORT || "5173";
const dataDir = path.join(root, ".dev-data");
mkdirSync(dataDir, { recursive: true });
const mplDir = path.join(dataDir, "mpl");
mkdirSync(mplDir, { recursive: true });

const env = {
  ...process.env,
  APP_ENV: "development",
  APP_URL: `http://127.0.0.1:${webPort}`,
  API_PROXY_TARGET: `http://127.0.0.1:${apiPort}`,
  DATA_DIR: dataDir,
  DATABASE_PATH: path.join(dataDir, "scoreomr.db"),
  SAMPLES_DIR: path.join(backend, "samples"),
  OMR_MOCK: process.env.OMR_MOCK || "true",
  MPLCONFIGDIR: mplDir,
  PYTHONUNBUFFERED: "1",
  UV_CACHE_DIR: path.join(root, ".uv-cache"),
  UV_PYTHON_INSTALL_DIR: path.join(root, ".uv-python"),
  UV_TOOL_DIR: path.join(root, ".uv-tools"),
  UV_TOOL_BIN_DIR: path.join(root, ".uv-bin"),
};

const colors = process.stdout.isTTY
  ? { api: "\x1b[36m", worker: "\x1b[35m", web: "\x1b[33m", reset: "\x1b[0m" }
  : { api: "", worker: "", web: "", reset: "" };

const children = [];
let stopping = false;

function run(name, command, args, cwd) {
  const child = spawn(command, args, { cwd, env, stdio: ["ignore", "pipe", "pipe"] });
  children.push({ name, child });
  const prefix = `${colors[name] || ""}[${name}]${colors.reset}`;
  const pipe = (stream, out) => {
    let buffer = "";
    stream.on("data", (chunk) => {
      buffer += chunk.toString();
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) if (line.trim()) out.write(`${prefix} ${line}\n`);
    });
  };
  pipe(child.stdout, process.stdout);
  pipe(child.stderr, process.stderr);
  child.on("exit", (code, signal) => {
    if (stopping) return;
    if (code !== 0 && signal !== "SIGTERM") {
      console.error(`${prefix} exited with code ${code}; shutting down`);
      shutdown(code || 1);
    }
  });
  return child;
}

function shutdown(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const { child } of children) {
    if (!child.killed) child.kill("SIGTERM");
  }
  setTimeout(() => {
    for (const { child } of children) {
      if (!child.killed) child.kill("SIGKILL");
    }
    process.exit(code);
  }, 2500);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

console.log(`
ScoreOMR development stack
  web   http://127.0.0.1:${webPort}
  api   http://127.0.0.1:${apiPort}/api/health
  data  ${dataDir}
  mode  ${env.OMR_MOCK === "true" ? "mock OMR (demo output)" : "real OMR engines"}
`);

run("api", python, ["-m", "uvicorn", "app.main:create_app", "--factory", "--reload", "--host", "127.0.0.1", "--port", apiPort], backend);
run("worker", python, ["-m", "app.worker"], backend);
run("web", "pnpm", ["--filter", "@scoreomr/web", "exec", "vite", "--host", "127.0.0.1", "--port", webPort], root);
