# 部署到阿里云轻量应用服务器

这份文档是**全 Docker + Caddy** 的备选路径，按「Ubuntu 24.04 x86_64 +
Docker Compose + Caddy 自动 HTTPS」写。法兰克福服务器 + 3015 + pm2 的主路径
请看 [DEPLOY_PM2.md](DEPLOY_PM2.md)。

> 目标：一台 2 vCPU / 4 GB 的轻量应用服务器，公网只开 22 / 80 / 443，
> 数据与代码都在一个目录/一个数据卷里，更新时一条命令。

---

## 1. 买多大的机器

| 规格 | 结论 |
|---|---|
| 2 vCPU / 4 GB / 60 GB | **推荐**。Audiveris 是 Java，homr 是 ONNX，双引擎串行跑 |
| 2 vCPU / 2 GB / 40 GB | 能跑，但需要 `AUDIVERIS_HEAP=1024m`，密集页面可能 OOM 或很慢 |
| 1 vCPU / 2 GB | 只适合临时测试；一次任务可能几十秒到几分钟 |

- 系统盘至少 40 GB：worker 镜像约 1.5–2 GB，加上构建缓存、结果文件。
- 地域：面向中国大陆用户选离用户近的地域；**域名需要 ICP 备案**才能在大陆
  服务器上通过 80/443 提供网站服务。没有备案可先用香港地域，或只做内网测试。
- 创建实例后先做一次**快照**，再开始折腾 Docker。

镜像选择：Ubuntu 24.04 LTS（x86_64）。Audiveris 只有 amd64 Linux 包，ARM
轻量服务器需要 amd64 模拟，性能和兼容性都不划算。

---

## 2. 安装 Docker 与 Compose

SSH 登录后：

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

退出 SSH 再登录（或 `newgrp docker`），确认：

```bash
docker version
docker compose version
```

如果拉取 Docker Hub 很慢，在阿里云容器镜像服务控制台获取专属加速地址，然后：

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'JSON'
{
  "registry-mirrors": ["https://<你的ID>.mirror.aliyuncs.com"]
}
JSON
sudo systemctl restart docker
```

> 镜像加速只影响 Docker Hub；GitHub 下载 Audiveris / homr 模型是另一件事，
> 见第 4 节。

---

## 3. 域名、备案与防火墙

1. 域名 A 记录指向轻量服务器公网 IP。
2. 大陆地域完成 ICP 备案（阿里云控制台有备案入口）。
3. 轻量应用服务器控制台 → 防火墙，放行：
   - `22/tcp`（最好限制来源 IP）
   - `80/tcp`
   - `443/tcp`
   - 不要放行 `8000`、`8080`；compose 里的 web 只绑定 `127.0.0.1:8080`。
4. 如果使用 Caddy，80/443 必须能从公网访问，否则证书签发失败。

---

## 4. 构建与启动

### 4.1 上传代码

```bash
# 在本地
tar --exclude=.git --exclude=node_modules --exclude=.venv -czf scoreomr.tgz scoreomr
scp scoreomr.tgz root@<服务器IP>:/root/

# 在服务器
cd /root
tar xzf scoreomr.tgz
cd scoreomr
```

也可以 `git clone` 你的 GitHub 仓库。这个文件夹是自包含的，不依赖原工程的
其他目录。

### 4.2 配置 `.env`

```bash
cp .env.example .env
nano .env
```

最小生产配置：

```dotenv
APP_ENV=production
APP_URL=https://omr.example.com
DOMAIN=omr.example.com

DAILY_LIMIT=1

# Google 登录可选；不填也能跑，邮箱/密码正常工作
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

SESSION_SECRET=                       # 留空，首次启动自动生成并持久化
SESSION_COOKIE_SECURE=                # 留空，HTTPS 自动 Secure

WORKER_PLATFORM=linux/amd64
AUDIVERIS_HEAP=1536m                  # 2 GB 机器改成 1024m

