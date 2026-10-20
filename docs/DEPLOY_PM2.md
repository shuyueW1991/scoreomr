# 服务器部署：pm2 + 3015 + Docker 后端

这是一个**免费、开源**的部署方案，不需要任何第三方 API key。

```text
浏览器
  │  https://你的域名:3015
  ▼
pm2 → node apps/web/server.mjs        ← 静态 SPA + /api 反向代理
  │  http://127.0.0.1:8000
  ▼
Docker: api (FastAPI + SQLite)  ←→  Docker: worker (Audiveris + homr)
  │
  └── scoreomr-data 卷（SQLite + 结果文件）
```

这样做的原因：

- 你的 3015 端口和 pm2 都能按现有习惯使用；
- Java / Audiveris / ONNX 这些重依赖留在 Docker 里，不装进宿主机；
- pm2 只负责轻量的 Node 入口，重启快、日志干净；
- 法兰克福网络拉 Docker Hub / PyPI / GitHub 都比较顺畅。

> **不填任何 key 也能跑。** 没有账户、没有登录、没有每日额度；任务历史按
> 浏览器本地 Cookie 归属。公开到互联网时建议 HTTPS；只在内网/本机测试可以先用 HTTP。

---

## 1. 服务器规格

| 规格 | 说明 |
|---|---|
| 2 vCPU / 4 GB / 40 GB+ | 推荐 |
| 2 vCPU / 2 GB | 能跑，`AUDIVERIS_HEAP=1024m`，密集页面可能 OOM |
| 系统 | Ubuntu 24.04 LTS x86_64 |
| 网络 | 法兰克福；出站可访问 Docker Hub / PyPI / GitHub |

开放端口：

- `22/tcp`：SSH（最好限制来源 IP）
- `3015/tcp`：pm2 Node 入口
- `80/tcp`：仅用于 Let's Encrypt 首次签发/续期（如需 HTTPS）
- `8000`：**不要开放**，只绑定 `127.0.0.1`，给 Node 网关访问

本项目默认 3015。如果端口冲突，把 `.env` 的 `PORT`、`APP_URL` 和 pm2 命令里的
端口一起改成空闲端口（如 3016）即可。

---

## 2. 安装运行环境

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
```

### Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
# 退出 SSH 再登录，确认：
docker version
docker compose version
```

### Node 22 + pnpm + pm2

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
sudo corepack enable
corepack prepare pnpm@11.28.5 --activate
sudo npm install -g pm2
node -v && pnpm -v && pm2 -v
```

---

## 3. 代码与 `.env`

```bash
cd /opt
sudo mkdir -p /opt/scoreomr
sudo chown "$USER":"$USER" /opt/scoreomr
git clone <你的仓库地址> /opt/scoreomr
cd /opt/scoreomr
cp .env.example .env
nano .env
```

一个最小配置（无账户、无额度、无自动清理）：

```dotenv
APP_ENV=production
APP_URL=https://omr.example.com:3015

PORT=3015
API_HOST_PORT=8000
TLS_CERT_FILE=/etc/scoreomr/tls/fullchain.pem
TLS_KEY_FILE=/etc/scoreomr/tls/privkey.pem
EDGE_TRUST_PROXY=0

AUDIVERIS_HEAP=1536m
WORKER_PLATFORM=linux/amd64
```

如果先用 HTTP 测试，把 `APP_URL` 改成 `http://服务器IP:3015`，并清空
`TLS_CERT_FILE` / `TLS_KEY_FILE`。公开使用时建议配 HTTPS。
Cookie 的 `Secure` 标记会自动根据 `APP_URL` 是否为 `https://` 决定。

---

## 4. HTTPS（可选，公开部署推荐）

假设域名 `omr.example.com` 已解析到服务器公网 IP。

```bash
sudo apt-get install -y certbot
# 80 端口空闲时用 standalone；如果 80 被占用，用 DNS-01 或 webroot
sudo certbot certonly --standalone -d omr.example.com
```

准备 pm2 用户可读的副本：

```bash
sudo mkdir -p /etc/scoreomr/tls
sudo cp /etc/letsencrypt/live/omr.example.com/fullchain.pem /etc/scoreomr/tls/
sudo cp /etc/letsencrypt/live/omr.example.com/privkey.pem   /etc/scoreomr/tls/
sudo chown -R "$USER":"$USER" /etc/scoreomr/tls
chmod 600 /etc/scoreomr/tls/privkey.pem
```

续期（证书 90 天有效）：

