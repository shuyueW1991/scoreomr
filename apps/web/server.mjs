#!/usr/bin/env node
/**
 * Minimal production web tier for pm2 / plain Node.
 *
 * - serves the built Vite SPA from apps/web/dist
 * - reverse-proxies /api/* to the FastAPI container on 127.0.0.1:8000
 * - optional TLS on the same port (mount certificates with env vars)
 *
 * No Express, no extra runtime dependencies: only Node's stdlib.
 *
 *   npm start -- --port 3015
 *   pm2 start npm --name "scoreomr" -- start -- --port 3015
 *
 * Env:
 *   API_ORIGIN=http://127.0.0.1:8000
 *   TLS_CERT_FILE=/etc/scoreomr/fullchain.pem
 *   TLS_KEY_FILE=/etc/scoreomr/privkey.pem
 *   EDGE_TRUST_PROXY=0|1   (1 only when Node is behind Cloudflare/Caddy)
 */
import fs from "node:fs";
import http from "node:http";
import https from "node:https";
import path from "node:path";
import { fileURLToPath } from "node:url";
import zlib from "node:zlib";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const dist = path.join(here, "dist");

// Load repo .env for local/pm2 runs. Containers get env from compose.
const envFile = path.join(root, ".env");
if (fs.existsSync(envFile) && typeof process.loadEnvFile === "function") {
  try {
    process.loadEnvFile(envFile);
  } catch (error) {
    console.warn(`[web] could not load ${envFile}: ${error.message}`);
  }
}

function getArg(name, fallback) {
  const args = process.argv.slice(2);
  const eq = args.find((value) => value.startsWith(`${name}=`));
  if (eq) return eq.slice(name.length + 1);
  const index = args.indexOf(name);
  if (index >= 0 && args[index + 1]) return args[index + 1];
  return fallback;
}

const port = Number(getArg("--port", process.env.PORT || "3015"));
const host = getArg("--host", process.env.HOST || "0.0.0.0");
const apiPort = process.env.API_HOST_PORT || "8000";
const apiOrigin = new URL(process.env.API_ORIGIN || `http://127.0.0.1:${apiPort}`);
const trustProxy = ["1", "true", "yes", "on"].includes(String(process.env.EDGE_TRUST_PROXY || "").toLowerCase());
const certFile = process.env.TLS_CERT_FILE || "";
const keyFile = process.env.TLS_KEY_FILE || "";

if (!Number.isInteger(port) || port < 1 || port > 65535) {
  console.error(`[web] invalid port: ${port}`);
  process.exit(1);
}
if (Boolean(certFile) !== Boolean(keyFile)) {
  console.error("[web] TLS_CERT_FILE and TLS_KEY_FILE must be set together");
  process.exit(1);
}
if (!fs.existsSync(path.join(dist, "index.html"))) {
  console.error(`[web] missing ${dist}/index.html — run "pnpm build" first`);
  process.exit(1);
}

const MIME = new Map(Object.entries({
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
  ".xml": "application/xml; charset=utf-8",
}));

const gzipCache = new Map();

function securityHeaders(proto) {
  const headers = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy":
      "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; " +
      "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; " +
      "font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; " +
      "frame-ancestors 'none'",
  };
  if (proto === "https") {
    headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains";
  }
  return headers;
}

function clientInfo(req) {
  let ip = req.socket.remoteAddress || "";
  let proto = req.socket.encrypted ? "https" : "http";
  if (trustProxy) {
    const cf = req.headers["cf-connecting-ip"];
    const xff = req.headers["x-forwarded-for"];
    const xfp = req.headers["x-forwarded-proto"];
    if (typeof cf === "string" && cf.trim()) ip = cf.trim();
    else if (typeof xff === "string" && xff.trim()) ip = xff.split(",")[0].trim();
    if (typeof xfp === "string" && xfp.trim()) proto = xfp.split(",")[0].trim();
  }
  return { ip, proto };
}

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
    ...securityHeaders(res.__omrProto || "http"),
  });
  res.end(body);
}

function serveFile(req, res, pathname, proto) {
  let relative = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
  let file = path.resolve(dist, relative);
  if (file !== dist && !file.startsWith(dist + path.sep)) {
    res.writeHead(403, { "Content-Type": "text/plain; charset=utf-8", ...securityHeaders(proto) });
    res.end("forbidden\n");
    return;
  }
  let stat;
  try {
    stat = fs.statSync(file);
  } catch {
    stat = null;
  }
  if (!stat || stat.isDirectory()) {
    if (path.extname(pathname)) {
      res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8", ...securityHeaders(proto) });
      res.end("not found\n");
      return;
    }
    file = path.join(dist, "index.html");
    stat = fs.statSync(file);
  }

  const ext = path.extname(file).toLowerCase();
  const type = MIME.get(ext) || "application/octet-stream";
  const headers = {
    "Content-Type": type,
    ...securityHeaders(proto),
  };
  headers["Cache-Control"] =
    pathname.startsWith("/assets/") ? "public, max-age=31536000, immutable" : "no-cache";

  let body = fs.readFileSync(file);
  const acceptsGzip = /\bgzip\b/.test(String(req.headers["accept-encoding"] || ""));
  const compressible = /^(text\/|application\/(json|javascript|xml)|image\/svg)/.test(type);
  if (acceptsGzip && compressible && body.length > 1024) {
    const cacheKey = `${file}:${stat.mtimeMs}:${stat.size}`;
    let compressed = gzipCache.get(cacheKey);
    if (!compressed) {
      compressed = zlib.gzipSync(body, { level: 6 });
      if (gzipCache.size > 40) gzipCache.clear();
      gzipCache.set(cacheKey, compressed);
    }
    body = compressed;
    headers["Content-Encoding"] = "gzip";
    headers["Vary"] = "Accept-Encoding";
  }
  headers["Content-Length"] = String(body.length);
  res.writeHead(200, headers);
  if (req.method === "HEAD") res.end();
  else res.end(body);
}

