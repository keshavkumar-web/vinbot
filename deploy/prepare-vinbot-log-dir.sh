#!/usr/bin/env bash
# Prepares /var/log/vinbot on the deployment host so the Vinbot container
# (running as uid 999 / gid 999, user `vinbot`) can create and rotate
# app.log through the bind-mounted volume (`-v /var/log/vinbot:/var/log/vinbot`
# in docker-compose.yml).
#
# WHY THIS SCRIPT HAS TO EXIST AT ALL: a bind mount replaces this path with
# the HOST directory's own inode, ownership, and permissions, completely
# overriding whatever `chown`/`chmod` the Docker image applied to the same
# path at build time. This is different from a Docker-managed NAMED volume
# (like this project's own vinbot-data, used for /app/data), which Docker
# seeds from the image's ownership the first time it's created — a bind
# mount never does that. See Dockerfile's own comment at the /var/log/vinbot
# RUN instruction for the same explanation in-repo.
#
# This is the exact same fix Jenkins now runs automatically before every
# deploy (cicd/Jenkinsfile's prepareLogDirectory()) — this script exists so
# the identical, correct commands are available for a manual/emergency
# deploy that bypasses Jenkins, rather than someone reaching for
# `chmod 777` under time pressure.
#
# Usage: sudo ./prepare-vinbot-log-dir.sh
# Idempotent — safe to run before every deploy, not just the first one.

set -euo pipefail

LOG_DIR="/var/log/vinbot"
VINBOT_UID=999
VINBOT_GID=999

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this as root (e.g. with sudo) — it needs to chown a directory" >&2
    echo "it may not currently own." >&2
    exit 1
fi

mkdir -p "$LOG_DIR"
chown -R "${VINBOT_UID}:${VINBOT_GID}" "$LOG_DIR"
# 750, not 777 and not the 775 used during the original manual fix: the
# container's vinbot user (owner) needs to write; nothing else on this host
# needs any access to these logs at all, including "other".
chmod 750 "$LOG_DIR"

echo "OK: ${LOG_DIR} is owned by ${VINBOT_UID}:${VINBOT_GID}, mode 750."