```bash
sudo certbot renew
sudo cp /etc/letsencrypt/live/omr.example.com/fullchain.pem /etc/scoreomr/tls/
sudo cp /etc/letsencrypt/live/omr.example.com/privkey.pem   /etc/scoreomr/tls/
sudo chown -R "$USER":"$USER" /etc/scoreomr/tls
pm2 restart scoreomr
```

也可以先用 Caddy 在 443 终止 TLS，再反代到 `127.0.0.1:3015`；此时公网地址是
`https://omr.example.com`（不带 3015），并设置 `EDGE_TRUST_PROXY=1`。

---

## 5. 账户与额度

**本工具没有账户系统：** 无注册、无登录、无 Google OAuth，也不依赖任何第三方
API key。任务历史按浏览器在本地写入的匿名 Cookie（`omr_anon`）归属——同一个
浏览器打开「我的任务」能看到自己的记录；换浏览器、换设备或清除 Cookie 后
历史不可见（结果文件仍留在数据卷里，可用文件管理找回）。**没有每日额度限制，**
默认同一浏览器同时只处理 1 个任务（`MAX_ACTIVE_JOBS` 可调），结果文件不会
自动清理。

---

## 6. 构建与启动

```bash
cd /opt/scoreomr

# 1) 前端依赖 + 构建（pm2 的 Node 网关需要 dist/）
pnpm install --frozen-lockfile
pnpm build

# 2) 启动后端容器（api + worker；不启动 web 容器）
docker compose -f compose.yml -f compose.pm2.yml up -d --build api worker

# 3) 等 API healthy
curl -fsS http://127.0.0.1:8000/api/health

# 4) 启动 pm2（两种方式任选）
pm2 start ecosystem.config.cjs
# 或者：
pm2 start npm --name "scoreomr" -- start -- --port 3015

# 5) 保存 + 开机自启
pm2 save
pm2 startup
# 按 pm2 输出的命令执行一次
```

一键版本（构建、启动容器、等待 API、启动 pm2）：

```bash
pnpm pm2:start
```

检查：

```bash
pm2 status
pm2 logs scoreomr --lines 100
docker compose -f compose.yml -f compose.pm2.yml ps
curl -k https://omr.example.com:3015/api/health
```

`/api/health` 应包含 `"worker":{"online":true,...}`。worker 首次启动要加载
Audiveris/homr，给 10–30 秒。

---

## 7. 验证识别与任务归属

1. 浏览器打开站点。
2. 上传一张图/运行一个样例；识别完成后结果可试听、可下载。
3. 打开「我的任务」应能看到本次记录；换一个浏览器（或清除 Cookie 后）再打开
   同一链接会得到 404，历史列表为空——这是设计行为。
4. 结果文件不会自动清理；备份与迁移见 README 第 6 节。
5. 若失败：`pm2 logs scoreomr`、`docker compose ... logs api worker`。

---

## 8. 更新、备份、排错

```bash
cd /opt/scoreomr
git pull
pnpm install --frozen-lockfile
pnpm build
docker compose -f compose.yml -f compose.pm2.yml up -d --build api worker
pm2 reload scoreomr --update-env

# 备份（SQLite 一致性备份）
pnpm db:backup

# 日志
pm2 logs scoreomr
docker compose -f compose.yml -f compose.pm2.yml logs -f api worker

# 查看 3015 / 8000
ss -ltnp | grep -E '3015|8000'
```

常见问题：

| 现象 | 处理 |
|---|---|
| 3015 打不开 | 云防火墙、`pm2 status`、`ss -ltnp`、证书路径权限 |
| 8000 被公网访问 | compose 已绑定 `127.0.0.1`；检查防火墙，不要开放 8000 |
| 「我的任务」为空 | 换过浏览器或清过 Cookie；结果文件仍在数据卷，可访问备份 |
| worker offline | `docker compose ... logs worker`；内存不足时降 `AUDIVERIS_HEAP` 或升级 4 GB |
| 从旧数据升级 | 建议清空旧数据卷（`docker compose down -v`）后重新部署；旧版本的数据结构不再使用 |

---

## 9. 所需 Key / API 清单

| 项 | 必需？ | 用途 |
|---|---|---|
| 第三方 API key | **不需要** | OMR 在本地 Audiveris + homr 完成 |
| 数据库 API | **不需要** | 内置 SQLite |
| 域名 + TLS | 否 | 公开部署建议配置 |

不配置任何 key，`pnpm pm2:start` 也能跑通：本地使用无额度限制，
任务历史按浏览器 Cookie 归属，结果文件不会自动清理。
