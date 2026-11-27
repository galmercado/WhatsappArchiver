# syntax=docker/dockerfile:1.7
# Three stages: `web` builds the SPA, `dev` is the hot-reload image, `runtime` is the hardened prod image.
# For reproducible builds pin the base images by digest (see docs/HARDENING.md).

FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.15-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WA_PORT=8000 \
    WA_STATIC_DIR=/app/static
RUN groupadd --system --gid 10001 wa \
 && useradd --system --uid 10001 --gid wa --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin wa
WORKDIR /app

FROM base AS dev
COPY pyproject.toml ./
COPY src ./src
RUN pip install -e .
COPY --from=web /web/dist /app/static
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 CMD ["python", "-m", "waarchive.server.healthcheck"]
CMD ["python", "-m", "waarchive.server", "--reload", "--verbose"]

FROM base AS runtime
COPY pyproject.toml ./
COPY src ./src
# Non-editable install; sources and build metadata are removed afterwards so only site-packages remains.
RUN pip install . && rm -rf /app/src /app/pyproject.toml /app/build /root/.cache
COPY --from=web /web/dist /app/static
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["python", "-m", "waarchive.server.healthcheck"]
CMD ["python", "-m", "waarchive.server"]
