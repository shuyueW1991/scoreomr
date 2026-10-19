# syntax=docker/dockerfile:1.7
# Lightweight API image: FastAPI + SQLite + PDF rasterisation only.
FROM python:3.12-slim

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG UV_VERSION=0.12.3

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    UV_INDEX_URL=${PIP_INDEX_URL} \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apt-get update \
 && apt-get install -y --no-install-recommends poppler-utils tini passwd fontconfig fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" "uv==${UV_VERSION}"

WORKDIR /app
COPY services/backend/pyproject.toml services/backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/backend/app ./app
COPY services/backend/omr_agent ./omr_agent
COPY services/backend/samples ./samples
RUN uv sync --frozen --no-dev

RUN useradd --uid 10001 --user-group --create-home --home-dir /home/app --shell /usr/sbin/nologin app \
 && mkdir -p /data \
 && chown -R app:app /data /home/app

ENV HOME=/home/app
USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=6s --start-period=20s --retries=3 \
  CMD ["/opt/venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/venv/bin/uvicorn", "app.main:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
