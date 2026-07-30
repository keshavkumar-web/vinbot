# syntax=docker/dockerfile:1

########################################################################
# Stage 1 — Frontend build (Node/Vite)
#
# Only this stage needs Node, npm, and node_modules. None of that exists
# in the final image — only the compiled static assets get copied out.
########################################################################
FROM node:20-slim AS frontend-builder

WORKDIR /frontend

# Lockfiles copied first so `npm ci` is cached whenever only app source
# changes, not dependencies — standard Docker layer-caching pattern.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ .
RUN npm run build
# Output: /frontend/dist


########################################################################
# Stage 2 — Python dependency build
#
# Installs ONLY the runtime dependencies (backend/requirements.txt) into
# an isolated virtualenv, kept separate from the final stage so that if a
# future dependency ever needs a compiler, that toolchain never ships in
# the production image.
########################################################################
FROM python:3.12-slim-bookworm AS python-builder

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


########################################################################
# Stage 3 — Runtime image
#
# Minimal: python:3.12-slim base + the venv from stage 2 + backend source
# + the compiled frontend from stage 1. No Node, no npm, no pip cache, no
# build toolchain, no test dependencies (requirements-test.txt /
# requirements-ingest.txt are never referenced here).
########################################################################
FROM python:3.12-slim-bookworm AS runtime

ARG GIT_COMMIT=unknown
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.title="Vinbot" \
      org.opencontainers.image.description="Vinbot Enterprise AI Knowledge Assistant" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}"

# PYTHONDONTWRITEBYTECODE: skip .pyc files — no benefit in a container that
#   doesn't reimport modules thousands of times over a long-lived process.
# PYTHONUNBUFFERED: stdout/stderr are unbuffered, so log lines reach
#   `docker logs` immediately instead of sitting in a buffer — required
#   for structured logging to stdout/stderr to be useful in real time.
# FRONTEND_DIST: overrides app/main.py's default (which assumes a sibling
#   frontend/dist one level above backend/, the source-tree layout) to
#   point at where stage 1's build output actually lands in this image.
# KNOWLEDGE_DB_PATH: redirects the pickle DB to its own subdirectory
# (/app/data) rather than the default bare /app/knowledge_db.pkl. This
# matters because Docker cannot bind/volume-mount a single FILE path that
# doesn't already exist as a file in the image — it silently creates a
# DIRECTORY there instead, which is not what we want. Mounting a volume at
# a dedicated directory (/app/data) sidesteps that entirely, and keeps the
# mount scoped to just the data that should outlive a container replace —
# not the whole /app tree (app code + static + uhbvn_tables.db stay part
# of the image, not the volume).
# TABLES_DB_PATH: NOT required to be set — /app/uhbvn_tables.db is already
# where app/tables.py's own default (BACKEND_DIR/uhbvn_tables.db) resolves
# to, since WORKDIR /app is what BACKEND_DIR computes to at runtime. Set
# explicitly anyway so the in-image path is documented here rather than
# implied. uhbvn_tables.db is release content (git-tracked, ~2.6MB) and is
# baked into the image below — it is deliberately NOT volume-mounted and
# NOT seeded at runtime: it must exist the instant the container starts,
# with no initialization step and no new failure mode where structured
# queries fail because a volume hasn't been populated yet.
#
# No PORT env var here, deliberately: the app listens on a FIXED internal
# port (8000, literal in both HEALTHCHECK and CMD below). Only the HOST
# side is meant to be configurable, and that's docker-compose.yml's job
# (`ports: "${HOST_PORT}:8000"`) — not something a shell needs to expand
# inside this container at all.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    FRONTEND_DIST=/app/static \
    KNOWLEDGE_DB_PATH=/app/data/knowledge_db.pkl \
    TABLES_DB_PATH=/app/uhbvn_tables.db

# Non-root service account. --system: no password, no interactive login
# capability — this account exists only to own and run this one process.
RUN groupadd --system vinbot \
    && useradd --system --gid vinbot --home-dir /app --no-create-home \
       --shell /usr/sbin/nologin vinbot

WORKDIR /app

# Runtime dependencies from the builder stage's venv — no compiler, no
# package-manager cache, nothing but the installed libraries themselves.
COPY --from=python-builder /opt/venv /opt/venv

