# ── Stage 1: Frontend (Vue/Vite) bauen ──────────────────────────────
FROM node:20-alpine AS frontend
WORKDIR /build/dashboard
COPY frontend/dashboard/package.json ./
RUN npm install
COPY frontend/dashboard/ ./
RUN npm run build

# ── Stage 2: Python-Runtime ─────────────────────────────────────────
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# System-Deps: snapclient (Snapcast) für Audio-Capture.
RUN apt-get update \
    && apt-get install -y --no-install-recommends snapclient \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

# Gebautes Frontend aus Stage 1 einbetten (wird statisch serviert).
COPY --from=frontend /build/dashboard/dist ./app/web

EXPOSE 8000
CMD ["python", "-m", "app.main"]
