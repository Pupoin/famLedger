# Single image: builds the React frontend, then runs the FastAPI backend which
# serves both the API and the built frontend on one port (see FRONTEND_DIST in
# backend/main.py). No nginx / reverse proxy needed — one image, one container.

# Stage 1: build the React frontend
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: backend + the built frontend it serves
FROM python:3.11-slim-bookworm

# Version string baked in at build time and reported at GET /api/health, so
# "did my upgrade actually take effect?" has an answer. Fed from the git tag by
# .github/workflows/release.yml; a local `docker build` honestly says "dev".
ARG MOSAIC_BUILD_VERSION=dev
ENV MOSAIC_BUILD_VERSION=${MOSAIC_BUILD_VERSION}

# gosu drops privileges in the entrypoint. Needed because the entrypoint must
# start as root to fix ownership of an existing (root-owned) data volume left
# behind by an older image, then hand off to an unprivileged user.
ARG POSTGRES_MAJOR=18
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu ca-certificates curl \
    && mkdir -p /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-${POSTGRES_MAJOR} \
    && rm -rf /var/lib/apt/lists/*

# Unprivileged runtime account. Fixed uid/gid so file ownership on a mounted
# volume stays stable across image rebuilds.
RUN groupadd --gid 10001 famledger \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin famledger

WORKDIR /app/backend

# Install dependencies first (cached layer — only re-runs if requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ .

# config.py is gitignored (no secrets — just reads env vars).
# On a fresh clone it won't exist, so fall back to config.example.py.
RUN test -f config.py || cp config.example.py config.py

# Built SPA from stage 1 — FastAPI serves it from ../frontend/dist
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Entrypoint (not CMD): it fixes volume ownership, creates the data dirs, drops
# privileges, then execs whatever command it was given. Making it the entrypoint
# rather than the command means one-off invocations get the same treatment —
#   docker compose run --rm mosaic python -m cli verify
# runs as `mosaic`, so a maintenance command cannot leave root-owned files in the
# volume that the app itself is then unable to write.
COPY scripts/start.sh /start.sh
RUN chmod +x /start.sh

# The application code itself is owned by root and only read by the app — the
# runtime user deliberately cannot modify its own source.
RUN chown -R famledger:famledger /app/frontend/dist

EXPOSE 8000

# Catches the failure `restart: unless-stopped` cannot: a process that still
# holds the port but can no longer serve. urllib raises on a non-200 (including
# the 503 that /api/health returns when the database is unreachable), so an
# unhandled exception here is the unhealthy signal. Uses the interpreter that is
# already present rather than adding curl to the image.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5)"]

# Starts as root purely to chown the data volume, then execs the command below
# as `mosaic`.
ENTRYPOINT ["/start.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
