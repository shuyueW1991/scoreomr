# syntax=docker/dockerfile:1.7
# Heavy OMR worker image: Audiveris (bundled JRE) + homr (ONNX, CPU).
#
# Audiveris ships an x86_64 Ubuntu 24.04 package only, so this image is
# linux/amd64.  On Apple Silicon compose requests amd64 + emulation; Aliyun
# ECS/Lightweight x86_64 runs it natively.
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG UV_VERSION=0.12.3
ARG APT_MIRROR=
ARG AUDIVERIS_VERSION=5.11.0
ARG AUDIVERIS_DEB_URL=https://github.com/Audiveris/audiveris/releases/download/5.11.0/Audiveris-5.11.0-ubuntu24.04-x86_64.deb
ARG AUDIVERIS_HEAP=1536m
ARG HOMR_INIT=1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    UV_INDEX_URL=${PIP_INDEX_URL} \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    HOME=/home/app \
    XDG_CACHE_HOME=/home/app/.cache \
    MPLCONFIGDIR=/home/app/.cache/matplotlib

# Optional Aliyun/China mirror for Ubuntu packages.
RUN if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s|http://archive.ubuntu.com/ubuntu|https://${APT_MIRROR}/ubuntu|g; s|http://security.ubuntu.com/ubuntu|https://${APT_MIRROR}/ubuntu|g" /etc/apt/sources.list.d/ubuntu.sources; \
    fi \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl tini passwd \
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
# the application environment.  UV_PROJECT_ENVIRONMENT points at /opt/venv,
# which uv creates and manages.
RUN python3 -m venv /opt/uv \
 && /opt/uv/bin/pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" "uv==${UV_VERSION}"

WORKDIR /app
COPY services/backend/pyproject.toml services/backend/uv.lock ./
RUN /opt/uv/bin/uv sync --frozen --no-dev --extra omr --no-install-project

COPY services/backend/app ./app
COPY services/backend/omr_agent ./omr_agent
RUN /opt/uv/bin/uv sync --frozen --no-dev --extra omr

# homr is installed after uv sync on purpose: a later sync would prune it as an
# extraneous package.  --init bakes ONNX + OCR weights into the image so a
# request never depends on GitHub being reachable at runtime.
RUN /opt/uv/bin/uv pip install --python /opt/venv/bin/python \
      --index-url "${PIP_INDEX_URL}" "homr==0.7.0"

RUN useradd --uid 10001 --user-group --create-home --home-dir /home/app --shell /usr/sbin/nologin app \
 && mkdir -p /data /home/app/.cache/matplotlib /home/app/.cache/rapidocr \
 && chown -R app:app /data /home/app

# Run init as root with HOME=/home/app so both package-level ONNX files and
# user-level OCR caches land in the image.  Set HOMR_INIT=0 for a smaller,
# network-dependent build (not recommended for production).
RUN if [ "${HOMR_INIT}" = "1" ]; then /opt/venv/bin/homr --init; fi \
 && chown -R app:app /home/app

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=8s --start-period=90s --retries=3 \
  CMD ["/opt/venv/bin/python", "-m", "app.healthcheck"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/venv/bin/python", "-m", "app.worker"]
