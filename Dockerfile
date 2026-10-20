# syntax=docker/dockerfile:1.7
# ScoreOMR single-container build for Zeabur / generic single-image PaaS.
#
# One image = three roles:
#   node apps/web/server.mjs   web gateway (SPA + /api proxy, listens on $PORT)
#   uvicorn                    FastAPI on 127.0.0.1:8000 (loopback only)
#   python -m app.worker       SQLite queue consumer (same data dir)
#
# Entry: deploy/zeabur-entrypoint.sh (tini -> entrypoint -> drop to uid 10001).
#
# This is the heavy path (Audiveris + homr), same engine stack as
# deploy/worker.Dockerfile, plus the web tier folded in so a single container
# is enough. Audiveris ships only linux/x86_64 packages, so the image is
# linux/amd64.

# ---------------------------------------------------------------- web build
FROM node:22-bookworm-slim AS web-build

ARG NPM_REGISTRY=https://registry.npmjs.org
ENV NPM_CONFIG_REGISTRY=${NPM_REGISTRY}

RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g pnpm@11.28.5 --registry="${NPM_REGISTRY}"

WORKDIR /repo
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml .npmrc ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile
COPY apps/web ./apps/web
RUN pnpm --filter @scoreomr/web build

# ---------------------------------------------------- runtime (worker base)
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG UV_VERSION=0.12.3
ARG APT_MIRROR=
ARG AUDIVERIS_VERSION=5.11.0
ARG AUDIVERIS_DEB_URL=https://github.com/Audiveris/audiveris/releases/download/5.11.0/Audiveris-5.11.0-ubuntu24.04-x86_64.deb
ARG AUDIVERIS_HEAP=1024m
ARG HOMR_INIT=1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    UV_INDEX_URL=${PIP_INDEX_URL} \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    HOME=/home/app \
    XDG_CACHE_HOME=/home/app/.cache \
    MPLCONFIGDIR=/home/app/.cache/matplotlib \
    APP_ENV=production \
    APP_NAME=ScoreOMR \
    APP_TIMEZONE=Asia/Shanghai \
    DATA_DIR=/data \
    DATABASE_PATH=/data/scoreomr.db \
    MAX_UPLOAD_MB=15 \
    MAX_GT_MB=2 \
    MAX_QUEUE_LENGTH=5 \
    MAX_ACTIVE_JOBS=1 \
    JOB_TIMEOUT_SECONDS=900 \
    WORKER_POLL_SECONDS=2 \
    OMR_MOCK=false \
    OMR_ENGINES=audiveris,homr \
    AUDIVERIS_BIN=/opt/audiveris/bin/Audiveris \
    HOMR_BIN=/opt/venv/bin/homr \
    OMR_DISABLE_UVX=1 \
    EDGE_TRUST_PROXY=1 \
    LOG_LEVEL=INFO

# Optional Aliyun/China mirror for Ubuntu packages.
RUN if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s|http://archive.ubuntu.com/ubuntu|https://${APT_MIRROR}/ubuntu|g; s|http://security.ubuntu.com/ubuntu|https://${APT_MIRROR}/ubuntu|g" /etc/apt/sources.list.d/ubuntu.sources; \
    fi \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl tini passwd util-linux \
      python3 python3-venv python3-pip dpkg \
      libasound2t64 libbsd0 libmd0 libx11-6 libxau6 libxcb1 libxdmcp6 \
      libxext6 libxi6 libxrender1 libxtst6 xdg-utils zlib1g \
      libfreetype6 libpng16-16 libjpeg-turbo8 libstdc++6 libgomp1 \
      fonts-dejavu-core fontconfig libglib2.0-0 libgl1 \
      poppler-utils \
 && rm -rf /var/lib/apt/lists/*

# Audiveris' .deb contains a jpackage runtime; no system JRE is required.
# The URL can be replaced with a GitHub proxy, e.g.
#   https://ghfast.top/https://github.com/Audiveris/...
RUN curl -fL --retry 3 --retry-delay 2 "${AUDIVERIS_DEB_URL}" -o /tmp/audiveris.deb \
 && mkdir -p /opt/audiveris-pkg \
 && dpkg-deb -x /tmp/audiveris.deb /opt/audiveris-pkg \
 && mv /opt/audiveris-pkg/opt/audiveris /opt/audiveris \
 && rm -rf /tmp/audiveris.deb /opt/audiveris-pkg \
 && test -x /opt/audiveris/bin/Audiveris \
 && sed -i "s/-Xmx8G/-Xmx${AUDIVERIS_HEAP}/" /opt/audiveris/lib/app/Audiveris.cfg \
 && grep -q -- "-Xmx${AUDIVERIS_HEAP}" /opt/audiveris/lib/app/Audiveris.cfg

# Keep uv in its own venv: uv sync is exact and would prune a uv installed in
# the application environment.  UV_PROJECT_ENVIRONMENT points at /opt/venv.
RUN python3 -m venv /opt/uv \
 && /opt/uv/bin/pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" "uv==${UV_VERSION}"

WORKDIR /app
COPY services/backend/pyproject.toml services/backend/uv.lock ./
RUN /opt/uv/bin/uv sync --frozen --no-dev --extra omr --no-install-project

COPY services/backend/app ./app
COPY services/backend/omr_agent ./omr_agent
COPY services/backend/samples ./samples
RUN /opt/uv/bin/uv sync --frozen --no-dev --extra omr

# homr is installed after uv sync on purpose: a later sync would prune it as an
# extraneous package.  --init bakes ONNX + OCR weights into the image so a
# request never depends on GitHub being reachable at runtime.
RUN /opt/uv/bin/uv pip install --python /opt/venv/bin/python \
      --index-url "${PIP_INDEX_URL}" "homr==0.7.0"

# Node runtime for server.mjs: copy the glibc node binary from the web build
# stage (node:22-bookworm-slim is Debian-based and links libc6/libstdc++,
# both already installed above; no separate nodejs package needed).
COPY --from=web-build /usr/local/bin/node /usr/local/bin/node

# Web tier: built SPA + the stdlib-only gateway that serves it and proxies /api.
COPY --from=web-build /repo/apps/web/dist /app/apps/web/dist
COPY apps/web/server.mjs /app/apps/web/server.mjs
COPY deploy/zeabur-entrypoint.sh /usr/local/bin/zeabur-entrypoint.sh
RUN chmod +x /usr/local/bin/zeabur-entrypoint.sh \
 && chmod +x /app/apps/web/server.mjs

RUN useradd --uid 10001 --user-group --create-home --home-dir /home/app --shell /usr/sbin/nologin app \
 && mkdir -p /data /home/app/.cache/matplotlib /home/app/.cache/rapidocr \
 && chown -R app:app /data /home/app

# Run init as root with HOME=/home/app so both package-level ONNX files and
# user-level OCR caches land in the image.
RUN if [ "${HOMR_INIT}" = "1" ]; then /opt/venv/bin/homr --init; fi \
 && chown -R app:app /home/app

EXPOSE 3000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/usr/local/bin/zeabur-entrypoint.sh"]