# 大陆网络建议
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
NPM_REGISTRY=https://registry.npmmirror.com
APT_MIRROR=mirrors.aliyun.com
```

> 不要把 `.env` 提交到 Git。`SESSION_SECRET` 留空时会在
> `/data/session_secret` 生成一个 0600 的随机值，后续重启/升级会复用。

### 4.3 如果 GitHub 下载失败

worker 构建需要从 GitHub 拉两样东西：

1. Audiveris 的 `.deb`（可直接换 URL）；
2. homr 的 ONNX/OCR 权重（`homr --init` 下载）。

**Audiveris：** 把 `.env` 的 URL 换成 GitHub 代理，例如：

```dotenv
AUDIVERIS_DEB_URL=https://ghfast.top/https://github.com/Audiveris/audiveris/releases/download/5.11.0/Audiveris-5.11.0-ubuntu24.04-x86_64.deb
```

**homr 模型：** 给构建过程一个代理：

```dotenv
HTTPS_PROXY=http://<代理地址>:<端口>
```

Compose 会把它作为 build arg 传给镜像。没有代理时，也可以在一台能访问
GitHub 的机器上构建好 worker 镜像，推到阿里云容器镜像服务 ACR，再在服务器
上拉取：

```bash
# 在能联网的 amd64 机器上
docker buildx build --platform linux/amd64 \
  -f deploy/worker.Dockerfile \
  -t registry.cn-hangzhou.aliyuncs.com/<命名空间>/scoreomr-worker:0.1.0 \
  --push .
```

然后在服务器上把 `compose.yml` 的 `image: scoreomr-worker:local` 改成该镜像，
并删除/注释 `build:` 段（或保留，`docker compose up -d` 会优先用已有镜像）。
如果你不想预下载模型，可设 `HOMR_INIT=0`，但这样第一次识别会依赖运行时能访问
GitHub，生产不推荐。

### 4.4 构建

```bash
# 先单独构建 worker，失败时容易看日志
docker compose build worker

# 再构建 api 与 web
docker compose build api web
```

首次构建预期：

- 下载 Ubuntu 基础镜像、Python/Node 依赖；
- 下载 Audiveris 约 78 MB 并解包；
- 下载 homr 模型，执行 `homr --init`；
- 总耗时取决于网络，可能 10–30 分钟。

### 4.5 启动

```bash
# 只在本机验证（HTTP）
docker compose up -d
curl -s http://127.0.0.1:8080/api/health

# 正式 HTTPS（推荐）
docker compose -f compose.yml -f compose.tls.yml up -d
```

Caddy 会自动申请 Let's Encrypt 证书并把 HTTP 重定向到 HTTPS。打开：

```text
https://omr.example.com
```

检查：

```bash
docker compose ps
curl -s https://omr.example.com/api/health
docker compose logs -f --tail=100 api worker caddy
```

`/api/health` 里应看到：

```json
{"ok":true,"db":"ok","queue":{"queued":0,"running":0},
 "worker":{"online":true,"engines":{"audiveris":true,"homr":true}}}
```

worker 刚启动时 `online` 可能短暂为 false；90 秒内没有心跳才视为离线。

---

## 5. Google 登录（可选）

不配置时完全正常，登录页只显示邮箱/密码。需要 Google 一键登录时：

1. Google Cloud Console → OAuth consent screen（External）：
   scopes 只需要 `openid`、`email`、`profile`。
2. Credentials → OAuth client ID → Web application：
   - Authorised redirect URI：`https://omr.example.com/api/auth/google/callback`
     （必须与 `APP_URL` 完全一致；pm2 + 3015 路径则带 `:3015`）。
3. `.env`：

```dotenv
GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxx
GOOGLE_REDIRECT_URI=https://omr.example.com/api/auth/google/callback
```

Google 登录即注册；同邮箱已有密码账户不会自动合并，先密码登录再在账户页绑定。
只保存邮箱和 Google `sub`，不保存头像/昵称。

### 每日免费额度

```dotenv
DAILY_LIMIT=1
```

未登录按 IP、登录后按账户计算；任务失败退还。
重建 API 容器后生效：

```bash
docker compose up -d api worker
```

---

## 6. 备份、更新、回滚

### 备份

```bash
pnpm db:backup
# 或
bash scripts/backup.sh
# => backups/scoreomr-YYYYmmdd-HHMMSS.db
```

