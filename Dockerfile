FROM oven/bun:1 AS frontend-build

WORKDIR /src/web-ui/frontend

COPY web-ui/frontend/package.json web-ui/frontend/bun.lock ./
RUN bun install --frozen-lockfile

COPY web-ui/frontend/ ./
RUN bun run build


FROM python:3.12-slim AS backend

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg pandoc tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.7.19 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY b2t/ ./b2t/
RUN uv sync --frozen --no-dev --extra web
RUN uv run playwright install --with-deps chromium

COPY web-ui/ ./web-ui/

RUN if ! getent group "${APP_GID}" >/dev/null; then groupadd --gid "${APP_GID}" appuser; fi \
    && if ! getent passwd "${APP_UID}" >/dev/null; then useradd --create-home --home-dir /home/appuser --uid "${APP_UID}" --gid "${APP_GID}" appuser; fi \
    && install -d --mode 0755 --owner "${APP_UID}" --group "${APP_GID}" /home/appuser \
    && install -d --mode 0700 --owner "${APP_UID}" --group "${APP_GID}" /home/appuser/.config/yutto \
    && chown -R "${APP_UID}:${APP_GID}" /app /ms-playwright

ENV HOME=/home/appuser

USER ${APP_UID}:${APP_GID}

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "backend.main:app", "--app-dir", "web-ui", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]


FROM nginx:alpine AS frontend

RUN apk add --no-cache tzdata

ENV FRONTEND_PORT=80 \
    BACKEND_HOST=backend \
    BACKEND_PORT=8000 \
    TZ=Asia/Shanghai

COPY --from=frontend-build /src/web-ui/frontend/dist/ /usr/share/nginx/html/
COPY docker/nginx.compose.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 80
