# syntax=docker/dockerfile:1
#
# Single-process image for the Meta Ad Agent: one container serves both the
# FastAPI backend and the built React/Vite SPA, same-origin. See README.md
# ("Deploy as a single unit") for the one-command deploy.

# --- Stage 1: build the frontend -> dist/ -------------------------------------
FROM node:20-slim AS frontend
WORKDIR /app
# Install deps against the lockfile first so this layer caches across code edits.
COPY package.json package-lock.json ./
RUN npm ci
# Build inputs (sources, configs, index.html, public assets).
COPY tsconfig*.json vite.config.ts eslint.config.js index.html ./
COPY src ./src
COPY public ./public
RUN npm run build

# --- Stage 2: Python runtime that serves the API + the built SPA --------------
FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Backend dependencies.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Backend source + the frontend build from stage 1.
COPY backend ./backend
COPY --from=frontend /app/dist ./dist

# Run as a non-root user. Pre-create the storage dir owned by appuser so a mounted
# named volume (docker-compose) inherits that ownership and the app can write to it.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/storage \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
# Keep live Meta writes OFF unless explicitly enabled at deploy time.
ENV META_LIVE_WRITES_ENABLED=false

# Shell form so ${PORT} (injected by Railway/Render/Fly) is expanded at runtime.
CMD uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000}
