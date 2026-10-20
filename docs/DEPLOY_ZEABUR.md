# Zeabur 一键部署（免费，公开 demo）

在免费 PaaS 上跑出**人人可用的公网公开实例**，不需要自己的服务器。整个服务
（web 网关 + FastAPI + OMR worker）打包成一个镜像，一个 Zeabur 服务就能跑。

> 前提：仓库推到 GitHub（可公开）。Zeabur 免费计划无需绑卡。

## 为什么能只用一个容器

现有 [ARCHITECTURE.md](ARCHITECTURE.md) 的三进程（Node 网关 / FastAPI / worker）
被合并进一个镜像：

- 镜像根：等同于 `deploy/worker.Dockerfile` 的重型运行时（Audiveris + homr + Python）；
- 额外装了一个纯 stdlib 的 Node 二进制，跑 `apps/web/server.mjs`（SPA + `/api` 反代）；
- 一个入口脚本 `deploy/zeabur-entrypoint.sh` 同时拉起三个进程，共享 `/data`：
  `uvicorn` 只监听 `127.0.0.1:8000`，`node server.mjs` 监听 Zeabur 分配的 `$PORT`，
  worker 在后台消费同一个 SQLite 队列。

这就是仓库根目录的 `Dockerfile`（Zeabur 会自动识别根目录 Dockerfile，无需改配置）。

## 第一步：推到 GitHub

```bash
cd /Users/Admin/Desktop/musique/ocr_for_scores/scoreomr
git init
git branch -M main
git add .
git commit -m "ScoreOMR: single-container build for Zeabur"
git remote add origin git@github.com:<你的账号>/<仓库名>.git
git push -u origin main
```

提交前确认 `.env` 未被跟踪（`.gitignore` 已忽略），仓库里没有真实密钥。

## 第二步：在 Zeabur 创建服务

1. 打开 <https://zeabur.com/zh-CN>，用 GitHub 登录（免费计划即可）；
2. 新建项目 → **从 Git 仓库导入** → 选择刚 push 的仓库；
3. 添加服务时选择 **Docker** 类型：Zeabur 检测到根目录 `Dockerfile` 后会自动
   按 Docker 构建，无需选框架；
4. 构建 + 部署。**首次构建较慢**（要下载 Audiveris、homr 的 ONNX 权重，
   肉眼预估 10–20 分钟），之后有缓存会快很多；
5. 部署成功后，在服务详情把 **networking / 公网端口** 绑定到 Zeabur 分配的公网
   域名（`https://<服务名>.zeabur.app`）。

> 若构建中途失败，先看构建日志：绝大多数失败集中在装 Audiveris 那一步（GitHub
> 下载 .deb）。可以重试；或者把仓库 fork 到能稳定访问 GitHub 的网络再构建。

## 第三步：设置环境变量（在 Zeabur 服务页的「Variables」里添加）

| 变量 | 值 | 说明 |
|---|---|---|
| `APP_URL` | `https://<你的服务名>.zeabur.app` | **必须填**，否则 Cookie 不带 Secure，任务历史归属失效 |
| `APP_ENV` | `production` | 默认可省略，但写了更明确 |
| `MAX_QUEUE_LENGTH` | `5` | 收紧额度：默认 20，公开实例压低防止被刷爆 |
| `MAX_ACTIVE_JOBS` | `1` | 每个浏览器同时最多 1 个任务（默认就是 1） |
| `MAX_UPLOAD_MB` | `15` | 收紧额度：默认 20 |
| `JOB_TIMEOUT_SECONDS` | `900` | 单任务超时，公开实例没必要更长 |
| `AUDIVERIS_HEAP` | `1024m` | 免费实例内存有限；镜像内默认已设为 1024m |

环境变量不需要全部填，上面只有 `APP_URL` 是必需的。其余变量镜像内已给出
收紧后的默认值，覆盖它们只是显式声明。

设置完成后，在服务页点 **Redeploy**，等状态变绿即完成。

## mac / Windows 上先本地验证镜像（可选，想省时间就跳过）

```bash
docker build -t scoreomr-all:test .
docker run --rm -e PORT=3000 -p 3000:3000 scoreomr-all:test
# 打开 http://127.0.0.1:3000
```

`AUDIVERIS_DEB_URL`、`PIP_INDEX_URL`、`APT_MIRROR` 都支持作为 build arg 传入，
国内构建时可换成镜像源。

## iPhone 怎么用它

1. 用 **Safari** 打开 `https://<你的服务名>.zeabur.app`（不要用微信/QQ内置浏览器）;
2. 点底部 **分享按钮 → 添加到主屏幕**：以后从桌面图标进入，像 App 一样用
   （这是网页书签，不是真 PWA，但点击就全屏打开，足够日常用）;
3. 使用方式：
   - **拍照上传**：用系统相机拍一页谱面（单行、别反光），或在聊天里保存图后
     从相册选择。iPhone 拍的照片建议选 **homr 鲁棒** 模式，抗退化最好；
   - **干净的数字谱 PDF/PNG**：选 **Audiveris 精校** 或默认的 **双引擎对比**;
   - 结果：`best.musicxml`（可导入 MuseScore / 分享）、`best.wav`（点开即播）、
     `best.mid`（iPhone 需用第三方播放器如 MuseScore / CosyCopter）、
     `notes.csv`、`piano_roll.png`;
   - 页面右上角可切 **中文 / EN / FR / RU**。
4. 隐私说明：任务归属用浏览器匿名 Cookie，**换浏览器或清 Cookie 后就看不到
   自己的历史**；结果文件不会自动删除，Zeabur 免费层的磁盘有限，公开实例建议
   偶尔在服务页清一次数据或接受它自动回收。

## 免费计划注意（别踩坑）

- **免费层有使用限制**（睡眠/配额），高峰期可能排队或短暂不可用；作为个人 demo
  够用，别承诺 SLA;
- **`/data` 用实例自带磁盘**：重启/重建可能丢数据（任务历史、结果都在里面）。
  想要持久化，在 Zeabur 面板给服务挂一个持久化存储卷并确保 `DATA_DIR=/data`
  指向挂载点；
- **公网公开 = 谁都能用**：虽然 `MAX_QUEUE_LENGTH=5` 已收紧，仍可能被陌生人
  消耗 CPU。若担心滥用，可以在服务前面再加一层 Cloudflare 的“质询”或访问限制，
  或用 Zeabur 的鉴权功能（见平台文档）。

## 和现有部署方式的关系

- 这个根目录 `Dockerfile` 是**第三条独立路径**，与
  [DEPLOY_PM2.md](DEPLOY_PM2.md) / [DEPLOY_ALIYUN.md](DEPLOY_ALIYUN.md) 并行，
  不冲突；本机 `docker compose`、`pnpm dev`、CI 均不受影响（它们各自指定
  `deploy/*.Dockerfile`，不会误用根目录的 Dockerfile）；
- 想要完整多容器、持久化、域名 + HTTPS，还是走阿里云 / 自有服务器路径更稳。