建议每天 cron 一次，并把 `backups/` 同步到 OSS 或另一台机器。结果文件默认只保留
7 天，数据库备份不包含结果文件；如果要保留结果，按 [README](../README.md#6-数据备份与迁移)
里的方式打包数据卷。

### 更新

```bash
cd /root/scoreomr
git pull                     # 或重新上传代码
docker compose build
docker compose up -d
docker compose ps
```

数据库 schema 目前通过 `CREATE TABLE IF NOT EXISTS` 幂等初始化，升级不会清数据。
如果以后引入迁移，会在 `app/db.py` 的 `SCHEMA_VERSION` 中体现。

### 回滚

```bash
git switch --detach <上一个版本>
docker compose build
docker compose up -d
# 如数据库不兼容，用备份恢复
bash scripts/restore.sh backups/xxx.db
```

---

## 7. 常见问题

**`/api/health` 502 / web 起不来**

- `docker compose ps` 看 api 是否 healthy；
- `docker compose logs api`；常见原因是 `.env` 里 `OMR_MOCK=true` 配了
  `APP_ENV=production`（启动校验会直接拒绝）；
- 数据卷权限：确认 `/data` 可写（镜像已 chown 到 10001；不要用 root 手改权限后
  又把卷挂到别的 uid）。

**worker 一直 offline / 任务永远 queued**

- `docker compose logs worker`；
- `exec format error`：宿主机是 ARM，但 worker 是 amd64。保持
  `WORKER_PLATFORM=linux/amd64`，或在 x86 服务器上构建；
- 模型缺失：确认构建时 `HOMR_INIT=1` 且日志里 `Init finished`；
- 内存不足：`dmesg | tail` 看 OOM；把 `AUDIVERIS_HEAP` 降到 1024m，或升级到 4 GB；
- 任务卡住：worker 心跳过期后会自动重排；最多尝试 2 次。

**所有未注册用户共用 1 次额度**

- 说明代理没有把真实 IP 传进来。检查：
  - 是否直接访问了 `http://IP:8080`（compose 绑定 127.0.0.1，正常访问不到）；
  - 宿主 Nginx 是否设置了 `proxy_set_header X-Forwarded-For $remote_addr;`；
  - 如用 Caddy，`deploy/Caddyfile` 已经覆盖了 XFF，不要在外层再加一层不改
    XFF 的代理。
- 同一 NAT 下多个匿名用户共享额度是设计行为；注册后按账户计。

**PDF 上传报“无法解析”**

- API 镜像已装 `poppler-utils`；确认没有自定义镜像把它删掉；
- 加密 PDF 不支持；只识别第一页。

**Caddy 证书失败**

- 域名是否解析到本机、80/443 是否放行、是否完成备案；
- `docker compose logs caddy`；
- 测试可先用 `docker compose up -d`（HTTP 8080）验证应用，再切 TLS。

**用宿主 Nginx 代替 Caddy**

web 容器只监听 `127.0.0.1:8080`。宿主 Nginx 必须**覆盖**而不是追加
`X-Forwarded-For`，否则匿名额度可能按代理 IP 计算或被伪造：

```nginx
server {
    listen 443 ssl http2;
    server_name omr.example.com;
    # ssl_certificate ...; ssl_certificate_key ...;

    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;   # 覆盖，不要用 $proxy_add_x_forwarded_for
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
```

**磁盘满了**

- `docker system df`；镜像/构建缓存占大头；
- 结果默认 7 天清理；可以调小 `JOB_RETENTION_DAYS`；
- `docker compose down` 不会删数据卷，`down -v` 会；不要随手 `-v`。

---

## 8. 安全清单

- [ ] 公网只开 22/80/443；API/worker/8080 不对公网开放。
- [ ] `APP_ENV=production`、`OMR_MOCK=false`、`DAILY_LIMIT` 符合预期。
- [ ] `.env` 权限 600，不提交 Git。
- [ ] HTTPS 正常，`SESSION_COOKIE_SECURE` 生效（看浏览器 cookie 的 Secure 标记）。
- [ ] 未登录和登录用户各完成一次识别，额度按预期扣减。
- [ ] 定期 `pnpm db:backup`，备份离开本机。
- [ ] 升级前打快照。
- [ ] 阅读 [NOTICE](../NOTICE) 中 Audiveris/homr 的 AGPL 义务。

---

## 9. 资源占用参考

| 进程 | 空闲 | 识别一张时 |
|---|---:|---:|
| api | 80–150 MB | 同上 |
| worker | 200–400 MB | 1.5–2.5 GB（Audiveris + homr 模型） |
| web/nginx | 10–30 MB | 同上 |
| caddy | 20–40 MB | 同上 |

4 GB 机器建议只跑一个 worker；2 GB 机器把 heap 调到 1024m，并接受更慢的速度。
一次任务串行处理，符合轻量服务器的 CPU 现实。