function proxyApi(req, res, proto) {
  // Build the target from path + query only. Using req.url as-is would let a
  // request target like "//evil.example/api" replace the upstream host.
  const local = new URL(req.url || "/", "http://scoreomr.local");
  const target = new URL(`${local.pathname}${local.search}`, apiOrigin);
  const { ip, proto: forwardedProto } = clientInfo(req);
  const headers = { ...req.headers };
  for (const name of ["connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"]) {
    delete headers[name];
  }
  headers.host = target.host;
  headers["x-real-ip"] = ip;
  headers["x-forwarded-for"] = ip;
  headers["x-forwarded-proto"] = trustProxy ? forwardedProto : proto;
  headers["x-forwarded-host"] = req.headers.host || "";

  const options = {
    protocol: target.protocol,
    hostname: target.hostname,
    port: target.port || (target.protocol === "https:" ? 443 : 80),
    path: `${target.pathname}${target.search}`,
    method: req.method,
    headers,
    timeout: 300000,
  };

  const upstream = (target.protocol === "https:" ? https : http).request(options, (upstreamRes) => {
    const responseHeaders = { ...upstreamRes.headers };
    delete responseHeaders.connection;
    delete responseHeaders["keep-alive"];
    delete responseHeaders["transfer-encoding"];
    const present = new Set(Object.keys(responseHeaders).map((key) => key.toLowerCase()));
    for (const [key, value] of Object.entries(securityHeaders(proto))) {
      if (!present.has(key.toLowerCase())) responseHeaders[key] = value;
    }
    res.writeHead(upstreamRes.statusCode || 502, responseHeaders);
    upstreamRes.pipe(res);
  });

  upstream.on("timeout", () => upstream.destroy(new Error("upstream timeout")));
  upstream.on("error", (error) => {
    console.error(`[web] api proxy error: ${error.message}`);
    if (!res.headersSent) sendJson(res, 502, { error: { code: "bad_gateway", message: "识别服务暂时不可用" } });
    else res.destroy();
  });
  req.on("aborted", () => upstream.destroy());
  res.on("close", () => upstream.destroy());
  req.pipe(upstream);
}

const handler = (req, res) => {
  res.__omrProto = req.socket.encrypted ? "https" : "http";
  const proto = res.__omrProto;
  if (req.url === "/healthz") {
    res.writeHead(200, { "Content-Type": "text/plain; charset=utf-8", ...securityHeaders(proto) });
    res.end("ok\n");
    return;
  }
  let pathname;
  try {
    pathname = decodeURIComponent(new URL(req.url || "/", "http://localhost").pathname);
  } catch {
    res.writeHead(400, { "Content-Type": "text/plain; charset=utf-8", ...securityHeaders(proto) });
    res.end("bad request\n");
    return;
  }
  if (pathname === "/api" || pathname.startsWith("/api/")) {
    proxyApi(req, res, proto);
    return;
  }
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405, { "Content-Type": "text/plain; charset=utf-8", ...securityHeaders(proto) });
    res.end("method not allowed\n");
    return;
  }
  try {
    serveFile(req, res, pathname, proto);
  } catch (error) {
    console.error(`[web] static error: ${error.message}`);
    if (!res.headersSent) {
      res.writeHead(500, { "Content-Type": "text/plain; charset=utf-8", ...securityHeaders(proto) });
      res.end("internal error\n");
    }
  }
};

const tlsEnabled = Boolean(certFile && keyFile);
const server = tlsEnabled
  ? https.createServer(
      { cert: fs.readFileSync(certFile), key: fs.readFileSync(keyFile) },
      handler,
    )
  : http.createServer(handler);

server.requestTimeout = 600000;
server.headersTimeout = 60000;

server.on("error", (error) => {
  console.error(`[web] server error: ${error.message}`);
  process.exit(1);
});

server.on("clientError", (error, socket) => {
  if (socket.writable) socket.end("HTTP/1.1 400 Bad Request\r\n\r\n");
  console.warn(`[web] client error: ${error.message}`);
});

server.listen(port, host, () => {
  console.log(`[web] ${tlsEnabled ? "https" : "http"}://${host}:${port} -> ${apiOrigin.origin}`);
  console.log(`[web] static root: ${dist}`);
  if (!tlsEnabled) console.warn("[web] TLS disabled; Google OAuth requires HTTPS in production");
});

function shutdown(signal) {
  console.log(`[web] ${signal} received; closing`);
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 5000);
}
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