# Backend source.
COPY backend/app ./app

# uhbvn_tables.db is version-controlled, part of this application release
# (like the code itself), and small — baked into the image so it exists
# immediately on container start, no runtime seeding required. Never
# volume-mounted (confirmed design decision — see TABLES_DB_PATH note
# above). knowledge_db.pkl is the opposite case and is deliberately NOT
# copied anywhere in this file — it is a generated artifact that changes
# independently of releases and is mounted from a persistent volume at
# runtime instead (see docker-compose.yml).
COPY backend/uhbvn_tables.db ./uhbvn_tables.db

# Compiled frontend from stage 1.
COPY --from=frontend-builder /frontend/dist ./static

# /app/data is created HERE, during the image build, and owned by the
# non-root `vinbot` user BEFORE any volume is ever attached — required
# because KNOWLEDGE_DB_PATH (above) points inside it, and Docker never
# chowns a volume for you: if this directory weren't already vinbot-owned
# in the image itself, a freshly mounted named volume would inherit root
# ownership and the app could never write knowledge_db.pkl into it. The
# rest of /app (code, static assets, uhbvn_tables.db) is chowned too, for
# read access under the non-root user, though only /app/data actually
# needs to be writable at runtime.
RUN mkdir -p /app/data \
    && chown -R vinbot:vinbot /app \
    && chmod 750 /app/data

# /var/log/vinbot: correction to this line's own earlier comment — unlike
# /app/data (a NAMED VOLUME, which Docker seeds from the image's ownership on
# first creation), production runs BIND-MOUNT a real host directory here
# (`-v /var/log/vinbot:/var/log/vinbot`). A bind mount replaces this path
# with the host directory's inode entirely — its host-side ownership wins,
# unconditionally, no matter what this RUN instruction sets at build time.
# See the deployment docs for why, and for the host-side step (Jenkins /
# deploy script) that actually prepares this directory's ownership in
# production. This line is still kept because it's not dead code in every
# case: it's what makes /var/log/vinbot vinbot-owned in the one scenario
# where nothing IS bind-mounted over it — a plain `docker run` with no `-v`
# flag at all (e.g. quick local testing) — so logging still works there too.
# logger.py also degrades to console-only logging if this path is ever
# missing/unwritable either way, so a misconfigured mount never crashes the
# container — it just logs without a file on disk.
RUN mkdir -p /var/log/vinbot \
    && chown -R vinbot:vinbot /var/log/vinbot

USER vinbot

EXPOSE 8000

# Real HTTP health check — not a "python is running" liveness stub. This
# issues an actual GET against the application's own /api/health endpoint
# (app/main.py) and fails (non-zero exit) unless it returns HTTP 200; a
# connection refused / non-200 / timeout all correctly report unhealthy.
# No curl/wget installed just to run this — Python is already present as
# the runtime itself, so this costs zero extra image size or attack
# surface. Port is the same fixed literal as CMD below, not read from an
# env var — see the ENV block's note on why PORT isn't a variable here.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import sys, urllib.request as u; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)"

# Exec-form (JSON array), NOT shell-form — this is a deliberate change
# from an earlier version of this file, worth explaining rather than
# leaving silent:
#   - The ONLY reason this was ever shell-form (`CMD exec python -m
#     uvicorn ... --port ${PORT}`) was to let a shell expand ${PORT} at
#     container start. Now that the port is a fixed literal (8000, per
#     the instruction to let docker-compose.yml own host-side
#     configurability instead), there is nothing left that needs shell
#     interpretation.
#   - Exec-form runs uvicorn AS PID 1 directly — Docker never spawns
#     `/bin/sh -c` at all for this form. That gets the same graceful-
#     shutdown property (SIGTERM from `docker stop` reaches uvicorn
#     immediately) that shell-form previously needed the `exec` builtin
#     to work around a shell for — more directly, with one less moving
#     part to explain.
#   - --workers 1 is still REQUIRED, not a default left alone:
#     app/sessions.py keeps chat history in an in-process dict. More than
#     one worker here would silently split a single user's conversation
#     across processes, even within ONE container. Do not raise this
#     without first moving session storage to Redis/a database.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
